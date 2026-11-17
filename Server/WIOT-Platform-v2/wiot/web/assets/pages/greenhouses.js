// Greenhouses (Track G, point 58): houses, zones and benches drawn on the satellite map, the sensors
// attached to each, and their latest readings. Edits stay in memory (undo/redo, plus a draft in this
// browser tab) until Save; the server refuses a save based on an older version (409) rather than
// overwriting someone else's edits. Drawing and editing are hand-written on Leaflet: the CSP allows
// no drawing plugin from a CDN. Geometry lives in gh-geo.js (pure, tested with node).
/* global L */
import { api, state, onEvent, ago, toast, ICONS, $, $$ } from "../api.js";
import { esc, fmtDateTime, T } from "../charts.js";
import { conv, unit, imperial } from "../units.js";
import { t } from "../i18n.js";
import * as G from "./gh-geo.js";

const IC = {
  house: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M3 20v-8.5a9 7 0 0 1 18 0V20"/><path d="M2 20h20M8.5 20V5.6M15.5 20V5.6M3.3 14h17.4"/></svg>',
  zone: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="4" width="18" height="16" rx="1.5"/><path d="M12 4v16M3 12h9" stroke-dasharray="2.2 2.2"/></svg>',
  bench: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><rect x="3" y="8" width="18" height="6" rx="1"/><path d="M6 14v4M18 14v4"/></svg>',
  rows: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="3.5" width="18" height="3.6" rx=".8"/><rect x="3" y="10.2" width="18" height="3.6" rx=".8"/><rect x="3" y="16.9" width="18" height="3.6" rx=".8"/></svg>',
  select: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round" stroke-linecap="round"><path d="M5 3.5l13 6.2-5.6 1.8-2.2 5.6z"/><path d="M12.6 11.7l5.4 5.4"/></svg>',
  rect: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M4.5 8l11-3.5 4 12.5-11 3.5z"/><circle cx="4.5" cy="8" r="1.7" fill="currentColor"/><circle cx="15.5" cy="4.5" r="1.7" fill="currentColor"/><circle cx="19.5" cy="17" r="1.7" fill="currentColor"/></svg>',
  poly: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M4 9.5l7-6 9 4.5-2.5 12H7z"/></svg>',
  undo: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M9 14 4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11"/></svg>',
  redo: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="m15 14 5-5-5-5"/><path d="M20 9H9.5a5.5 5.5 0 0 0 0 11H13"/></svg>',
  trash: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/></svg>',
  check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="m5 12.5 4.5 4.5L19 7.5"/></svg>',
  warn: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M12 3 2 21h20L12 3z"/><path d="M12 10v5M12 18v.5"/></svg>',
  move: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v18M3 12h18M9 6l3-3 3 3M9 18l3 3 3-3M6 9l-3 3 3 3M18 9l3 3-3 3"/></svg>',
  focus: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M4 9V5h4M20 9V5h-4M4 15v4h4M20 15v4h-4"/><circle cx="12" cy="12" r="2.5"/></svg>',
  tree: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M5 4v15M5 7h5M5 13h5M5 19h5"/><rect x="11" y="4.5" width="9" height="4" rx="1"/><rect x="11" y="11" width="9" height="4" rx="1"/><rect x="11" y="17" width="9" height="4" rx="1"/></svg>',
  close: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M7 7l10 10M17 7 7 17"/></svg>',
};

// Fixed semantic colours per house type: they must read on satellite imagery in Night and Day views.
const KINDS = {
  glass: { label: "Glasshouse", color: "#38bdf8" },
  poly: { label: "Plastic house", color: "#facc15" },
  net: { label: "Net house", color: "#4ade80" },
  tunnel: { label: "Tunnel", color: "#fb923c" },
  shade: { label: "Shade house", color: "#c084fc" },
  other: { label: "Other", color: "#cbd5e1" },
};
const OUTSIDE = "#f87171";                    // a zone or bench sticking out of its parent
const LEVEL = { house: "House", zone: "Zone", bench: "Bench" };
const DELETED = { house: "House deleted", zone: "Zone deleted", bench: "Bench deleted" };
const TOOLS = [["select", "Select", "V"], ["house", "House", "H"], ["zone", "Zone", "Z"], ["bench", "Bench", "B"]];
const LIMITS = { houses: 200, zones: 50, benchesPerZone: 1000, benches: 5000, points: 200,
  attach: { house: 20, zone: 20, bench: 10 }, name: { house: 80, zone: 80, bench: 60 } };
const ID_RE = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,23}$/;
const TEMP = new Set(["air_temp_c", "soil_temp_c", "water_temp_c"]);
const CROPS = ["Tomato", "Cucumber", "Pepper", "Eggplant", "Lettuce", "Strawberry", "Melon", "Herbs", "Flowers", "Seedlings"];
const HISTORY_MAX = 60, HISTORY_CHARS = 40e6;  // undo snapshots (a 5000-bench layout is ~1 MB of JSON)
const MIN_AREA = 0.5;                          // m²: anything smaller is a mis-click (the server needs 0.05)
const SNAP_PX = 10;
const MAX_BODY = 2 * 1024 * 1024;              // the server's limit for PUT /greenhouses/layout

// Kept across re-renders: route() redraws the page on theme / language / company switches and page
// changes, which must not lose the edits, the undo history or the map view.
let carry = null;
// Saves still in flight when the page re-renders, per company: the next render waits for them, so
// it loads the saved version and takes over the carried edits instead of racing the PUT.
const pendingSaves = new Map();
let lastKind = "poly";
let rowsDefaults = { width: 1.6, path: 0.8, margin: 0.5, dir: "along", replace: false };

const int = (n) => Math.round(n).toLocaleString("en-US");
const num = (v, d) => (+v).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
const countText = (n, one, many) => `${int(n)} ${n === 1 ? one : many}`;
function areaParts(m2) {
  const big = imperial() ? m2 >= 4046.8564 : m2 >= 10000;
  if (big) return [num(conv(m2 / 10000, "area"), 2), unit("area")];
  const v = imperial() ? m2 * 10.7639 : m2;
  return [v < 100 ? num(v, 1) : int(v), imperial() ? "ft²" : "m²"];
}
const fmtArea = (m2) => areaParts(m2).join(" ");
const fmtAreaHtml = (m2) => { const [v, u] = areaParts(m2); return `${v}<small>${u}</small>`; };
const fmtLen = (m) => `${num(conv(m, "length"), 1)} ${unit("length")}`;
const DOT = '<i class="gh-dotsep" aria-hidden="true">·</i>';   // a real element: stays between items in Arabic too
const akey = (a) => (a.kind === "device" ? `d:${a.device_id}` : `n:${a.region}:${a.node_id}`);
const letters = (i) => (i < 26 ? String.fromCharCode(65 + i) : letters(Math.floor(i / 26) - 1) + String.fromCharCode(65 + (i % 26)));

export async function render(root) {
  const page = document.createElement("div");
  page.className = "ops gh";
  page.innerHTML = `<section class="panel"><div class="empty">Loading…</div></section>`;
  root.appendChild(page);
  const params = { company: state.company };
  await pendingSaves.get(state.company);               // never rejects
  const [data, att, cat, live] = await Promise.all([
    api("/greenhouses/layout", { params }),
    api("/greenhouses/attachables", { params }).catch(() => ({ devices: [], nodes: [] })),
    api("/devices/catalog", { params }).catch(() => ({ metrics: [] })),
    api("/greenhouses/live", { params }).catch(() => ({ values: {} })),
  ]);
  if (!page.isConnected) return undefined;             // the user moved on while it loaded
  return mount(page, data, att, cat, live);
}

function mount(page, data, att, cat, liveData) {
  const company = state.company, canEdit = !!data.can_edit, Q = () => ({ company });
  // Per user too: another account signed in later in this tab must never see these edits.
  const draftKey = `wiot.gh.draft.${company}.${state.user?.username || ""}`;
  const devices = new Map((att.devices || []).map((d) => [d.device_id, d]));
  const nodes = att.nodes || [];
  const metrics = new Map((cat.metrics || []).map((m, i) => [m.key, { ...m, order: i }]));

  // ------------------------------------------------------------ editing state
  let version = data.version, meta = { by: data.updated_by, at: data.updated_at };
  let saved = JSON.stringify(data.layout);             // the server's copy, for the "unsaved" check
  let layout = data.layout, hist = [saved], hi = 0;   // undo / redo: JSON snapshots
  let sel = null, tool = "select", shapePref = { house: "rect", zone: "poly", bench: "rect" };
  let draw = null, rows = null, live = liveData || { values: {} }, saving = false, conflict = false, newer = null, offer = null, flash = null;
  let index = new Map(), outside = new Map(), snapPts = [], moving = null;
  const collapsed = new Set(), benchOpen = new Set();
  const areaCache = new WeakMap();                     // polygons are never mutated in place, so they key the cache
  const back = carry && carry.company === company && carry.version === version ? carry : null;
  carry = null;
  if (back) {
    hist = back.hist; hi = back.hi; layout = JSON.parse(hist[hi]); sel = back.sel; shapePref = back.shapePref;
    offer = back.offer || null;                        // a draft still waiting in the banner stays offered
  } else if (canEdit) offer = readDraft();

  const isDirty = () => hist[hi] !== saved;
  const areaOf = (el) => {
    let a = areaCache.get(el.polygon);
    if (a === undefined) { a = G.area(el.polygon); areaCache.set(el.polygon, a); }
    return a;
  };
  const setHtml = (el, html) => { if (el && el._gh !== html) { el._gh = html; el.innerHTML = html; } };

  // -------------------------------------------------------------------- page
  page.innerHTML = `
    <section class="panel gh-head"><header><h2><span class="ico">${IC.house}</span>Greenhouse layout</h2><span class="meta gh-saved" id="gh-saved"></span></header>
      <div class="body"><div class="tiles gh-tiles" id="gh-tiles"></div></div></section>
    <div id="gh-banner" hidden></div>
    <div class="gh-grid">
      <section class="panel gh-map-panel"><div class="gh-mapbox">
        <div class="gh-map" id="gh-map"></div>
        ${canEdit ? `<div class="gh-top">${toolbarHtml()}${saveHtml()}</div>` : ""}
        <div class="gh-legend glass" id="gh-legend" hidden></div>
        <div class="gh-empty glass" id="gh-empty" hidden></div>
      </div></section>
      <aside class="gh-side">
        <section class="panel gh-tree-panel"><header><h2><span class="ico">${IC.tree}</span>Structure</h2><span class="meta" id="gh-tree-meta"></span></header>
          <div class="gh-tree" id="gh-tree" role="tree" aria-label="Houses, zones and benches"></div></section>
        <section class="panel gh-props" id="gh-props"></section>
      </aside>
    </div>
    <section class="panel gh-warn" id="gh-warn" hidden></section>
    <datalist id="gh-crops">${CROPS.map((c) => `<option value="${c}">`).join("")}</datalist>`;

  function toolbarHtml() {
    return `<div class="gh-tools glass" role="toolbar" aria-label="Layout tools">
      <div class="gh-tb-row">
        <div class="gh-seg" role="group" aria-label="Tool">${TOOLS.map(([k, label, key]) =>
          `<button type="button" data-tool="${k}" title="${label} · ${key}" aria-label="${label}">${IC[k]}<span class="lbl">${label}</span></button>`).join("")}</div>
        <button type="button" class="gh-tb" id="gh-rows" title="Fill the selected zone with rows of benches" aria-label="Bench rows…">${IC.rows}<span class="lbl">Bench rows…</span></button>
        <span class="gh-sep" aria-hidden="true"></span>
        <div class="gh-seg" role="group" aria-label="Shape">
          <button type="button" data-shape="rect" title="Rectangle: three clicks" aria-label="Rectangle">${IC.rect}<span class="lbl">Rectangle</span></button>
          <button type="button" data-shape="poly" title="Polygon: click each corner" aria-label="Polygon">${IC.poly}<span class="lbl">Polygon</span></button></div>
        <span class="gh-sep" aria-hidden="true"></span>
        <button type="button" class="gh-tb icon" id="gh-undo" title="Undo · Ctrl+Z" aria-label="Undo">${IC.undo}</button>
        <button type="button" class="gh-tb icon" id="gh-redo" title="Redo · Ctrl+Y" aria-label="Redo">${IC.redo}</button>
        <button type="button" class="gh-tb icon" id="gh-del" title="Delete · Del" aria-label="Delete">${IC.trash}</button>
      </div>
      <div class="gh-hint" id="gh-hint" aria-live="polite"><span class="gh-hint-ctx" id="gh-hint-ctx"></span><span class="gh-hint-txt" id="gh-hint-txt"></span><b class="gh-hint-dim" id="gh-hint-dim" data-i18n-skip></b><span class="gh-hint-act" id="gh-hint-act"></span></div>
    </div>`;
  }
  function saveHtml() {
    return `<div class="gh-save glass" id="gh-save-card"><span class="gh-state" id="gh-state"></span>
      <button type="button" class="btn sm ghost" id="gh-discard">Discard</button>
      <button type="button" class="btn sm primary" id="gh-save">${IC.check}<span>Save</span></button></div>`;
  }

  // --------------------------------------------------------------------- map
  const mapEl = $("#gh-map", page);
  const map = L.map(mapEl, { zoomControl: false, zoomSnap: 0.25, maxZoom: 22 });
  const tiles = { maxZoom: 22, maxNativeZoom: 18 };    // zoom past the imagery so benches can be drawn
  if (data.map?.tiles) L.tileLayer(data.map.tiles, { ...tiles, attribution: esc(data.map.attribution || "") }).addTo(map);
  if (data.map?.labels) L.tileLayer(data.map.labels, { ...tiles, opacity: 0.75 }).addTo(map);
  const corner = document.documentElement.dir === "rtl" ? "bottomleft" : "bottomright";   // the legend takes the other side
  L.control.zoom({ position: corner }).addTo(map);
  L.control.scale({ position: corner, imperial: imperial(), metric: !imperial() }).addTo(map);
  for (const [name, z, events] of [["ghShapes", 410, true], ["ghDraft", 450, false], ["ghLabels", 460, false]]) {
    const pane = map.createPane(name);
    pane.style.zIndex = z;
    if (!events) pane.style.pointerEvents = "none";    // previews and labels never take clicks
  }
  // One canvas for every house, zone and bench (up to 5000 benches); it also hit-tests clicks,
  // topmost first, so a bench wins over its zone and a zone over its house.
  const shapeR = L.canvas({ pane: "ghShapes", padding: 0.3, tolerance: 3 });
  const overlayR = L.svg({ pane: "ghDraft", padding: 0.3 });
  const shapeLayer = L.layerGroup().addTo(map), selLayer = L.layerGroup().addTo(map), hoverLayer = L.layerGroup().addTo(map);
  const rowsLayer = L.layerGroup().addTo(map), draftLayer = L.layerGroup().addTo(map);
  const labelLayer = L.layerGroup().addTo(map), handleLayer = L.layerGroup().addTo(map);
  const shapes = new Map();
  let shapeOrder = "", selShapes = [];
  const accent = () => T.accent || "#5aa2ff";
  const padTop = canEdit ? 120 : 40;

  if (back?.center) map.setView(back.center, back.zoom);
  else fitView();
  function fitView() {
    const v = data.view || {};
    if (v.bounds) map.fitBounds(v.bounds, { paddingTopLeft: [40, padTop], paddingBottomRight: [40, 40], maxZoom: 20 });
    else map.setView(v.center || [26.8, 30.8], v.zoom || 6);
  }
  const ro = new ResizeObserver(() => map.invalidateSize({ pan: false }));
  ro.observe(mapEl);

  // ------------------------------------------------------------------ model
  function reindex() {
    index = new Map();
    for (const h of layout.houses) {
      index.set(h.id, { level: "house", el: h, parent: null, house: h });
      for (const z of h.zones) {
        index.set(z.id, { level: "zone", el: z, parent: h, house: h });
        for (const b of z.benches) index.set(b.id, { level: "bench", el: b, parent: z, house: h });
      }
    }
  }
  function computeOutside() {                          // same rule and tolerance as the server's warnings
    outside = new Map();
    for (const h of layout.houses) {
      const inHouse = G.container(h.polygon);
      for (const z of h.zones) {
        if (!inHouse(z.polygon)) outside.set(z.id, h.id);
        const inZone = G.container(z.polygon);
        for (const b of z.benches) if (!inZone(b.polygon)) outside.set(b.id, z.id);
      }
    }
  }
  const totalBenches = () => layout.houses.reduce((a, h) => a + h.zones.reduce((s, z) => s + z.benches.length, 0), 0);
  const ctxHouse = () => index.get(sel)?.house || null;
  const ctxZone = () => {
    const it = index.get(sel);
    return it?.level === "zone" ? it.el : it?.level === "bench" ? it.parent : null;
  };
  function subtreeOf(it) {
    if (it.level === "bench") return [it.el];
    if (it.level === "zone") return [it.el, ...it.el.benches];
    return [it.el, ...it.el.zones.flatMap((z) => [z, ...z.benches])];
  }

  // Unique IDs (<= 24 characters) and names in the user's language for new shapes.
  function idFactory() {
    const taken = new Set(index.keys());
    const free = (id) => ID_RE.test(id) && !taken.has(id);
    const claim = (id) => { taken.add(id); return id; };
    const numbered = (prefix) => { for (let n = 1; ; n++) if (free(`${prefix}${n}`)) return [claim(`${prefix}${n}`), n]; };
    return {
      house() {
        for (let n = layout.houses.length + 1; n < 1e5; n++) if (free(`GH-${n}`)) return { id: claim(`GH-${n}`), name: `${t("House")} ${n}` };
        const [id, n] = numbered("H-"); return { id, name: `${t("House")} ${n}` };
      },
      zone(h) {
        for (let i = h.zones.length; i < 702; i++) {
          const id = `${h.id}-${letters(i)}`;
          if (free(id)) return { id: claim(id), name: `${t("Zone")} ${letters(i)}` };
        }
        const [id, n] = numbered("Z-"); return { id, name: `${t("Zone")} ${n}` };
      },
      bench(z, queued = 0) {                           // queued: benches of this batch not in z.benches yet
        for (let n = z.benches.length + queued + 1; n < 1e5; n++) {
          const id = `${z.id}-${String(n).padStart(2, "0")}`;
          if (id.length > 24) break;
          if (free(id)) return { id: claim(id), name: `${t("Bench")} ${n}` };
        }
        const [id, n] = numbered("B-"); return { id, name: `${t("Bench")} ${n}` };
      },
    };
  }

  // ---------------------------------------------------------------- history
  function commit({ keepProps = false } = {}) {
    const snap = JSON.stringify(layout);
    if (snap !== hist[hi]) {
      hist = hist.slice(0, hi + 1);
      hist.push(snap);
      let total = hist.reduce((a, s) => a + s.length, 0);
      while (hist.length > HISTORY_MAX || (hist.length > 2 && total > HISTORY_CHARS)) total -= hist.shift().length;
      hi = hist.length - 1;
      if (offer) { offer = null; paintBanner(); }    // editing on means the old draft is not wanted
    }
    afterChange({ keepProps });
  }
  function undo() { if (canEdit && hi > 0) { hi -= 1; restore(); } }
  function redo() { if (canEdit && hi < hist.length - 1) { hi += 1; restore(); } }
  function restore() {
    moving = null;
    if (draw) draw.pts = [];
    layout = JSON.parse(hist[hi]);
    afterChange();
  }
  function afterChange({ keepProps = false } = {}) {
    reindex();
    if (sel && !index.has(sel)) sel = null;
    if (rows && !index.has(rows.zoneId)) closeRows(false);
    computeOutside();
    ensureDraw();
    syncShapes(); paintSelection(); paintHandles(); paintLabels(); paintLegend(); paintEmpty();
    paintTree(true); if (keepProps) refreshPropsHead(); else paintProps();
    if (rows) updateRows();
    paintTiles(); paintSaved(); paintToolbar(); paintWarnings(); paintDraft(); paintHint();
    scheduleDraft();
  }

  // ------------------------------------------------------------ map shapes
  function styleFor(level, el, out) {
    if (level === "house") {
      const c = (KINDS[el.kind] || KINDS.other).color;
      return { color: c, weight: 2, opacity: 0.95, fillColor: c, fillOpacity: 0.16, dashArray: null };
    }
    if (level === "zone") return { color: out ? OUTSIDE : "#ffffff", weight: out ? 2 : 1.4, opacity: 0.92, fillColor: "#ffffff", fillOpacity: 0.08, dashArray: out ? "4 3" : "6 4" };
    return { color: out ? OUTSIDE : "#f8fafc", weight: out ? 1.6 : 1, opacity: 0.9, fillColor: "#f8fafc", fillOpacity: 0.07, dashArray: out ? "4 3" : null };
  }
  function syncShapes() {
    const ids = [];                                    // draw order: houses, then zones, then benches
    for (const h of layout.houses) ids.push(h.id);
    for (const h of layout.houses) for (const z of h.zones) ids.push(z.id);
    for (const h of layout.houses) for (const z of h.zones) for (const b of z.benches) ids.push(b.id);
    const order = ids.join("\n");
    if (order !== shapeOrder) { shapeLayer.clearLayers(); shapes.clear(); shapeOrder = order; }
    for (const id of ids) {
      const it = index.get(id), out = outside.has(id);
      const key = JSON.stringify(it.el.polygon), sk = `${it.level}|${it.el.kind || ""}|${out}`;
      const s = shapes.get(id);
      if (!s) {
        const layer = L.polygon(it.el.polygon, { renderer: shapeR, ...styleFor(it.level, it.el, out) }).addTo(shapeLayer);
        layer.on("click", (e) => onShapeClick(id, e));
        shapes.set(id, { layer, key, sk });
        continue;
      }
      if (s.key !== key) { s.layer.setLatLngs(it.el.polygon); s.key = key; }
      if (s.sk !== sk) { s.layer.setStyle(styleFor(it.level, it.el, out)); s.sk = sk; }
    }
  }

  function paintSelection() {
    selLayer.clearLayers();
    selShapes = [];
    const it = index.get(sel);
    if (!it) return;
    selShapes = [
      L.polygon(it.el.polygon, { renderer: overlayR, interactive: false, color: "#ffffff", opacity: 0.8, weight: 6, fill: false }),
      L.polygon(it.el.polygon, { renderer: overlayR, interactive: false, color: accent(), weight: 2.5, fillColor: accent(), fillOpacity: 0.16 }),
    ];
    selShapes.forEach((l) => l.addTo(selLayer));
  }
  let hovered = null;
  function hover(id) {
    if (id === hovered) return;
    hovered = id;
    hoverLayer.clearLayers();
    const it = id && id !== sel ? index.get(id) : null;
    if (it) L.polygon(it.el.polygon, { renderer: overlayR, interactive: false, color: accent(), weight: 2, dashArray: "5 4", fillColor: accent(), fillOpacity: 0.08 }).addTo(hoverLayer);
  }

  // Names on the map: houses from zoom 17, zones from zoom 19, only inside the view.
  function paintLabels() {
    labelLayer.clearLayers();
    const z = map.getZoom();
    if (z < 17) return;
    const view = map.getBounds().pad(0.2), editing = canEdit && tool === "select" ? sel : null;
    let n = 0;
    const add = (el, cls) => {
      const c = G.centroid(el.polygon);
      if (n >= 400 || el.id === editing || !view.contains(c)) return;   // the move handle sits there
      n += 1;
      L.marker(c, { pane: "ghLabels", interactive: false, keyboard: false,
        icon: L.divIcon({ className: "", iconSize: null, html: `<span class="gh-lbl ${cls}" data-i18n-skip>${esc(el.name)}</span>` }) }).addTo(labelLayer);
    };
    for (const h of layout.houses) {
      const zones = z >= 19 && h.zones.length;
      add(h, zones ? "house up" : "house");
      if (zones) h.zones.forEach((zz) => add(zz, "zone"));
    }
  }

  function paintLegend() {
    const el = $("#gh-legend", page);
    const kinds = Object.keys(KINDS).filter((k) => layout.houses.some((h) => h.kind === k));
    el.hidden = !kinds.length;
    const zones = layout.houses.some((h) => h.zones.length), benches = layout.houses.some((h) => h.zones.some((z) => z.benches.length));
    setHtml(el, kinds.length ? `<div class="lg-title">Greenhouses</div>
      ${kinds.map((k) => `<div class="lg-row"><i class="gh-sw" style="--c:${KINDS[k].color}"></i><span>${KINDS[k].label}</span></div>`).join("")}
      ${zones ? `<div class="lg-row"><i class="gh-sw zone"></i><span>Zone</span></div>` : ""}
      ${benches ? `<div class="lg-row"><i class="gh-sw bench"></i><span>Bench</span></div>` : ""}
      ${outside.size ? `<div class="lg-row"><i class="gh-sw out"></i><span>Outside its parent</span></div>` : ""}` : "");
  }

  function paintEmpty() {
    const el = $("#gh-empty", page);
    const show = !layout.houses.length && !(tool === "house" && canEdit);
    el.hidden = !show;
    setHtml(el, !show ? "" : canEdit
      ? `<span class="gh-empty-ico">${IC.house}</span><b>No greenhouses yet</b><p>Draw your first greenhouse: choose House, then click three corners on the map</p>
         <button type="button" class="btn sm primary" id="gh-start">${IC.house}<span>Draw a house</span></button>`
      : `<span class="gh-empty-ico">${IC.house}</span><b>No greenhouse layout yet</b><p>An administrator can draw the houses, zones and benches of this company here.</p>`);
  }

  // ---------------------------------------------------------------- tools
  function setTool(k) {
    if (!canEdit) return;
    if (k !== "select" && rows) closeRows();
    tool = k;
    flash = null;
    if (draw) draw.pts = [];
    ensureDraw(); syncMapMode();
    paintToolbar(); paintHandles(); paintLabels(); paintEmpty(); paintDraft(); paintHint();
  }
  function setShape(mode) {
    if (tool === "select") return;
    shapePref[tool] = mode;
    ensureDraw(); syncMapMode();
    paintToolbar(); paintDraft(); paintHint();
  }
  let dblTimer = null;
  function syncMapMode() {
    const drawing = tool !== "select", poly = drawing && shapePref[tool] === "poly";
    mapEl.classList.toggle("gh-drawing", drawing);
    clearTimeout(dblTimer);
    if (poly) map.doubleClickZoom.disable();
    // Re-enabled a moment later: the double-click that finishes a polygon must not also zoom.
    else dblTimer = setTimeout(() => map.doubleClickZoom.enable(), 450);
  }
  function limitText() {
    if (tool === "house" && layout.houses.length >= LIMITS.houses) return "At most 200 houses per company";
    if (tool === "zone" && (ctxHouse()?.zones.length || 0) >= LIMITS.zones) return "At most 50 zones per house";
    if (tool === "bench") {
      if ((ctxZone()?.benches.length || 0) >= LIMITS.benchesPerZone) return "At most 1,000 benches per zone";
      if (totalBenches() >= LIMITS.benches) return "At most 5,000 benches per company";
    }
    return "";
  }
  // The shape being drawn: its level, the parent it goes into and the corners clicked so far.
  function ensureDraw() {
    if (tool === "select" || !canEdit || limitText()) { draw = null; snapPts = []; return; }
    const parent = tool === "house" ? null : tool === "zone" ? ctxHouse() : ctxZone();
    if (tool !== "house" && !parent) { draw = null; snapPts = []; return; }
    const key = parent ? parent.id : "";
    if (!draw || draw.level !== tool || draw.parent !== key || draw.mode !== shapePref[tool]) {
      draw = { level: tool, parent: key, mode: shapePref[tool], pts: [], cursor: null, snap: false };
    }
    snapPts = targetsFor(tool, parent, null);
  }
  // Corners a new or moved corner snaps to: the parent's and the siblings' (other houses for a house).
  function targetsFor(level, parent, skipId) {
    const out = [];
    const add = (els) => {
      for (const el of els) {
        if (el.id === skipId) continue;
        for (const p of el.polygon) { if (out.length >= 4000) return; out.push(p); }
      }
    };
    if (level === "house") add(layout.houses);
    else if (parent) { add([parent]); add(level === "zone" ? parent.zones : parent.benches); }
    return out;
  }
  function snap(pt, off) {
    if (off || !snapPts.length) return { pt: G.roundPt(pt), hit: false };
    const c = map.latLngToContainerPoint(pt);
    let best = null, bd = SNAP_PX;
    for (const v of snapPts) {
      const d = c.distanceTo(map.latLngToContainerPoint(v));
      if (d < bd) { bd = d; best = v; }
    }
    return best ? { pt: [best[0], best[1]], hit: true } : { pt: G.roundPt(pt), hit: false };
  }
  const pxDist = (a, b) => map.latLngToContainerPoint(a).distanceTo(map.latLngToContainerPoint(b));

  // --------------------------------------------------------- map events
  function onShapeClick(id, e) {
    // Select tool: pick the shape. Drawing without a house / zone yet: the click picks it.
    // Otherwise the click is a corner and the map handler takes it.
    if (tool === "select" || !draw) { e.originalEvent._gh = true; select(id); }
  }
  let createdAt = 0;
  function onMapClick(e) {
    if (e.originalEvent?._gh) return;
    if (performance.now() - createdAt < 450) return;   // rest of the double-click that finished a shape
    if (tool === "select") { if (sel) select(null); return; }
    if (!draw) return;
    const { pt } = snap([e.latlng.lat, e.latlng.lng], e.originalEvent?.altKey);
    const pts = draw.pts;
    if (pts.length && pxDist(pts[pts.length - 1], pt) < 4) return;          // second click of a double-click
    if (draw.mode === "poly" && pts.length >= 3 && pxDist(pts[0], pt) < SNAP_PX) { finishPoly(); return; }
    if (pts.length >= LIMITS.points) { flashHint("A shape can have at most 200 corners"); return; }
    pts.push(pt);
    flash = null;
    if (draw.mode === "rect" && pts.length === 3) { finishRect(); return; }
    paintDraft(); paintHint();
  }
  let moveRaf = 0, lastMove = null;
  function onMapMove(e) {
    if (!draw) return;
    lastMove = { pt: [e.latlng.lat, e.latlng.lng], alt: e.originalEvent?.altKey };
    if (moveRaf) return;
    moveRaf = requestAnimationFrame(() => {
      moveRaf = 0;
      if (!draw || !lastMove) return;
      const s = snap(lastMove.pt, lastMove.alt);
      draw.cursor = s.pt; draw.snap = s.hit;
      paintDraft(); paintDims();
    });
  }
  map.on("click", onMapClick);
  map.on("mousemove", onMapMove);
  map.on("mouseout", () => { if (draw) { draw.cursor = null; draw.snap = false; paintDraft(); paintDims(); } });
  map.on("dblclick", () => { if (draw?.mode === "poly") finishPoly(); });
  map.on("moveend", paintLabels);
  map.on("zoomend", paintHandles);                     // midpoint handles depend on wall length on screen

  function finishRect() {
    const [A, B, C] = draw.pts;
    const poly = G.rect3(A, B, C);
    if (!poly || G.area(poly) < MIN_AREA) { draw.pts.pop(); flashHint("Too small: click farther from the first wall"); return; }
    create(poly);
  }
  function finishPoly() {
    if (!draw || draw.pts.length < 3) return;
    const pts = draw.pts.slice();
    if (G.area(pts) < MIN_AREA) { flashHint("The shape is too small"); return; }
    if (G.selfIntersects(pts)) { flashHint("Walls cross each other: click the corners in order around the shape"); return; }
    create(pts);
  }
  function create(poly) {
    const ids = idFactory(), parent = draw.parent ? index.get(draw.parent)?.el : null;
    let el;
    if (draw.level === "house") {
      const n = ids.house();
      el = { id: n.id, name: n.name, polygon: poly, attach: [], kind: lastKind, crop: "", notes: "", zones: [] };
      layout.houses.push(el);
    } else if (draw.level === "zone") {
      const n = ids.zone(parent);
      el = { id: n.id, name: n.name, polygon: poly, attach: [], crop: parent.crop || "", benches: [] };
      parent.zones.push(el);
    } else {
      const n = ids.bench(parent);
      el = { id: n.id, name: n.name, polygon: poly, attach: [] };
      parent.benches.push(el);
    }
    draw = null; tool = "select"; sel = el.id; createdAt = performance.now();
    syncMapMode();
    commit();
    // No auto-focus on the Name field: the V / H / Z / B shortcuts and Ctrl+Z must keep working
    // right after a shape is drawn (house, then zone, then bench) instead of typing into the name.
  }

  // ---------------------------------------------------------- draft preview
  function paintDraft() {
    draftLayer.clearLayers();
    if (!draw) return;
    const pts = draw.pts, cur = draw.cursor, c = accent();
    const line = (ll, dash) => L.polyline(ll, { renderer: overlayR, interactive: false, color: c, weight: 2, dashArray: dash ? "6 5" : null }).addTo(draftLayer);
    const fill = (ll) => L.polygon(ll, { renderer: overlayR, interactive: false, color: c, weight: 2, fillColor: c, fillOpacity: 0.18 }).addTo(draftLayer);
    if (draw.mode === "rect") {
      if (pts.length === 1 && cur) line([pts[0], cur], true);
      if (pts.length === 2) {
        const r = cur && G.rect3(pts[0], pts[1], cur);
        if (r) fill(r);
        line(pts, false);
      }
    } else if (pts.length) {
      if (cur && pts.length >= 2) fill([...pts, cur]);
      line(pts, false);
      if (cur) line([pts[pts.length - 1], cur], true);
    }
    const closable = draw.mode === "poly" && pts.length >= 3;
    pts.forEach((p, i) => L.circleMarker(p, { renderer: overlayR, interactive: false, radius: i === 0 && closable ? 6 : 4, color: "#ffffff", weight: 2, fillColor: c, fillOpacity: 1 }).addTo(draftLayer));
    if (cur && draw.snap) L.circleMarker(cur, { renderer: overlayR, interactive: false, radius: 8, color: "#facc15", weight: 2, fill: false }).addTo(draftLayer);
  }
  function dimsText() {
    if (!draw) return "";
    const pts = draw.pts, cur = draw.cursor;
    if (draw.mode === "rect") {
      if (pts.length === 1 && cur) return fmtLen(G.distance(pts[0], cur));
      const r = pts.length === 2 && cur ? G.rect3(pts[0], pts[1], cur) : null;
      return r ? `${fmtLen(G.distance(r[0], r[1]))} × ${fmtLen(G.distance(r[1], r[2]))} · ${fmtArea(G.area(r))}` : "";
    }
    const all = cur ? [...pts, cur] : pts;
    if (all.length >= 3) return fmtArea(G.area(all));
    return all.length === 2 ? fmtLen(G.distance(all[0], all[1])) : "";
  }

  // ------------------------------------------------------------------ hint
  let flashTimer = null;
  function flashHint(text) {
    flash = text;
    paintHint();
    clearTimeout(flashTimer);
    flashTimer = setTimeout(() => { flash = null; paintHint(); }, 4000);
  }
  function hintState() {
    if (flash) return { text: flash, warn: true };
    if (tool === "select") {
      if (!sel) return { text: layout.houses.length ? "Click a shape to select it" : "Choose House, then click on the map" };
      return { text: "Drag the corners or the centre handle; right-click a corner to remove it" };
    }
    const limit = limitText();
    if (limit) return { text: limit, warn: true };
    if (!draw) return { text: tool === "zone" ? "Select a house first" : "Select a zone first", warn: true };
    const parent = draw.parent ? index.get(draw.parent)?.el : null, n = draw.pts.length;
    const text = draw.mode === "rect"
      ? (n === 0 ? "Click the first corner" : n === 1 ? "Click the second corner along one wall" : "Click to set the width")
      : "Click corners; double-click or press Enter to finish";
    const actions = !n ? "" : `${draw.mode === "poly" && n >= 3 ? `<button type="button" class="btn sm primary" data-hint="finish">Finish</button>` : ""}
      <button type="button" class="btn sm ghost" data-hint="back">Undo corner</button><button type="button" class="btn sm ghost" data-hint="cancel">Cancel</button>`;
    return { text, ctx: parent ? `<span data-i18n-skip>${esc(parent.name)}</span>` : "", actions };
  }
  function paintHint() {
    if (!canEdit) return;
    const h = hintState(), txt = $("#gh-hint-txt", page);
    $("#gh-hint", page).classList.toggle("idle", tool === "select" && !flash);   // narrow maps hide idle tips
    setHtml($("#gh-hint-ctx", page), h.ctx || "");
    setHtml(txt, esc(h.text));
    txt.classList.toggle("warn", !!h.warn);
    setHtml($("#gh-hint-act", page), h.actions || "");
    paintDims();
  }
  function paintDims() {
    const el = $("#gh-hint-dim", page);
    if (el) el.textContent = dimsText();
  }

  // ------------------------------------------------------------- editing handles
  function paintHandles() {
    if (moving) return;                                // never pull a handle out from under the pointer
    handleLayer.clearLayers();
    const it = canEdit && tool === "select" ? index.get(sel) : null;
    if (!it) return;
    const pts = it.el.polygon;
    pts.forEach((p, i) => {
      const m = handle(p, "v", "Drag to move this corner; right-click to remove it");
      m.on("dragstart", () => startEdit(it, m));
      m.on("drag", (e) => dragCorner(it, i, m, e));
      m.on("dragend", endEdit);
      m.on("contextmenu", () => removeCorner(it, i));
    });
    if (pts.length < LIMITS.points) {
      pts.forEach((p, i) => {
        const q = pts[(i + 1) % pts.length];
        if (pxDist(p, q) < 30) return;                 // a short wall on screen: no room for an extra handle
        const m = handle(G.midpoint(p, q), "m", "Drag to add a corner");
        m.on("dragstart", () => { startEdit(it, m); it.el.polygon = [...it.el.polygon.slice(0, i + 1), G.midpoint(p, q), ...it.el.polygon.slice(i + 1)]; });
        m.on("drag", (e) => dragCorner(it, i + 1, m, e));
        m.on("dragend", endEdit);
      });
    }
    const c = handle(G.centroid(pts), "c", it.level === "bench" ? "Drag to move" : "Drag to move with everything inside");
    c.on("dragstart", () => startMove(it, c));
    c.on("drag", () => dragMove(it, c));
    c.on("dragend", endEdit);
  }
  function handle(pos, kind, title) {
    const size = kind === "c" ? 28 : kind === "m" ? 11 : 13;
    return L.marker(pos, { draggable: true, keyboard: false, title, zIndexOffset: kind === "c" ? 900 : 1000, autoPan: true, ghKind: kind,
      icon: L.divIcon({ className: "", iconSize: [size, size], iconAnchor: [size / 2, size / 2], html: `<div class="gh-h ${kind}">${kind === "c" ? IC.move : ""}</div>` }) })
      .addTo(handleLayer);
  }
  function startEdit(it, active) {
    moving = { it, before: it.el.polygon };            // put back if the drag leaves too small a shape
    snapPts = targetsFor(it.level, it.parent, it.el.id);
    // Midpoint and centre handles go stale while a corner moves; they come back on drop.
    handleLayer.eachLayer((m) => { if (m !== active && m.options.ghKind !== "v") m.setOpacity(0); });
  }
  function dragCorner(it, i, m, e) {
    const ll = m.getLatLng(), s = snap([ll.lat, ll.lng], e.originalEvent?.altKey);
    const pts = it.el.polygon.slice();
    pts[i] = s.pt;
    it.el.polygon = pts;
    if (s.hit) m.setLatLng(s.pt);
    queueGeometry(it, false);
  }
  function startMove(it, m) {
    const els = subtreeOf(it);
    moving = { it, start: m.getLatLng(), els: els.map((el) => [el, el.polygon]), live: els.length <= 300 };
    handleLayer.eachLayer((h) => { if (h !== m) h.setOpacity(0); });
  }
  function dragMove(it, m) {
    if (!moving?.start) return;
    const p = m.getLatLng(), dLat = p.lat - moving.start.lat, dLon = p.lng - moving.start.lng;
    // Big subtrees (a house with thousands of benches) follow on drop, to keep the drag smooth.
    for (const [el, poly] of moving.live ? moving.els : moving.els.slice(0, 1)) el.polygon = G.translate(poly, dLat, dLon);
    moving.delta = [dLat, dLon];
    queueGeometry(it, moving.live);
  }
  function endEdit() {
    const m = moving;
    if (m?.start && m.delta) for (const [el, poly] of m.els) el.polygon = G.translate(poly, ...m.delta);
    moving = null;
    if (m?.before && G.area(m.it.el.polygon) < MIN_AREA) {   // a corner or midpoint drag, as finishRect / removeCorner check
      m.it.el.polygon = m.before;
      shapes.get(m.it.el.id)?.layer.setLatLngs(m.before);    // the drag redrew it directly
      flashHint("The shape is too small");
    }
    commit();
  }
  function removeCorner(it, i) {
    if (it.el.polygon.length <= 3) { flashHint("A shape needs at least 3 corners"); return; }
    const pts = it.el.polygon.filter((_, k) => k !== i);
    if (G.area(pts) < MIN_AREA) { flashHint("The shape is too small"); return; }
    it.el.polygon = pts;
    commit();
  }
  let geomRaf = 0, geomTask = null;
  function queueGeometry(it, subtree) {               // redraw at most once per frame while dragging
    geomTask = { it, subtree };
    if (geomRaf) return;
    geomRaf = requestAnimationFrame(() => {
      geomRaf = 0;
      const { it: x, subtree: all } = geomTask;
      for (const el of all ? subtreeOf(x) : [x.el]) shapes.get(el.id)?.layer.setLatLngs(el.polygon);
      selShapes.forEach((l) => l.setLatLngs(x.el.polygon));
    });
  }

  // ------------------------------------------------------------- selection
  function select(id, pan = false) {
    if (id !== sel) {
      sel = id;
      if (rows && rows.zoneId !== id) closeRows(false);
      ensureDraw();
      paintSelection(); paintHandles(); paintLabels(); paintTree(true); paintProps(); paintToolbar(); paintDraft(); paintHint();
    }
    if (pan && id) panTo(id);
  }
  function panTo(id) {
    const it = index.get(id);
    if (!it) return;
    const b = L.latLngBounds(it.el.polygon), nw = map.latLngToContainerPoint(b.getNorthWest()), se = map.latLngToContainerPoint(b.getSouthEast());
    if (map.getBounds().contains(b) && Math.max(se.x - nw.x, se.y - nw.y) > 60) return;   // already well in view
    map.flyToBounds(b, { paddingTopLeft: [40, padTop], paddingBottomRight: [40, 40], maxZoom: { house: 19, zone: 20, bench: 21 }[it.level], duration: 0.5 });
  }
  function removeSelected() {
    const it = index.get(sel);
    if (!it || !canEdit) return;
    const kids = it.level === "house" ? it.el.zones.length : it.level === "zone" ? it.el.benches.length : 0;
    if (kids && !confirm(t(it.level === "house" ? "Delete this house with its zones and benches?" : "Delete this zone with its benches?"))) return;
    if (it.level === "house") layout.houses = layout.houses.filter((h) => h !== it.el);
    else if (it.level === "zone") it.parent.zones = it.parent.zones.filter((z) => z !== it.el);
    else it.parent.benches = it.parent.benches.filter((b) => b !== it.el);
    sel = it.parent ? it.parent.id : null;
    commit();
    toast(DELETED[it.level]);
  }

  // ------------------------------------------------------------------ tree
  function paintTree(reveal = false) {
    const box = $("#gh-tree", page);
    $("#gh-tree-meta", page).textContent = layout.houses.length ? countText(layout.houses.length, "house", "houses") : "";
    if (!layout.houses.length) {
      box.innerHTML = `<div class="empty">${canEdit ? "No houses yet. Draw one on the map." : "No houses yet"}</div>`;
      return;
    }
    const it = index.get(sel);
    if (it) { collapsed.delete(it.house.id); if (it.level === "bench") benchOpen.add(it.parent.id); }
    const active = box.contains(document.activeElement) ? document.activeElement : null;
    const refocus = active?.dataset.toggle ? `[data-toggle="${CSS.escape(active.dataset.toggle)}"]`
      : active?.dataset.sel ? `[data-sel="${CSS.escape(active.dataset.sel)}"]` : null;
    box.innerHTML = layout.houses.map(houseHtml).join("");
    if (refocus) box.querySelector(refocus)?.focus({ preventScroll: true });
    if (reveal) scrollTree(box);
  }
  function scrollTree(box) {                           // scroll the list only, never the page
    const row = box.querySelector(".gh-row.sel");
    if (!row) return;
    const top = row.offsetTop, bottom = top + row.offsetHeight;
    if (top < box.scrollTop) box.scrollTop = top - 8;
    else if (bottom > box.scrollTop + box.clientHeight) box.scrollTop = bottom - box.clientHeight + 8;
  }
  const twisty = (key, open, label) => `<button type="button" class="gh-tw" data-toggle="${esc(key)}" aria-expanded="${open}" aria-label="${label}">${ICONS.chevron}</button>`;
  function rowHtml(level, el, lead, subs, toggle) {
    const out = outside.has(el.id);
    return `<div class="gh-row ${level} ${sel === el.id ? "sel" : ""}">${toggle || `<span class="gh-tw-pad"></span>`}
      <button type="button" class="gh-pick" data-sel="${esc(el.id)}" role="treeitem" aria-selected="${sel === el.id}">${lead}
        <span class="gh-txt"><span class="gh-name" data-i18n-skip>${esc(el.name)}</span>${subs.length ? `<span class="gh-sub">${subs.join(DOT)}</span>` : ""}</span>
        ${out ? `<span class="gh-flag" title="Extends outside its parent">${IC.warn}</span>` : ""}</button></div>`;
  }
  function houseHtml(h) {
    const open = !collapsed.has(h.id);
    const subs = [`<span class="mono" data-i18n-skip>${esc(h.id)}</span>`, `<span class="tnum">${fmtArea(areaOf(h))}</span>`];
    if (h.zones.length) subs.push(`<span>${countText(h.zones.length, "zone", "zones")}</span>`);
    const lead = `<i class="gh-dot" style="--c:${(KINDS[h.kind] || KINDS.other).color}"></i>`;
    return `<div class="gh-node">${rowHtml("house", h, lead, subs, h.zones.length ? twisty(`h:${h.id}`, open, open ? "Collapse" : "Expand") : "")}
      ${open && h.zones.length ? `<div class="gh-kids" role="group">${h.zones.map(zoneHtml).join("")}</div>` : ""}</div>`;
  }
  function zoneHtml(z) {
    const subs = [];
    if (z.crop) subs.push(`<span data-i18n-skip>${esc(z.crop)}</span>`);
    subs.push(`<span class="tnum">${fmtArea(areaOf(z))}</span>`);
    let html = rowHtml("zone", z, `<span class="gh-lead">${IC.zone}</span>`, subs, "");
    if (z.benches.length) {
      const open = benchOpen.has(z.id), shown = open ? z.benches.slice(0, 300) : [];
      html += `<div class="gh-row group">${twisty(`b:${z.id}`, open, open ? "Collapse" : "Expand")}
        <button type="button" class="gh-pick" data-toggle="${esc(`b:${z.id}`)}" aria-expanded="${open}"><span class="gh-lead">${IC.bench}</span>
          <span class="gh-txt"><span>${countText(z.benches.length, "bench", "benches")}</span></span></button></div>`;
      if (open) {
        html += `<div class="gh-kids" role="group">${shown.map((b) => rowHtml("bench", b, "", [`<span class="mono" data-i18n-skip>${esc(b.id)}</span>`], "")).join("")}
          ${z.benches.length > shown.length ? `<div class="gh-more"><span>More benches: select them on the map</span> <span class="tnum">+${int(z.benches.length - shown.length)}</span></div>` : ""}</div>`;
      }
    }
    return `<div class="gh-node">${html}</div>`;
  }
  function toggleTree(key) {
    const id = key.slice(2), set = key[0] === "h" ? collapsed : benchOpen;
    if (set.has(id)) set.delete(id); else set.add(id);
    paintTree();
  }
  const treeEl = $("#gh-tree", page);
  treeEl.addEventListener("click", (e) => {
    const tg = e.target.closest("[data-toggle]");
    if (tg) { toggleTree(tg.dataset.toggle); return; }
    const pick = e.target.closest("[data-sel]");
    if (pick) select(pick.dataset.sel, true);
  });
  treeEl.addEventListener("mouseover", (e) => hover(e.target.closest("[data-sel]")?.dataset.sel || null));
  treeEl.addEventListener("mouseleave", () => hover(null));

  // ------------------------------------------------------------ properties
  function paintProps() {
    const box = $("#gh-props", page), it = index.get(sel);
    hover(null);
    if (!it) { box.innerHTML = idleHtml(); return; }
    const { level, el } = it;
    box.innerHTML = `<header><h2><span class="ico">${IC[level]}</span><span class="gh-title" id="gp-title" data-i18n-skip>${esc(el.name)}</span></h2><span class="meta">${LEVEL[level]}</span></header>
      <div class="body">
        <div id="gp-crumbs">${crumbsHtml(it)}</div>
        ${canEdit ? fieldsHtml(it) : infoHtml(it)}
        <div id="gp-stats">${statsHtml(it)}</div>
        ${actionsHtml(it)}
        ${rows && rows.zoneId === el.id ? rowsHtml() : ""}
        <div class="gh-sec"><div class="section-title">Sensors here</div><div id="gp-sensors">${sensorsHtml(it)}</div></div>
        <div class="gh-sec"><div class="section-title">Latest readings</div><div id="gp-reads">${readingsHtml(it)}</div></div>
      </div>`;
    wireProps(box, it);
  }
  function refreshPropsHead() {                        // after a field edit: keep the inputs (and the focus)
    const it = index.get(sel);
    if (!it) { paintProps(); return; }
    const title = $("#gp-title", page);
    if (title) title.textContent = it.el.name;
    setHtml($("#gp-crumbs", page), crumbsHtml(it));
    setHtml($("#gp-stats", page), statsHtml(it));
    paintReadings();                                   // an ID or sensor change can make them stale
  }
  function idleHtml() {
    return `<header><h2><span class="ico">${IC.select}</span>Properties</h2></header><div class="body">
      <p class="gh-idle">Select a house, zone or bench on the map or in the list to see its details, sensors and readings.</p>
      ${canEdit ? `<div class="section-title">Keyboard</div><dl class="gh-keys">
        <dt><kbd data-i18n-skip>V</kbd><kbd data-i18n-skip>H</kbd><kbd data-i18n-skip>Z</kbd><kbd data-i18n-skip>B</kbd></dt><dd>Select, House, Zone, Bench</dd>
        <dt><kbd data-i18n-skip>Enter</kbd></dt><dd>Finish a polygon</dd>
        <dt><kbd data-i18n-skip>Backspace</kbd></dt><dd>Remove the last corner</dd>
        <dt><kbd data-i18n-skip>Esc</kbd></dt><dd>Cancel drawing or clear the selection</dd>
        <dt><kbd data-i18n-skip>Del</kbd></dt><dd>Delete the selection</dd>
        <dt><kbd data-i18n-skip>Ctrl Z</kbd><kbd data-i18n-skip>Ctrl Y</kbd></dt><dd>Undo, redo</dd>
        <dt><kbd data-i18n-skip>Alt</kbd></dt><dd>Hold to place a corner without snapping</dd></dl>` : ""}</div>`;
  }
  function crumbsHtml(it) {
    if (it.level === "house") return "";
    const chain = it.level === "zone" ? [it.house] : [it.house, it.parent];
    return `<nav class="gh-crumbs" aria-label="Parents">${chain.map((el) => `<button type="button" data-sel="${esc(el.id)}" data-i18n-skip>${esc(el.name)}</button>${ICONS.chevron}`).join("")}<span data-i18n-skip>${esc(it.el.name)}</span></nav>`;
  }
  function fieldsHtml({ level, el }) {
    const f = [`<div class="field"><label for="gp-id">ID</label><input class="input mono" id="gp-id" value="${esc(el.id)}" maxlength="24" spellcheck="false" autocomplete="off" aria-describedby="gp-id-msg"><div class="hint" id="gp-id-msg"></div></div>`,
      `<div class="field"><label for="gp-name">Name</label><input class="input" id="gp-name" value="${esc(el.name)}" maxlength="${LIMITS.name[level]}" autocomplete="off" aria-describedby="gp-name-msg"><div class="hint" id="gp-name-msg"></div></div>`];
    if (level === "house") f.push(`<div class="field"><label for="gp-kind">Type</label><select class="input" id="gp-kind">${Object.entries(KINDS).map(([k, v]) => `<option value="${k}" ${k === el.kind ? "selected" : ""}>${v.label}</option>`).join("")}</select></div>`);
    if (level !== "bench") f.push(`<div class="field"><label for="gp-crop">Crop</label><input class="input" id="gp-crop" value="${esc(el.crop || "")}" maxlength="40" list="gh-crops" placeholder="e.g. Tomato" autocomplete="off"></div>`);
    if (level === "house") f.push(`<div class="field full"><label for="gp-notes">Notes</label><textarea class="input" id="gp-notes" rows="2" maxlength="300">${esc(el.notes || "")}</textarea></div>`);
    return `<div class="form-grid gh-form">${f.join("")}</div>`;
  }
  function infoHtml({ level, el }) {
    const rowsKv = [["ID", `<span class="mono" data-i18n-skip>${esc(el.id)}</span>`]];
    if (level === "house") rowsKv.push(["Type", esc((KINDS[el.kind] || KINDS.other).label)]);
    if (level !== "bench") rowsKv.push(["Crop", el.crop ? `<span data-i18n-skip>${esc(el.crop)}</span>` : `<span class="muted">–</span>`]);
    if (level === "house" && el.notes) rowsKv.push(["Notes", `<span data-i18n-skip>${esc(el.notes)}</span>`]);
    return `<dl class="kv gh-kv">${rowsKv.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("")}</dl>`;
  }
  function rectSize(poly) {                            // [length, width] of a rectangle, else null
    if (poly.length !== 4) return null;
    const xy = G.toLocal(poly), e = (i) => [xy[(i + 1) % 4][0] - xy[i][0], xy[(i + 1) % 4][1] - xy[i][1]];
    for (let i = 0; i < 4; i++) {
      const a = e(i), b = e((i + 1) % 4), cos = (a[0] * b[0] + a[1] * b[1]) / (Math.hypot(...a) * Math.hypot(...b) || 1);
      if (Math.abs(cos) > 0.02) return null;
    }
    const s = [Math.hypot(...e(0)), Math.hypot(...e(1))];
    return [Math.max(...s), Math.min(...s)];
  }
  function statsHtml(it) {
    const { level, el } = it, a = areaOf(el), cells = [["Area", fmtArea(a)]];
    if (level === "house") {
      cells.push(["Zones", int(el.zones.length)], ["Benches", int(el.zones.reduce((s, z) => s + z.benches.length, 0))]);
    } else if (level === "zone") {
      const under = el.benches.reduce((s, b) => s + areaOf(b), 0);
      cells.push(["Benches", int(el.benches.length)]);
      if (under) cells.push(["Under benches", `${Math.round((100 * under) / a)} %`]);
    }
    const size = rectSize(el.polygon);
    cells.push(size ? ["Size", `${num(conv(size[0], "length"), 1)} × ${fmtLen(size[1])}`] : ["Corners", int(el.polygon.length)]);
    return `<dl class="gh-spec">${cells.map(([l, v]) => `<div><dt>${l}</dt><dd class="tnum">${v}</dd></div>`).join("")}</dl>`;
  }
  function actionsHtml({ level }) {
    const b = [];
    if (canEdit && level === "house") b.push(`<button type="button" class="btn sm" data-act="zone">${IC.zone}<span>Draw a zone</span></button>`);
    if (canEdit && level === "zone") b.push(`<button type="button" class="btn sm" data-act="bench">${IC.bench}<span>Draw a bench</span></button>`,
      `<button type="button" class="btn sm" data-act="rows" ${rows ? "disabled" : ""}>${IC.rows}<span>Bench rows…</span></button>`);
    b.push(`<button type="button" class="btn sm ghost" data-act="zoom">${IC.focus}<span>Zoom to</span></button>`);
    if (canEdit) b.push(`<button type="button" class="btn sm danger gh-del" data-act="delete">${IC.trash}<span>${{ house: "Delete house", zone: "Delete zone", bench: "Delete bench" }[level]}</span></button>`);
    return `<div class="gh-actions">${b.join("")}</div>`;
  }
  function wireProps(box, it) {
    const { el } = it;
    $("#gp-crumbs", box).addEventListener("click", (e) => { const b = e.target.closest("[data-sel]"); if (b) select(b.dataset.sel, true); });
    $$("[data-act]", box).forEach((b) => b.addEventListener("click", () => {
      const act = b.dataset.act;
      if (act === "zoom") { const bb = L.latLngBounds(el.polygon); map.flyToBounds(bb, { paddingTopLeft: [40, padTop], paddingBottomRight: [40, 40], maxZoom: 21, duration: 0.5 }); }
      else if (act === "delete") removeSelected();
      else if (act === "rows") openRows();
      else setTool(act);
    }));
    wireSensors(box, it);
    if (!canEdit) return;
    const idIn = $("#gp-id", box), nameIn = $("#gp-name", box);
    idIn.addEventListener("input", () => showError(idIn, "#gp-id-msg", idError(idIn.value.trim(), el.id)));
    idIn.addEventListener("change", () => {
      const v = idIn.value.trim();
      if (v === el.id || showError(idIn, "#gp-id-msg", idError(v, el.id))) return;
      for (const set of [collapsed, benchOpen]) if (set.delete(el.id)) set.add(v);
      if (rows?.zoneId === el.id) rows.zoneId = v;
      el.id = v; sel = v;
      commit({ keepProps: true });
    });
    idIn.addEventListener("keydown", (e) => { if (e.key === "Escape") { idIn.value = el.id; showError(idIn, "#gp-id-msg", ""); } });
    nameIn.addEventListener("change", () => {
      const v = nameIn.value.trim();
      if (!v) { nameIn.value = el.name; showError(nameIn, "#gp-name-msg", "A name is required"); return; }
      showError(nameIn, "#gp-name-msg", "");
      if (v !== el.name) { el.name = v; commit({ keepProps: true }); }
    });
    $("#gp-kind", box)?.addEventListener("change", (e) => { el.kind = e.target.value; lastKind = el.kind; commit({ keepProps: true }); });
    $("#gp-crop", box)?.addEventListener("change", (e) => { el.crop = e.target.value.trim().slice(0, 40); commit({ keepProps: true }); });
    $("#gp-notes", box)?.addEventListener("change", (e) => { el.notes = e.target.value.trim().slice(0, 300); commit({ keepProps: true }); });
    if (rows && rows.zoneId === el.id) wireRows(box);
  }
  function idError(v, current) {
    if (!ID_RE.test(v)) return "Use up to 24 letters, digits, dots, dashes or underscores, starting with a letter or digit";
    if (v !== current && index.has(v)) return "This ID is already used by another house, zone or bench";
    return "";
  }
  function showError(input, msgSel, msg) {
    input.classList.toggle("gh-invalid", !!msg);
    input.setAttribute("aria-invalid", msg ? "true" : "false");
    const box = $(msgSel, page);
    if (box) { box.textContent = msg; box.classList.toggle("gh-err", !!msg); }
    return !!msg;
  }

  // ---------------------------------------------------------------- sensors
  function sensorsHtml({ level, el }) {
    const chips = el.attach.map(chipHtml).join("");
    let html = chips ? `<div class="gh-chips">${chips}</div>` : `<div class="gh-none">No sensors attached</div>`;
    if (!canEdit) return html;
    const taken = new Set(el.attach.map(akey)), full = el.attach.length >= LIMITS.attach[level];
    const devOpts = [...devices.values()].filter((d) => !taken.has(`d:${d.device_id}`)).map((d) =>
      `<option value="${esc(`d:${d.device_id}`)}" data-i18n-skip>${esc(d.name)} · ${esc(d.device_id)}${d.enabled ? "" : ` · ${esc(t("disabled"))}`}</option>`);
    const nodeOpts = nodes.filter((n) => !taken.has(`n:${n.region}:${n.node_id}`)).map((n) =>
      `<option value="${esc(`n:${n.region}:${n.node_id}`)}" data-i18n-skip>${esc(t("Node"))} ${n.node_id} · ${esc(n.region)}${n.name ? ` · ${esc(n.name)}` : ""}</option>`);
    const none = !devOpts.length && !nodeOpts.length;
    html += `<label class="sr-only" for="gp-attach">Attach sensor</label>
      <select class="input gh-attach" id="gp-attach" ${full || none ? "disabled" : ""}>
        <option value="">${full ? "Sensor limit reached" : none ? "No more sensors to attach" : "Attach sensor…"}</option>
        ${devOpts.length ? `<optgroup label="${esc(t("Third-party devices"))}">${devOpts.join("")}</optgroup>` : ""}
        ${nodeOpts.length ? `<optgroup label="${esc(t("WIOT nodes"))}">${nodeOpts.join("")}</optgroup>` : ""}</select>
      ${full ? `<div class="hint">${level === "bench" ? "At most 10 sensors per bench" : "At most 20 sensors per house or zone"}</div>` : ""}`;
    return html;
  }
  function chipHtml(a, i) {
    let title, sub, warn = "";
    if (a.kind === "device") {
      const d = devices.get(a.device_id);
      title = `<b data-i18n-skip>${esc(d?.name || a.device_id)}</b>`;
      sub = `<small class="mono" data-i18n-skip>${esc(a.device_id)}</small>`;
      if (!d) warn = `<small class="gh-chip-warn">Not registered</small>`;
      else if (!d.enabled) warn = `<small class="gh-chip-warn">Disabled</small>`;
    } else {
      const n = nodes.find((x) => x.region === a.region && x.node_id === a.node_id);
      title = `<b><span>Node</span> <span data-i18n-skip>${esc(a.node_id)}</span></b>`;
      sub = `<small data-i18n-skip>${esc(a.region)}${n?.name ? ` · ${esc(n.name)}` : ""}</small>`;
    }
    return `<div class="gh-chip"><span class="gh-chip-ico">${a.kind === "device" ? ICONS.sensor : ICONS.node}</span><span class="gh-chip-t">${title}${sub}${warn}</span>
      ${canEdit ? `<button type="button" class="gh-x" data-detach="${i}" title="Remove sensor" aria-label="Remove sensor">${IC.close}</button>` : ""}</div>`;
  }
  function wireSensors(box, it) {
    const host = $("#gp-sensors", box);
    if (!canEdit || !host) return;
    host.onclick = (e) => {
      const x = e.target.closest("[data-detach]");
      if (!x) return;
      it.el.attach = it.el.attach.filter((_, k) => k !== +x.dataset.detach);
      commit({ keepProps: true });
      repaintSensors(it);
    };
    host.onchange = (e) => {
      if (e.target.id !== "gp-attach" || !e.target.value) return;
      const [kind, a, b] = e.target.value.split(":");
      const att = kind === "d" ? { kind: "device", device_id: a, region: null, node_id: null } : { kind: "node", device_id: null, region: a, node_id: +b };
      it.el.attach = [...it.el.attach, att];
      commit({ keepProps: true });
      repaintSensors(it);
      $("#gp-attach", page)?.focus();
    };
  }
  function repaintSensors(it) {
    const host = $("#gp-sensors", page);
    if (host) host.innerHTML = sensorsHtml(it);
  }

  // ---------------------------------------------------------------- readings
  function fmtMetric(key, v) {
    if (TEMP.has(key)) return [num(conv(v, "temp"), 1), unit("temp")];
    const m = metrics.get(key);
    return [num(v, m?.decimals ?? 1), m?.unit || ""];
  }
  // /greenhouses/live is keyed by the SAVED layout and rolls up each element's whole subtree. An
  // element whose ID or sensors (in its subtree) differ from the saved copy has no matching values yet.
  let savedIds = { src: null, map: null };
  function savedById() {
    if (savedIds.src !== saved) {
      const map = new Map();
      try {
        for (const h of JSON.parse(saved).houses || []) {
          map.set(h.id, h);
          for (const z of h.zones || []) { map.set(z.id, z); for (const b of z.benches || []) map.set(b.id, b); }
        }
      } catch { /* an unreadable copy: nothing matches */ }
      savedIds = { src: saved, map };
    }
    return savedIds.map;
  }
  const sensorSet = (el) => [...new Set([el, ...(el.zones || []).flatMap((z) => [z, ...z.benches]), ...(el.benches || [])]
    .flatMap((x) => (x.attach || []).map(akey)))].sort().join("|");
  const liveMatches = (el) => { const s = savedById().get(el.id); return !!s && sensorSet(s) === sensorSet(el); };
  function readingsHtml({ level, el, parent }) {
    let vals = null, from = null;
    if (liveMatches(el)) vals = live.values?.[el.id];
    else if (sensorSet(el)) return `<div class="gh-none">Save the layout to update these readings</div>`;
    if (!vals && level === "bench" && !el.attach.length && liveMatches(parent) && live.values?.[parent.id]) { vals = live.values[parent.id]; from = parent; }
    if (!vals || !Object.keys(vals).length) return `<div class="gh-none">No fresh readings (last 3 h)</div>`;
    const order = (k) => metrics.get(k)?.order ?? 999;
    const list = Object.entries(vals).sort(([a], [b]) => order(a) - order(b)).map(([k, r]) => {
      const [v, u] = fmtMetric(k, r.value);
      const untrusted = r.untrusted > 0 ? `<span class="gh-untrusted" title="Includes readings from unsigned devices">untrusted</span>` : "";
      return `<div class="gh-read${untrusted ? " untrusted" : ""}"><span class="gh-read-l">${esc(metrics.get(k)?.label || k)}</span>
        <b class="gh-read-v tnum">${v}${u ? `<small>${esc(u)}</small>` : ""}</b>
        <span class="gh-read-m"><span>${r.n === 1 ? "1 sensor" : `${int(r.n)} sensors`}</span>${DOT}<span>${esc(ago(r.ts))}</span>${untrusted}</span></div>`;
    }).join("");
    return `${from ? `<div class="gh-from"><span>From zone</span> <b data-i18n-skip>${esc(from.name)}</b></div>` : ""}<div class="gh-reads">${list}</div>`;
  }
  function paintReadings() {
    const it = index.get(sel);
    if (it) setHtml($("#gp-reads", page), readingsHtml(it));
  }
  async function loadLive() {
    try {
      const r = await api("/greenhouses/live", { params: Q() });
      if (!page.isConnected) return;
      live = r;
      paintReadings();
    } catch { /* keep the last values; the next event or poll retries */ }
  }

  // -------------------------------------------------------------- bench rows
  function openRows() {
    const z = ctxZone();
    if (!z) { flashHint("Select a zone first"); return; }
    if (tool !== "select") setTool("select");
    if (sel !== z.id) select(z.id);
    rows = { zoneId: z.id, ...rowsDefaults };
    paintProps(); paintToolbar(); updateRows();
    $("#gp-rows", page)?.scrollIntoView({ block: "nearest" });
    if (matchMedia("(pointer: fine)").matches) $("#gr-w", page)?.focus();
  }
  function closeRows(repaint = true) {
    rows = null;
    rowsLayer.clearLayers();
    if (repaint) { paintProps(); paintToolbar(); }
  }
  function rowsHtml() {
    const r = rows;
    return `<div class="gh-rows" id="gp-rows"><div class="section-title">Bench rows</div>
      <div class="form-grid gh-rows-grid">
        <div class="field"><label for="gr-w">Width (m)</label><input class="input mono" type="number" id="gr-w" min="0.2" max="20" step="0.1" value="${r.width}" title="Bench width"></div>
        <div class="field"><label for="gr-p">Path (m)</label><input class="input mono" type="number" id="gr-p" min="0" max="20" step="0.1" value="${r.path}" title="Walkway between benches"></div>
        <div class="field"><label for="gr-m">Margin (m)</label><input class="input mono" type="number" id="gr-m" min="0" max="20" step="0.1" value="${r.margin}" title="Distance kept from the zone edge"></div>
        <div class="field full"><label for="gr-d">Direction</label><select class="input" id="gr-d">
          <option value="along" ${r.dir === "along" ? "selected" : ""}>Along the longest wall</option><option value="across" ${r.dir === "across" ? "selected" : ""}>Across</option></select></div>
        <div class="field full"><label class="check"><input type="checkbox" id="gr-r" ${r.replace ? "checked" : ""}> Replace existing benches</label></div>
      </div>
      <div class="gh-rows-sum" id="gr-sum"></div>
      <div class="row"><button type="button" class="btn sm primary" id="gr-go">${IC.rows}<span>Add benches</span></button><button type="button" class="btn sm ghost" id="gr-x">Cancel</button></div></div>`;
  }
  let rowsTimer = null;
  function wireRows(box) {
    const read = () => {
      const val = (id, lo, hi, d) => { const v = parseFloat($(id, box).value); return Number.isFinite(v) ? Math.min(hi, Math.max(lo, v)) : d; };
      Object.assign(rows, { width: val("#gr-w", 0.2, 20, 1.6), path: val("#gr-p", 0, 20, 0.8), margin: val("#gr-m", 0, 20, 0.5),
        dir: $("#gr-d", box).value, replace: $("#gr-r", box).checked });
      clearTimeout(rowsTimer);
      rowsTimer = setTimeout(updateRows, 120);
    };
    $$("#gp-rows input, #gp-rows select", box).forEach((i) => i.addEventListener(i.type === "checkbox" || i.tagName === "SELECT" ? "change" : "input", read));
    $("#gr-go", box).addEventListener("click", applyRows);
    $("#gr-x", box).addEventListener("click", () => closeRows());
  }
  function rowsPlan() {
    const z = index.get(rows.zoneId)?.el;
    if (!z) return { z: null, plan: [], room: 0 };
    const plan = G.benchRows(z.polygon, { width: rows.width, path: rows.path, margin: rows.margin, direction: rows.dir,
      avoid: rows.replace ? [] : z.benches.map((b) => b.polygon), max: LIMITS.benchesPerZone });
    const keep = rows.replace ? 0 : z.benches.length;
    const room = Math.max(0, Math.min(LIMITS.benchesPerZone - keep, LIMITS.benches - (totalBenches() - z.benches.length) - keep));
    return { z, plan, room };
  }
  function updateRows() {
    rowsLayer.clearLayers();
    const sum = $("#gr-sum", page);
    if (!rows || !sum) return;
    const { plan, room } = rowsPlan(), n = Math.min(plan.length, room);
    plan.slice(0, n).forEach((p) => L.polygon(p, { renderer: overlayR, interactive: false, color: "#fde047", weight: 1.2, dashArray: "4 3", fillColor: "#fde047", fillOpacity: 0.2 }).addTo(rowsLayer));
    const lengths = plan.slice(0, n).map((p) => G.distance(p[0], p[1]));
    const range = lengths.length ? [Math.min(...lengths), Math.max(...lengths)] : null;
    sum.innerHTML = !plan.length ? `<span class="gh-err">No bench fits: make the zone larger or the margin smaller</span>`
      : `<b>${countText(n, "bench fits", "benches fit")}</b>
         ${range ? `<span><span>Bench length</span> <span class="tnum" data-i18n-skip>${range[1] - range[0] < 0.05 ? fmtLen(range[0]) : `${num(conv(range[0], "length"), 1)}–${fmtLen(range[1])}`}</span></span>` : ""}
         ${plan.length > n ? `<span class="gh-err">Limit reached: only ${int(n)} more benches allowed here</span>` : ""}`;
    $("#gr-go", page).disabled = !n;
  }
  function applyRows() {
    const { z, plan, room } = rowsPlan(), n = Math.min(plan.length, room);
    if (!z || !n) return;
    if (rows.replace && z.benches.length) {
      const q = z.benches.length === 1 ? "Replace the existing bench of this zone?" : `Replace the ${z.benches.length} existing benches of this zone?`;
      if (!confirm(t(q))) return;
      z.benches = [];
      reindex();
    }
    const ids = idFactory();
    z.benches = [...z.benches, ...plan.slice(0, n).map((polygon, k) => { const b = ids.bench(z, k); return { id: b.id, name: b.name, polygon, attach: [] }; })];
    rowsDefaults = { width: rows.width, path: rows.path, margin: rows.margin, dir: rows.dir, replace: rows.replace };
    rows = null;
    rowsLayer.clearLayers();
    benchOpen.delete(z.id);
    commit();
    toast(n === 1 ? "1 bench added" : `${int(n)} benches added`, "ok");
  }

  // ------------------------------------------------------------- page chrome
  function paintTiles() {
    let zones = 0, benches = 0, attach = 0, area = 0, under = 0;
    for (const h of layout.houses) {
      area += areaOf(h); attach += h.attach.length;
      for (const z of h.zones) {
        zones += 1; attach += z.attach.length;
        for (const b of z.benches) { benches += 1; attach += b.attach.length; under += areaOf(b); }
      }
    }
    const cells = [
      ["Houses", int(layout.houses.length), ""],
      ["Zones", int(zones), ""],
      ["Benches", int(benches), benches ? `<span>Bench area</span> <span class="tnum">${fmtArea(under)}</span>` : ""],
      ["Covered area", fmtAreaHtml(area), area && under ? `<span>Under benches</span> <span class="tnum">${Math.round((100 * under) / area)} %</span>` : ""],
      ["Sensors attached", int(attach), ""],
    ];
    setHtml($("#gh-tiles", page), cells.map(([l, v, s]) => `<div class="tile"><div class="label">${l}</div><div class="v">${v}</div>${s ? `<div class="s">${s}</div>` : ""}</div>`).join(""));
  }
  function paintSaved() {
    setHtml($("#gh-saved", page), meta.at
      ? `<span>Saved by</span> <b data-i18n-skip>${esc(meta.by || "–")}</b>${DOT}<span class="tnum">${esc(fmtDateTime(meta.at).slice(0, 16))}</span>`
      : `<span>Not saved yet</span>`);
    paintSaveCard();
  }
  function paintSaveCard() {
    if (!canEdit) return;
    const dirty = isDirty();
    setHtml($("#gh-state", page), saving ? `<i class="gh-dotstate busy"></i><span>Saving…</span>`
      : dirty ? `<i class="gh-dotstate dirty"></i><span>Unsaved changes</span>` : `<span class="gh-ok">${IC.check}</span><span>All changes saved</span>`);
    $("#gh-save", page).disabled = !dirty || saving;
    $("#gh-discard", page).disabled = !dirty || saving;
    $("#gh-save-card", page).classList.toggle("dirty", dirty);
  }
  function paintToolbar() {
    if (!canEdit) return;
    $$("[data-tool]", page).forEach((b) => { const on = b.dataset.tool === tool; b.classList.toggle("on", on); b.setAttribute("aria-pressed", String(on)); });
    const mode = tool === "select" ? null : shapePref[tool];
    $$("[data-shape]", page).forEach((b) => { const on = b.dataset.shape === mode; b.classList.toggle("on", on); b.setAttribute("aria-pressed", String(on)); b.disabled = !mode; });
    $("#gh-undo", page).disabled = hi <= 0;
    $("#gh-redo", page).disabled = hi >= hist.length - 1;
    $("#gh-del", page).disabled = !sel;
    $("#gh-rows", page).classList.toggle("on", !!rows);
    paintSaveCard();
  }
  function paintWarnings() {
    const box = $("#gh-warn", page);
    box.hidden = !outside.size;
    if (!outside.size) { setHtml(box, ""); return; }
    const items = [...outside.keys()].slice(0, 50).map((id) => {
      const it = index.get(id);
      return `<li><span class="gh-warn-ico">${IC[it.level]}</span><span class="gh-warn-what"><b data-i18n-skip>${esc(it.el.name)}</b><span class="mono" data-i18n-skip>${esc(id)}</span></span>
        <span class="dim">${it.level === "zone" ? "Extends outside its house" : "Extends outside its zone"}</span>
        <button type="button" class="btn sm ghost" data-show="${esc(id)}">Show</button></li>`;
    }).join("");
    setHtml(box, `<header><h2><span class="ico">${IC.warn}</span>Shapes outside their parent</h2><span class="meta tnum">${int(outside.size)}</span></header>
      <div class="body"><p class="note">They are saved as drawn, but readings and areas are clearer when every zone lies inside its house and every bench inside its zone.</p>
        <ul class="gh-warn-list">${items}</ul>${outside.size > 50 ? `<p class="note"><span>More shapes are outside their parent:</span> <span class="tnum">+${int(outside.size - 50)}</span></p>` : ""}</div>`);
  }
  $("#gh-warn", page).addEventListener("click", (e) => { const b = e.target.closest("[data-show]"); if (b) select(b.dataset.show, true); });

  // -------------------------------------------------------- draft and saving
  function readDraft() {
    try {
      const d = JSON.parse(sessionStorage.getItem(draftKey) || "null");
      if (!d || typeof d.layout !== "string" || d.layout === saved || !Array.isArray(JSON.parse(d.layout).houses)) return null;
      return { layout: d.layout, at: d.at, stale: d.version !== version };
    } catch { return null; }
  }
  let draftTimer = null;
  function scheduleDraft() { clearTimeout(draftTimer); draftTimer = setTimeout(writeDraft, 500); }
  function writeDraft() {
    clearTimeout(draftTimer);
    if (!canEdit || offer) return;                     // an offered draft stays until the user decides
    try {
      if (isDirty()) sessionStorage.setItem(draftKey, JSON.stringify({ version, at: Date.now(), layout: hist[hi] }));
      else sessionStorage.removeItem(draftKey);
    } catch { /* storage full or blocked: the edits stay in memory */ }
  }
  function dropDraft() {
    try { sessionStorage.removeItem(draftKey); } catch { /* storage blocked */ }
  }
  function paintBanner() {
    const host = $("#gh-banner", page);
    let html = "";
    if (conflict) {
      html = `<div class="gh-banner bad" role="alert"><span class="gh-banner-ico">${IC.warn}</span>
        <div class="txt"><b>Not saved</b><span>Someone else saved the layout. Reload to see their changes; your edits are kept as a draft.</span></div>
        <div class="gh-banner-act"><button type="button" class="btn sm primary" data-b="reload">${ICONS.refresh}<span>Reload</span></button></div></div>`;
    } else if (newer) {                                 // another editor saved while this tab has unsaved edits
      html = `<div class="gh-banner" role="status"><span class="gh-banner-ico">${IC.warn}</span>
        <div class="txt"><b>A newer layout was saved</b><span>Saving your edits now would be refused. Reload to see the other changes; your edits are kept as a draft.</span></div>
        <div class="gh-banner-act"><button type="button" class="btn sm primary" data-b="reload">${ICONS.refresh}<span>Reload</span></button></div></div>`;
    } else if (offer) {
      html = `<div class="gh-banner" role="status"><span class="gh-banner-ico">${IC.undo}</span>
        <div class="txt"><b>Unsaved changes found</b><span>${offer.stale ? "They were made on an older version of the layout. Saving them replaces the newer version."
          : "This browser tab kept your edits from an earlier visit."}</span></div>
        <div class="gh-banner-act"><button type="button" class="btn sm primary" data-b="restore">Restore unsaved changes</button>
          <button type="button" class="btn sm ghost" data-b="drop">Discard draft</button></div></div>`;
    }
    host.hidden = !html;
    setHtml(host, html);
  }
  $("#gh-banner", page).addEventListener("click", (e) => {
    const b = e.target.closest("[data-b]")?.dataset.b;
    if (b === "reload") reload();
    else if (b === "restore" && offer) { const d = offer; offer = null; layout = JSON.parse(d.layout); sel = null; commit(); paintBanner(); }
    else if (b === "drop") { offer = null; dropDraft(); paintBanner(); }
  });
  async function save() {
    if (saving || !isDirty()) return;
    const body = hist[hi], sentFrom = version;
    // The server counts UTF-8 bytes (Content-Length), not characters.
    if (new Blob([body]).size > MAX_BODY - 1024) { toast("The layout is too large to save (over 2 MB). Remove some benches or corners.", "error"); return; }
    saving = true;
    paintSaveCard();
    let settle;
    const pending = new Promise((res) => { settle = res; });
    pendingSaves.set(company, pending);
    try {
      const r = await api("/greenhouses/layout", { method: "PUT", params: Q(), body: { layout: JSON.parse(body), version: sentFrom } });
      version = r.version; saved = body; conflict = false;
      meta = { by: state.user?.username, at: Math.floor(Date.now() / 1000) };
      if (!page.isConnected) {
        // The page re-rendered meanwhile: hand the new version to the carried edits (the next render
        // waits for this save), and drop the draft only when it holds nothing newer than this save.
        if (carry?.company === company && carry.version === sentFrom) carry.version = version;
        try { if (JSON.parse(sessionStorage.getItem(draftKey) || "null")?.layout === body) dropDraft(); } catch { /* storage blocked */ }
        return;
      }
      if (isDirty()) writeDraft(); else dropDraft();  // edits made while saving stay restorable
      toast("Layout saved", "ok");
      paintReadings();
      loadLive();
    } catch (err) {
      if (!page.isConnected) return;
      if (err.status === 409) { conflict = true; writeDraft(); }
      else { toast(err.message, "error"); if (err.status === 422) showInvalid(err.message); }
    } finally {
      saving = false;
      if (pendingSaves.get(company) === pending) pendingSaves.delete(company);
      settle();
      if (page.isConnected) { paintSaved(); paintBanner(); }
    }
  }
  function showInvalid(msg) {                          // "layout.houses.0.zones.1.polygon: ..." -> select that shape
    const m = /houses\.(\d+)(?:\.zones\.(\d+))?(?:\.benches\.(\d+))?/.exec(msg || "");
    if (!m) return;
    const h = layout.houses[+m[1]], z = m[2] !== undefined ? h?.zones[+m[2]] : null, b = m[3] !== undefined ? z?.benches[+m[3]] : null;
    const el = b || z || h;
    if (el) select(el.id, true);
  }
  async function reload() {
    try {
      const d = await api("/greenhouses/layout", { params: Q() });
      if (!page.isConnected) return;
      if (isDirty()) writeDraft();                     // keep unsaved edits restorable after the reload
      version = d.version; meta = { by: d.updated_by, at: d.updated_at };
      saved = JSON.stringify(d.layout); layout = d.layout; hist = [saved]; hi = 0;
      conflict = false; newer = null; draw = null;
      offer = readDraft();
      afterChange(); paintBanner(); loadLive();
    } catch (err) { toast(err.message, "error"); }
  }
  function discard() {
    if (!isDirty()) return;
    layout = JSON.parse(saved);                        // a new history step: Undo brings the edits back
    commit();
    toast("Changes discarded. Undo brings them back.");
  }

  // ----------------------------------------------------------------- input
  function escape() {
    if (draw?.pts.length) { draw.pts = []; flash = null; paintDraft(); paintHint(); return; }
    if (tool !== "select") { setTool("select"); return; }
    if (rows) { closeRows(); return; }
    if (sel) select(null);
  }
  function onKey(e) {
    if (!page.isConnected || e.defaultPrevented) return;
    const tg = e.target;
    if (tg?.closest?.("input, textarea, select, [contenteditable]") || tg?.isContentEditable) return;   // typing
    const k = e.key, lower = k.length === 1 ? k.toLowerCase() : k;
    if ((e.ctrlKey || e.metaKey) && !e.altKey) {
      if (lower === "z" && !e.shiftKey) { e.preventDefault(); undo(); }
      else if (lower === "y" || (lower === "z" && e.shiftKey)) { e.preventDefault(); redo(); }
      return;
    }
    if (e.altKey || e.ctrlKey || e.metaKey) return;
    if (k === "Escape") escape();
    else if (k === "Enter") {
      if (tg?.closest?.("button, a")) return;
      if (draw?.mode === "poly" && draw.pts.length >= 3) { e.preventDefault(); finishPoly(); }
    } else if (k === "Backspace") {
      if (draw?.pts.length) { e.preventDefault(); draw.pts.pop(); paintDraft(); paintHint(); }
    } else if (k === "Delete") {
      if (sel && !draw?.pts.length) { e.preventDefault(); removeSelected(); }
    } else if (canEdit && !e.shiftKey) {
      const next = { v: "select", h: "house", z: "zone", b: "bench" }[lower];
      if (next) setTool(next);
    }
  }
  const onUnload = (e) => { if (isDirty()) { e.preventDefault(); e.returnValue = ""; } };
  addEventListener("keydown", onKey);
  addEventListener("beforeunload", onUnload);

  if (canEdit) {
    $$("[data-tool]", page).forEach((b) => b.addEventListener("click", () => setTool(b.dataset.tool)));
    $$("[data-shape]", page).forEach((b) => b.addEventListener("click", () => setShape(b.dataset.shape)));
    $("#gh-rows", page).addEventListener("click", () => (rows ? closeRows() : openRows()));
    $("#gh-undo", page).addEventListener("click", undo);
    $("#gh-redo", page).addEventListener("click", redo);
    $("#gh-del", page).addEventListener("click", removeSelected);
    $("#gh-save", page).addEventListener("click", save);
    $("#gh-discard", page).addEventListener("click", discard);
    $("#gh-hint", page).addEventListener("click", (e) => {
      const a = e.target.closest("[data-hint]")?.dataset.hint;
      if (!a || !draw) return;
      if (a === "finish") finishPoly();
      else if (a === "back") { draw.pts.pop(); paintDraft(); paintHint(); }
      else if (a === "cancel") { draw.pts = []; paintDraft(); paintHint(); }
    });
    $("#gh-empty", page).addEventListener("click", (e) => { if (e.target.closest("#gh-start")) setTool("house"); });
  }

  // ------------------------------------------------------------------ live
  let liveTimer = null;
  const off = onEvent((m) => {
    if ((m.type === "device_reading" || m.type === "telemetry") && m.company === company && !liveTimer) {
      liveTimer = setTimeout(() => { liveTimer = null; loadLive(); }, 3000);    // at most one refresh per 3 s
    }
    // Someone saved the layout elsewhere: follow it when nothing is being edited here, else warn before a 409.
    if (m.type === "greenhouse_layout" && m.company === company && !saving && +m.data?.version > version) {
      if (isDirty() || draw?.pts.length) { newer = m.data; paintBanner(); }
      else { reload(); toast("The layout was updated by another user", "ok"); }
    }
  });
  const poll = setInterval(loadLive, 60000);

  syncMapMode();
  afterChange();
  paintBanner();
  if (sel) panTo(sel);

  return () => {
    off();
    clearTimeout(liveTimer); clearInterval(poll); clearTimeout(flashTimer); clearTimeout(rowsTimer); clearTimeout(dblTimer); clearTimeout(draftTimer);
    cancelAnimationFrame(moveRaf); cancelAnimationFrame(geomRaf);
    removeEventListener("keydown", onKey);
    removeEventListener("beforeunload", onUnload);
    writeDraft();
    const c = map.getCenter();
    carry = { company, version, hist, hi, sel, shapePref, offer, center: [c.lat, c.lng], zoom: map.getZoom() };
    ro.disconnect();
    map.remove();
  };
}
