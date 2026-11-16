// Satellite viewer (R2.7): the Copernicus Browser's layers on the farm map, and every satellite dataset over the farm.
// Images come from /api/v2/eo/render.png (Copernicus Sentinel Hub, or the open Sentinel-2 archive without an account);
// the availability timeline from /api/v2/eo/availability. Global L = Leaflet (vendor).
import { api, state, toast, ICONS, $, $$ } from "../api.js";
import { esc, fmtNum } from "../charts.js";
import { t } from "../i18n.js";

const int = (n) => Number(n || 0).toLocaleString("en-US");
const RENDERER = { sentinelhub: "Copernicus Sentinel Hub", open: "open Sentinel-2 archive (AWS)" };
const BROWSER_DS = { S2L2A: "S2_L2A_CDAS", S2L1C: "S2L1C_CDAS", S1GRD: "S1_CDAS_IW_VVVH", S3OLCI: "S3OLCI_CDAS", S3SLSTR: "S3SLSTR_CDAS" };

function swatch(colors) {
  return `<span class="sv-sw" style="background:linear-gradient(135deg,${colors.map(esc).join(",")})"></span>`;
}

function legendHtml(lg) {
  if (!lg) return "";
  if (lg.kind === "ramp") {
    const s = lg.stops, lo = s[0].value, hi = s[s.length - 1].value;
    const grad = s.map((x) => `${esc(x.color)} ${(((x.value - lo) / (hi - lo)) * 100).toFixed(1)}%`).join(",");
    const mid = (lo + hi) / 2;
    return `<div class="sv-legend"><div class="sv-ramp" style="background:linear-gradient(90deg,${grad})"></div>
      <div class="sv-ramp-lbl"><span>${fmtNum(lo, 2)}</span><span>${fmtNum(mid, 2)}</span><span>${fmtNum(hi, 2)}${lg.unit ? ` ${esc(lg.unit)}` : ""}</span></div></div>`;
  }
  return `<div class="sv-legend sv-classes">${lg.items.map((i) => `<span><i style="background:${esc(i.color)}"></i>${esc(i.label)}</span>`).join("")}</div>`;
}

export async function mountViewer(host) {
  const cfg = await api("/eo/layers", { params: { company: state.company } });
  const missions = cfg.missions.filter((m) => m.renderers.length);
  host.innerHTML = `<section class="panel sv"><header><h2><span class="ico">${ICONS.world}</span>Satellite viewer</h2>
      <span class="meta" id="sv-src">${missions.length ? "" : "not configured"}</span></header>
    ${missions.length ? "" : `<div class="body"><div class="inv-link">Satellite imagery is off on this server. Set WIOT_SATELLITE_PROVIDER to auto or open for Sentinel-2 from the open archive without an account (needs numpy and Pillow, the analytics extra). With a free Copernicus Data Space account, also set WIOT_SENTINEL_CLIENT_ID and WIOT_SENTINEL_CLIENT_SECRET for Sentinel-1, -2 and -3 layers.</div></div>`}
    <div class="sv-wrap" ${missions.length ? "" : "hidden"}>
      <aside class="sv-side">
        <div class="field"><label for="sv-mission">Satellite</label><select class="input" id="sv-mission">
          ${missions.map((m) => `<option value="${esc(m.id)}">${esc(m.title)} · ${esc(m.resolution)}</option>`).join("")}</select>
          <small class="dim" id="sv-about"></small></div>
        <div class="field"><label for="sv-date">Date</label><select class="input" id="sv-date"><option value="">Latest image (last 30 days)</option></select>
          <small class="dim" id="sv-date-note">Pass dates appear when the catalogue has answered.</small></div>
        <div class="field" id="sv-cloud-f"><label for="sv-cloud">Maximum cloud cover <b id="sv-cloud-v">30 %</b></label>
          <input type="range" id="sv-cloud" min="0" max="100" step="5" value="30"></div>
        <div class="sv-h">Layers</div>
        <div class="sv-layers" id="sv-layers" role="listbox" aria-label="Layers"></div>
      </aside>
      <div class="sv-main">
        <div class="sv-tools">
          <label class="sv-op" for="sv-op"><span>Opacity</span><input type="range" id="sv-op" min="0" max="100" step="5" value="100"><b id="sv-op-v">100 %</b></label>
          <label class="sv-chk"><input type="checkbox" id="sv-fields" checked> <span>Field outlines</span></label>
          <span class="sv-tools-end"><button class="btn sm" type="button" id="sv-dl">${ICONS.download}<span>Download image</span></button>
            <a class="btn sm" id="sv-cb" target="_blank" rel="noopener noreferrer">Open in Copernicus Browser</a></span>
        </div>
        <div class="sv-mapbox"><div id="sv-map" class="sv-map"></div><div class="sv-status" id="sv-status" aria-live="polite"></div></div>
      </div>
    </div></section>`;
  if (!missions.length || !host.isConnected) {
    return { setAvailability() {}, destroy() {}, goTo() { toast("This satellite cannot be drawn on this server", "error"); } };
  }

  const st = { mission: missions[0].id, layer: "TRUE_COLOR", date: "", cloud: 30, opacity: 1, fields: true,
    custom: { mode: "composite", r: "B12", g: "B08", b: "B04", a: "B08", b2: "B11", script: "" }, dates: {} };
  const map = L.map($("#sv-map", host), { zoomControl: false, zoomSnap: 0.25 });
  map.createPane("svImages").style.zIndex = 350;          // satellite images under the field outlines
  L.tileLayer(cfg.map.tiles, { maxZoom: 19, maxNativeZoom: 18, attribution: esc(cfg.map.attribution) }).addTo(map);
  L.control.zoom({ position: "bottomright" }).addTo(map);
  L.control.scale({ position: "bottomright", imperial: false }).addTo(map);
  const fieldLayer = L.geoJSON({ type: "FeatureCollection", features: cfg.fields.map((f) => ({ type: "Feature", properties: { name: f.name }, geometry: f.geometry })) },
    { style: { color: "#facc15", weight: 1.6, fill: false, opacity: 0.95 }, interactive: false }).addTo(map);
  if (cfg.bbox) map.fitBounds([[cfg.bbox[1], cfg.bbox[0]], [cfg.bbox[3], cfg.bbox[2]]], { padding: [30, 30] });
  else map.setView([26.8, 30.8], 6);
  setTimeout(() => map.invalidateSize(), 50);

  let overlay = null, overlayUrl = null, overlayName = "", pending = null, seq = 0, timer = null;
  const status = (html, kind = "") => { const el = $("#sv-status", host); el.className = `sv-status ${kind}`; el.innerHTML = html; el.hidden = !html; };
  const layersOf = (m) => cfg.layers.filter((l) => l.missions.includes(m));
  const layerInfo = () => cfg.layers.find((l) => l.id === st.layer);
  const usable = (l) => l.renderers.length > 0;

  function drawSide() {
    const m = missions.find((x) => x.id === st.mission);
    $("#sv-about", host).textContent = m.about;
    $("#sv-cloud-f", host).hidden = !m.cloud;
    if (!layersOf(st.mission).some((l) => l.id === st.layer && usable(l))) st.layer = (layersOf(st.mission).find(usable) || {}).id;
    $("#sv-layers", host).innerHTML = layersOf(st.mission).map((l) => `<button type="button" class="sv-layer ${l.id === st.layer ? "on" : ""}" data-l="${esc(l.id)}"
        role="option" aria-selected="${l.id === st.layer}" ${usable(l) ? "" : "disabled title=\"Needs the Copernicus Sentinel Hub account\""}>
        ${swatch(l.swatch)}<span><b>${esc(l.title)}</b><small>${esc(l.about)}</small></span></button>
        ${l.id === st.layer && (l.legend || l.id === "CUSTOM") ? `<div class="sv-detail">${legendHtml(l.legend)}${l.id === "CUSTOM" ? `<div id="sv-custom" class="sv-custom"></div>` : ""}</div>` : ""}`).join("");
    $$("[data-l]", host).forEach((b) => b.addEventListener("click", () => { if (b.dataset.l !== st.layer) { st.layer = b.dataset.l; drawSide(); schedule(0); } }));
    drawCustom();
    drawDates();
    drawLink();
  }

  function drawLink() {                                   // the same place and date in the Copernicus Browser
    const c = map.getCenter();
    const q = new URLSearchParams({ zoom: Math.round(map.getZoom()), lat: c.lat.toFixed(5), lng: c.lng.toFixed(5), themeId: "DEFAULT-THEME", datasetId: BROWSER_DS[st.mission] || "" });
    if (st.date) { q.set("fromTime", `${st.date}T00:00:00.000Z`); q.set("toTime", `${st.date}T23:59:59.999Z`); }
    $("#sv-cb", host).href = `https://browser.dataspace.copernicus.eu/?${q}`;
  }

  function drawCustom() {
    const box = $("#sv-custom", host);
    if (!box) return;
    const c = st.custom, opts = (v) => cfg.bands.map((b) => `<option ${b === v ? "selected" : ""}>${esc(b)}</option>`).join("");
    const sh = cfg.own_evalscript;                        // the supervisor, with the Copernicus account
    box.innerHTML = `<div class="seg" role="group" aria-label="Custom type">
        <button type="button" class="${c.mode === "composite" ? "on" : ""}" data-m="composite">Composite</button>
        <button type="button" class="${c.mode === "index" ? "on" : ""}" data-m="index">Index</button>
        ${sh ? `<button type="button" class="${c.mode === "script" ? "on" : ""}" data-m="script">Evalscript</button>` : ""}</div>
      ${c.mode === "composite" ? `<div class="sv-bands"><label>R<select class="input" data-c="r">${opts(c.r)}</select></label>
        <label>G<select class="input" data-c="g">${opts(c.g)}</select></label><label>B<select class="input" data-c="b">${opts(c.b)}</select></label></div>` : ""}
      ${c.mode === "index" ? `<div class="sv-bands"><label>A<select class="input" data-c="a">${opts(c.a)}</select></label>
        <label>B<select class="input" data-c="b2">${opts(c.b2)}</select></label></div><small class="dim">Index = (A − B) / (A + B)</small>` : ""}
      ${c.mode === "script" ? `<label class="sr-only" for="sv-script">Evalscript</label><textarea class="input mono" id="sv-script" rows="9" spellcheck="false"
        placeholder="//VERSION=3&#10;function setup() { … }&#10;function evaluatePixel(s) { … }">${esc(c.draft ?? c.script)}</textarea>
        <button class="btn sm primary" type="button" id="sv-run">Run evalscript</button>
        <small class="dim">Runs at Copernicus Sentinel Hub, not on this server, and uses the account's processing units.</small>` : ""}`;
    $$("[data-m]", box).forEach((b) => b.addEventListener("click", () => { c.mode = b.dataset.m; drawCustom(); if (c.mode !== "script") schedule(0); }));
    $$("[data-c]", box).forEach((s) => s.addEventListener("change", () => { c[s.dataset.c] = s.value; schedule(0); }));
    $("#sv-script", box)?.addEventListener("input", (e) => { c.draft = e.target.value; });
    $("#sv-run", box)?.addEventListener("click", () => { c.script = $("#sv-script", box).value; c.draft = c.script; schedule(0); });
  }

  function drawDates() {
    const sel = $("#sv-date", host), key = st.mission === "S2L1C" ? "S2L2A" : st.mission, items = st.dates[key];
    if (!items) {
      sel.innerHTML = `<option value="">Latest image (last 30 days)</option>`;
      $("#sv-date-note", host).textContent = st.datesLoaded ? "No pass dates of this satellite from the catalogue."
        : "Pass dates appear when the catalogue has answered.";
      return;
    }
    const seen = new Set();
    const rows = items.filter((i) => !seen.has(i.date) && seen.add(i.date));
    sel.innerHTML = `<option value="">Latest image (last 30 days)</option>` + rows.map((i) =>
      `<option value="${esc(i.date)}" ${i.date === st.date ? "selected" : ""}>${esc(i.date)} · ${esc(i.platform || "")}${i.cloud == null ? "" : ` · ${fmtNum(i.cloud, 0)} % cloud`}</option>`).join("");
    $("#sv-date-note", host).textContent = `${rows.length} pass dates over this farm in the catalogue.`;
  }

  const dropPending = () => {                              // an image still loading is replaced by a newer one
    if (!pending) return;
    map.removeLayer(pending.layer);
    URL.revokeObjectURL(pending.url);
    pending = null;
  };
  const clearOverlay = () => {
    seq += 1;
    dropPending();
    if (overlay) map.removeLayer(overlay);
    if (overlayUrl) URL.revokeObjectURL(overlayUrl);
    overlay = null; overlayUrl = null;
  };
  const cloudOf = (meta) => meta.cloud ?? (st.dates[st.mission === "S2L1C" ? "S2L2A" : st.mission] || []).find((i) => i.date === meta.from)?.cloud;

  function schedule(ms = 450) { clearTimeout(timer); timer = setTimeout(renderNow, ms); }

  async function renderNow() {
    if (!host.isConnected) return;
    if (!st.layer) { status("No layer of this satellite can be drawn on this server.", "warn"); return; }
    if (map.getZoom() < 8) { clearOverlay(); status("Zoom in to see a satellite image of the area.", "warn"); return; }
    const id = ++seq, b = map.getBounds(), size = map.getSize(), k = Math.min(window.devicePixelRatio || 1, 1.5);
    const bounds = L.latLngBounds(b.getSouthWest(), b.getNorthEast());
    const q = { mission: st.mission, layer: st.layer, west: b.getWest().toFixed(6), south: b.getSouth().toFixed(6), east: b.getEast().toFixed(6),
      north: b.getNorth().toFixed(6), width: Math.min(1600, Math.round(size.x * k)), height: Math.min(1600, Math.round(size.y * k)), cloud: st.cloud };
    if (st.date) q.date = st.date;
    const c = st.custom;
    let req;
    if (st.layer === "CUSTOM" && c.mode === "script") {
      if (!c.script.trim()) { status("Write an evalscript and press Run evalscript.", "warn"); return; }
      req = api("/eo/render.png", { method: "POST", raw: true,
        body: { ...q, west: +q.west, south: +q.south, east: +q.east, north: +q.north, evalscript: c.script, date: st.date || null } });
    } else {
      if (st.layer === "CUSTOM") Object.assign(q, c.mode === "composite" ? { mode: "composite", bands: `${c.r},${c.g},${c.b}` } : { mode: "index", bands: `${c.a},${c.b2}` });
      req = api("/eo/render.png", { params: q, raw: true });
    }
    const slow = (layerInfo()?.renderers || [])[0] === "open" && !cfg.sentinelhub;
    status(`<span class="sv-spin"></span>Drawing ${esc(layerInfo()?.title || st.layer)}${slow ? " from the open archive (up to a minute the first time)" : ""}…`);
    try {
      const res = await req;
      if (id !== seq) return;
      const wait = res.status === 503 ? Number(res.headers.get("Retry-After")) : 0;
      if (wait > 0) {                                     // the server is drawing other images: ask again shortly
        status(`<span class="sv-spin"></span>Waiting for the server to draw the image…`);
        schedule(Math.min(wait, 30) * 1000);
        return;
      }
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        const msg = typeof d.detail === "string" ? d.detail : Array.isArray(d.detail) ? d.detail.map((x) => x.msg).join("; ") : `Error ${res.status}`;
        status(esc(msg), "error");
        return;
      }
      const meta = JSON.parse(res.headers.get("X-Imagery") || "{}");
      const url = URL.createObjectURL(await res.blob());
      if (id !== seq) { URL.revokeObjectURL(url); return; }
      dropPending();
      const next = L.imageOverlay(url, bounds, { opacity: st.opacity, interactive: false, className: "sv-img", pane: "svImages" }).addTo(map);
      const name = `wiot_${q.mission}_${q.layer}_${q.date || meta.from || "latest"}.png`;
      pending = { layer: next, url };
      next.once("load", () => {
        if (pending?.layer !== next) return;               // a newer image took its place meanwhile
        pending = null;
        if (overlay) map.removeLayer(overlay);
        if (overlayUrl) URL.revokeObjectURL(overlayUrl);
        overlay = next; overlayUrl = url; overlayName = name;
      });
      next.once("error", () => {
        if (pending?.layer !== next) return;
        dropPending();
        if (id === seq) status("The image could not be shown.", "error");
      });
      const when = meta.mosaic === "leastCC" ? `least-cloudy mosaic ${meta.from} – ${meta.to}` : meta.mosaic === "mostRecent" && !st.date
        ? `most recent pass, ${meta.from} – ${meta.to}` : `${meta.from}${cloudOf(meta) != null ? ` · ${fmtNum(cloudOf(meta), 0)} % cloud` : ""}`;
      $("#sv-src", host).textContent = `${RENDERER[meta.provider] || meta.provider}${meta.cached ? " · cached" : ""}`;
      status(`${esc(missions.find((m) => m.id === st.mission).title)} · ${esc(layerInfo()?.title || "")} · ${esc(when)}`, "ok");
    } catch (err) { if (id === seq) status(esc(err.message), "error"); }
  }

  map.on("moveend", () => { drawLink(); schedule(); });
  $("#sv-mission", host).addEventListener("change", (e) => { st.mission = e.target.value; st.date = ""; drawSide(); schedule(0); });
  $("#sv-date", host).addEventListener("change", (e) => { st.date = e.target.value; drawSide(); schedule(0); });
  $("#sv-cloud", host).addEventListener("input", (e) => { st.cloud = +e.target.value; $("#sv-cloud-v", host).textContent = `${st.cloud} %`; });
  $("#sv-cloud", host).addEventListener("change", () => schedule(0));
  $("#sv-op", host).addEventListener("input", (e) => { st.opacity = e.target.value / 100; $("#sv-op-v", host).textContent = `${e.target.value} %`; overlay?.setOpacity(st.opacity); });
  $("#sv-fields", host).addEventListener("change", (e) => { st.fields = e.target.checked; if (st.fields) fieldLayer.addTo(map); else map.removeLayer(fieldLayer); });
  $("#sv-dl", host).addEventListener("click", () => {
    if (!overlayUrl) { toast("Nothing drawn yet", "error"); return; }
    const a = document.createElement("a");
    a.href = overlayUrl; a.download = overlayName; a.click();
  });
  drawSide();
  schedule(0);

  return {
    setAvailability(av) {
      st.dates = {};
      for (const m of av.missions || []) if (m.ok) st.dates[m.id] = m.items;
      st.datesLoaded = true;
      drawDates();
    },
    destroy() {
      clearTimeout(timer);
      clearOverlay();
      map.remove();
    },
    goTo(mission, date) {
      if (!missions.some((m) => m.id === mission)) { toast("This satellite cannot be drawn on this server", "error"); return; }
      st.mission = mission; st.date = date;
      $("#sv-mission", host).value = mission;
      drawSide(); schedule(0);
      host.scrollIntoView({ behavior: "smooth", block: "start" });
    },
  };
}

// ------------------------------------------------------------------------------------------ availability
export function mountAvailability(host, viewer) {
  host.innerHTML = `<section class="panel"><header><h2><span class="ico">${ICONS.clock}</span>Satellite data over this farm</h2>
      <label class="sr-only" for="av-days">Period</label>
      <select class="input" id="av-days" style="margin-inline-start:auto;max-width:160px;height:32px">
        <option value="30">Last 30 days</option><option value="90" selected>Last 90 days</option><option value="180">Last 6 months</option><option value="365">Last 12 months</option></select></header>
    <div class="body" id="av-body"><div class="empty"><span class="sv-spin"></span>Asking the Copernicus, Earth Search and EUMETSAT catalogues…</div></div></section>`;

  let gen = 0;
  async function load() {
    const days = +$("#av-days", host).value, my = ++gen;
    $("#av-body", host).innerHTML = `<div class="empty"><span class="sv-spin"></span>Asking the Copernicus, Earth Search and EUMETSAT catalogues…</div>`;
    let d;
    try { d = await api("/eo/availability", { params: { company: state.company, days } }); }
    catch (err) { if (my === gen && host.isConnected) $("#av-body", host).innerHTML = `<div class="empty">${esc(err.message)}</div>`; return; }
    if (my !== gen || !host.isConnected) return;          // a newer period was chosen meanwhile, or the page was left
    viewer.setAvailability(d);
    const start = new Date(`${d.from}T00:00:00Z`), n = Math.round((new Date(`${d.to}T00:00:00Z`) - start) / 86400000) + 1;
    const dayOf = (i) => new Date(start.getTime() + i * 86400000).toISOString().slice(0, 10);
    const cls = (m, items) => {
      if (!items.length) return "";
      if (m === "S2L2A" || m === "LANDSAT") { const c = Math.min(...items.map((x) => x.cloud ?? 100)); return c < 10 ? "clear" : c < 40 ? "partly" : "cloudy"; }
      return "pass";
    };
    const strip = (m) => {
      const byDay = {};
      for (const it of m.items || []) (byDay[it.date] ||= []).push(it);
      return `<div class="av-strip" style="grid-template-columns:repeat(${n},minmax(0,1fr));--gap:${n > 120 ? 0 : 1}px">${Array.from({ length: n }, (_, i) => {
        const day = dayOf(i), its = byDay[day] || [], c = cls(m.id, its);
        const tip = its.length ? `${day}: ${its.map((x) => `${x.platform || ""} ${x.time || ""}${x.cloud == null ? "" : ` · ${t(`${fmtNum(x.cloud, 0)} % cloud`)}`}${x.orbit ? ` · ${t(`orbit ${x.orbit}`)}` : ""}`).join(" | ")}` : day;
        return `<button type="button" class="av-day ${c}" ${its.length && m.viewer ? `data-go="${esc(m.id)}" data-day="${day}"` : "tabindex=\"-1\""} title="${esc(tip)}" aria-label="${esc(tip)}"></button>`;
      }).join("")}</div>`;
    };
    const months = Array.from({ length: n }, (_, i) => dayOf(i)).filter((x, i) => i === 0 || x.endsWith("-01"));
    const head = `<div class="av-row av-head"><div></div><div class="av-axis">${months.map((m) => `<span style="inset-inline-start:${((new Date(`${m}T00:00:00Z`) - start) / 86400000 / n * 100).toFixed(2)}%">${m.slice(0, 7)}</span>`).join("")}</div><div></div></div>`;
    const rows = d.missions.map((m) => `<div class="av-row"><div class="av-name"><b>${esc(m.title)}</b><small>${esc(m.source)}</small></div>
      ${m.ok ? strip(m) : `<div class="av-err">Catalogue not reachable: ${esc(m.error || "")}</div>`}
      <div class="av-count">${m.ok ? `<b>${int(m.count)}${m.exact === false ? "+" : ""}</b><small>${m.items[0] ? `latest ${esc(m.items[0].date)}` : "none"}</small>${m.partial ? `<small class="av-partial">older passes not drawn</small>` : ""}` : ""}</div></div>`).join("");
    const eum = d.eumetsat.map((e) => `<tr><td>${esc(e.title)}</td><td class="mono sm">${esc(e.id)}</td>
      <td class="num">${e.ok ? int(e.count) : "–"}</td><td>${e.ok && e.latest ? `<bdi class="mono sm">${esc(String(e.latest).slice(0, 16).replace("T", " "))}</bdi>` : `<span class="dim">${e.ok ? "none over this farm" : esc(e.error || "")}</span>`}</td></tr>`).join("");
    const nd = d.server.ndvi || [], wsat = d.server.wiot_sat || [];
    $("#av-body", host).innerHTML = `<div class="av-scroll"><div style="min-width:${Math.round(n * 1.4) + 180}px">${head}${rows}</div></div>
      <div class="av-legend"><span><i class="av-day clear"></i>clear (&lt; 10 % cloud)</span><span><i class="av-day partly"></i>partly cloudy</span>
        <span><i class="av-day cloudy"></i>cloudy</span><span><i class="av-day pass"></i>pass</span>
        <span class="dim"><span>Click a day to open it in the viewer.</span> <span>Data from ${esc(d.from)} to ${esc(d.to)}${d.cached ? " (cached)" : ""}.</span></span></div>
      <div class="table-wrap" style="margin-top:14px"><table class="data"><thead><tr><th>EUMETSAT product (Meteosat, Metop)</th><th>Collection</th><th class="num">Products in period</th><th>Latest (UTC)</th></tr></thead>
        <tbody>${eum}</tbody></table></div>
      <p class="note"><span>On this server:</span> <span>${nd.length ? `NDVI of the fields stored for ${fmtNum(nd.length, 0)} passes (latest ${esc(nd[0].date)}, ${esc(nd[0].source)})` : "no field NDVI stored in this period"}</span>;
        <span>${wsat.length ? `${fmtNum(wsat.length, 0)} WIOT-SAT products` : "no WIOT-SAT products"}</span>. <span>Download Meteosat products in the EUMETSAT Data Store panel below.</span></p>`;
    $$("[data-go]", host).forEach((b) => b.addEventListener("click", () => viewer.goTo(b.dataset.go, b.dataset.day)));
  }
  $("#av-days", host).addEventListener("change", load);
  load();
}
