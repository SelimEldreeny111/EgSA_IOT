// World operations: every company's sites on one map with live node status and local time.
/* global L */
import { api, state, ICONS, ago, badge, $, $$ } from "../api.js";
import { esc, fmtNum } from "../charts.js";
import { t, I18N } from "../i18n.js";
import { flag, countryName } from "./org.js";

const STATUS_COLOR = { ok: "#22c55e", partial: "#f59e0b", down: "#ef4444", idle: "#94a3b8" };
const siteStatus = (s) => (!s.nodes ? "idle" : s.online === s.nodes ? "ok" : s.online === 0 ? "down" : "partial");
const STATUS_LABEL = { ok: "All nodes online", partial: "Some nodes need attention", down: "All nodes offline", idle: "No nodes reporting" };
const localTime = (tz) => { try { return new Date().toLocaleTimeString("en-GB", { timeZone: tz, hour: "2-digit", minute: "2-digit", hourCycle: "h23" }); } catch { return "–"; } };
const utcOffset = (tz) => {
  try {
    const p = new Intl.DateTimeFormat("en-US", { timeZone: tz, timeZoneName: "shortOffset" }).formatToParts(new Date()).find((x) => x.type === "timeZoneName");
    return p ? p.value.replace("GMT", "UTC") : "";
  } catch { return ""; }
};

export async function render(root) {
  let map = null, layer = null, timer = null, data = null, ro = null;
  root.innerHTML = `<div class="agri-kpis world-kpis" id="w-kpis"></div>
    <div class="farm-grid world-grid">
      <section class="panel map-panel"><div id="farm-map"></div>
        <div class="map-overlay tl glass" id="w-legend"></div></section>
      <section class="panel zone-panel"><header><h2><span class="ico">${ICONS.world}</span>${t("Companies & sites")}</h2><span class="meta" id="w-meta"></span></header>
        <div class="body world-list" id="w-list"></div></section>
    </div>`;

  function kpis() {
    const cs = data.companies, sites = cs.flatMap((c) => c.sites);
    const countries = new Set([...cs.map((c) => c.country), ...sites.map((s) => s.country)].filter(Boolean));
    const nodes = sites.reduce((a, s) => a + s.nodes, 0), online = sites.reduce((a, s) => a + s.online, 0);
    const cards = [
      [ICONS.world, "Countries", countries.size, [...countries].map(flag).join(" ") || "–"],
      [ICONS.org, "Companies", cs.length, `${cs.filter((c) => c.sites.some((s) => s.nodes)).length} ${t("with live sites")}`],
      [ICONS.region, "Sites", sites.length, `${sites.filter((s) => s.lat !== null && s.lat !== undefined).length} ${t("on the map")}`],
      [ICONS.node, "Nodes online", `${online}<small>/ ${nodes}</small>`, `${sites.reduce((a, s) => a + s.offline, 0)} ${t("offline")} · ${sites.reduce((a, s) => a + s.late, 0)} ${t("late")}`, online < nodes ? "warn" : "hl"],
      [ICONS.overview, "Uplinks · 24 h", fmtNum(sites.reduce((a, s) => a + s.uplinks_24h, 0), 0), t("all sites")],
      [ICONS.clock, "Time zones", new Set(cs.map((c) => c.timezone)).size, [...new Set(cs.map((c) => utcOffset(c.timezone)))].join(" · ")],
    ];
    $("#w-kpis", root).innerHTML = cards.map(([ic, l, v, s, cls]) => `<div class="agri-kpi ${cls || ""}"><div class="ak-ico">${ic}</div><div><div class="label">${t(l)}</div><div class="ak-v">${v}</div><div class="ak-s">${s}</div></div></div>`).join("");
  }

  function initMap() {
    map = L.map($("#farm-map", root), { zoomControl: false, worldCopyJump: true, minZoom: 2 }).setView([24, 20], 3);
    L.tileLayer(data.map.tiles, { maxZoom: 19, maxNativeZoom: 18, attribution: esc(data.map.attribution) }).addTo(map);
    if (data.map.labels) L.tileLayer(data.map.labels, { maxZoom: 19, maxNativeZoom: 18, opacity: 0.8 }).addTo(map);
    L.control.zoom({ position: "bottomright" }).addTo(map);
    layer = L.layerGroup().addTo(map);
    ro = new ResizeObserver(() => map && map.invalidateSize({ pan: false }));
    ro.observe($("#farm-map", root));
  }

  function goto(company, region, page) {
    window.dispatchEvent(new CustomEvent("wiot:goto", { detail: { company, region, page } }));
  }

  function paintMap(fit) {
    layer.clearLayers();
    const b = L.latLngBounds([]);
    data.companies.forEach((c) => c.sites.forEach((s) => {
      if (s.lat === null || s.lat === undefined) return;
      const st = siteStatus(s), col = STATUS_COLOR[st], r = 9 + Math.min(16, Math.sqrt(s.nodes) * 4);
      const halo = L.circleMarker([s.lat, s.lon], { radius: r + 9, color: col, weight: 0, fillColor: col, fillOpacity: 0.18, interactive: false }).addTo(layer);
      if (st !== "idle") halo.getElement()?.classList.add("w-pulse");
      const m = L.circleMarker([s.lat, s.lon], { radius: r, color: "#fff", weight: 2, fillColor: col, fillOpacity: 0.92 }).addTo(layer);
      m.bindTooltip(`<b>${esc(c.display_name)}</b> · ${esc(s.name)}`, { direction: "top", offset: [0, -r] });
      m.bindPopup(`<div class="w-pop"><div class="w-pop-h">${flag(s.country || c.country)} <b>${esc(s.name)}</b></div>
        <div class="muted">${esc(c.display_name)} · <span class="mono">${esc(s.region)}</span></div>
        <div class="w-pop-g"><span>${t("Online")}</span><b>${s.online}/${s.nodes}</b><span>${t("Uplinks · 24 h")}</span><b>${fmtNum(s.uplinks_24h, 0)}</b>
        <span>${t("Last seen")}</span><b>${s.last_seen ? ago(s.last_seen) : "–"}</b><span>${t("Local time")}</span><b>${localTime(c.timezone)} <small>${esc(utcOffset(c.timezone))}</small></b></div>
        <div class="row"><button class="btn sm primary" data-go="farm">${t("Open farm")}</button><button class="btn sm" data-go="overview">${t("Fleet overview")}</button></div></div>`);
      m.on("popupopen", (e) => e.popup.getElement().querySelectorAll("[data-go]").forEach((btn) =>
        btn.addEventListener("click", () => goto(c.name, s.region, btn.dataset.go))));
      b.extend([s.lat, s.lon]);
    }));
    if (fit && b.isValid()) map.fitBounds(b.pad(0.6), { maxZoom: 6 });
  }

  function legend() {
    $("#w-legend", root).innerHTML = `<div class="lg-title">${t("Site status")}</div>` +
      Object.entries(STATUS_LABEL).map(([k, l]) => `<div class="lg-row"><i style="background:${STATUS_COLOR[k]}"></i>${t(l)}</div>`).join("") +
      `<div class="lg-row muted" style="margin-top:4px">${t("Marker size = number of nodes")}</div>`;
  }

  function list() {
    const cs = data.companies;
    $("#w-meta", root).textContent = `${cs.length} · ${new Date().toLocaleTimeString("en-GB", { hour12: false })}`;
    $("#w-list", root).innerHTML = cs.map((c, i) => {
      const nodes = c.sites.reduce((a, s) => a + s.nodes, 0), online = c.sites.reduce((a, s) => a + s.online, 0);
      const unplaced = c.sites.filter((s) => s.lat === null || s.lat === undefined);
      return `<div class="w-card ${c.name === state.company ? "sel" : ""}" data-i="${i}">
        <div class="w-card-h"><span class="w-flag">${flag(c.country)}</span><div class="grow"><b>${esc(c.display_name)}</b>
          <div class="muted sm">${esc(countryName(c.country) || t("Country not set"))} · <span class="mono">${esc(c.timezone)}</span></div></div>
          <div class="w-time"><b class="mono">${localTime(c.timezone)}</b><div class="muted sm">${esc(utcOffset(c.timezone))}</div></div></div>
        <div class="w-card-s">${badge(nodes ? (online === nodes ? ["good", `${online}/${nodes} online`] : ["warning", `${online}/${nodes} online`]) : ["neutral", "No nodes"])}
          <span class="muted sm">${c.sites.length} ${t(c.sites.length === 1 ? "site" : "sites")} · ${t(c.units === "imperial" ? "Imperial" : "Metric")}</span></div>
        ${c.sites.map((s) => `<div class="w-site" data-go="${esc(c.name)}|${esc(s.region)}"><i style="background:${STATUS_COLOR[siteStatus(s)]}"></i>
          <span class="grow">${esc(s.name)}</span><span class="mono sm">${s.online}/${s.nodes}</span>${s.lat === null || s.lat === undefined ? `<span class="muted sm" title="${t("Add coordinates on the Organization page")}">${t("not on map")}</span>` : ""}</div>`).join("")}
        ${!c.sites.length ? `<div class="muted sm">${t("No sites yet — add regions on the Organization page.")}</div>` : ""}
        ${unplaced.length && state.user.permissions.command ? `<a class="sm" href="#/org">${t("Set locations")} →</a>` : ""}</div>`;
    }).join("") || `<div class="empty">${t("No companies")}</div>`;
    $$(".w-card", root).forEach((el) => el.addEventListener("click", (e) => {
      if (e.target.closest("[data-go], a")) return;
      const c = cs[+el.dataset.i], pts = c.sites.filter((s) => s.lat !== null && s.lat !== undefined).map((s) => [s.lat, s.lon]);
      if (pts.length) map.flyToBounds(L.latLngBounds(pts).pad(0.8), { maxZoom: 9, duration: 1.2 });
      else if (c.lat !== null && c.lat !== undefined) map.flyTo([c.lat, c.lon], 7);
    }));
    $$(".w-site", root).forEach((el) => el.addEventListener("click", () => { const [c, r] = el.dataset.go.split("|"); goto(c, r, "farm"); }));
  }

  async function load(first) {
    const [w, farm] = await Promise.all([api("/org/world"), first ? api("/farm/overview", { params: { company: state.company, region: state.region } }) : null]);
    data = { ...w, map: farm?.map || data?.map };
    if (first) initMap();
    kpis(); paintMap(first); legend(); list();
  }
  await load(true);
  timer = setInterval(() => load(false).catch(() => {}), 30000);
  return () => { clearInterval(timer); ro?.disconnect(); map?.remove(); };
}
