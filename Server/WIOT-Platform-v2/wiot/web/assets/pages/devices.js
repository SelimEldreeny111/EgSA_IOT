// Devices (Track G, point 53): third-party climate, soil, water-quality and tank sensors that send JSON
// over MQTT (signed with a per-device secret, or unsigned) or reach the server through a LoRaWAN network
// server (The Things Stack webhook, ChirpStack HTTP integration). Readings are stored per catalog metric
// in SI units; temperatures are shown in the company's unit system. The page renders English text; the
// Arabic layer (i18n.js) translates text nodes, so user data sits in data-i18n-skip elements.
import { api, state, onEvent, ago, badge, toast, ICONS, $, $$ } from "../api.js";
import { esc, fmtNum, fmtDateTime, lineChart, legend, hideTip, PALETTE } from "../charts.js";
import { formHtml, readForm, copy } from "../forms.js";
import { conv, unit } from "../units.js";
import { t } from "../i18n.js";

const TEMP = new Set(["air_temp_c", "soil_temp_c", "water_temp_c"]);          // shown in °C or °F
const STATE = { online: ["good", "Online"], silent: ["critical", "Silent"], waiting: ["info", "Waiting"], disabled: ["neutral", "Disabled"] };
const VIA = { mqtt: "MQTT", ttn: "The Things Stack", chirpstack: "ChirpStack" };
const KINDS = [["ttn", "The Things Stack"], ["chirpstack", "ChirpStack"]];
const RANGES = [[24, "24 h"], [168, "7 days"], [720, "30 days"], [8760, "1 year"]];
const FILTERS = [["all", "All"], ["online", "Online"], ["silent", "Silent"], ["waiting", "Waiting"]];
const ID_RE = /^[A-Za-z0-9][A-Za-z0-9_-]{0,39}$/;
const ID_PATTERN = "[A-Za-z0-9][A-Za-z0-9_\\-]{0,39}";       // same rule for the browser's own form check
const RESERVED = new Set(["catalog", "sources"]);              // path segments of the devices API
const MAX_MAPPING = 32;
const SILENT_FACTOR = 3, SILENT_MIN_S = 900;                   // the server's rule (services/devices.py)
const ICON = {
  search: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>',
  plus: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>',
  copy: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V6a2 2 0 0 1 2-2h9"/></svg>',
  x: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"/></svg>',
};

// Survives route() re-renders (theme, language, company switches) so the page reopens where it was.
const memo = { company: null, tab: "devices", sel: null, filter: "all", q: "", metric: null, hours: 24 };

const nowS = () => Math.floor(Date.now() / 1000);
const fmtInt = (n) => Number(n || 0).toLocaleString("en-US");
const num = (v, d) => (v === null || v === undefined || !Number.isFinite(+v) ? "–"
  : (+v).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d }));
// display only (payload values, read-only mapping): 4 decimals, or 6 significant digits below 1 so 0.00001 stays visible
const rawNum = (v) => (Number.isInteger(+v) ? String(+v) : String(+(Math.abs(+v) >= 1 ? (+v).toFixed(4) : (+v).toPrecision(6))));
const toMinutes = (s) => Math.round(((+s || 900) / 60) * 100) / 100;
const dash = '<span class="dim">–</span>';
const smooth = () => (matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth");

/** Online / silent / waiting / disabled, recomputed locally so states stay right between reloads. */
function linkState(d, now = nowS()) {
  if (!d.enabled) return "disabled";
  if (!d.last_seen) return "waiting";
  return now - d.last_seen > Math.max(SILENT_FACTOR * (d.interval_s || 900), SILENT_MIN_S) ? "silent" : "online";
}
function connBadge(d) {
  if (d.protocol === "lorawan") return badge(["info", "LoRaWAN"]);
  return d.auth === "hmac" ? badge(["good", "MQTT · signed"]) : badge(["warning", "MQTT · unsigned"]);
}
function fmtInterval(s) {
  s = Math.round(+s || 0);
  if (s < 60) return `${s} s`;
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;   // the server allows 10 s steps
  const out = [];
  if (h) out.push(`${h} h`);
  if (m) out.push(`${m} min`);
  if (sec) out.push(`${sec} s`);
  return out.join(" ");
}
/** False only when the server says the address is loopback/private (older servers send no flag). */
const isPublic = (x) => x?.public !== false;
const MQTT_WARN = "This is the server's own broker address. Set WIOT_DEVICE_MQTT_HOST to the broker your devices can reach.";
const HOOK_WARN = "Set WIOT_PUBLIC_URL to an HTTPS address the network server can reach.";
function indexCatalog(cat) {
  const byKey = {};
  cat.metrics.forEach((m, i) => { byKey[m.key] = { ...m, order: i }; });
  return { ...cat, byKey };
}
/** [number, unit] in display units: temperatures follow the company's unit system, the rest the catalog unit. */
function parts(M, metric, v) {
  const m = M.byKey[metric] || { decimals: 2, unit: "" };
  return TEMP.has(metric) ? [num(conv(v, "temp"), m.decimals), unit("temp")] : [num(v, m.decimals), m.unit];
}
function numHtml(M, metric, v) {
  const [n, u] = parts(M, metric, v);
  return `<span class="dv-num"><b>${n}</b>${u ? `<small>${esc(u)}</small>` : ""}</span>`;
}
/** Metrics a device has values for: climate, soil and water first, battery and radio last. */
function metricsOf(M, d) {
  const rank = (k) => (M.byKey[k].group === "device" ? 1000 : 0) + M.byKey[k].order;
  return Object.keys(d.values || {}).filter((k) => M.byKey[k]).sort((a, b) => rank(a) - rank(b));
}
function chipsHtml(M, d) {
  const keys = metricsOf(M, d);
  if (!keys.length) return dash;
  const chips = keys.slice(0, 3).map((k) => {
    const v = d.values[k], untrusted = v.trusted === false;
    return `<span class="dv-chip ${untrusted ? "untrusted" : ""}" title="${esc(M.byKey[k].label)}${untrusted ? " · untrusted" : ""}">${numHtml(M, k, v.value)}</span>`;
  }).join("");
  return `<div class="dv-vals">${chips}${keys.length > 3 ? `<span class="dv-more">+${keys.length - 3}</span>` : ""}</div>`;
}
function copyRow(text, label) {
  return `<div class="dv-copyrow"><input class="input mono" readonly value="${esc(text)}" aria-label="${esc(label)}">
    <button type="button" class="btn sm" data-copy="${esc(text)}">${ICON.copy}Copy</button></div>`;
}
/** Ready-to-run publisher for a signed MQTT device (paho-mqtt). */
function pythonCode(M, topic, secret) {
  return [
    "import hmac, hashlib, json, time",
    "import paho.mqtt.publish as publish",
    "",
    `topic = ${JSON.stringify(topic)}`,
    `secret = ${JSON.stringify(secret)}`,
    'p = json.dumps({"ts": int(time.time()), "temperature": 24.5, "humidity": 61, "co2": 812})',
    'sig = hmac.new(secret.encode(), (topic + "\\n" + p).encode(), hashlib.sha256).hexdigest()',
    `publish.single(topic, json.dumps({"p": p, "sig": sig}), qos=1, hostname=${JSON.stringify(String(M.mqtt.host))}, port=${Number(M.mqtt.port) || 1883})`,
  ].join("\n");
}

export async function render(root) {
  if (memo.company !== state.company) Object.assign(memo, { company: state.company, sel: null, metric: null });
  const Q = () => ({ company: state.company });
  root.innerHTML = `<div class="ops dv" id="dv"><section class="panel"><div class="empty">Loading…</div></section></div>`;
  const wrap = $("#dv", root);
  let data, M;
  try {
    const [list, cat] = await Promise.all([api("/devices", { params: Q() }), api("/devices/catalog", { params: Q() })]);
    data = list; M = indexCatalog(cat);
  } catch (err) {
    wrap.innerHTML = `<section class="panel"><div class="empty">${esc(err.message)}</div></section>`;
    return () => {};                                           // a function, never undefined: see app.js route()
  }
  if (!wrap.isConnected) return () => {};                      // the user left while the page was loading
  data.unknown = data.unknown || [];

  const canEdit = !!data.can_edit;
  let alive = true, mode = "view", guideDone = false;          // mode "new": the side panel holds a registration form
  let liveTimer = null, reloadSoon = null, chartDirty = false, selTouched = false;
  let rseq = 0;                                                // GET /devices answers older than the latest request or local edit are dropped
  let shownSecret = null, lastKey = null;                      // "shown once" boxes stay until their Close button is used
  const chart = { seq: 0, device: null, metric: null, hours: 24, res: null, points: [], lo: null, hi: null, until: 0, keys: "", truncated: false };
  const q = (sel) => wrap.querySelector(sel);
  const byId = (id) => data.devices.find((d) => d.device_id === id) || null;
  const sorted = () => data.devices.slice().sort((a, b) => a.name.localeCompare(b.name) || a.device_id.localeCompare(b.device_id));
  const groups = Object.entries(M.groups).map(([g, label]) => [label, M.metrics.filter((m) => m.group === g)]).filter(([, ms]) => ms.length);
  // optgroup labels are attributes the Arabic layer does not touch, so this select is translated here
  const metricOptionsBase = groups.map(([label, ms]) => `<optgroup label="${esc(t(label))}">${ms.map((m) =>
    `<option value="${esc(m.key)}">${esc(t(m.label))} (${esc(m.unit)})</option>`).join("")}</optgroup>`).join("");
  const metricOptions = (sel) => `<option value="">${esc(t("Choose a metric"))}</option>`
    + (sel ? metricOptionsBase.replace(`value="${esc(sel)}"`, `value="${esc(sel)}" selected`) : metricOptionsBase);

  const tabs = [["devices", "Devices"], ...(canEdit ? [["sources", "LoRaWAN connections"]] : []), ["guide", "Set-up guide"]];
  wrap.innerHTML = `
    <div class="tiles dv-tiles" id="dv-tiles"></div>
    <div class="tabs dv-tabs" role="tablist" aria-label="Device pages">${tabs.map(([k, l]) => `<button type="button" role="tab" data-tab="${k}" aria-selected="false">${l}</button>`).join("")}</div>
    <div class="dv-pane" data-pane="devices" role="tabpanel">
      <div class="ed-split dv-split">
        <div class="dv-col">
          <section class="panel">
            <header><h2><span class="ico">${ICONS.sensor}</span>Third-party devices</h2><span class="meta" id="dv-count"></span>
              ${canEdit ? `<button type="button" class="btn sm primary" id="dv-new">${ICON.plus}New device</button>` : ""}</header>
            <div class="dv-toolbar">
              <label class="dv-search">${ICON.search}<input class="input" id="dv-q" type="search" placeholder="Search name, ID or DevEUI" aria-label="Search devices" value="${esc(memo.q)}" autocomplete="off" spellcheck="false"></label>
              <div class="seg dv-filter" id="dv-filter" role="group" aria-label="Filter by status"></div>
            </div>
            <div class="table-wrap dv-table-wrap"><table class="data dv-table"><thead><tr><th>Device</th><th>Connection</th><th>Latest readings</th><th>Last reading</th><th>Status</th><th>Location</th></tr></thead>
              <tbody id="dv-rows"></tbody></table></div>
            <div id="dv-empty"></div>
          </section>
          <section class="panel" id="dv-unknown" hidden></section>
          <section class="panel dv-chart" id="dv-chart" hidden></section>
        </div>
        <section class="panel dv-side" id="dv-side"></section>
      </div>
    </div>
    ${canEdit ? `<div class="dv-pane" data-pane="sources" role="tabpanel" hidden></div>` : ""}
    <div class="dv-pane" data-pane="guide" role="tabpanel" hidden></div>`;

  // ------------------------------------------------------------------ summary and list
  function counts(now = nowS()) {
    const c = { all: data.devices.length, online: 0, silent: 0, waiting: 0, disabled: 0 };
    data.devices.forEach((d) => { c[linkState(d, now)] += 1; });
    return c;
  }
  function paintTiles() {
    const list = data.devices, c = counts();
    const mqtt = list.filter((d) => d.protocol === "mqtt").length;
    const readings = list.reduce((a, d) => a + (d.uplinks_24h || 0), 0);
    const tile = (label, value, sub, cls = "") => `<div class="tile ${cls}"><div class="label">${label}</div><div class="v">${fmtInt(value)}</div><div class="s">${sub}</div></div>`;
    const mix = list.length ? `<span>${mqtt} MQTT</span> · <span>${list.length - mqtt} LoRaWAN</span>${c.disabled ? ` · <span>${c.disabled} disabled</span>` : ""}` : "None registered yet";
    q("#dv-tiles").innerHTML = [
      tile("Devices", list.length, mix),
      tile("Online", c.online, "Reporting on schedule"),
      tile("Silent", c.silent, "Missed 3 reports (at least 15 min)", c.silent ? "crit" : ""),
      tile("Waiting for first reading", c.waiting, "Registered, nothing received yet"),
      tile("Readings in 24 h", readings, "Accepted uplinks, all devices"),
    ].join("");
  }
  /** Repaint a live-updated container without dropping keyboard focus from the item (by key) that had it. */
  function keepFocus(box, sel, key, paint) {
    const fid = document.activeElement?.closest?.(sel)?.dataset[key];
    paint();
    if (fid !== undefined && !box.contains(document.activeElement)) {
      box.querySelector(`[data-${key}="${CSS.escape(fid)}"]`)?.focus({ preventScroll: true });
    }
  }
  function paintFilter() {
    const c = counts(), box = q("#dv-filter");
    keepFocus(box, "#dv-filter [data-f]", "f", () => {
      box.innerHTML = FILTERS.map(([k, l]) => `<button type="button" data-f="${k}" class="${memo.filter === k ? "on" : ""}" aria-pressed="${memo.filter === k}">${l}<span class="dv-n">${c[k]}</span></button>`).join("");
    });
  }
  function visible(now) {
    const term = memo.q.trim().toLowerCase(), hex = term.replace(/[\s:-]/g, "");
    return sorted().filter((d) => (memo.filter === "all" || linkState(d, now) === memo.filter)
      && (!term || `${d.name} ${d.device_id} ${d.model || ""}`.toLowerCase().includes(term)
        || (hex !== "" && (d.dev_eui || "").toLowerCase().includes(hex))));
  }
  function rowHtml(d, now) {
    const loc = d.locations || [];
    return `<tr class="clickable ${mode === "view" && d.device_id === memo.sel ? "sel" : ""}" data-id="${esc(d.device_id)}" tabindex="0">
      <td><div class="dv-name"><b data-i18n-skip>${esc(d.name)}</b><div class="nh-sub"><span class="mono" data-i18n-skip>${esc(d.device_id)}</span>${d.model ? `<span data-i18n-skip>${esc(d.model)}</span>` : ""}</div></div></td>
      <td>${connBadge(d)}</td>
      <td>${chipsHtml(M, d)}</td>
      <td class="tnum">${d.last_seen ? `<span title="${esc(fmtDateTime(d.last_seen))}">${esc(ago(d.last_seen))}</span>` : '<span class="dim">never</span>'}</td>
      <td>${badge(STATE[linkState(d, now)])}</td>
      <td>${loc.length ? `<div class="dv-loc"><span data-i18n-skip>${esc(loc[0])}</span>${loc.length > 1 ? `<div class="nh-sub">+${loc.length - 1} more</div>` : ""}</div>` : dash}</td></tr>`;
  }
  function emptyHtml() {
    return `<div class="dv-empty"><span class="ico">${ICONS.sensor}</span><b>No third-party devices yet</b>
      <p>Connect climate, soil, water-quality and tank sensors that send JSON over MQTT, or that reach the server through The Things Stack or ChirpStack.</p>
      ${canEdit ? `<div class="row"><button type="button" class="btn primary" data-new>${ICON.plus}Register your first device</button><button type="button" class="btn ghost" data-goto="guide">Read the set-up guide</button></div>`
        : "<p>An administrator registers devices on this page.</p>"}</div>`;
  }
  function paintTable() {
    const list = data.devices, now = nowS(), none = !list.length;
    q(".dv-toolbar").hidden = none;
    q(".dv-table-wrap").hidden = none;
    q("#dv-empty").innerHTML = none ? emptyHtml() : "";
    const rows = none ? [] : visible(now);
    q("#dv-count").textContent = rows.length === list.length ? String(list.length) : `${rows.length}/${list.length}`;
    const body = q("#dv-rows");
    keepFocus(body, "#dv-rows tr[data-id]", "id", () => {
      body.innerHTML = none ? "" : rows.map((d) => rowHtml(d, now)).join("")
        || '<tr><td colspan="6"><div class="empty">No devices match the search or filter.</div></td></tr>';
    });
  }
  function paintUnknown() {
    const box = q("#dv-unknown"), list = data.unknown || [];
    box.hidden = !list.length;
    if (!list.length) { box.innerHTML = ""; return; }
    const fields = (f) => (f?.length ? `<div class="dv-vals dv-fields">${f.slice(0, 6).map((x) => `<span class="chip" data-i18n-skip>${esc(x)}</span>`).join("")}${f.length > 6 ? `<span class="dv-more">+${f.length - 6}</span>` : ""}</div>` : dash);
    // the topic is wiotx/<company>/<ID>/up, so the ID column says it all; the name comes from the network server
    box.innerHTML = `<header><h2><span class="ico">${ICONS.tower}</span>Heard but not registered</h2><span class="meta">${list.length}</span></header>
      <div class="table-wrap"><table class="data dv-table"><thead><tr><th>Via</th><th>ID</th><th>Fields</th><th class="num">Messages</th><th>Last heard</th>${canEdit ? "<th></th>" : ""}</tr></thead><tbody>
      ${list.map((u, i) => `<tr><td>${badge([u.via === "mqtt" ? "neutral" : "info", VIA[u.via] || u.via])}</td>
        <td><span class="mono" data-i18n-skip>${esc(u.id)}</span>${u.name ? `<div class="nh-sub" data-i18n-skip>${esc(u.name)}</div>` : ""}</td>
        <td>${fields(u.fields)}</td>
        <td class="num">${fmtInt(u.count)}</td>
        <td><span title="${esc(fmtDateTime(u.last_at))}">${esc(ago(u.last_at))}</span></td>
        ${canEdit ? `<td class="num"><button type="button" class="btn sm" data-reg="${i}">Register</button></td>` : ""}</tr>`).join("")}
      </tbody></table></div>
      <div class="body"><p class="note">Messages from unregistered devices are not stored. Register a device to start storing its readings. The list keeps the last 20 and starts again when the server restarts.</p></div>`;
  }
  function paintAll() { paintTiles(); paintFilter(); paintTable(); paintUnknown(); }

  // ------------------------------------------------------------------ selection
  const markSel = () => $$("#dv-rows tr[data-id]", wrap).forEach((tr) => tr.classList.toggle("sel", mode === "view" && tr.dataset.id === memo.sel));
  function select(id, { secret = null, scroll = true, force = false } = {}) {
    const same = mode === "view" && id === memo.sel;
    mode = "view"; memo.sel = id;
    markSel();
    if (!same || force) { renderSide({ secret }); renderChart(); }       // a second click keeps unsaved edits
    if (scroll && matchMedia("(max-width: 1250px)").matches) q("#dv-side").scrollIntoView({ behavior: smooth(), block: "start" });
  }
  function openNew(preset = null) {
    if (!canEdit) return;
    if (memo.tab !== "devices") setTab("devices");
    mode = "new";
    markSel();
    renderSide({ preset });
    renderChart();
    const side = q("#dv-side"), top = side.getBoundingClientRect().top;
    if (top < 60 || top > innerHeight - 160) side.scrollIntoView({ behavior: smooth(), block: "start" });
    side.querySelector(preset ? '[name="name"]' : '[name="device_id"]')?.focus({ preventScroll: true });
  }
  /** Prefill for a device heard on MQTT or by a network server but not registered yet. */
  function presetFrom(u) {
    if (u.via === "mqtt") return { device_id: u.id, name: u.id, protocol: "mqtt", heard: u };
    const eui = String(u.id).toUpperCase().replace(/[^0-9A-F]/g, "");
    const taken = new Set(data.devices.map((d) => d.device_id.toLowerCase()));
    const slug = String(u.name || "").replace(/[^A-Za-z0-9_-]+/g, "-").replace(/^[-_]+|[-_]+$/g, "").slice(0, 40).replace(/[-_]+$/, "");
    const ok = slug && ID_RE.test(slug) && !taken.has(slug.toLowerCase()) && !RESERVED.has(slug.toLowerCase());
    return { device_id: ok ? slug : `LW-${eui.slice(-6)}`, name: u.name || `LoRaWAN ${eui.slice(-6)}`, protocol: "lorawan", dev_eui: eui, heard: u };
  }
  /** Merge a create/update response into the list (it carries no readings or diagnostics). */
  function upsert(dev) {
    const i = data.devices.findIndex((x) => x.device_id === dev.device_id);
    const base = i >= 0 ? data.devices[i] : { last_seen: null, measured_at: null, values: {}, uplinks_24h: 0, stats: {}, last_payload: null, locations: [] };
    const next = { ...base, ...dev };
    delete next.secret;
    if (i >= 0) data.devices[i] = next; else data.devices.push(next);
  }
  function renderSide(opts = {}) {
    const d = mode === "view" ? byId(memo.sel) : null;
    if (!canEdit) { details(d); return; }
    if (!d) mode = "new";
    editor(d, opts);
  }

  // ------------------------------------------------------------------ side panel: shared parts
  function factsHtml(d) {
    return `<div class="dv-facts">
      <div><span class="label">Device ID</span><span class="mono" data-i18n-skip>${esc(d.device_id)}</span></div>
      <div><span class="label">Readings in 24 h</span><span class="tnum">${fmtInt(d.uplinks_24h)}</span></div>
      <div><span class="label">Last reading</span>${d.last_seen ? `<span title="${esc(fmtDateTime(d.last_seen))}">${esc(ago(d.last_seen))}</span>` : '<span class="dim">never</span>'}</div>
      <div><span class="label">Registered</span><span class="tnum">${esc(fmtDateTime(d.created_at).slice(0, 10))}</span><span class="nh-sub" data-i18n-skip>${esc(d.created_by || "")}</span></div></div>`;
  }
  function payloadHtml(d, canMap) {
    const lp = d.last_payload, head = '<div class="section-title">Last payload</div>';
    if (!lp) return `<div class="dv-sec">${head}<p class="note">No message from this device since the server started.</p></div>`;
    const explicit = new Map((d.mapping || []).map((m) => [m.field, m.metric]));
    const auto = !explicit.size;                       // without a mapping the suggested fields are stored
    const label = (k) => esc(M.byKey[k]?.label || k);
    const items = Object.entries(lp.fields || {}).map(([f, v]) => {
      const sug = lp.suggested?.[f];
      let st;
      if (explicit.has(f)) st = `<span class="dv-tag ok">${label(explicit.get(f))}</span>`;
      else if (sug && auto) st = `<span class="dv-tag ok">${label(sug)}</span><small>automatic</small>`;
      else if (sug) st = `<span class="dv-tag">${label(sug)}</span><small>suggested</small>`;
      else st = "<small>not mapped</small>";
      const btn = canMap && !explicit.has(f) && !(sug && auto)
        ? `<button type="button" class="btn sm" data-map="${esc(f)}" data-metric="${esc(sug || "")}">Map</button>` : "<span></span>";
      return `<li><span class="dv-kv"><code>${esc(f)}</code><i>=</i><b>${esc(rawNum(v))}</b></span><span class="dv-st">${st}</span>${btn}</li>`;
    }).join("");
    const rej = (lp.rejected || []).map((r) => {
      const m = M.byKey[r.metric] || {};
      return `<li><span class="dv-kv"><code>${esc(r.field)}</code><i>=</i><b>${esc(rawNum(r.value))}</b></span><span>${esc(m.label || r.metric)}</span>
        ${m.unit !== undefined ? `<span class="nh-sub tnum">${esc(`${fmtInt(m.min)} – ${fmtInt(m.max)} ${m.unit}`)}</span>` : ""}</li>`;
    }).join("");
    return `<div class="dv-sec">${head}
      <div class="nh-sub dv-when">${esc(ago(lp.at))} · ${esc(VIA[lp.source] || lp.source || "")}</div>
      ${items ? `<ul class="dv-payload">${items}</ul>` : '<p class="note">The last message had no numeric fields.</p>'}
      ${rej ? `<div class="dv-rej"><b>Outside the valid range (not stored)</b><ul>${rej}</ul></div>` : ""}</div>`;
  }
  function statsHtml(d) {
    const s = d.stats || {};
    return `<div class="dv-sec"><div class="section-title">Message counts</div>
      <div class="dv-stats"><div><span class="label">Accepted</span><b>${fmtInt(s.accepted)}</b></div>
        <div class="${s.rejected ? "bad" : ""}"><span class="label">Rejected</span><b>${fmtInt(s.rejected)}</b></div>
        <div><span class="label">Duplicates</span><b>${fmtInt(s.duplicates)}</b></div></div>
      ${s.last_error ? `<div class="dv-err"><b>Last error</b><span title="${esc(fmtDateTime(s.last_error_at))}">${esc(ago(s.last_error_at))}</span><div>${esc(s.last_error)}</div></div>` : ""}
      <p class="note">Counted since the server started.</p></div>`;
  }
  function heardHtml(u) {
    return `<div class="dv-heard"><div><b>Heard on the network</b><div class="nh-sub">${esc(VIA[u.via] || u.via)} · ${esc(ago(u.last_at))}</div></div>
      ${u.fields?.length ? `<p class="note">Fields in its last uplink. Map the ones you need, or leave the mapping empty for automatic field names.</p>
        <ul class="dv-payload">${u.fields.map((f) => `<li><span class="dv-kv"><code>${esc(f)}</code></span><span></span><button type="button" class="btn sm" data-map="${esc(f)}" data-metric="">Map</button></li>`).join("")}</ul>` : ""}</div>`;
  }
  function secretBox({ secret, topic }) {
    const code = pythonCode(M, topic, secret);
    return `<div class="secret-box dv-secret" role="status">
      <b>Copy this secret now — it will not be shown again.</b>
      ${copyRow(secret, "Device secret")}
      <div class="dv-code-h"><span>Python example (paho-mqtt)</span><button type="button" class="btn sm ghost" data-copy="${esc(code)}">${ICON.copy}Copy code</button></div>
      <pre class="mono sm">${esc(code)}</pre>
      ${isPublic(M.mqtt) ? "" : `<p class="dv-addr-warn">${MQTT_WARN}</p>`}
      <div><button type="button" class="btn sm" data-done>Close</button></div></div>`;
  }
  function mapRowHtml(r = {}) {
    // the exact stored value (not rawNum): a save resends the mapping and must not round the scale or offset
    const val = (x, dflt) => (x === undefined || x === null || x === "" || +x === dflt ? "" : esc(String(+x)));
    return `<div class="dv-map-row">
      <label class="dv-cell c-f"><span class="dv-cap">Payload field</span><input class="input mono" data-k="field" value="${esc(r.field || "")}" maxlength="330" placeholder="e.g. climate.co2" spellcheck="false" autocomplete="off"></label>
      <label class="dv-cell c-m"><span class="dv-cap">Measurement</span><select class="input" data-k="metric">${metricOptions(r.metric)}</select></label>
      <label class="dv-cell c-s"><span class="dv-cap">Scale</span><input class="input" type="number" step="any" data-k="scale" value="${val(r.scale, 1)}" placeholder="1"></label>
      <label class="dv-cell c-o"><span class="dv-cap">Offset</span><input class="input" type="number" step="any" data-k="offset" value="${val(r.offset, 0)}" placeholder="0"></label>
      <button type="button" class="btn sm ghost dv-x" data-rm title="Remove field" aria-label="Remove field">${ICON.x}</button></div>`;
  }

  // ------------------------------------------------------------------ editor (can_edit)
  function deviceFields(isNew, region, minMinutes) {
    const regions = [...new Set([...(state.regions || []), ...(region ? [region] : [])])];
    return [
      ...(isNew ? [{ k: "device_id", label: "Device ID", required: true, mono: true, maxlength: 40, placeholder: "e.g. GH1-CLIMATE",
        hint: "Letters, digits, _ or -. Part of the MQTT topic; cannot be changed later." }] : []),
      { k: "name", label: "Name", required: true, maxlength: 80, placeholder: "e.g. House 1 climate", full: !isNew },
      // full width: the option texts are long and would be cut off in a half-width select
      { k: "protocol", label: "Connection", type: "select", full: true, options: [["mqtt", "MQTT JSON"], ["lorawan", "LoRaWAN (TTN or ChirpStack)"]] },
      { k: "auth", label: "Security", type: "select", full: true, options: [["hmac", "Signed (HMAC, recommended)"], ["none", "Unsigned (readings marked untrusted)"]] },
      { k: "dev_eui", label: "DevEUI", mono: true, full: true, maxlength: 32, placeholder: "e.g. A840410000000007", hint: "16 hexadecimal characters, from the device label or the network server" },
      { k: "model", label: "Model", maxlength: 80, placeholder: "e.g. EM500-CO2" },
      { k: "region", label: "Region", type: "select", options: [["", t("— none —")], ...regions.map((r) => [r, r])], hint: "Optional. Silent-device alerts are filed under this region." },
      { k: "interval_min", label: "Reporting interval (minutes)", type: "number", required: true, min: minMinutes, max: 1440, step: "any", hint: "Silent alert after 3 missed reports (at least 15 min)" },
      { k: "enabled", label: "Status", type: "check", text: "Enabled: accept readings" },
      { k: "lat", label: "Latitude", type: "number", step: "any", min: -90, max: 90, placeholder: "Optional" },
      { k: "lon", label: "Longitude", type: "number", step: "any", min: -180, max: 180, placeholder: "Optional" },
      { k: "notes", label: "Notes", type: "textarea", full: true, maxlength: 500 },
    ];
  }

  function editor(d, { preset = null, secret = null } = {}) {
    const side = q("#dv-side"), isNew = !d;
    const startMin = isNew ? 15 : toMinutes(d.interval_s);
    const values = isNew
      ? { device_id: preset?.device_id || "", name: preset?.name || "", protocol: preset?.protocol || "mqtt", auth: "hmac",
          dev_eui: preset?.dev_eui || "", region: "", interval_min: 15, enabled: true }
      : { name: d.name, protocol: d.protocol, auth: d.auth === "none" ? "none" : "hmac", dev_eui: d.dev_eui || "", model: d.model || "",
          region: d.region || "", interval_min: startMin, enabled: d.enabled, lat: d.lat ?? "", lon: d.lon ?? "", notes: d.notes || "" };
    const fields = deviceFields(isNew, values.region, Math.min(1, startMin));
    const wasSigned = !isNew && d.protocol === "mqtt" && d.auth === "hmac";
    // Fields the server maps automatically today; they are kept when the first explicit row is added.
    const autoFields = !isNew && !(d.mapping || []).length ? (d.last_payload?.suggested || {}) : {};

    side.innerHTML = `<header><h2><span class="ico">${isNew ? ICONS.sensor : ICONS.edit}</span>${isNew ? "<span>Register a device</span>" : `<span class="dv-ttl" data-i18n-skip>${esc(d.name)}</span>`}</h2>
        ${isNew ? "" : `<span class="meta">${badge(STATE[linkState(d)])}</span>`}</header>
      <div class="body">
        <div id="dv-secret">${secret ? secretBox(secret) : ""}</div>
        ${isNew ? (preset?.heard ? heardHtml(preset.heard) : "") : factsHtml(d)}
        <form id="dv-form" autocomplete="off">
          ${formHtml(fields, values)}
          <div class="dv-proto" id="dv-proto"></div>
          <div class="dv-sec">
            <div class="section-title">Payload mapping</div>
            <div class="dv-map">
              <div class="dv-map-head" id="dv-map-head" aria-hidden="true"><span>Payload field</span><span>Measurement</span><span>Scale</span><span>Offset</span><span></span></div>
              <div id="dv-map-rows">${(isNew ? [] : d.mapping || []).map(mapRowHtml).join("")}</div>
            </div>
            <button type="button" class="btn sm dv-map-add" id="dv-map-add">${ICON.plus}Add field</button>
            <p class="note">Leave empty to map common field names automatically (temperature, humidity, co2 …)</p>
            <p class="note">Once a field is mapped, only mapped fields are stored. Stored value = payload value × scale + offset, in the metric's unit.</p>
          </div>
          ${isNew ? "" : `<div id="dv-live">${payloadHtml(d, true) + statsHtml(d)}</div>`}
          <div class="dv-actions">
            <button class="btn primary" type="submit">${isNew ? "Create" : "Save changes"}</button>
            ${wasSigned ? `<button type="button" class="btn" id="dv-rotate">${ICONS.key}New secret</button>` : ""}
            ${isNew && data.devices.length ? '<button type="button" class="btn ghost" id="dv-cancel">Cancel</button>' : ""}
            ${isNew ? "" : '<button type="button" class="btn danger" id="dv-del">Delete</button>'}
          </div>
        </form>
      </div>`;

    side.dataset.dev = isNew ? "" : d.device_id;               // paintSideLive() refreshes this device's live parts
    const form = side.querySelector("#dv-form"), rows = side.querySelector("#dv-map-rows");
    const el = (k) => form.elements.namedItem(k);
    if (el("device_id")) { el("device_id").pattern = ID_PATTERN; el("device_id").title = "Letters, digits, _ or -, starting with a letter or digit"; }

    // MQTT-only and LoRaWAN-only fields are hidden, not removed, so typed values survive a switch.
    function sync() {
      const proto = el("protocol").value;
      form.querySelector('[data-field="auth"]').hidden = proto !== "mqtt";
      form.querySelector('[data-field="dev_eui"]').hidden = proto !== "lorawan";
      paintProto();
    }
    function paintProto() {
      const box = form.querySelector("#dv-proto"), proto = el("protocol").value, signed = el("auth").value === "hmac";
      box.classList.toggle("warn", proto === "mqtt" && !signed);
      if (proto === "lorawan") {
        box.innerHTML = `<p>Uplinks arrive through a LoRaWAN connection (The Things Stack or ChirpStack) and are matched by DevEUI.</p>
          <button type="button" class="btn sm" data-goto="sources">${ICONS.key}LoRaWAN connections</button>`;
        return;
      }
      const id = isNew ? el("device_id").value.trim() : d.device_id;
      const topic = M.mqtt.topic.replace("<device_id>", ID_RE.test(id) ? id : "<device_id>");
      const line = !signed ? "Anyone on the broker can publish to this topic: readings are stored but marked untrusted."
        : wasSigned ? "Each message is verified with the device secret."
          : isNew ? "A secret is created with the device and shown once." : "Saving issues a device secret, shown once.";
      box.innerHTML = `<div class="dv-topic"><span class="label">MQTT topic</span><code>${esc(topic)}</code>
          <button type="button" class="btn sm ghost dv-copy" data-copy="${esc(topic)}" title="Copy topic" aria-label="Copy topic">${ICON.copy}</button></div>
        <p class="${signed ? "" : "dv-warn"}">${line}</p>${!signed && wasSigned ? '<p class="dv-warn">Saving removes the device secret.</p>' : ""}`;
    }
    el("protocol").addEventListener("change", sync);
    el("auth").addEventListener("change", sync);
    el("device_id")?.addEventListener("input", paintProto);

    // ---- payload mapping rows
    const rowCount = () => rows.children.length;
    function syncMap() {
      side.querySelector("#dv-map-head").hidden = !rowCount();
      side.querySelector("#dv-map-add").disabled = rowCount() >= MAX_MAPPING;
    }
    function flash(row) { row.classList.remove("fresh"); void row.offsetWidth; row.classList.add("fresh"); }
    function addRow(r, focus) {
      rows.insertAdjacentHTML("beforeend", mapRowHtml(r));
      const row = rows.lastElementChild;
      flash(row);
      if (focus) row.querySelector(r.field ? '[data-k="metric"]' : '[data-k="field"]').focus();
    }
    function addMapping(r = {}) {
      const same = r.field && [...rows.children].find((row) => row.querySelector('[data-k="field"]').value.trim() === r.field);
      if (same) { flash(same); same.querySelector('[data-k="metric"]').focus(); return; }
      if (rowCount() >= MAX_MAPPING) { toast("At most 32 mapped fields per device", "error"); return; }
      const kept = rowCount() ? [] : Object.entries(autoFields).filter(([f]) => f !== r.field).slice(0, MAX_MAPPING - 1);
      kept.forEach(([field, metric]) => addRow({ field, metric }, false));
      addRow(r, true);
      if (kept.length) toast("Fields that were mapped automatically were added too, so they keep being stored", "ok");
      syncMap();
    }
    side.querySelector("#dv-map-add").addEventListener("click", () => addMapping());
    rows.addEventListener("click", (e) => {
      const b = e.target.closest("[data-rm]");
      if (b) { b.closest(".dv-map-row").remove(); syncMap(); }
    });
    // delegated: the last payload block is repainted with live readings (paintSideLive)
    side.querySelector(".body").addEventListener("click", (e) => {
      const b = e.target.closest("[data-map]");
      if (b) addMapping({ field: b.dataset.map, metric: b.dataset.metric });
    });

    function readMapping() {
      const out = [];
      for (const row of rows.children) {
        const get = (k) => row.querySelector(`[data-k="${k}"]`);
        const field = get("field").value.trim(), metric = get("metric").value;
        const scale = get("scale").value.trim(), offset = get("offset").value.trim();
        if (!field && !metric) continue;                                  // an untouched empty row
        if (!field) { get("field").focus(); throw new Error("Enter the payload field of each mapping row"); }
        if (!metric) { get("metric").focus(); throw new Error("Choose a metric for each mapped field"); }
        out.push({ field, metric, scale: scale === "" ? 1 : +scale, offset: offset === "" ? 0 : +offset });
      }
      return out;
    }
    function collect() {
      const v = readForm(form, fields), proto = v.protocol;
      if (isNew && !ID_RE.test(v.device_id)) throw new Error("Device ID must be 1..40 letters, digits, _ or -, starting with a letter or digit");
      if (isNew && RESERVED.has(v.device_id.toLowerCase())) throw new Error("This device ID is reserved; choose another");
      if (!v.name) throw new Error("Give the device a name");
      const eui = (v.dev_eui || "").replace(/[\s:-]/g, "");
      if (proto === "lorawan" && !/^[0-9A-Fa-f]{16}$/.test(eui)) throw new Error("DevEUI must be 16 hexadecimal characters");
      if ((v.lat === null) !== (v.lon === null)) throw new Error("Enter both latitude and longitude, or neither");
      // an unchanged interval keeps its exact seconds (the server allows 10 s steps)
      const interval_s = !isNew && v.interval_min === startMin ? d.interval_s : Math.round((v.interval_min || 0) * 60);
      if (!(interval_s >= 10 && interval_s <= 86400)) throw new Error("Reporting interval must be 1 to 1440 minutes");
      const mapping = readMapping();
      const body = { name: v.name, protocol: proto, model: v.model, region: v.region || null, interval_s,
        lat: v.lat, lon: v.lon, enabled: v.enabled, notes: v.notes, mapping };
      // an unchanged mapping is left out of the PATCH, so the stored rows are kept exactly as they are
      const norm = (list) => JSON.stringify((list || []).map((m) => [m.field, m.metric, +(m.scale ?? 1), +(m.offset ?? 0)]));
      if (!isNew && norm(mapping) === norm(d.mapping)) delete body.mapping;
      if (isNew) body.device_id = v.device_id;
      if (proto === "mqtt") body.auth = v.auth; else body.dev_eui = eui.toUpperCase();
      return body;
    }
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      let body;
      try { body = collect(); } catch (err) { toast(err.message, "error"); return; }
      const btn = form.querySelector('button[type="submit"]');
      btn.disabled = true;
      try {
        const r = await api(isNew ? "/devices" : `/devices/${encodeURIComponent(d.device_id)}`, { method: isNew ? "POST" : "PATCH", params: Q(), body });
        if (!alive) return;
        toast(isNew ? "Device registered" : "Changes saved", "ok");
        rseq++;                                                   // a GET /devices already in flight predates this save
        upsert(r);
        if (isNew) data.unknown = data.unknown.filter((u) => u.id !== r.device_id && u.id !== r.dev_eui);
        // a secret shown after create or rotate stays until its Close button, unless the device no longer has one
        if (r.secret) shownSecret = { device_id: r.device_id, secret: r.secret, topic: r.topic };
        else if (shownSecret?.device_id === r.device_id && !(r.protocol === "mqtt" && r.auth === "hmac")) shownSecret = null;
        paintAll();
        select(r.device_id, { secret: shownSecret?.device_id === r.device_id ? shownSecret : null, scroll: false, force: true });
        reload().catch(() => {});
      } catch (err) { toast(err.message, "error"); btn.disabled = false; }
    });
    side.querySelector("#dv-rotate")?.addEventListener("click", async (e) => {
      if (!confirm(t("Issue a new secret? The current secret stops working immediately."))) return;
      const b = e.currentTarget;
      b.disabled = true;
      try {
        const r = await api(`/devices/${encodeURIComponent(d.device_id)}/secret`, { method: "POST", params: Q() });
        if (!alive) return;
        const slot = side.querySelector("#dv-secret");
        shownSecret = { device_id: d.device_id, secret: r.secret, topic: d.topic };
        slot.innerHTML = secretBox(shownSecret);
        slot.scrollIntoView({ behavior: smooth(), block: "nearest" });
        toast("New secret issued", "ok");
      } catch (err) { toast(err.message, "error"); }
      b.disabled = false;
    });
    side.querySelector("#dv-del")?.addEventListener("click", async (e) => {
      if (!confirm(t("Delete this device and all its stored readings?"))) return;
      const b = e.currentTarget;
      b.disabled = true;
      try {
        const r = await api(`/devices/${encodeURIComponent(d.device_id)}`, { method: "DELETE", params: Q() });
        if (!alive) return;
        toast(`Device deleted · ${fmtInt(r.readings_deleted)} readings removed`, "ok");
        rseq++;                                                   // a GET /devices already in flight predates this delete
        if (shownSecret?.device_id === d.device_id) shownSecret = null;
        data.devices = data.devices.filter((x) => x.device_id !== d.device_id);
        memo.sel = sorted()[0]?.device_id || null;
        paintAll();
        if (memo.sel) select(memo.sel, { scroll: false, force: true });
        else { mode = "new"; renderSide(); renderChart(); }
        reload().catch(() => {});
      } catch (err) { toast(err.message, "error"); b.disabled = false; }
    });
    side.querySelector("#dv-cancel")?.addEventListener("click", () => {
      const back = byId(memo.sel) ? memo.sel : sorted()[0]?.device_id;
      if (back) select(back, { scroll: false, force: true });
    });
    sync();
    syncMap();
  }

  // ------------------------------------------------------------------ details (read-only users)
  function mappingTable(d) {
    if (!(d.mapping || []).length) return '<p class="note">No mapping: common field names (temperature, humidity, co2 …) are mapped automatically.</p>';
    return `<div class="table-wrap dv-mini"><table class="data"><thead><tr><th>Payload field</th><th>Measurement</th><th class="num">Scale</th><th class="num">Offset</th></tr></thead><tbody>
      ${d.mapping.map((m) => `<tr><td class="mono" data-i18n-skip>${esc(m.field)}</td><td>${esc(M.byKey[m.metric]?.label || m.metric)}</td>
        <td class="num">${esc(rawNum(m.scale ?? 1))}</td><td class="num">${esc(rawNum(m.offset ?? 0))}</td></tr>`).join("")}</tbody></table></div>`;
  }
  function details(d) {
    const side = q("#dv-side");
    side.dataset.dev = d ? d.device_id : "";
    if (!d) {
      side.innerHTML = `<header><h2><span class="ico">${ICONS.sensor}</span>Device details</h2></header>
        <div class="dv-empty"><b>No device selected</b><p>Select a device in the list to see how it connects and what it reports.</p></div>`;
      return;
    }
    const locs = d.locations || [];
    side.innerHTML = `<header><h2><span class="ico">${ICONS.sensor}</span><span class="dv-ttl" data-i18n-skip>${esc(d.name)}</span></h2><span class="meta">${badge(STATE[linkState(d)])}</span></header>
      <div class="body">
        <dl class="kv dv-kvl">
          <dt>Device ID</dt><dd class="mono" data-i18n-skip>${esc(d.device_id)}</dd>
          <dt>Connection</dt><dd>${connBadge(d)}</dd>
          ${d.protocol === "mqtt" ? `<dt>MQTT topic</dt><dd><code data-i18n-skip>${esc(d.topic || "")}</code></dd>` : `<dt>DevEUI</dt><dd class="mono" data-i18n-skip>${esc(d.dev_eui || "")}</dd>`}
          <dt>Model</dt><dd>${d.model ? `<span data-i18n-skip>${esc(d.model)}</span>` : dash}</dd>
          <dt>Region</dt><dd>${d.region ? `<span class="mono" data-i18n-skip>${esc(d.region)}</span>` : dash}</dd>
          <dt>Reporting interval</dt><dd>${esc(fmtInterval(d.interval_s))}</dd>
          <dt>Last reading</dt><dd>${d.last_seen ? `<span title="${esc(fmtDateTime(d.last_seen))}">${esc(ago(d.last_seen))}</span>` : '<span class="dim">never</span>'}</dd>
          <dt>Readings in 24 h</dt><dd class="tnum">${fmtInt(d.uplinks_24h)}</dd>
          <dt>Location</dt><dd>${locs.length ? locs.map((l) => `<div data-i18n-skip>${esc(l)}</div>`).join("") : dash}</dd>
          <dt>Coordinates</dt><dd>${d.lat !== null && d.lat !== undefined ? `<span class="mono">${(+d.lat).toFixed(5)}, ${(+d.lon).toFixed(5)}</span>` : dash}</dd>
          ${d.notes ? `<dt>Notes</dt><dd data-i18n-skip>${esc(d.notes)}</dd>` : ""}
        </dl>
        <div class="dv-sec"><div class="section-title">Payload mapping</div>${mappingTable(d)}</div>
        ${payloadHtml(d, false)}
        ${statsHtml(d)}
      </div>`;
  }

  // ------------------------------------------------------------------ chart of the selected device
  function dropPlot() { const p = q("#dv-plot"); if (p?._ro) { p._ro.disconnect(); p._ro = null; } }
  function markSeg(sel, attr, val) {
    $$(`${sel} [data-${attr}]`, wrap).forEach((b) => { const on = b.dataset[attr] === val; b.classList.toggle("on", on); b.setAttribute("aria-pressed", String(on)); });
  }
  function renderChart() {
    const box = q("#dv-chart"), d = mode === "view" ? byId(memo.sel) : null;
    dropPlot();
    chart.seq++; chart.device = null;                       // drops answers to earlier requests
    if (!d) { box.hidden = true; box.innerHTML = ""; return; }
    const keys = metricsOf(M, d);
    if (!keys.includes(memo.metric)) memo.metric = keys[0] || null;
    chart.keys = keys.join();
    box.hidden = false;
    box.innerHTML = `<header class="dv-chart-head"><h2><span class="ico">${ICONS.analytics}</span>Readings</h2><span class="dv-chart-dev" data-i18n-skip>${esc(d.name)}</span>
        ${keys.length ? `<div class="seg" id="dv-range" role="group" aria-label="Time range">${RANGES.map(([h, l]) => `<button type="button" data-h="${h}" class="${memo.hours === h ? "on" : ""}" aria-pressed="${memo.hours === h}">${l}</button>`).join("")}</div>` : ""}</header>
      <div class="body">${keys.length ? `
        <div class="seg dv-metrics" id="dv-metric" role="group" aria-label="Measurement">${keys.map((k) => `<button type="button" data-m="${esc(k)}" class="${k === memo.metric ? "on" : ""}" aria-pressed="${k === memo.metric}">${esc(M.byKey[k].label)}</button>`).join("")}</div>
        <div class="dv-sum" id="dv-sum"></div>
        <div class="dv-plot" id="dv-plot"></div>
        <div id="dv-legend"></div>
        <div id="dv-chart-note"></div>`
      : '<div class="dv-empty"><b>No readings yet</b><p>The chart appears after the first accepted reading from this device.</p></div>'}</div>`;
    if (!keys.length) return;
    q("#dv-range").addEventListener("click", (e) => {
      const b = e.target.closest("[data-h]"); if (!b) return;
      memo.hours = +b.dataset.h; markSeg("#dv-range", "h", b.dataset.h); loadSeries();
    });
    q("#dv-metric").addEventListener("click", (e) => {
      const b = e.target.closest("[data-m]"); if (!b) return;
      memo.metric = b.dataset.m; markSeg("#dv-metric", "m", memo.metric); loadSeries();
    });
    loadSeries();
  }
  async function loadSeries() {
    const d = byId(memo.sel), metric = memo.metric, hours = memo.hours;
    if (!d || !metric || !q("#dv-plot")) return;
    const my = ++chart.seq;
    chart.device = null;                                     // live points wait for this series
    dropPlot();
    q("#dv-plot").innerHTML = '<div class="empty">Loading…</div>';
    q("#dv-legend").innerHTML = "";
    paintSum();
    try {
      const r = await api(`/devices/${encodeURIComponent(d.device_id)}/series`, { params: { ...Q(), metric, hours } });
      if (!alive || my !== chart.seq) return;
      Object.assign(chart, { device: d.device_id, metric, hours, res: r.resolution, points: r.points || [], lo: r.min, hi: r.max, until: r.until || nowS(), truncated: !!r.truncated });
      drawChart();
    } catch (err) {
      if (alive && my === chart.seq && q("#dv-plot")) q("#dv-plot").innerHTML = `<div class="empty">${esc(err.message)}</div>`;
    }
  }
  function drawChart() {
    const plot = q("#dv-plot");
    if (!plot || !chart.device || chart.device !== memo.sel) return;
    const m = M.byKey[chart.metric], isTemp = TEMP.has(chart.metric);
    const cv = (v) => (isTemp ? conv(v, "temp") : v);
    const u = isTemp ? unit("temp") : m.unit;
    const color = PALETTE[0];                                 // read at draw time: the palette follows Night / Day
    const raw = chart.points.map(([x, v]) => [x, cv(v)]);
    const rawBand = chart.res === "hourly" && chart.lo?.length && chart.hi?.length
      ? chart.lo.map((p, i) => [p[0], cv(p[1]), cv(chart.hi[i]?.[1] ?? p[1])]) : null;
    // Break the line where the device was silent, so outages show as gaps (same rule as the Silent state;
    // hourly buckets also allow one empty hour). The band has no null support: it collapses to zero height instead.
    const dev = byId(chart.device), silentS = Math.max(SILENT_FACTOR * (dev?.interval_s || 900), SILENT_MIN_S);
    const brk = chart.res === "hourly" ? Math.max(5400, silentS + 3600) : silentS;
    const points = [];
    raw.forEach((p, i) => { if (i && p[0] - raw[i - 1][0] > brk) points.push([raw[i - 1][0] + 1, null]); points.push(p); });
    let band = null;
    if (rawBand) {
      band = [];
      rawBand.forEach((b, i) => {
        const prev = rawBand[i - 1];
        if (i && b[0] - prev[0] > brk) band.push([prev[0] + 1, prev[1], prev[1]], [b[0] - 1, prev[1], prev[1]]);
        band.push(b);
      });
    }
    lineChart(plot, {
      height: 260, xType: "time", unit: u ? ` ${u}` : "", area: !band, xDomain: [chart.until - chart.hours * 3600, chart.until],
      yFormat: (v) => fmtNum(v, m.decimals), empty: "No readings in this period",
      series: [{ name: m.label, color, points, band, markers: raw.length < 3 }],
    });
    q("#dv-legend").innerHTML = band && points.length
      ? legend([{ name: "Hourly mean", color, line: true }, { name: "Hourly minimum to maximum", color: `color-mix(in srgb, ${color} 30%, transparent)` }]) : "";
    paintSum();
    paintNote();
  }
  function paintSum() {
    const box = q("#dv-sum"), d = byId(memo.sel), metric = memo.metric;
    if (!box) return;
    if (!d || !metric) { box.innerHTML = ""; return; }
    const latest = d.values?.[metric];
    const ready = chart.device === d.device_id && chart.metric === metric;
    const vals = ready ? chart.points.map((p) => p[1]) : [];
    const hourly = ready && chart.res === "hourly";
    // reduce, not Math.min(...): spreading up to 20000 values can overflow the call stack
    const least = (a) => (a.length ? a.reduce((x, y) => (y < x ? y : x)) : null);
    const most = (a) => (a.length ? a.reduce((x, y) => (y > x ? y : x)) : null);
    const lo = hourly && chart.lo?.length ? least(chart.lo.map((p) => p[1])) : least(vals);
    const hi = hourly && chart.hi?.length ? most(chart.hi.map((p) => p[1])) : most(vals);
    const mean = vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null;
    const cell = (label, v, sub = "") => `<div><span class="label">${label}</span><div class="v">${v === null || v === undefined ? "–" : numHtml(M, metric, v)}</div>${sub}</div>`;
    box.innerHTML = cell("Latest", latest?.value, latest ? `<div class="nh-sub" title="${esc(fmtDateTime(latest.ts))}">${esc(ago(latest.ts))}</div>` : "")
      + cell("Minimum", lo) + cell("Average", mean) + cell("Maximum", hi)
      + `<div><span class="label">${hourly ? "Hours with data" : "Readings"}</span><div class="v tnum">${ready ? fmtInt(vals.length) : "–"}</div></div>`;
  }
  function paintNote() {
    const box = q("#dv-chart-note"), d = byId(memo.sel);
    if (!box) return;
    const untrusted = d?.values?.[memo.metric]?.trusted === false;
    box.innerHTML = `<p class="note">${chart.res === "hourly" ? "Hourly means with the minimum to maximum range. Hourly summaries are kept after raw readings expire."
      : "Every stored reading, at the time it was measured."}</p>${chart.truncated && chart.device === memo.sel
      ? '<p class="note">This period has more readings than the chart can hold: only the most recent are shown.</p>' : ""}${untrusted ? '<p class="note dv-untrusted">Readings from an unsigned device are marked untrusted</p>' : ""}`;
  }

  // ------------------------------------------------------------------ LoRaWAN connections (can_edit)
  const SRC_FIELDS = [
    { k: "name", label: "Name", required: true, maxlength: 80, placeholder: "e.g. TTN farm application" },
    { k: "kind", label: "Network server", type: "select", options: KINDS },
  ];
  function srcRow(s) {
    return `<tr class="${s.revoked_at ? "dim" : ""}"><td><b data-i18n-skip>${esc(s.name)}</b>
        <div class="nh-sub dv-by"><span data-i18n-skip>${esc(s.created_by)}</span><span class="tnum">${esc(fmtDateTime(s.created_at).slice(0, 16))}</span></div></td>
      <td>${esc(VIA[s.kind] || s.kind)}</td>
      <td class="mono" data-i18n-skip>${esc(s.prefix)}…</td>
      <td>${s.last_used_at ? `<span title="${esc(fmtDateTime(s.last_used_at))}">${esc(ago(s.last_used_at))}</span>` : '<span class="dim">never</span>'}</td>
      <td class="num">${fmtInt(s.uplinks)}</td>
      <td>${s.revoked_at ? badge(["neutral", "Revoked"]) : badge(["good", "Active"])}</td>
      <td class="num">${s.revoked_at ? "" : `<button type="button" class="btn sm danger" data-revoke="${esc(s.id)}">Revoke</button>`}</td></tr>`;
  }
  function keyBox(r) {
    const ttn = r.kind === "ttn", url = ttn ? M.webhooks.ttn : M.webhooks.chirpstack, bearer = `Bearer ${r.key}`;
    const steps = ttn ? [
      `<span>Open your application in The Things Stack console and go to</span> <b class="dv-path" dir="ltr" data-i18n-skip>Integrations → Webhooks → Add webhook → Custom webhook</b>`,
      `<span>Webhook format</span> <b class="dv-path" data-i18n-skip>JSON</b>`,
      `<span>Base URL</span>${copyRow(url, "Base URL")}`,
      `<span>Additional header</span> <code>Authorization</code>${copyRow(bearer, "Authorization header")}`,
      `<span>Enabled event types: only</span> <b class="dv-path" data-i18n-skip>Uplink message</b> <span>(leave its path empty)</span>`,
      "<span>Save the webhook. Readings appear with each device's next uplink.</span>",
    ] : [
      `<span>Open the application in ChirpStack and go to</span> <b class="dv-path" dir="ltr" data-i18n-skip>Integrations → HTTP</b>`,
      `<span>Payload encoding</span> <b class="dv-path" data-i18n-skip>JSON</b>`,
      `<span>Event endpoint URL</span>${copyRow(url, "Event endpoint URL")}`,
      `<span>Headers</span> <code>Authorization</code>${copyRow(bearer, "Authorization header")}`,
      "<span>Submit. Uplinks arrive with each device's next transmission; status events add the battery level.</span>",
    ];
    return `<div class="secret-box dv-secret" role="status">
      <b>Copy this key now — it will not be shown again.</b>
      ${copyRow(r.key, "Connection key")}
      <div class="section-title">${ttn ? "Set up The Things Stack" : "Set up ChirpStack v4"}</div>
      <ol class="dv-steps">${steps.map((s) => `<li>${s}</li>`).join("")}</ol>
      ${isPublic(M.webhooks) ? "" : `<p class="dv-addr-warn">${HOOK_WARN}</p>`}
      <p class="note">Devices are matched by DevEUI: register them on the Devices tab first.</p>
      <div class="row"><button type="button" class="btn sm" data-goto="devices">Go to Devices</button><button type="button" class="btn sm ghost" data-done>Close</button></div></div>`;
  }
  async function renderSources() {
    const pane = q('[data-pane="sources"]');
    if (!pane) return;
    if (!pane.childElementCount) pane.innerHTML = '<section class="panel"><div class="empty">Loading…</div></section>';
    let list;
    try { list = (await api("/devices/sources", { params: Q() })).sources || []; }
    catch (err) { if (alive) pane.innerHTML = `<section class="panel"><div class="empty">${esc(err.message)}</div></section>`; return; }
    if (!alive) return;
    const created = lastKey;                                       // the new key's box stays until its Close button
    const active = list.filter((s) => !s.revoked_at).length;
    pane.innerHTML = `<div class="ed-split dv-split">
      <section class="panel"><header><h2><span class="ico">${ICONS.key}</span>LoRaWAN connections</h2><span class="meta"><span>${active}</span> <span>active</span></span></header>
        ${list.length ? `<div class="table-wrap"><table class="data"><thead><tr><th>Name</th><th>Network server</th><th>Key</th><th>Last used</th><th class="num">Uplinks</th><th>Status</th><th></th></tr></thead>
          <tbody>${list.map(srcRow).join("")}</tbody></table></div>`
        : `<div class="dv-empty"><span class="ico">${ICONS.key}</span><b>No LoRaWAN connections yet</b><p>Create a connection key for The Things Stack or ChirpStack, then add it to the network server's webhook. A key works for this company only.</p></div>`}
        <div class="body"><p class="note">Devices are matched by DevEUI, so register them on the Devices tab first. Revoking a key stops its network server immediately.</p></div></section>
      <section class="panel"><header><h2><span class="ico">${ICONS.hook}</span>New connection</h2></header>
        <form class="body" id="dv-src-form">${formHtml(SRC_FIELDS, { kind: "ttn" })}<button class="btn primary" type="submit">${ICONS.key}Create connection key</button></form>
        <div class="body dv-src-out" ${created ? "" : "hidden"}>${created ? keyBox(created) : ""}</div>
        <div class="body dv-endpoints"><div class="section-title">Webhook addresses</div>
          <div><span class="label">The Things Stack</span>${copyRow(M.webhooks.ttn, "The Things Stack webhook URL")}</div>
          <div><span class="label">ChirpStack</span>${copyRow(M.webhooks.chirpstack, "ChirpStack webhook URL")}</div>
          ${isPublic(M.webhooks) ? "" : `<p class="dv-addr-warn">${HOOK_WARN}</p>`}</div></section></div>`;
    pane.querySelector("#dv-src-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const form = e.currentTarget, b = form.querySelector('button[type="submit"]');
      b.disabled = true;
      try {
        const r = await api("/devices/sources", { method: "POST", params: Q(), body: readForm(form, SRC_FIELDS) });
        if (!alive) return;
        toast("Connection key created", "ok");
        lastKey = r;
        await renderSources();
        pane.querySelector(".dv-src-out")?.scrollIntoView({ behavior: smooth(), block: "nearest" });
      } catch (err) { toast(err.message, "error"); b.disabled = false; }
    });
    $$("[data-revoke]", pane).forEach((b) => b.addEventListener("click", async () => {
      if (!confirm(t("Revoke this connection? Its network server can no longer deliver uplinks."))) return;
      b.disabled = true;
      try {
        await api(`/devices/sources/${encodeURIComponent(b.dataset.revoke)}`, { method: "DELETE", params: Q() });
        if (String(lastKey?.id) === b.dataset.revoke) lastKey = null;   // its key box would show a dead key
        if (alive) { toast("Connection revoked", "ok"); renderSources(); }
      } catch (err) { toast(err.message, "error"); b.disabled = false; }
    }));
  }

  // ------------------------------------------------------------------ set-up guide (everyone)
  function renderGuide() {
    const pane = q('[data-pane="guide"]'), mq = M.mqtt, topic = mq.topic;
    // short lines: the guide cards are narrow and code should not need sideways scrolling
    const plain = JSON.stringify({ ts: nowS(), temperature: 24.5, humidity: 61, co2: 812 }, null, 2);
    const envelope = ["{", '  "p": "<JSON text>",', '  "sig": "<hex HMAC-SHA256 of topic + newline + p>"', "}"].join("\n");
    const sub = [`mosquitto_pub -h ${mq.host} -p ${mq.port} \\`, `  -t "${topic}" \\`, `  -m '{"temperature": 24.5, "humidity": 61}'`].join("\n");
    pane.innerHTML = `<div class="dv-guide">
      <section class="panel"><header><h2><span class="ico">${ICONS.shield}</span>MQTT, signed (recommended)</h2></header>
        <div class="body">
          <dl class="dv-dl"><dt>Broker</dt><dd><code data-i18n-skip>${esc(`${mq.host}:${mq.port}`)}</code>${mq.connected ? badge(["good", "Connected"]) : badge(["warning", "Not connected"])}</dd>
            <dt>Topic</dt><dd><code data-i18n-skip>${esc(topic)}</code></dd></dl>
          ${isPublic(mq) ? "" : `<p class="dv-addr-warn">${MQTT_WARN}</p>`}
          <div class="dv-lbl">Message</div>
          <pre class="dv-code">${esc(envelope)}</pre>
          <ul class="dv-list">
            <li>The "p" text is a JSON object with "ts" (Unix seconds) and the readings.</li>
            <li>"sig" is the hexadecimal HMAC-SHA256 of the topic, a newline and "p", keyed with the device secret.</li>
            <li>Each message must be newer than the last one stored: replayed messages are refused.</li>
            <li>Readings up to 7 days late are accepted, so a device can send what it buffered while offline.</li>
          </ul>
          <div class="dv-lbl">Python</div>
          <pre class="dv-code">${esc(pythonCode(M, topic, "<secret>"))}</pre>
        </div></section>
      <section class="panel"><header><h2><span class="ico">${ICONS.sensor}</span>MQTT, unsigned</h2></header>
        <div class="body">
          <dl class="dv-dl"><dt>Topic</dt><dd><code data-i18n-skip>${esc(topic)}</code></dd></dl>
          <div class="dv-lbl">Message</div>
          <pre class="dv-code">${esc(plain)}</pre>
          <ul class="dv-list">
            <li>A plain JSON object. "ts" is optional: without it the arrival time is used.</li>
            <li>Nested objects are allowed; their fields are named with dots, for example climate.co2.</li>
            <li>Readings are stored but marked untrusted, because anyone on a public broker can publish to the topic.</li>
          </ul>
          <div class="dv-lbl">Test from a terminal</div>
          <pre class="dv-code">${esc(sub)}</pre>
        </div></section>
      <section class="panel"><header><h2><span class="ico">${ICONS.tower}</span>LoRaWAN</h2></header>
        <div class="body">
          <ul class="dv-list">
            <li>The Things Stack (v3) and ChirpStack (v4) deliver uplinks to this server by webhook, with a connection key per network server.</li>
            <li>Decode payloads in the network server (payload formatter or codec) so uplinks arrive as JSON objects.</li>
            <li>Devices are matched by DevEUI: register each device on the Devices tab first.</li>
            <li>Signal strength (RSSI and SNR of the best gateway) is stored with every uplink; ChirpStack status events add the battery level.</li>
          </ul>
          ${canEdit ? `<div><button type="button" class="btn" data-goto="sources">${ICONS.key}Use the LoRaWAN connections tab</button></div>`
            : '<p class="note">An administrator creates the connection keys on the LoRaWAN connections tab.</p>'}
        </div></section>
    </div>
    <section class="panel"><header><h2><span class="ico">${ICONS.analytics}</span>Metric catalog</h2><span class="meta">${M.metrics.length}</span></header>
      <div class="body"><p class="note dv-flush">Readings are stored per metric, in the unit below. Values outside the valid range are rejected and not stored. Common field names (temperature, humidity, co2, battery …) are mapped automatically; for other names or units add a mapping with a scale and offset, for example µS/cm to dS/m with scale 0.001.</p></div>
      <div class="table-wrap"><table class="data dv-cat"><thead><tr><th>Key</th><th>Name</th><th>Unit</th><th class="num">Valid range</th></tr></thead><tbody>
        ${groups.map(([label, ms]) => `<tr class="dv-grp"><td colspan="4">${esc(label)}</td></tr>${ms.map((m) => `<tr><td class="mono" data-i18n-skip>${esc(m.key)}</td><td>${esc(m.label)}</td>
          <td>${esc(m.unit)}</td><td class="num">${esc(`${fmtInt(m.min)} – ${fmtInt(m.max)}`)}</td></tr>`).join("")}`).join("")}
      </tbody></table></div></section>`;
  }

  // ------------------------------------------------------------------ tabs, live updates, refresh
  function setTab(k, { reveal = false } = {}) {
    if (!q(`[data-pane="${k}"]`)) k = "devices";
    memo.tab = k;
    $$(".dv-tabs [data-tab]", wrap).forEach((b) => { const on = b.dataset.tab === k; b.classList.toggle("on", on); b.setAttribute("aria-selected", String(on)); });
    $$("[data-pane]", wrap).forEach((p) => { p.hidden = p.dataset.pane !== k; });
    if (k === "sources") renderSources();
    if (k === "guide" && !guideDone) { guideDone = true; renderGuide(); }
    if (reveal) q(".dv-tabs").scrollIntoView({ behavior: smooth(), block: "nearest" });
  }
  async function reload() {
    const my = ++rseq;
    const r = await api("/devices", { params: Q() });
    if (!alive || my !== rseq) return;                       // a newer reload, save or delete has happened since
    data = { ...r, unknown: r.unknown || [] };
    paintAll();
    paintSideLive();
  }
  /** Refresh the side panel's live parts (status, last reading, counts, last payload); form inputs are left alone. */
  function paintSideLive() {
    const side = q("#dv-side"), d = mode === "view" ? byId(memo.sel) : null;
    if (!d || side.dataset.dev !== d.device_id) return;
    const pay = side.querySelector(".dv-payload"), top = pay ? pay.scrollTop : 0;
    if (!canEdit) details(d);
    else {
      const meta = side.querySelector(":scope > header .meta");
      if (meta) meta.innerHTML = badge(STATE[linkState(d)]);
      const facts = side.querySelector(".dv-facts");
      if (facts) facts.outerHTML = factsHtml(d);
      const live = side.querySelector("#dv-live");
      if (live) {
        const had = live.contains(document.activeElement) ? document.activeElement.dataset.map : undefined;
        live.innerHTML = payloadHtml(d, true) + statsHtml(d);
        if (had !== undefined) live.querySelector(`[data-map="${CSS.escape(had)}"]`)?.focus({ preventScroll: true });
      }
    }
    const pay2 = side.querySelector(".dv-payload");
    if (pay2 && top) pay2.scrollTop = top;
  }
  function scheduleReload() {
    clearTimeout(reloadSoon);
    reloadSoon = setTimeout(() => { if (alive) reload().catch(() => {}); }, 1500);
  }
  /** One device_reading event: update the device in memory; painting is throttled to once a second. */
  function applyReading(r) {
    const d = byId(r.device_id);
    if (!d) { scheduleReload(); return; }                     // registered in another session since the page loaded
    d.values = d.values || {};
    for (const [k, v] of Object.entries(r.values || {})) {
      const cur = d.values[k];
      if (!cur || r.ts >= cur.ts) d.values[k] = { value: v, ts: r.ts, trusted: r.trusted };
    }
    d.last_seen = Math.max(d.last_seen || 0, r.received_at || nowS());
    d.measured_at = Math.max(d.measured_at || 0, r.ts || 0);
    if (r.ts >= nowS() - 86400) d.uplinks_24h = (d.uplinks_24h || 0) + 1;
    if (d.device_id === memo.sel) selTouched = true;
    const v = r.values?.[chart.metric];
    if (chart.device === d.device_id && chart.hours === 24 && chart.res === "raw" && v !== undefined) {
      const span = chart.hours * 3600;
      chart.until = Math.max(chart.until, nowS());           // the 24 h window moves with the clock
      // only readings inside the window (a device clock may run up to 10 min ahead; the window then follows it)
      if (Number.isFinite(r.ts) && r.ts >= chart.until - span && r.ts <= chart.until + 600) {
        chart.until = Math.max(chart.until, r.ts);
        const pts = chart.points;
        if (!pts.some((p) => p[0] === r.ts)) {
          pts.push([r.ts, v]);
          if (pts.length > 1 && pts[pts.length - 2][0] > r.ts) pts.sort((a, b) => a[0] - b[0]);
        }
      }
      const lo = chart.until - span;                         // points that left the window are dropped
      if (chart.points.length && chart.points[0][0] < lo) chart.points = chart.points.filter((p) => p[0] >= lo);
      chartDirty = true;
    }
  }
  function flushLive() {
    liveTimer = null;
    if (!alive) return;
    paintTiles(); paintFilter(); paintTable();
    const d = mode === "view" ? byId(memo.sel) : null;
    if (d && selTouched) {
      if (metricsOf(M, d).join() !== chart.keys) renderChart();      // a new metric appeared: rebuild the selector
      else if (chartDirty) drawChart();
      else { paintSum(); paintNote(); }
      paintSideLive();
    }
    selTouched = false; chartDirty = false;
  }

  // shared buttons: copy, close a secret box, jump to a tab, register a device
  wrap.addEventListener("click", async (e) => {
    const cp = e.target.closest("[data-copy]");
    if (cp) { const ok = await copy(cp.dataset.copy); toast(ok ? "Copied" : "Copy failed", ok ? "ok" : "error"); return; }
    const done = e.target.closest("[data-done]");
    if (done) {
      if (done.closest(".dv-src-out")) lastKey = null; else shownSecret = null;
      done.closest(".secret-box")?.remove();
      return;
    }
    const go = e.target.closest("[data-goto]");
    if (go) { setTab(go.dataset.goto, { reveal: true }); return; }
    if (e.target.closest("[data-new]")) openNew();
  });
  $$(".dv-tabs [data-tab]", wrap).forEach((b) => b.addEventListener("click", () => setTab(b.dataset.tab)));
  q("#dv-q").addEventListener("input", (e) => { memo.q = e.target.value; paintTable(); });
  q("#dv-filter").addEventListener("click", (e) => {
    const b = e.target.closest("[data-f]"); if (!b) return;
    memo.filter = b.dataset.f; paintFilter(); paintTable();
  });
  q("#dv-rows").addEventListener("click", (e) => { const tr = e.target.closest("tr[data-id]"); if (tr) select(tr.dataset.id); });
  q("#dv-rows").addEventListener("keydown", (e) => {
    if (e.key !== "Enter" && e.key !== " ") return;
    const tr = e.target.closest("tr[data-id]"); if (!tr) return;
    e.preventDefault(); select(tr.dataset.id);
  });
  q("#dv-new")?.addEventListener("click", () => openNew());
  q("#dv-unknown").addEventListener("click", (e) => {
    const b = e.target.closest("[data-reg]");
    const u = b && data.unknown[+b.dataset.reg];
    if (u) openNew(presetFrom(u));
  });

  if (memo.sel && !byId(memo.sel)) memo.sel = null;
  if (!memo.sel && data.devices.length) memo.sel = sorted()[0].device_id;
  mode = memo.sel ? "view" : "new";
  paintAll();
  renderSide();
  renderChart();
  setTab(memo.tab);

  const off = onEvent((m) => {
    if (m.type === "socket" && m.data?.open) { scheduleReload(); return; }      // may have missed readings
    if (m.type !== "device_reading" || m.company !== state.company || !m.data) return;
    applyReading(m.data);
    if (!liveTimer) liveTimer = setTimeout(flushLive, 1000);
  });
  const tick = setInterval(() => { if (alive) { paintTiles(); paintFilter(); paintTable(); paintSideLive(); } }, 30000);   // ages and silent states
  const poll = setInterval(() => { if (alive && !document.hidden) reload().catch(() => {}); }, 60000);   // unknown devices, counts
  return () => {
    alive = false;
    off();
    clearTimeout(liveTimer); clearTimeout(reloadSoon);
    clearInterval(tick); clearInterval(poll);
    dropPlot();
    hideTip();
  };
}
