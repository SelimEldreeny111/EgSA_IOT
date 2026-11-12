// Smart farm: satellite map with live zones, irrigation control, weather/ET0, satellite readiness.
/* global L */
import { api, state, onEvent, scoped, ago, badge, LINK_BADGE, toast, ICONS, $, $$, h } from "../api.js";
import { esc, gauge, lineChart, barChart, fmtNum, fmtDateTime, PALETTE, T, legend } from "../charts.js";
import { fmtU, fmtUs, conv, unit } from "../units.js";
import { I18N } from "../i18n.js";

// Agronomic status colours (semantic, fixed in both views; always shown with a label).
const STATUS = {
  dry: { color: "#f59e0b", label: "Below target", cls: "warning" },
  optimal: { color: "#22c55e", label: "In target band", cls: "good" },
  wet: { color: "#3b82f6", label: "Above target", cls: "info" },
  offline: { color: "#94a3b8", label: "Node offline", cls: "critical" },
  no_data: { color: "#94a3b8", label: "No data", cls: "neutral" },
  sensor_fault: { color: "#ef4444", label: "Probe fault", cls: "critical" },
};
const LAYERS = { moisture: "Soil moisture", ec: "Salinity (EC)", temp: "Soil temp", irrigation: "Irrigation" };
const ICON = {
  drop: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 3s6 6.5 6 11a6 6 0 0 1-12 0c0-4.5 6-11 6-11z"/></svg>',
  pivot: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M12 12l6-5"/><circle cx="12" cy="12" r="1.5" fill="currentColor"/></svg>',
  alert: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 3 2 21h20L12 3z"/><path d="M12 10v5M12 18v.5"/></svg>',
  water: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 15c3-2 6 2 9 0s6-2 9 0M3 19c3-2 6 2 9 0s6-2 9 0M12 3l3 5a3 3 0 1 1-6 0l3-5z"/></svg>',
  sun: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>',
  cloud: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M7 18h10a4 4 0 0 0 .5-8A6 6 0 0 0 6 9.5 4.3 4.3 0 0 0 7 18z"/></svg>',
  "cloud-sun": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 4.5V3M4.9 6.4l-1-1M3.5 11H2M12.8 6.2A4 4 0 0 0 6 9.5"/><path d="M9 20h8a3.5 3.5 0 0 0 .4-7A5 5 0 0 0 8 13a3.5 3.5 0 0 0 1 7z"/></svg>',
  rain: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M7 15h10a4 4 0 0 0 .5-8A6 6 0 0 0 6 6.5 4.3 4.3 0 0 0 7 15z"/><path d="M8 18l-1 3M12 18l-1 3M16 18l-1 3"/></svg>',
  fog: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 10h16M3 14h18M6 18h12M7 6h10"/></svg>',
  storm: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M7 14h10a4 4 0 0 0 .5-8A6 6 0 0 0 6 5.5 4.3 4.3 0 0 0 7 14z"/><path d="m12 15-2 4h4l-2 4"/></svg>',
  snow: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2v20M4 7l16 10M20 7 4 17"/></svg>',
  wind: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 8h11a3 3 0 1 0-3-3M3 12h16a3 3 0 1 1-3 3M3 16h8"/></svg>',
  gauge: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 18a9 9 0 1 1 16 0"/><path d="m12 14 4-5"/></svg>',
  sat: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m13 7 4 4-6 6-4-4z"/><path d="m15 5 2-2 4 4-2 2M9 15l-2 2-4-4 2-2M3 21a6 6 0 0 1 6-6"/></svg>',
  tower: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 9v13M8 22l4-13 4 13M9 17h6"/><path d="M8.5 5.5a5 5 0 0 0 0 7M15.5 5.5a5 5 0 0 1 0 7M5.6 2.6a9 9 0 0 0 0 12.8M18.4 2.6a9 9 0 0 1 0 12.8"/></svg>',
  cell: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 20v-3M9 20v-6M14 20V10M19 20V5"/></svg>',
  cloudsrv: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M7 18h10a4 4 0 0 0 .5-8A6 6 0 0 0 6 9.5 4.3 4.3 0 0 0 7 18z"/><path d="M10 13h4"/></svg>',
  check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="m5 12 5 5 9-10"/></svg>',
  cross: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M6 6l12 12M18 6 6 18"/></svg>',
};
const pct = (v) => (v === null || v === undefined ? "–" : `${(+v).toFixed(1)}%`);
const dest = (lat, lon, m, deg) => {
  const r = (deg * Math.PI) / 180;
  return [lat + (m * Math.cos(r)) / 111320, lon + (m * Math.sin(r)) / (111320 * Math.cos((lat * Math.PI) / 180))];
};
function ramp(v, lo, hi, stops) {
  if (v === null || v === undefined) return "#94a3b8";
  const t = Math.max(0, Math.min(1, (v - lo) / (hi - lo))), i = Math.min(stops.length - 2, Math.floor(t * (stops.length - 1)));
  const f = t * (stops.length - 1) - i, a = stops[i], b = stops[i + 1];
  const c = (k) => Math.round(parseInt(a.slice(k, k + 2), 16) * (1 - f) + parseInt(b.slice(k, k + 2), 16) * f).toString(16).padStart(2, "0");
  return `#${c(1)}${c(3)}${c(5)}`;
}
const EC_RAMP = ["#22c55e", "#a3e635", "#facc15", "#fb923c", "#ef4444"];
const TEMP_RAMP = ["#38bdf8", "#22c55e", "#facc15", "#f97316", "#dc2626"];

export async function render(root) {
  let data = null, map = null, layer = "moisture", selected = null, editMode = false, refreshTimer = null;
  const lyr = { zones: [], chips: [], arms: [], devices: [], links: [], gw: [] };
  let armTimer = null, armAngle = 0, resizeObs = null, setup = null;

  const skeleton = () => {
    root.innerHTML = `<div class="agri-kpis" id="kpis"></div>
    <div class="farm-grid">
      <section class="panel map-panel"><div id="farm-map"></div>
        <div class="map-overlay tl glass" id="site-card"></div>
        <div class="map-overlay tr glass" id="wx-card"></div>
        <div class="map-overlay bl glass" id="legend-card"></div>
        <div class="map-overlay br glass" id="bh-card"></div>
      </section>
      <section class="panel zone-panel" id="zone"><div class="empty">Select a field on the map</div></section>
    </div>
    <div class="grid g-wide" style="margin-top:16px">
      <section class="panel"><header><h2><span class="ico">${ICON.drop}</span>Irrigation plan · all fields</h2><span class="meta" id="plan-meta"></span></header>
        <div class="table-wrap"><table class="data"><thead><tr><th>Field</th><th>Crop</th><th>Soil moisture vs target</th><th>Status</th><th>Valve</th><th class="num">Flow <small>${unit("flow")}</small></th><th class="num">Today <small>${unit("volume")}</small></th><th>Advice</th><th>Auto</th></tr></thead><tbody id="plan"></tbody></table></div></section>
      <section class="panel"><header><h2><span class="ico">${ICON.sun}</span>Weather &amp; evapotranspiration · 7 days</h2><span class="meta" id="wx-meta"></span></header><div class="body" id="wx"></div></section>
    </div>
    <section class="panel" style="margin-top:16px"><header><h2><span class="ico">${ICON.sat}</span>Connectivity &amp; satellite backhaul readiness</h2>
      <span class="meta"><label>Satellite budget <input class="input mono" id="budget" type="number" min="1" max="10000" value="48" style="width:80px;padding:3px 6px;display:inline-block"> msgs/node/day</label></span></header>
      <div class="body" id="sat"></div></section>`;
    $("#budget", root).addEventListener("change", paintSatellite);
  };
  skeleton();

  // ------------------------------------------------------------------ data
  async function load() {
    data = await api("/farm/overview", { params: scoped() });
    if (!data.configured) return renderUnconfigured();
    if (!map) initMap();
    paintKpis(); paintMap(); paintPlan(); paintWeather(); paintSiteCard();
    if (!selected || !data.zones.find((z) => z.id === selected)) selected = (data.zones.find((z) => z.status === "dry") || data.zones[0])?.id;
    paintZone();
  }

  // ------------------------------------------- farm set-up (no layout yet)
  const DEMO = "Demo_AgriFarm";
  const CROPS = ["Wheat", "Maize", "Alfalfa", "Potato", "Sugar beet", "Tomato", "Vegetables", "Olive", "Date palm", "Citrus", "Other"];

  async function layoutSaved() {
    teardownSetup();
    skeleton();
    await load();
    if (data?.configured) paintSatellite().catch(() => {});
  }
  function teardownSetup() {
    if (!setup) return;
    setup.ro.disconnect();
    setup.map.remove();
    setup = null;
  }
  function demoButton() {
    return state.company !== DEMO && (state.companies || []).includes(DEMO) ? `<button class="btn" id="open-demo">${ICON.pivot}Open the demo farm</button>` : "";
  }
  function wireDemo() {
    $("#open-demo", root)?.addEventListener("click", () => {
      const sel = document.getElementById("sel-company");
      if (!sel) return;
      sel.value = DEMO;
      sel.dispatchEvent(new Event("change"));
    });
  }

  async function renderUnconfigured() {
    if (setup) return; // the builder is already open: keep what the user has entered
    if (!state.user.permissions.command) {
      root.innerHTML = `<section class="panel"><div class="body setup-empty">
        <div class="setup-icon">${ICON.pivot}</div>
        <h2>No farm map for ${esc(state.company)} yet</h2>
        <p class="dim">An administrator or supervisor can place this company's nodes on the satellite map as irrigation fields.
        Live readings for these nodes are already on the Overview page.</p>
        <div class="row" style="justify-content:center">${demoButton()}<a class="btn" href="#/overview">Open overview</a></div></div></section>`;
      wireDemo();
      return;
    }

    // Nodes that have reported for this company, in every region.
    const nodes = [];
    for (const region of state.regions?.length ? state.regions : ["Region_1"]) {
      try {
        (await api("/fleet", { params: { company: state.company, region } })).nodes
          .forEach((n) => nodes.push({ node_id: n.node_id, region, link: n.link_state || "offline" }));
      } catch { /* region without data */ }
    }
    const f = { radius: 100, min: 26, max: 38, gw: null,
      fields: nodes.map((n, i) => ({ ...n, name: `Field ${i + 1}`, crop: "Wheat", pos: null })) };

    root.innerHTML = `
      <section class="panel"><div class="body row setup-intro">
        <div class="setup-icon sm">${ICON.pivot}</div>
        <div class="grow"><h2>Set up the farm map · ${esc(state.company)}</h2>
          <div class="dim">${nodes.length} node${nodes.length === 1 ? "" : "s"} reported for this company. Place them on the satellite map as irrigation fields —
          this only saves the map; nothing is sent to the nodes.</div></div>
        <div class="row">${demoButton()}</div></div></section>
      <div class="farm-grid" style="margin-top:16px">
        <section class="panel map-panel"><div id="farm-map"></div>
          <div class="map-overlay tl glass setup-steps" id="setup-hint"></div></section>
        <section class="panel zone-panel"><header><h2><span class="ico">${ICON.drop}</span>Farm details</h2></header>
          <div class="body setup-form">
            <label class="label" for="s-name">Farm name</label>
            <input class="input" id="s-name" maxlength="100" value="${esc(state.company)} farm">
            <label class="label" for="s-loc">Location</label>
            <input class="input" id="s-loc" maxlength="150" placeholder="e.g. East Owainat, New Valley, Egypt">
            <label class="label" for="s-lat">Gateway position · latitude, longitude</label>
            <div class="row nowrap"><input class="input mono" id="s-lat" placeholder="22.2489" inputmode="decimal">
              <input class="input mono" id="s-lon" placeholder="28.7116" inputmode="decimal"><button class="btn sm" id="s-go">Place</button></div>
            <div class="two">
              <div><label class="label" for="s-r">Field radius · m</label><input class="input mono" id="s-r" type="number" min="10" max="5000" step="10" value="${f.radius}"></div>
              <div><label class="label" for="s-min">Moisture target · %</label>
                <div class="row nowrap"><input class="input mono" id="s-min" type="number" min="0" max="100" step="0.5" value="${f.min}"><span class="muted">to</span>
                <input class="input mono" id="s-max" type="number" min="0" max="100" step="0.5" value="${f.max}"></div></div>
            </div>
            <label class="label">Fields · one per node</label>
            <div id="s-fields"></div>
            <label class="label" for="s-primary">Gateway backhaul</label>
            <div class="row nowrap"><select class="input" id="s-primary"><option value="cellular">Cellular</option><option value="wifi">Wi-Fi</option>
              <option value="ethernet">Ethernet</option><option value="satellite">Satellite</option></select>
              <label class="check"><input type="checkbox" id="s-sat" checked> Satellite-ready</label></div>
            <button class="btn primary setup-save" id="s-save" disabled>Save farm layout</button>
            <details class="setup-adv"><summary>Advanced · paste a layout JSON</summary>
              <p class="muted">Same format as <span class="mono">wiot/data/demo_farm_layout.json</span> (pivots or polygons, gateways, probes).</p>
              <textarea class="input mono" id="layout-json" rows="8" placeholder='{"site": {"name": "...", "center": [lat, lon], "zoom": 14}, "zones": [...], "devices": [...], "gateways": [...]}'></textarea>
              <button class="btn sm" id="save-json">Validate &amp; save JSON</button></details>
          </div></section>
      </div>`;
    wireDemo();

    const smap = L.map($("#farm-map", root), { zoomControl: false, zoomSnap: 0.25 }).setView([26.8, 30.8], 6);
    L.tileLayer(data.map.tiles, { maxZoom: 19, maxNativeZoom: 18, attribution: esc(data.map.attribution) }).addTo(smap);
    if (data.map.labels) L.tileLayer(data.map.labels, { maxZoom: 19, maxNativeZoom: 18, opacity: 0.75 }).addTo(smap);
    L.control.zoom({ position: "bottomright" }).addTo(smap);
    L.control.scale({ position: "bottomright", imperial: false }).addTo(smap);
    const ro = new ResizeObserver(() => smap.invalidateSize({ pan: false }));
    ro.observe($("#farm-map", root));
    const group = L.layerGroup().addTo(smap);
    setup = { map: smap, ro };

    const hint = () => {
      $("#setup-hint", root).innerHTML = !nodes.length
        ? `No nodes have reported for ${esc(state.company)} yet — fields appear here once they send data.`
        : f.gw ? `<b>Step 2</b> · Drag the gateway and each field (F1${nodes.length > 1 ? `–F${nodes.length}` : ""}) onto their real positions, then <b>Save farm layout</b>.`
          : `<b>Step 1</b> · Zoom to the farm and click where its gateway stands — or type its coordinates.`;
    };
    const arrange = () => { // starting positions: a neat grid just north of the gateway
      const cols = Math.ceil(Math.sqrt(f.fields.length)), sp = f.radius * 2.4;
      f.fields.forEach((x, i) => {
        const c = i % cols, r = Math.floor(i / cols);
        const north = f.radius * 1.9 + r * sp, east = (c - (cols - 1) / 2) * sp;
        x.pos = [f.gw[0] + north / 111320, f.gw[1] + east / (111320 * Math.cos((f.gw[0] * Math.PI) / 180))];
      });
    };
    const draw = () => {
      group.clearLayers();
      if (!f.gw) return;
      f.fields.forEach((x, i) => {
        const circle = L.circle(x.pos, { radius: f.radius, color: "#4ade80", weight: 2, fillColor: "#22c55e", fillOpacity: 0.18 }).addTo(group);
        const pin = L.marker(x.pos, { draggable: true, autoPan: true, icon: L.divIcon({ className: "", iconSize: [44, 26], iconAnchor: [22, 13], html: `<div class="setup-pin">F${i + 1}</div>` }) }).addTo(group);
        pin.bindTooltip(esc(x.name), { direction: "top", offset: [0, -12] });
        pin.on("drag", (e) => circle.setLatLng(e.target.getLatLng()));
        pin.on("dragend", (e) => { const p = e.target.getLatLng(); x.pos = [p.lat, p.lng]; });
      });
      const gw = L.marker(f.gw, { draggable: true, autoPan: true, zIndexOffset: 1000, icon: L.divIcon({ className: "", iconSize: [36, 36], iconAnchor: [18, 18], html: `<div class="setup-gw">${ICON.tower}</div>` }) }).addTo(group);
      gw.bindTooltip("Gateway", { direction: "top", offset: [0, -16] });
      gw.on("dragend", (e) => { const p = e.target.getLatLng(); f.gw = [p.lat, p.lng]; syncInputs(); });
    };
    const syncInputs = () => { $("#s-lat", root).value = f.gw[0].toFixed(6); $("#s-lon", root).value = f.gw[1].toFixed(6); };
    const place = (lat, lon) => {
      f.gw = [lat, lon];
      arrange(); syncInputs(); draw(); hint();
      $("#s-save", root).disabled = !nodes.length;
      const b = L.latLngBounds([f.gw, f.gw]);
      f.fields.forEach((x) => b.extend(L.latLng(x.pos).toBounds(f.radius * 2)));
      smap.flyToBounds(b.pad(0.6), { maxZoom: 17, duration: 0.8 });
    };
    const paintFields = () => {
      $("#s-fields", root).innerHTML = f.fields.length ? f.fields.map((x, i) => `<div class="setup-field" data-i="${i}">
          <span class="setup-tag">F${i + 1}</span>
          <div class="grow"><input class="input" data-k="name" maxlength="60" value="${esc(x.name)}" aria-label="Field ${i + 1} name">
            <div class="muted mono setup-node">Node ${x.node_id} · ${esc(x.region)} · ${esc(x.link)}</div></div>
          <select class="input" data-k="crop" aria-label="Field ${i + 1} crop">${CROPS.map((c) => `<option ${c === x.crop ? "selected" : ""}>${c}</option>`).join("")}</select>
        </div>`).join("")
        : `<div class="empty">No nodes have reported for this company yet.</div>`;
      $$(".setup-field", root).forEach((row) => row.querySelectorAll("[data-k]").forEach((inp) => inp.addEventListener("input", () => {
        f.fields[+row.dataset.i][inp.dataset.k] = inp.value;
        if (inp.dataset.k === "name" && f.gw) draw();
      })));
    };

    smap.on("click", (e) => { if (!f.gw && nodes.length) place(e.latlng.lat, e.latlng.lng); });
    $("#s-go", root).addEventListener("click", () => {
      const lat = parseFloat($("#s-lat", root).value), lon = parseFloat($("#s-lon", root).value);
      if (!(lat >= -90 && lat <= 90 && lon >= -180 && lon <= 180)) { toast("Enter latitude and longitude in decimal degrees", "error"); return; }
      place(lat, lon);
    });
    $("#s-r", root).addEventListener("change", (e) => {
      f.radius = Math.max(10, Math.min(5000, +e.target.value || 100));
      e.target.value = f.radius;
      draw();
    });
    $("#s-min", root).addEventListener("change", (e) => { f.min = +e.target.value; });
    $("#s-max", root).addEventListener("change", (e) => { f.max = +e.target.value; });
    $("#s-save", root).addEventListener("click", async () => {
      if (!f.gw || !f.fields.length) return;
      if (!(f.min < f.max)) { toast("The moisture target needs a lower value on the left", "error"); return; }
      const name = $("#s-name", root).value.trim() || `${state.company} farm`;
      const pts = f.fields.map((x) => x.pos).concat([f.gw]);
      const center = [pts.reduce((a, p) => a + p[0], 0) / pts.length, pts.reduce((a, p) => a + p[1], 0) / pts.length];
      const primary = $("#s-primary", root).value;
      const backhaul = ["lora", primary];
      if ($("#s-sat", root).checked && primary !== "satellite") backhaul.push("satellite");
      const layout = {
        site: { name, location: $("#s-loc", root).value.trim(), center, zoom: 15, timezone: "Africa/Cairo" },
        gateways: [{ id: "GW-01", name: "Farm gateway", lat: f.gw[0], lon: f.gw[1], backhaul, primary }],
        zones: f.fields.map((x, i) => ({ id: `F-${i + 1}`, name: x.name.trim() || `Field ${i + 1}`, crop: x.crop, shape: "circle",
          center: x.pos, radius_m: f.radius, node_id: x.node_id, region: x.region, moisture_min: f.min, moisture_max: f.max, auto_irrigation: false })),
        devices: f.fields.map((x) => {
          const p = dest(x.pos[0], x.pos[1], f.radius * 0.45, 150); // probe beside the field's centre label
          return { node_id: x.node_id, region: x.region, lat: p[0], lon: p[1], label: `${(x.name.trim() || "Field").slice(0, 60)} · probe`, gateway: "GW-01" };
        }),
      };
      const btn = $("#s-save", root);
      btn.disabled = true;
      try {
        await api("/farm/layout", { method: "PUT", params: { company: state.company }, body: layout });
        toast("Farm layout saved", "ok");
        await layoutSaved();
      } catch (err) { toast(err.message, "error"); btn.disabled = false; }
    });
    $("#save-json", root).addEventListener("click", async () => {
      try {
        await api("/farm/layout", { method: "PUT", params: { company: state.company }, body: JSON.parse($("#layout-json", root).value) });
        toast("Layout saved", "ok");
        await layoutSaved();
      } catch (err) { toast(err.message, "error"); }
    });
    paintFields();
    hint();
  }

  // ------------------------------------------------------------------- map
  function initMap() {
    map = L.map($("#farm-map", root), { zoomControl: false, attributionControl: true, zoomSnap: 0.25, preferCanvas: false })
      .setView(data.site.center, data.site.zoom);
    L.tileLayer(data.map.tiles, { maxZoom: 19, maxNativeZoom: 18, attribution: esc(data.map.attribution) }).addTo(map);
    if (data.map.labels) L.tileLayer(data.map.labels, { maxZoom: 19, maxNativeZoom: 18, opacity: 0.75 }).addTo(map);
    L.control.zoom({ position: "bottomright" }).addTo(map);
    const b = L.latLngBounds([]);
    data.zones.forEach((z) => (z.shape === "polygon" ? z.polygon.forEach((p) => b.extend(p)) : b.extend(L.latLng(z.center).toBounds(z.radius_m * 2))));
    data.gateways.forEach((g) => b.extend([g.lat, g.lon]));
    // Small plots (campus test beds) need a closer view than pivots so their labels do not overlap.
    if (b.isValid()) map.fitBounds(b, { paddingTopLeft: [40, 120], paddingBottomRight: [40, 40], maxZoom: 18.75 });
    L.control.scale({ position: "bottomright", imperial: false }).addTo(map);
    armTimer = setInterval(spinArms, 60);
    // Keep Leaflet's viewport in sync with CSS layout changes (grid reflow, theme switch, window resize).
    resizeObs = new ResizeObserver(() => map && map.invalidateSize({ pan: false }));
    resizeObs.observe($("#farm-map", root));
  }

  function zoneColor(z) {
    if (layer === "ec") return z.ec ? ramp(z.ec, 500, 1100, EC_RAMP) : "#94a3b8";
    if (layer === "temp") return z.soil_temp !== null && z.soil_temp !== undefined ? ramp(z.soil_temp, 12, 34, TEMP_RAMP) : "#94a3b8";
    if (layer === "irrigation") return z.irrigating ? "#22d3ee" : "#e2e8f0";
    return (STATUS[z.status] || STATUS.no_data).color;
  }
  function chipValue(z) {
    if (layer === "ec") return z.ec ? `${fmtNum(z.ec, 0)}<small>µS</small>` : "–";
    if (layer === "temp") return z.soil_temp !== null && z.soil_temp !== undefined ? fmtUs(z.soil_temp, "temp") : "–";
    if (layer === "irrigation") return z.irrigating ? fmtUs(z.flow_m3h, "flow", 0) : "Idle";
    return z.moisture !== null && z.moisture !== undefined ? `${(+z.moisture).toFixed(1)}<small>%</small>` : "–";
  }

  function clearLayers() {
    Object.values(lyr).forEach((arr) => { arr.forEach((l) => map.removeLayer(l)); arr.length = 0; });
  }
  function paintMap() {
    clearLayers();
    const gw = Object.fromEntries(data.gateways.map((g) => [g.id, g]));
    // LoRa links gateway -> probes
    data.devices.forEach((d) => {
      const g = gw[d.gateway]; if (!g) return;
      const ok = d.link_state === "online";
      lyr.links.push(L.polyline([[g.lat, g.lon], [d.lat, d.lon]], { color: ok ? "#38bdf8" : "#f87171", weight: 1.6, opacity: 0.85, dashArray: "6 8", className: ok ? "lora-link" : "lora-link down", interactive: false }).addTo(map));
    });
    data.zones.forEach((z) => {
      const c = zoneColor(z), sel = z.id === selected;
      const circle = (z.shape === "polygon" ? L.polygon(z.polygon) : L.circle(z.center, { radius: z.radius_m }))
        .setStyle({ color: sel ? "#ffffff" : c, weight: sel ? 3.5 : 2, opacity: 0.95, fillColor: c, fillOpacity: layer === "irrigation" && !z.irrigating ? 0.08 : 0.32, className: z.irrigating ? "zone-irrigating" : "" })
        .addTo(map);
      circle.on("click", () => { selected = z.id; paintMap(); paintZone(); });
      lyr.zones.push(circle);
      const chip = L.marker(z.center, { interactive: true, keyboard: false, icon: L.divIcon({ className: "", iconSize: null,
        html: `<div class="zone-chip ${sel ? "sel" : ""}" style="--c:${c}"><div class="zc-top"><i></i>${esc(z.id)} · ${esc(z.crop || "")}</div><div class="zc-val">${chipValue(z)}</div>${z.irrigating ? `<div class="zc-flag">${ICON.drop} Irrigating</div>` : ""}</div>` }) }).addTo(map);
      chip.on("click", () => { selected = z.id; paintMap(); paintZone(); });
      lyr.chips.push(chip);
      if (z.irrigating && z.shape === "circle") {
        const glow = L.polyline([z.center, z.center], { color: "#a5f3fc", weight: 9, opacity: 0.25, interactive: false }).addTo(map);
        const arm = L.polyline([z.center, z.center], { color: "#ecfeff", weight: 3, opacity: 0.95, interactive: false }).addTo(map);
        arm._zone = z; glow._zone = z; lyr.arms.push(glow, arm);
      }
    });
    data.devices.forEach((d) => {
      const m = L.marker([d.lat, d.lon], { draggable: editMode, icon: L.divIcon({ className: "", iconSize: [18, 18], iconAnchor: [9, 9],
        html: `<div class="probe ${d.link_state}"><span></span></div>` }) })
        .bindTooltip(`<b>Node ${d.node_id}</b> · ${esc(d.label || "")}<br>${esc(d.power_mode || "–")} · ${d.battery_v ? d.battery_v.toFixed(2) + " V" : "–"} · ${ago(d.last_seen)}`, { direction: "top", offset: [0, -8], className: "map-tip" })
        .addTo(map);
      m.on("dragend", () => { const p = m.getLatLng(); d.lat = +p.lat.toFixed(6); d.lon = +p.lng.toFixed(6); });
      lyr.devices.push(m);
    });
    data.gateways.forEach((g) => {
      const m = L.marker([g.lat, g.lon], { draggable: editMode, icon: L.divIcon({ className: "", iconSize: [44, 44], iconAnchor: [22, 22],
        html: `<div class="gw-marker"><span class="ring"></span><span class="ring r2"></span><div class="gw-core">${ICON.tower}</div></div>` }) })
        .bindTooltip(`<b>${esc(g.name)}</b> (${esc(g.id)})<br>Backhaul: ${g.backhaul.map(esc).join(" · ")} · primary ${esc(g.primary)}`, { direction: "top", offset: [0, -18], className: "map-tip" })
        .addTo(map);
      m.on("dragend", () => { const p = m.getLatLng(); g.lat = +p.lat.toFixed(6); g.lon = +p.lng.toFixed(6); paintMap(); });
      lyr.gw.push(m);
    });
    paintLegend(); paintBackhaul();
  }
  function spinArms() {
    if (!lyr.arms.length) return;
    armAngle = (armAngle + 1.2) % 360;
    lyr.arms.forEach((a) => { const z = a._zone; a.setLatLngs([z.center, dest(z.center[0], z.center[1], z.radius_m * 0.97, armAngle + z.radius_m % 90)]); });
  }

  function paintSiteCard() {
    $("#site-card", root).innerHTML = `<div class="sc-title">${esc(data.site.name)}</div><div class="sc-sub">${esc(data.site.location || "")} · ${fmtU(data.kpis.area_ha, "area")} · ${data.zones.length} fields</div>
      <div class="seg" id="layer-seg">${Object.entries(LAYERS).map(([k, l]) => `<button data-l="${k}" class="${k === layer ? "on" : ""}">${l}</button>`).join("")}</div>
      ${state.user.permissions.command ? `<div class="row" style="margin-top:8px"><button class="btn sm ${editMode ? "primary" : ""}" id="edit-btn">${editMode ? "Save positions" : "Edit positions"}</button>${editMode ? `<button class="btn sm ghost" id="edit-cancel">Cancel</button>` : ""}</div>` : ""}`;
    $$("#layer-seg button", root).forEach((b) => b.addEventListener("click", () => { layer = b.dataset.l; paintSiteCard(); paintMap(); }));
    $("#edit-btn", root)?.addEventListener("click", async () => {
      if (!editMode) { editMode = true; paintSiteCard(); paintMap(); toast("Drag probes and gateways, then save", ""); return; }
      try {
        const { layout } = await api("/farm/layout", { params: { company: state.company } });
        layout.devices = layout.devices.map((d) => { const live = data.devices.find((x) => x.node_id === d.node_id && x.region === d.region); return live ? { ...d, lat: live.lat, lon: live.lon } : d; });
        layout.gateways = layout.gateways.map((g) => { const live = data.gateways.find((x) => x.id === g.id); return live ? { ...g, lat: live.lat, lon: live.lon } : g; });
        await api("/farm/layout", { method: "PUT", params: { company: state.company }, body: layout });
        toast("Layout saved", "ok"); editMode = false; await load();
      } catch (err) { toast(err.message, "error"); }
    });
    $("#edit-cancel", root)?.addEventListener("click", () => { editMode = false; load(); });
  }
  function paintLegend() {
    let body;
    if (layer === "moisture") body = ["dry", "optimal", "wet", "offline"].map((k) => `<div class="lg-row"><i style="background:${STATUS[k].color}"></i>${STATUS[k].label}</div>`).join("");
    else if (layer === "ec") body = `<div class="lg-ramp" style="background:linear-gradient(90deg,${EC_RAMP.join(",")})"></div><div class="lg-scale"><span>500</span><span>800</span><span>1100 µS/cm</span></div>`;
    else if (layer === "temp") body = `<div class="lg-ramp" style="background:linear-gradient(90deg,${TEMP_RAMP.join(",")})"></div><div class="lg-scale"><span>${Math.round(conv(12, "temp"))}</span><span>${Math.round(conv(23, "temp"))}</span><span>${Math.round(conv(34, "temp"))} ${unit("temp")}</span></div>`;
    else body = `<div class="lg-row"><i style="background:#22d3ee"></i>Irrigating (pivot arm turning)</div><div class="lg-row"><i style="background:#e2e8f0"></i>Idle</div>`;
    $("#legend-card", root).innerHTML = `<div class="lg-title">${LAYERS[layer]}</div>${body}<div class="lg-row"><i class="dot-probe"></i>Soil probe · <i class="dot-gw"></i>Gateway</div>`;
  }
  function paintBackhaul() {
    const g = data.gateways[0];
    if (!g) { $("#bh-card", root).classList.add("hidden"); return; }
    const has = (t) => g.backhaul.includes(t);
    $("#bh-card", root).innerHTML = `<div class="lg-title">Backhaul · ${esc(g.id)}</div>
      <div class="bh-path"><span class="bh-hop">${ICON.drop}<b>Probes</b></span><span class="bh-line lora"></span><span class="bh-hop">${ICON.tower}<b>LoRa GW</b></span><span class="bh-line ${g.primary === "satellite" ? "sat" : "cell"}"></span><span class="bh-hop">${ICON.cloudsrv}<b>WIOT</b></span></div>
      <div class="bh-row">${ICON.cell}<span>Cellular</span>${has("cellular") ? badge([g.primary === "cellular" ? "good" : "neutral", g.primary === "cellular" ? "Primary" : "Standby"]) : badge(["neutral", "n/a"])}</div>
      <div class="bh-row">${ICON.sat}<span>Satellite IoT</span>${has("satellite") ? badge([g.primary === "satellite" ? "good" : "info", g.primary === "satellite" ? "Primary" : "Ready · roadmap"]) : badge(["neutral", "not fitted"])}</div>`;
  }

  // ------------------------------------------------------------------ KPIs
  function paintKpis() {
    const k = data.kpis, w = data.weather;
    const cards = [
      [ICON.drop, "Avg soil moisture", k.avg_moisture === null ? "–" : `${k.avg_moisture}<small>%</small>`, `${k.optimal} of ${k.zones} fields in target band`, "hl"],
      [ICON.pivot, "Irrigating now", `${k.irrigating}<small>/ ${k.zones}</small>`, `${fmtU(k.flow_now_m3h, "flow", 0)} total flow · ${k.auto_zones} on automatic`],
      [ICON.alert, "Need attention", `${data.alerts.length}`, `${k.dry} dry · ${k.wet} wet · ${k.offline} offline`, data.alerts.length ? "warn" : ""],
      [ICON.water, "Water applied today", fmtUs(k.water_today_m3, "volume", 0), `${fmtU(k.area_ha, "area")} under pivots`],
      [ICON.sun, "Reference ET₀ today", w.available ? fmtUs(w.et0_today_mm, "depth", 2) : "–", w.available ? "FAO-56 Penman–Monteith" : "weather offline"],
      [ICON[w.current?.icon] || ICON.cloud, "Weather now", w.available ? `${Math.round(conv(w.current.temp_c, "temp"))}<small>${unit("temp")}</small>` : "–", w.available ? `${esc(w.current.label)} · ${w.current.humidity}% RH · ${Math.round(conv(w.current.wind_kmh, "speed"))} ${unit("speed")}` : esc(w.reason || "")],
    ];
    $("#kpis", root).innerHTML = cards.map(([ic, l, v, s, cls]) => `<div class="agri-kpi ${cls || ""}"><div class="ak-ico">${ic}</div><div><div class="label">${l}</div><div class="ak-v">${v}</div><div class="ak-s">${s}</div></div></div>`).join("");
    $("#wx-card", root).innerHTML = w.available ? `<div class="wx-now"><span class="wx-ico">${ICON[w.current.icon] || ICON.cloud}</span><div><div class="wx-t">${Math.round(conv(w.current.temp_c, "temp"))}${unit("temp")}</div><div class="wx-l">${esc(w.current.label)}</div></div></div>
      <div class="wx-grid"><span>${ICON.drop}${w.current.humidity}%</span><span>${ICON.wind}${Math.round(conv(w.current.wind_kmh, "speed"))} ${unit("speed")}</span><span>${ICON.sun}ET₀ ${fmtU(w.et0_today_mm, "depth", 2)}</span><span>${ICON.rain}${fmtNum(conv(w.rain_next_24h_mm, "depth"), 1)} ${unit("depth")}/24h</span></div>`
      : `<div class="wx-l">${esc(w.reason || "Weather unavailable")}</div>`;
    const warn = (data.weather_warnings || []).map((x) => x.kind === "frost_risk"
      ? `<div class="wx-warn frost">${ICONS.thermo}<span>Frost risk ${esc(x.date)}: minimum ${fmtU(x.tmin_c, "temp")}</span></div>`
      : `<div class="wx-warn heat">${ICONS.thermo}<span>Heat stress ${esc(x.date)}: maximum ${fmtU(x.tmax_c, "temp")}</span></div>`).join("");
    if (warn) $("#wx-card", root).insertAdjacentHTML("beforeend", warn);
  }

  // ---------------------------------------------------------------- zone
  const INDEX_LABEL = { on_target: ["good", "On target"], under: ["warning", "Under-irrigated"], over: ["warning", "Over-irrigated"],
    insufficient_data: ["neutral", "Not enough data"] };
  function indexCell(ix) {
    if (!ix) return `<div><div class="label">Irrigation index</div><b>–</b><div class="muted" style="font-size:11px">no meter totals</div></div>`;
    const [cls, label] = INDEX_LABEL[ix.status] || ["neutral", ix.status];
    return `<div title="Applied ${fmtU(ix.applied_mm, "depth", 1)} vs crop need ${fmtU(ix.etc_mm, "depth", 1)} over ${ix.days} days (${ix.days_with_data} with meter totals)">
      <div class="label">Irrigation index</div><b>${fmtNum(ix.ratio, 2)}×</b><div class="muted" style="font-size:11px">${esc(label)} · 7 days</div></div>`;
  }

  async function paintZone() {
    const z = data.zones.find((x) => x.id === selected), box = $("#zone", root);
    if (!z) return;
    const st = STATUS[z.status] || STATUS.no_data, canWrite = state.user.permissions.command, monitoring = z.node_type === "monitoring";
    const band = [0, 60], pos = (v) => `${Math.max(0, Math.min(100, ((v - band[0]) / (band[1] - band[0])) * 100))}%`;
    box.innerHTML = `<header><h2><span class="ico">${ICON.pivot}</span>${esc(z.name)}</h2><span class="meta">${esc(z.crop || "")} · ${fmtU(z.area_ha, "area")} · node ${z.node_id ?? "–"}</span></header>
      <div class="body">
        <div class="zone-top"><div id="z-gauge"></div><div style="flex:1;min-width:0">
          <div class="row" style="gap:6px;margin-bottom:8px">${badge([st.cls, st.label])}${z.link_state ? badge(LINK_BADGE[z.link_state] || ["neutral", z.link_state]) : ""}${z.irrigating ? badge(["info", "Irrigating"]) : ""}</div>
          <div class="label">Target band ${z.moisture_min}–${z.moisture_max}% VWC</div>
          <div class="band-bar"><span class="band" style="left:${pos(z.moisture_min)};width:calc(${pos(z.moisture_max)} - ${pos(z.moisture_min)})"></span>${z.moisture !== undefined && z.moisture !== null ? `<span class="needle" style="left:${pos(z.moisture)}"></span>` : ""}</div>
          <div class="band-scale"><span>0%</span><span>30%</span><span>60%</span></div>
        </div></div>
        <div class="advice ${z.status}"><span>${z.status === "dry" ? ICON.alert : ICON.drop}</span><div><b>Advice</b><div>${esc(z.advice || "")}</div></div></div>
        <div class="zone-stats">
          <div><div class="label">Soil temp</div><b>${z.soil_temp !== null && z.soil_temp !== undefined ? fmtU(z.soil_temp, "temp") : "–"}</b></div>
          <div><div class="label">Salinity (EC)</div><b>${z.ec ? fmtNum(z.ec, 0) + " µS/cm" : "–"}</b></div>
          <div><div class="label">Flow now</div><b>${fmtU(z.flow_m3h ?? 0, "flow", 0)}</b></div>
          <div><div class="label">Water today</div><b>${fmtU(z.water_today_m3 ?? 0, "volume", 0)}</b></div>
          <div><div class="label">Crop ET today</div><b>${fmtU(z.etc_today_mm, "depth", 2)}</b><span class="muted" style="font-size:11px"> Kc ${z.kc}</span></div>
          <div><div class="label">Battery · probe</div><b>${z.battery_v ? z.battery_v.toFixed(2) + " V" : "–"}</b><span class="muted" style="font-size:11px"> ${esc(z.probe || "")}</span></div>
          ${indexCell(z.irrigation_index)}
        </div>
        ${monitoring ? `<div class="valve-box mon"><div class="mon-ico">${ICONS.sensor}</div><div style="flex:1;min-width:0"><div class="label">Node type</div>
          <div class="valve-state">Monitoring node</div><div class="muted" style="font-size:12px">Sensors only — this field's node has no valve. Irrigation for it is not controlled from WIOT; use a control node to automate it.</div></div></div>` : `<div class="valve-box"><div><div class="label">Valve</div><div class="valve-state ${z.valve}">${esc((z.valve || "–").toUpperCase())}</div><div class="muted" style="font-size:11.5px">${esc(z.power_mode || "")} · last uplink ${ago(z.last_seen)}</div></div>
          <div class="row">${canWrite ? `<button class="btn primary" id="v-open" ${z.valve === "open" ? "disabled" : ""}>Start irrigation</button><button class="btn" id="v-close" ${z.valve === "closed" ? "disabled" : ""}>Stop</button>` : `<span class="muted">Read-only role</span>`}</div></div>`}
        <div class="auto-box">${monitoring ? `<b>Target moisture band</b>` : `<label class="check"><input type="checkbox" id="z-auto" ${z.auto_irrigation ? "checked" : ""} ${canWrite ? "" : "disabled"}> <b>Automatic irrigation</b></label>`}
          <div class="muted" style="font-size:12px;margin:4px 0 8px">${monitoring ? "Used for irrigation advice and alerts on this monitored field." : "Opens the valve below the band, closes it above — through the audited command journal."}</div>
          <div class="row"><label class="label">Min %</label><input class="input mono" id="z-min" type="number" min="0" max="100" step="0.5" value="${z.moisture_min}" style="width:80px" ${canWrite ? "" : "disabled"}>
            <label class="label">Max %</label><input class="input mono" id="z-max" type="number" min="0" max="100" step="0.5" value="${z.moisture_max}" style="width:80px" ${canWrite ? "" : "disabled"}>
            ${canWrite ? `<button class="btn sm" id="z-save">Save</button>` : ""}</div></div>
        <div class="section-title" style="margin-top:14px">Soil moisture · 24 h</div><div id="z-chart"></div>
        <div class="section-title" style="margin-top:10px">Irrigation flow · 24 h</div><div id="z-flow"></div>
      </div>`;
    gauge($("#z-gauge", box), { value: z.moisture !== null && z.moisture !== undefined ? z.moisture / 60 : null, text: z.moisture !== null && z.moisture !== undefined ? `${(+z.moisture).toFixed(1)}%` : "–", label: "Soil moisture", color: st.color, size: 128 });
    const valve = async (v) => {
      const sleeping = z.power_mode && z.power_mode !== "NORMAL";
      try {
        const r = await api("/commands", { method: "POST", body: { ...scoped(), node_id: z.node_id, cmd_type: "VALVE", cmd_data: v, delivery: sleeping ? "next_wake" : "now" } });
        toast(`${z.name}: valve ${v ? "OPEN" : "CLOSE"} #${r.request_id} ${r.queued ? "queued for next wake" : "sent"}`, "ok");
      } catch (err) { toast(err.message, "error"); }
    };
    $("#v-open", box)?.addEventListener("click", () => valve(1));
    $("#v-close", box)?.addEventListener("click", () => valve(0));
    const saveZone = async (body) => {
      try { await api(`/farm/zones/${encodeURIComponent(z.id)}`, { method: "PATCH", params: { company: state.company }, body }); toast(`${z.name} updated`, "ok"); load(); }
      catch (err) { toast(err.message, "error"); }
    };
    $("#z-auto", box)?.addEventListener("change", (e) => saveZone({ auto_irrigation: e.target.checked }));
    $("#z-save", box)?.addEventListener("click", () => saveZone({ moisture_min: +$("#z-min", box).value, moisture_max: +$("#z-max", box).value }));
    try {
      const hst = await api(`/farm/zones/${encodeURIComponent(z.id)}/history`, { params: { company: state.company, hours: 24 } });
      if (selected !== z.id) return;
      lineChart($("#z-chart", box), { height: 170, xType: "time", unit: "%", series: [{ name: "Soil moisture", color: PALETTE[2], area: true, points: hst.moisture.map((p) => [p[0], p[1]]) }],
        refLines: [{ y: hst.band[0], label: `min ${hst.band[0]}%`, color: "#f59e0b" }, { y: hst.band[1], label: `max ${hst.band[1]}%`, color: "#3b82f6" }], yFormat: (v) => v.toFixed(0), empty: "No moisture samples in 24 h" });
      lineChart($("#z-flow", box), { height: 110, xType: "time", unit: ` ${unit("flow")}`, zero: true, series: [{ name: "Flow", color: PALETTE[0], area: true, points: hst.flow.map((p) => [p[0], conv(p[1], "flow")]) }], yFormat: (v) => v.toFixed(0), empty: "No flow in 24 h" });
    } catch { /* history is optional */ }
  }

  // ---------------------------------------------------------------- plan
  function paintPlan() {
    $("#plan-meta", root).textContent = `${data.zones.length} fields · ${data.alerts.length} alerts`;
    $("#plan", root).innerHTML = data.zones.map((z) => {
      const st = STATUS[z.status] || STATUS.no_data, m = z.moisture;
      const p = (v) => `${Math.max(0, Math.min(100, (v / 60) * 100))}%`;
      return `<tr class="clickable ${z.id === selected ? "sel" : ""}" data-z="${esc(z.id)}"><td class="mono"><b>${esc(z.id)}</b></td><td>${esc(z.crop)}</td>
        <td><div class="mini-band"><span class="band" style="left:${p(z.moisture_min)};width:calc(${p(z.moisture_max)} - ${p(z.moisture_min)})"></span>${m !== null && m !== undefined ? `<span class="needle" style="left:${p(m)};background:${st.color}"></span>` : ""}</div><span class="mono" style="font-size:11.5px">${pct(m)}</span></td>
        <td>${badge([st.cls, st.label])}</td><td class="mono">${z.node_type === "monitoring" ? `<span class="muted">Monitoring</span>` : esc((z.valve || "–").toUpperCase())}</td><td class="num">${fmtNum(conv(z.flow_m3h ?? 0, "flow"), 0)}</td><td class="num">${fmtNum(conv(z.water_today_m3 ?? 0, "volume"), 0)}</td>
        <td class="dim" style="white-space:normal;min-width:240px;font-size:12px">${esc(z.advice || "")}</td><td>${z.node_type === "monitoring" ? `<span class="muted">–</span>` : z.auto_irrigation ? badge(["info", "Auto"]) : `<span class="muted">Manual</span>`}</td></tr>`;
    }).join("");
    $$("#plan tr[data-z]", root).forEach((tr) => tr.addEventListener("click", () => { selected = tr.dataset.z; paintMap(); paintZone(); paintPlan(); map.flyTo(data.zones.find((z) => z.id === selected).center, Math.max(map.getZoom(), 15), { duration: 0.6 }); }));
  }

  // ------------------------------------------------------------- weather
  function paintWeather() {
    const w = data.weather, box = $("#wx", root);
    if (!w.available) { box.innerHTML = `<div class="empty">${esc(w.reason || "Weather unavailable")}</div>`; $("#wx-meta", root).textContent = ""; return; }
    $("#wx-meta", root).textContent = `${w.source === "open-meteo" ? "Open-Meteo" : (w.source || "")} · ${fmtDateTime(w.fetched_at).slice(11, 16)}`;
    const days = w.daily || [];
    box.innerHTML = `<div class="wx-days">${days.map((d) => `<div class="wx-day"><div class="label">${new Date(d.date + "T12:00").toLocaleDateString(I18N.lang === "ar" ? "ar-EG" : "en-GB", { weekday: "short" })}</div><span class="wx-ico sm">${ICON[d.icon] || ICON.cloud}</span>
        <div class="mono"><b>${Math.round(conv(d.tmax, "temp"))}°</b> <span class="muted">${Math.round(conv(d.tmin, "temp"))}°</span></div><div class="mono wx-et">ET₀ ${fmtNum(conv(d.et0_mm, "depth"), 2)}</div>${d.rain_mm ? `<div class="mono wx-rain">${fmtU(d.rain_mm, "depth", 1)}</div>` : ""}</div>`).join("")}</div>
      <div id="wx-chart" style="margin-top:12px"></div>${legend([{ name: `Reference ET₀ (${unit("depth")}/day)`, color: PALETTE[3] }, { name: `Rain (${unit("depth")}/day)`, color: PALETTE[0] }])}
      <p class="note">Crop water demand = ET₀ × Kc (FAO-56). With ${fmtU(days.reduce((a, d) => a + (d.rain_mm || 0), 0), "depth", 1)} rain forecast this week, irrigation must replace ≈${fmtU(days.reduce((a, d) => a + (d.et0_mm || 0), 0), "depth", 1)} × Kc.</p>`;
    barChart($("#wx-chart", box), { height: 170, categories: days.map((d) => d.date), catLabel: (d) => String(d).slice(5),
      series: [{ name: `ET₀ ${unit("depth")}`, values: days.map((d) => conv(d.et0_mm || 0, "depth")), color: PALETTE[3] }, { name: `Rain ${unit("depth")}`, values: days.map((d) => conv(d.rain_mm || 0, "depth")), color: PALETTE[0] }], showZero: true, yFormat: (v) => fmtNum(v, 1), tipFormat: (v) => `${(+v).toFixed(2)} ${unit("depth")}` });
  }

  // ----------------------------------------------------------- satellite
  async function paintSatellite() {
    const budget = +$("#budget", root).value || 48;
    const c = await api("/farm/connectivity", { params: scoped({ budget }) });
    const g = c.gateways[0];
    const fits = c.nodes.filter((n) => n.fits_budget).length;
    $("#sat", root).innerHTML = `<div class="sat-grid">
      <div><div class="sat-topo">
        <div class="st-node"><span>${ICON.drop}</span><b>${c.nodes.length} soil probes</b><small>STM32 · AES-128</small></div><div class="st-link lora"><em>LoRa 433 MHz · WOR</em></div>
        <div class="st-node"><span>${ICON.tower}</span><b>${esc(g?.name || "Gateway")}</b><small>${esc(g?.id || "")}</small></div>
        <div class="st-fork"><div class="st-link cell"><em>Cellular · ${g?.primary === "cellular" ? "primary" : "standby"}</em></div><div class="st-link sat"><em>Satellite IoT · ${g?.backhaul?.includes("satellite") ? (g.primary === "satellite" ? "primary" : "roadmap") : "not fitted"}</em></div></div>
        <div class="st-node"><span>${ICON.cloudsrv}</span><b>WIOT Platform</b><small>MQTT · journal · analytics</small></div></div>
        <p class="note">Satellite IoT links deliver small messages with minutes of latency and a daily message budget. WIOT already stores and forwards samples, queues commands for sleeping nodes and reconciles late ACKs — so the same firmware and server can switch backhaul without redesign.</p></div>
      <div><div class="label" style="margin-bottom:8px">Readiness checklist</div><ul class="ready">${c.readiness.map((r) => `<li class="${r.ok ? "ok" : "no"}"><span>${r.ok ? ICON.check : ICON.cross}</span><div><b>${esc(r.item)}</b><div class="muted">${esc(r.detail)}</div></div></li>`).join("")}</ul></div></div>
      <div class="table-wrap" style="margin-top:14px"><table class="data"><thead><tr><th>Node</th><th>Path</th><th>Link</th><th class="num">Reports/day</th><th class="num">Avg payload B</th><th class="num">Avg frame B</th><th class="num">Bytes/day</th><th>Within ${budget}/day</th></tr></thead>
      <tbody>${c.nodes.map((n) => `<tr><td class="mono">${n.node_id} <span class="dim">${esc(n.label)}</span></td><td class="mono dim">${n.path.map(esc).join(" → ")}</td><td>${badge(LINK_BADGE[n.link_state] || ["neutral", n.link_state])}</td>
        <td class="num">${n.reports_per_day}</td><td class="num">${n.avg_payload_b ?? "–"}</td><td class="num">${n.avg_frame_b ?? "–"}</td><td class="num">${n.bytes_per_day ? fmtNum(n.bytes_per_day, 0) : "–"}</td>
        <td>${n.fits_budget ? badge(["good", "Fits"]) : badge(["warning", `Report ≥ ${Math.round(n.budget_interval_s / 60)} min`])}</td></tr>`).join("")}</tbody></table></div>
      <p class="note">${fits} of ${c.nodes.length} nodes fit a ${budget} messages/day satellite plan at their current reporting rate. Frame size = 1 B version + 16 B IV + AES-CBC-padded protobuf, measured since server start.</p>`;
  }
  // -------------------------------------------------------------- live
  const off = onEvent((m) => {
    if ((m.type === "telemetry" || m.type === "command") && m.company === state.company && data?.configured) {
      clearTimeout(refreshTimer);
      refreshTimer = setTimeout(() => { if (!editMode) load().catch(() => {}); }, 1500);
    }
    if (m.type === "automation" && m.company === state.company) toast(`Automation: ${m.data.zone} valve ${m.data.action.toUpperCase()} at ${(+m.data.moisture).toFixed(1)}% moisture`, "ok");
  });
  await load();
  if (data?.configured) paintSatellite().catch((err) => { $("#sat", root).innerHTML = `<div class="empty">${esc(err.message)}</div>`; });
  const satTimer = setInterval(() => { if (data?.configured) paintSatellite().catch(() => {}); }, 30000);
  return () => { off(); clearTimeout(refreshTimer); clearInterval(armTimer); clearInterval(satTimer); resizeObs?.disconnect(); if (map) map.remove(); teardownSetup(); };
}
