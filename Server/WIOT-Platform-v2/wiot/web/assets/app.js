// Application shell: session bootstrap, navigation, header, routing.
import { api, state, connectStream, onEvent, selectStreamCompany, ICONS, $, $$, toast, currentTheme, savedTheme, setTheme, themeToggleHtml } from "./api.js";
import { esc, applyTheme, DISPLAY, fmtClock } from "./charts.js";
import { initLang, setLang, langToggleHtml, t, I18N } from "./i18n.js";
import { UNITS } from "./units.js";
import * as farm from "./pages/farm.js";
import * as world from "./pages/world.js";
import * as org from "./pages/org.js";
import * as overview from "./pages/overview.js";
import * as commands from "./pages/commands.js";
import * as analytics from "./pages/analytics.js";
import * as history from "./pages/history.js";
import * as flash from "./pages/flash.js";
import * as admin from "./pages/admin.js";

const ROUTES = {
  farm: { mod: farm, label: "Smart farm", icon: ICONS.farm, group: "Operations" },
  world: { mod: world, label: "World operations", icon: ICONS.world, group: "Operations" },
  overview: { mod: overview, label: "Fleet overview", icon: ICONS.overview, group: "Operations" },
  commands: { mod: commands, label: "Command center", icon: ICONS.commands, group: "Operations" },
  analytics: { mod: analytics, label: "Data science", icon: ICONS.analytics, group: "Insights" },
  history: { mod: history, label: "Message history", icon: ICONS.history, group: "Insights" },
  flash: { mod: flash, label: "Flash data", icon: ICONS.chip, group: "Insights" },
  org: { mod: org, label: "Organization", icon: ICONS.org, group: "Settings" },
  admin: { mod: admin, label: "Administration", icon: ICONS.admin, group: "Settings" },
};
let cleanup = null, fleetSummary = null;

async function boot() {
  const me = await api("/auth/me");
  state.user = me.user;
  await loadCompanies();
  const saved = sessionStorageGet("wiot.company");
  state.company = (saved && state.companies.includes(saved)) ? saved
    : (state.companies.includes(me.user.company) ? me.user.company : state.companies[0]);
  applyProfile();
  initLang(state.profiles[state.company]?.language);
  await loadRegions();
  renderRail();
  renderTopbar();
  connectStream();
  onEvent((m) => { if (m.type === "broker" || m.type === "hello") paintBroker(); });
  addEventListener("hashchange", route);
  addEventListener("wiot:goto", (e) => gotoSite(e.detail));
  route();
  setInterval(tickClock, 1000);
  setInterval(refreshFleetPill, 15000);
}
async function loadCompanies() {
  const list = (await api("/companies")).companies;
  state.companies = list.map((c) => c.name);
  state.profiles = Object.fromEntries(list.map((c) => [c.name, c]));
}
// Company profile -> display time zone and unit system for every page.
function applyProfile() {
  const p = state.profiles?.[state.company] || {};
  DISPLAY.tz = p.timezone || undefined;
  UNITS.system = p.units || "metric";
}
async function switchCompany(company) {
  state.company = company; sessionStorageSet("wiot.company", company);
  applyProfile(); selectStreamCompany(company); await loadRegions();
}
// World page -> open a company's site on another page.
async function gotoSite({ company, region, page }) {
  if (company && company !== state.company && state.companies.includes(company)) await switchCompany(company);
  if (region && state.regions.includes(region)) state.region = region;
  renderTopbar();
  if (location.hash === `#/${page}`) route(); else location.hash = `#/${page}`;
}
function sessionStorageGet(k) { try { return sessionStorage.getItem(k); } catch { return null; } }
function sessionStorageSet(k, v) { try { sessionStorage.setItem(k, v); } catch { /* private mode */ } }

async function loadRegions() {
  try { state.regions = (await api("/regions", { params: { company: state.company } })).regions; }
  catch { state.regions = ["Region_1"]; }
  if (!state.regions.includes(state.region)) state.region = state.regions[0] || "Region_1";
}

function renderRail() {
  const rail = $("#rail"), u = state.user;
  const visible = Object.entries(ROUTES).filter(([k]) => k !== "admin" || u.permissions.manage_users || u.permissions.supervisor);
  let group = "", nav = "";
  for (const [k, r] of visible) {
    if (r.group !== group) { group = r.group; nav += `<div class="sb-group">${esc(group)}</div>`; }
    nav += `<a class="nav" href="#/${k}" data-route="${k}" data-tip="${esc(r.label)}" aria-label="${esc(r.label)}">${r.icon}<span>${esc(r.label)}</span></a>`;
  }
  const initials = u.username.replace(/[^A-Za-z0-9]/g, " ").trim().split(/\s+/).map((w) => w[0]).join("").slice(0, 2).toUpperCase() || "U";
  rail.innerHTML = `<div class="sb-brand"><img src="/favicon.svg" alt=""><div><b>WIOT</b><span>Control Center</span></div></div>${nav}
    <div class="spacer"></div>
    <a class="nav" href="/api/docs" target="_blank" rel="noopener" data-tip="API documentation" aria-label="API documentation">${ICONS.system}<span>API documentation</span></a>
    <div class="sb-user"><div class="av" data-i18n-skip>${esc(initials)}</div><div class="who"><b data-i18n-skip>${esc(u.username)}</b><span>${esc(u.role)}</span></div>
      <a href="#" id="logout" data-tip="Sign out" aria-label="Sign out" title="Sign out">${ICONS.logout}</a></div>
    <button class="sb-collapse" id="sb-collapse" type="button" aria-label="Collapse sidebar">${ICONS.chevron}<span>Collapse</span></button>`;
  $("#logout").addEventListener("click", async (e) => { e.preventDefault(); await api("/auth/logout", { method: "POST" }).catch(() => {}); location.href = "/login"; });
  $("#sb-collapse").addEventListener("click", () => {
    const shell = document.querySelector(".shell"), narrow = innerWidth <= 1440;
    const collapsed = narrow ? !shell.classList.contains("expanded") : !shell.classList.contains("collapsed");
    setSidebar(collapsed ? "expanded" : "collapsed");
  });
  setSidebar(localStorageGet("wiot.sidebar"), false);
  markActive();
}
function setSidebar(mode, persist = true) {
  const shell = document.querySelector(".shell");
  shell.classList.toggle("collapsed", mode === "collapsed");
  shell.classList.toggle("expanded", mode === "expanded");
  if (persist) { try { localStorage.setItem("wiot.sidebar", mode); } catch { /* storage blocked */ } }
}
function localStorageGet(k) { try { return localStorage.getItem(k); } catch { return null; } }
function markActive() {
  const key = currentKey();
  document.querySelectorAll("#rail a[data-route]").forEach((a) => a.classList.toggle("active", a.dataset.route === key));
}
const currentKey = () => { const k = (location.hash.replace(/^#\/?/, "").split("?")[0]) || "farm"; return ROUTES[k] ? k : "farm"; };

function renderTopbar() {
  const u = state.user, canSwitch = u.permissions.global_read, r = ROUTES[currentKey()];
  const company = state.profiles[state.company]?.display_name || state.company;
  $("#topbar").innerHTML = `
    <div class="tb-title"><h1 id="page-title">${esc(r.label)}</h1>
      <div class="crumbs"><span>${esc(r.group)}</span><i></i><b data-i18n-skip>${esc(company)}</b><i></i><span class="mono" data-i18n-skip>${esc(state.region)}</span></div></div>
    <div class="tb-tools">
      <div class="status-chip" id="pill-fleet" title="Nodes online in this region">…</div>
      <div class="status-chip" id="pill-broker" title="MQTT broker">…</div>
      ${canSwitch ? `<label class="tb-select"><span>Company</span><select id="sel-company" data-i18n-skip>${state.companies.map((c) => `<option value="${esc(c)}" ${c === state.company ? "selected" : ""}>${esc(state.profiles[c]?.display_name || c)}</option>`).join("")}</select></label>` : ""}
      <label class="tb-select"><span>Region</span><select id="sel-region" data-i18n-skip>${state.regions.map((x) => `<option ${x === state.region ? "selected" : ""}>${esc(x)}</option>`).join("")}</select></label>
      <div class="tb-clock" title="Local time of the selected company"><span id="pill-clock">--:--:--</span><small id="pill-tz"></small></div>
      <div id="pill-theme">${themeToggleHtml()}</div>
      <div id="pill-lang">${langToggleHtml()}</div>
    </div>`;
  $("#sel-company")?.addEventListener("change", async (e) => { await switchCompany(e.target.value); renderTopbar(); route(); });
  $("#sel-region").addEventListener("change", (e) => { state.region = e.target.value; renderTopbar(); route(); });
  bindThemeToggle();
  $$("#lang-toggle [data-lang]").forEach((b) => b.addEventListener("click", () => switchLang(b.dataset.lang)));
  paintBroker(); tickClock(); refreshFleetPill();
}

// English / Arabic: re-render the shell and page from English source, then translate.
function switchLang(lang) {
  if (lang === I18N.lang) return;
  setLang(lang);
  renderRail(); renderTopbar(); route();
}

// Night / Day: swap CSS tokens, refresh chart palette, redraw the current page.
function switchTheme(mode, persist = true) {
  if (mode === currentTheme()) return;
  setTheme(mode, persist);
  applyTheme();
  $("#pill-theme").innerHTML = themeToggleHtml();
  bindThemeToggle();
  route();
}
function bindThemeToggle() {
  $("#theme-toggle")?.addEventListener("click", () => switchTheme(currentTheme() === "light" ? "dark" : "light"));
}
// Follow the operating system's light/dark setting until the user picks a view.
matchMedia("(prefers-color-scheme: light)").addEventListener?.("change", (e) => {
  if (!savedTheme()) switchTheme(e.matches ? "light" : "dark", false);
});

function paintBroker() {
  const el = $("#pill-broker"); if (!el) return;
  const s = state.broker?.state || "unknown";
  const cls = s === "ready" ? "var(--good)" : s === "disconnected" ? "var(--critical)" : "var(--warning)";
  el.innerHTML = `<span class="dot ${s === "ready" ? "pulse" : ""}" style="background:${cls}"></span><span class="k">MQTT</span><b>${esc(s.charAt(0).toUpperCase() + s.slice(1))}</b>`;
}
function tickClock() {
  const el = $("#pill-clock"); if (el) el.textContent = fmtClock();
  const tz = $("#pill-tz");
  if (tz) {
    const zone = state.profiles?.[state.company]?.timezone;
    let off = "";
    try { off = new Intl.DateTimeFormat("en-US", { timeZone: zone, timeZoneName: "shortOffset" }).formatToParts(new Date()).find((x) => x.type === "timeZoneName")?.value.replace("GMT", "UTC") || ""; } catch { /* unknown zone */ }
    tz.textContent = off; tz.title = zone || "";
  }
}
async function refreshFleetPill() {
  try {
    const f = await api("/fleet", { params: { company: state.company, region: state.region } });
    fleetSummary = f.summary;
    const el = $("#pill-fleet");
    const all = f.summary.nodes && f.summary.online === f.summary.nodes, col = !f.summary.nodes ? "var(--muted)" : all ? "var(--good)" : f.summary.online ? "var(--warning)" : "var(--critical)";
    if (el) el.innerHTML = `<span class="dot" style="background:${col}"></span><b>${f.summary.online}/${f.summary.nodes}</b><span class="k">online</span>`;
  } catch { /* header is best-effort */ }
}

function route() {
  const key = (location.hash.replace(/^#\/?/, "").split("?")[0]) || "farm";
  const r = ROUTES[key] || ROUTES.farm;
  markActive();
  if (cleanup) { try { cleanup(); } catch { /* ignore */ } cleanup = null; }
  const title = $("#page-title"); if (title) { title.textContent = r.label; const g = document.querySelector(".crumbs span"); if (g) g.textContent = r.group; }
  const root = $("#page"); root.innerHTML = "";
  document.title = `${t(r.label)} · ${t("WIOT Control Center")}`;
  Promise.resolve(r.mod.render(root, { fleetSummary })).then((fn) => { cleanup = fn || null; })
    .catch((err) => { root.innerHTML = `<div class="panel"><div class="empty">${esc(err.message)}</div></div>`; toast(err.message, "error"); });
}

boot().catch((err) => { if (err.status !== 401) document.body.innerHTML = `<div class="empty">${esc(err.message)}</div>`; });
