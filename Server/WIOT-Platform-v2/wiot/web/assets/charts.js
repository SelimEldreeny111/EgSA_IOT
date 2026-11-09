// Minimal dependency-free SVG charts with hover tooltips (dark theme).
const NS = "http://www.w3.org/2000/svg";
// Live theme state: arrays/objects are mutated in place by applyTheme() so importers keep valid references.
export const PALETTE = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"];
export const SEQ = [];
export const T = {};
const SEQ_DARK = ["#104281", "#184f95", "#1c5cab", "#256abf", "#2a78d6", "#3987e5", "#5598e7", "#6da7ec", "#86b6ef", "#9ec5f4"];
const SEQ_LIGHT = ["#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7", "#3987e5", "#2a78d6", "#256abf", "#1c5cab"];

/** Read the active Night/Day tokens from CSS into the chart palette. */
export function applyTheme() {
  const cs = getComputedStyle(document.documentElement);
  const v = (n) => cs.getPropertyValue(n).trim();
  const light = document.documentElement.dataset.theme === "light";
  PALETTE.splice(0, PALETTE.length, ...[1, 2, 3, 4, 5, 6, 7, 8].map((i) => v(`--s${i}`) || PALETTE[i - 1]));
  SEQ.splice(0, SEQ.length, ...(light ? SEQ_LIGHT : SEQ_DARK));
  Object.assign(T, {
    light, text: v("--text"), text2: v("--text-2"), muted: v("--muted"), line: v("--line"), line2: v("--line-2"),
    panel: v("--panel"), accent: v("--chart-accent"), empty: v("--empty"), chance: v("--chance"),
    good: PALETTE[2], warn: PALETTE[3], bad: PALETTE[7], ref: light ? "#b4532a" : "#ec835a",
  });
}
applyTheme();

/** Colour for a delivery-risk tier (blue = likely, amber = uncertain, red = unlikely). */
export const riskColor = (tier) => (tier === "LIKELY" ? T.accent : tier === "UNCERTAIN" ? T.warn : T.bad);

let tipEl;
function tip() {
  if (!tipEl) { tipEl = document.createElement("div"); tipEl.className = "tooltip"; document.body.appendChild(tipEl); }
  return tipEl;
}
export function showTip(evt, html) {
  const t = tip(); t.innerHTML = html; t.classList.add("show");
  const pad = 14, w = t.offsetWidth, h = t.offsetHeight;
  let x = evt.clientX + pad, y = evt.clientY + pad;
  if (x + w > innerWidth - 8) x = evt.clientX - w - pad;
  if (y + h > innerHeight - 8) y = evt.clientY - h - pad;
  t.style.left = x + "px"; t.style.top = y + "px";
}
export function hideTip() { tip().classList.remove("show"); }

export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
function el(tag, attrs = {}, parent) {
  const n = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) if (v !== undefined && v !== null) n.setAttribute(k, v);
  if (parent) parent.appendChild(n);
  return n;
}
export function fmtNum(v, d = 2) {
  if (v === null || v === undefined || Number.isNaN(v)) return "–";
  const a = Math.abs(v);
  if (a >= 1e6) return (v / 1e6).toFixed(1) + "M";
  if (a >= 1e4) return (v / 1e3).toFixed(1) + "k";
  if (a >= 100) return v.toFixed(0);
  if (a >= 10) return v.toFixed(Math.min(d, 1));
  return v.toFixed(d);
}
// Times are shown in the selected company's time zone (Organization → company profile).
export const DISPLAY = { tz: undefined };
const _fmt = new Map();
function _parts(t) {
  const key = DISPLAY.tz || "";
  let f = _fmt.get(key);
  if (!f) {
    try { f = new Intl.DateTimeFormat("en-GB", { timeZone: DISPLAY.tz, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23" }); }
    catch { f = new Intl.DateTimeFormat("en-GB", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23" }); }
    _fmt.set(key, f);
  }
  const o = {};
  for (const p of f.formatToParts(new Date(t * 1000))) o[p.type] = p.value;
  return o;
}
/** Seconds east of UTC for the display time zone at epoch ``t``. */
export function tzOffset(t = Date.now() / 1000) {
  const o = _parts(t);
  return Math.round((Date.UTC(+o.year, +o.month - 1, +o.day, +o.hour, +o.minute, +o.second) / 1000 - Math.floor(t)) / 60) * 60;
}
export function fmtTime(t, span) {
  const o = _parts(t);
  if (span !== undefined && span > 2 * 86400) return `${o.month}-${o.day}`;
  return `${o.hour}:${o.minute}`;
}
export function fmtDateTime(t) {
  const o = _parts(t);
  return `${o.year}-${o.month}-${o.day} ${o.hour}:${o.minute}:${o.second}`;
}
export function fmtClock(t = Date.now() / 1000) {
  const o = _parts(t);
  return `${o.hour}:${o.minute}:${o.second}`;
}
function niceTicks(lo, hi, n = 5) {
  if (!(hi > lo)) { hi = lo + 1; }
  const span = hi - lo, step0 = span / n, mag = 10 ** Math.floor(Math.log10(step0));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => span / s <= n) || mag * 10;
  const out = [];
  // Include the first tick at or above `hi` so axes always enclose the data.
  for (let v = Math.ceil(lo / step) * step; v < hi + step - step * 1e-9; v += step) out.push(+v.toFixed(10));
  return out;
}

function mount(container, height) {
  container.innerHTML = "";
  container.classList.add("chart");
  const w = Math.max(container.clientWidth || 300, 120);
  const svg = el("svg", { viewBox: `0 0 ${w} ${height}`, height, role: "img" }, container);
  return { svg, w, h: height };
}
function autoResize(container, render) {
  if (container._ro) container._ro.disconnect();
  let last = container.clientWidth;
  const ro = new ResizeObserver(() => {
    if (Math.abs(container.clientWidth - last) > 4) { last = container.clientWidth; render(); }
  });
  ro.observe(container);
  container._ro = ro;
  render();
}

// ---------------------------------------------------------------- line / area
export function lineChart(container, opt) {
  autoResize(container, () => drawLine(container, opt));
}
function drawLine(container, opt) {
  const H = opt.height || 220, m = { l: 46, r: 14, t: 10, b: 24, ...(opt.margin || {}) };
  const { svg, w } = mount(container, H);
  const series = (opt.series || []).filter((s) => s.points && s.points.length);
  if (!series.length) { container.innerHTML = `<div class="empty">${esc(opt.empty || "No data in range")}</div>`; return; }
  const xs = series.flatMap((s) => s.points.map((p) => p[0]));
  const ys = series.flatMap((s) => s.points.map((p) => p[1]).concat((s.band || []).flatMap((b) => [b[1], b[2]])))
    .filter((v) => v !== null && Number.isFinite(v));
  let [x0, x1] = opt.xDomain || [Math.min(...xs), Math.max(...xs)];
  if (x1 === x0) { x0 -= 1; x1 += 1; }
  let [y0, y1] = opt.yDomain || [Math.min(...ys, ...(opt.refLines || []).map((r) => r.y)), Math.max(...ys, ...(opt.refLines || []).map((r) => r.y))];
  if (!opt.yDomain) { const pad = (y1 - y0) * 0.08 || Math.abs(y1) * 0.1 || 1; y0 = opt.zero ? Math.min(0, y0) : y0 - pad; y1 += pad; }
  const yt = niceTicks(y0, y1, opt.yTicks || 4); y0 = Math.min(y0, yt[0]); y1 = Math.max(y1, yt[yt.length - 1]);
  const X = (v) => m.l + ((v - x0) / (x1 - x0)) * (w - m.l - m.r);
  const Y = (v) => H - m.b - ((v - y0) / (y1 - y0)) * (H - m.t - m.b);
  const g = el("g", { class: "grid" }, svg), ax = el("g", { class: "axis" }, svg);
  const yf = opt.yFormat || ((v) => fmtNum(v));
  yt.forEach((v) => { el("line", { x1: m.l, x2: w - m.r, y1: Y(v), y2: Y(v) }, g); const t = el("text", { x: m.l - 6, y: Y(v) + 3, "text-anchor": "end" }, ax); t.textContent = yf(v); });
  const xt = opt.xType === "time" ? timeTicks(x0, x1, Math.max(2, Math.floor((w - m.l) / 90))) : niceTicks(x0, x1, Math.max(2, Math.floor((w - m.l) / 70)));
  const xf = opt.xFormat || (opt.xType === "time" ? (v) => fmtTime(v, x1 - x0) : (v) => fmtNum(v));
  xt.forEach((v) => { if (v < x0 || v > x1) return; const t = el("text", { x: X(v), y: H - 6, "text-anchor": "middle" }, ax); t.textContent = xf(v); });
  el("line", { class: "baseline", x1: m.l, x2: w - m.r, y1: H - m.b, y2: H - m.b }, svg);
  (opt.refLines || []).forEach((r) => {
    el("line", { x1: m.l, x2: w - m.r, y1: Y(r.y), y2: Y(r.y), stroke: r.color || T.muted, "stroke-dasharray": "4 4", "stroke-width": 1 }, svg);
    if (r.label) { const t = el("text", { x: w - m.r, y: Y(r.y) - 4, "text-anchor": "end", fill: r.color || T.muted, "font-size": 11, "font-family": "var(--sans)" }, svg); t.textContent = r.label; }
  });
  series.forEach((s, i) => {
    const color = s.color || PALETTE[i % PALETTE.length];
    if (s.band && s.band.length) {
      const top = s.band.map((b) => `${X(b[0])},${Y(b[2])}`), bot = s.band.slice().reverse().map((b) => `${X(b[0])},${Y(b[1])}`);
      el("polygon", { points: top.concat(bot).join(" "), fill: color, opacity: 0.12 }, svg);
    }
    const segs = []; let cur = [];
    s.points.forEach((p) => { if (p[1] === null || !Number.isFinite(p[1])) { if (cur.length) segs.push(cur); cur = []; } else cur.push(p); });
    if (cur.length) segs.push(cur);
    segs.forEach((seg) => {
      const d = seg.map((p, j) => `${j ? "L" : "M"}${X(p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`).join("");
      if (opt.area || s.area) {
        const grad = `g${Math.random().toString(36).slice(2, 8)}`;
        const defs = el("defs", {}, svg), lg = el("linearGradient", { id: grad, x1: 0, x2: 0, y1: 0, y2: 1 }, defs);
        el("stop", { offset: "0%", "stop-color": color, "stop-opacity": 0.32 }, lg); el("stop", { offset: "100%", "stop-color": color, "stop-opacity": 0 }, lg);
        el("path", { d: `${d}L${X(seg[seg.length - 1][0])},${Y(y0)}L${X(seg[0][0])},${Y(y0)}Z`, fill: `url(#${grad})` }, svg);
      }
      el("path", { d, fill: "none", stroke: color, "stroke-width": s.width || 2, "stroke-linejoin": "round", "stroke-linecap": "round", "stroke-dasharray": s.dash || null }, svg);
      if (s.markers || seg.length === 1) seg.forEach((p) => el("circle", { cx: X(p[0]), cy: Y(p[1]), r: 3.5, fill: color, stroke: T.panel, "stroke-width": 2 }, svg));
    });
  });
  // crosshair
  const cross = el("line", { y1: m.t, y2: H - m.b, stroke: T.muted, "stroke-width": 1, opacity: 0 }, svg);
  const dots = series.map((s, i) => el("circle", { r: 4.5, fill: s.color || PALETTE[i % PALETTE.length], stroke: T.panel, "stroke-width": 2, opacity: 0 }, svg));
  const hit = el("rect", { x: m.l, y: m.t, width: w - m.l - m.r, height: H - m.t - m.b, fill: "transparent" }, svg);
  hit.addEventListener("mousemove", (e) => {
    const r = svg.getBoundingClientRect(), px = ((e.clientX - r.left) / r.width) * w;
    const xv = x0 + ((px - m.l) / (w - m.l - m.r)) * (x1 - x0);
    let rows = "", xLabel = null;
    series.forEach((s, i) => {
      let best = null;
      for (const p of s.points) if (p[1] !== null && (!best || Math.abs(p[0] - xv) < Math.abs(best[0] - xv))) best = p;
      if (!best) return;
      xLabel = xLabel ?? best[0];
      cross.setAttribute("x1", X(best[0])); cross.setAttribute("x2", X(best[0])); cross.setAttribute("opacity", 0.6);
      dots[i].setAttribute("cx", X(best[0])); dots[i].setAttribute("cy", Y(best[1])); dots[i].setAttribute("opacity", 1);
      rows += `<div class="r"><span><i class="dot" style="background:${s.color || PALETTE[i]}"></i> ${esc(s.name || "")}</span><b>${esc(yf(best[1]))}${esc(opt.unit || "")}</b></div>`;
    });
    const head = opt.xType === "time" ? fmtDateTime(xLabel) : (opt.xTipFormat || xf)(xLabel);
    showTip(e, `<div class="t">${esc(head)}</div>${rows}`);
  });
  hit.addEventListener("mouseleave", () => { hideTip(); cross.setAttribute("opacity", 0); dots.forEach((d) => d.setAttribute("opacity", 0)); });
}
function timeTicks(x0, x1, n) {
  const span = x1 - x0, steps = [60, 300, 900, 1800, 3600, 7200, 10800, 21600, 43200, 86400, 172800, 604800];
  const step = steps.find((s) => span / s <= n) || 604800 * 4;
  const tz = -tzOffset(x0), out = [];
  for (let v = Math.ceil((x0 - tz) / step) * step + tz; v <= x1; v += step) out.push(v);
  return out;
}

// --------------------------------------------------------------------- bars
export function barChart(container, opt) { autoResize(container, () => drawBars(container, opt)); }
function drawBars(container, opt) {
  const H = opt.height || 200, m = { l: 44, r: 10, t: 10, b: opt.rotate ? 46 : 24, ...(opt.margin || {}) };
  const cats = opt.categories || [];
  if (!cats.length) { container.innerHTML = `<div class="empty">${esc(opt.empty || "No data")}</div>`; return; }
  const { svg, w } = mount(container, H);
  const series = opt.series;
  const totals = cats.map((_, i) => opt.stacked ? series.reduce((a, s) => a + (s.values[i] || 0), 0) : Math.max(...series.map((s) => s.values[i] || 0)));
  let y1 = opt.yMax ?? Math.max(...totals, 0) * 1.08; if (!(y1 > 0)) y1 = 1;
  const yt = niceTicks(0, y1, 4); y1 = yt[yt.length - 1];
  const Y = (v) => H - m.b - (v / y1) * (H - m.t - m.b);
  const g = el("g", { class: "grid" }, svg), ax = el("g", { class: "axis" }, svg);
  const yf = opt.yFormat || ((v) => fmtNum(v, 0));
  yt.forEach((v) => { el("line", { x1: m.l, x2: w - m.r, y1: Y(v), y2: Y(v) }, g); const t = el("text", { x: m.l - 6, y: Y(v) + 3, "text-anchor": "end" }, ax); t.textContent = yf(v); });
  const band = (w - m.l - m.r) / cats.length, gap = Math.max(2, band * 0.18);
  const groupW = band - gap, bw = opt.stacked ? groupW : (groupW - 2 * (series.length - 1)) / series.length;
  const every = Math.max(1, Math.ceil(cats.length / Math.max(1, Math.floor((w - m.l) / (opt.rotate ? 22 : 48)))));
  cats.forEach((c, i) => {
    const gx = m.l + i * band + gap / 2; let acc = 0;
    series.forEach((s, j) => {
      const v = s.values[i] || 0; if (v <= 0 && !opt.showZero) return;
      const x = opt.stacked ? gx : gx + j * (bw + 2);
      const yTop = Y(opt.stacked ? acc + v : v), yBot = Y(opt.stacked ? acc : 0);
      const color = (s.colors && s.colors[i]) || s.color || PALETTE[j % PALETTE.length];
      const hgt = Math.max(0, yBot - yTop - (opt.stacked && acc > 0 ? 2 : 0));
      const r = Math.min(3, bw / 2, hgt);
      const path = `M${x},${yBot}V${yTop + r}Q${x},${yTop} ${x + r},${yTop}H${x + bw - r}Q${x + bw},${yTop} ${x + bw},${yTop + r}V${yBot}Z`;
      const bar = el("path", { d: path, fill: color }, svg);
      const hit = el("rect", { x: gx, y: m.t, width: groupW, height: H - m.t - m.b, fill: "transparent" }, svg);
      const html = `<div class="t">${esc(opt.catLabel ? opt.catLabel(c) : c)}</div>` + series.map((ss, k) => `<div class="r"><span><i class="dot" style="background:${(ss.colors && ss.colors[i]) || ss.color || PALETTE[k]}"></i> ${esc(ss.name)}</span><b>${esc((opt.tipFormat || yf)(ss.values[i] || 0))}</b></div>`).join("");
      hit.addEventListener("mousemove", (e) => { bar.setAttribute("opacity", 0.8); showTip(e, html); });
      hit.addEventListener("mouseleave", () => { bar.setAttribute("opacity", 1); hideTip(); });
      acc += v;
    });
    if (i % every === 0) {
      const lx = gx + groupW / 2, t = el("text", opt.rotate ? { x: lx, y: H - m.b + 10, "text-anchor": "end", transform: `rotate(-40 ${lx} ${H - m.b + 10})` } : { x: lx, y: H - 6, "text-anchor": "middle" }, ax);
      t.textContent = opt.catLabel ? opt.catLabel(c) : c;
    }
  });
  el("line", { class: "baseline", x1: m.l, x2: w - m.r, y1: Y(0), y2: Y(0) }, svg);
}

export function histogram(container, { edges, counts, color, xFormat, height, unit }) {
  const cats = counts.map((_, i) => i);
  barChart(container, {
    categories: cats, height, series: [{ name: "Count", values: counts, color: color || PALETTE[0] }],
    catLabel: (i) => `${(xFormat || fmtNum)(edges[i])}–${(xFormat || fmtNum)(edges[i + 1])}${unit || ""}`,
    rotate: false, margin: { b: 24 },
  });
}

// ---------------------------------------------------------- horizontal bars
export function hbarChart(container, opt) { autoResize(container, () => drawHbars(container, opt)); }
function drawHbars(container, opt) {
  const rows = opt.rows || [];
  if (!rows.length) { container.innerHTML = `<div class="empty">No data</div>`; return; }
  const rowH = opt.rowHeight || 24, m = { l: opt.labelWidth || 170, r: 56, t: 4, b: 20 };
  const H = m.t + m.b + rows.length * rowH;
  const { svg, w } = mount(container, H);
  const max = opt.max ?? Math.max(...rows.map((r) => (r.ci ? r.ci[1] : r.value) || 0)) * 1.05;
  const min = opt.min ?? 0;
  const X = (v) => m.l + ((v - min) / (max - min || 1)) * (w - m.l - m.r);
  const ax = el("g", { class: "axis" }, svg), g = el("g", { class: "grid" }, svg);
  const xf = opt.format || ((v) => fmtNum(v, 3));
  niceTicks(min, max, 4).forEach((v) => { if (v > max) return; el("line", { x1: X(v), x2: X(v), y1: m.t, y2: H - m.b }, g); const t = el("text", { x: X(v), y: H - 5, "text-anchor": "middle" }, ax); t.textContent = xf(v); });
  rows.forEach((r, i) => {
    const y = m.t + i * rowH, bh = Math.min(14, rowH - 8), cy = y + rowH / 2;
    const lab = el("text", { x: m.l - 8, y: cy + 4, "text-anchor": "end", fill: r.highlight ? T.text : T.text2, "font-size": 11.5, "font-weight": r.highlight ? 600 : 400 }, svg);
    lab.textContent = r.label.length > 28 ? r.label.slice(0, 27) + "…" : r.label;
    const color = r.color || (r.highlight ? T.accent : opt.color || PALETTE[0]);
    const x0 = X(Math.max(min, Math.min(0, r.value))), x1 = X(Math.max(0, r.value));
    const bar = el("rect", { x: Math.min(x0, x1), y: cy - bh / 2, width: Math.max(1, Math.abs(x1 - x0)), height: bh, rx: 3, fill: color, opacity: r.muted ? 0.45 : 1 }, svg);
    if (r.highlight) el("rect", { x: Math.min(x0, x1) - 2, y: cy - bh / 2 - 2, width: Math.abs(x1 - x0) + 4, height: bh + 4, rx: 4, fill: "none", stroke: T.accent, "stroke-width": 1.2, opacity: 0.8 }, svg);
    if (r.ci) {
      el("line", { x1: X(r.ci[0]), x2: X(r.ci[1]), y1: cy, y2: cy, stroke: T.text, "stroke-width": 1.4, opacity: 0.8 }, svg);
      [r.ci[0], r.ci[1]].forEach((v) => el("line", { x1: X(v), x2: X(v), y1: cy - 4, y2: cy + 4, stroke: T.text, "stroke-width": 1.4, opacity: 0.8 }, svg));
    }
    const vt = el("text", { x: w - m.r + 6, y: cy + 4, fill: T.text2, "font-size": 11.5, "font-family": "var(--sans)", style: "font-variant-numeric: tabular-nums" }, svg);
    vt.textContent = xf(r.value);
    const hit = el("rect", { x: 0, y, width: w, height: rowH, fill: "transparent" }, svg);
    hit.addEventListener("mousemove", (e) => { bar.setAttribute("opacity", 0.8); showTip(e, `<div class="t">${esc(r.label)}</div><div class="r"><span>${esc(opt.valueLabel || "value")}</span><b>${esc(xf(r.value))}</b></div>${r.ci ? `<div class="r"><span>95% CI</span><b>${esc(xf(r.ci[0]))} – ${esc(xf(r.ci[1]))}</b></div>` : ""}${r.extra || ""}`); });
    hit.addEventListener("mouseleave", () => { bar.setAttribute("opacity", r.muted ? 0.45 : 1); hideTip(); });
  });
  if (opt.zeroLine) el("line", { x1: X(0), x2: X(0), y1: m.t, y2: H - m.b, stroke: T.muted }, svg);
}

// --------------------------------------------------------------- heatmap
export function heatmap(container, { rows, cols, values, rowLabel, colLabel, unit }) {
  const max = Math.max(1, ...values.flat());
  container.innerHTML = "";
  const wrap = document.createElement("div");
  wrap.className = "heat";
  wrap.style.gridTemplateColumns = `64px repeat(${cols.length}, minmax(6px, 1fr))`;
  const lab = (t) => { const d = document.createElement("div"); d.style.cssText = "font:11px var(--sans);color:var(--muted);min-height:0"; d.textContent = t; return d; };
  rows.forEach((r, i) => {
    wrap.appendChild(lab(rowLabel ? rowLabel(r) : r));
    cols.forEach((c, j) => {
      const v = values[i][j] || 0, cell = document.createElement("div");
      const k = v ? Math.min(SEQ.length - 1, Math.floor((v / max) * (SEQ.length - 1))) : -1;
      cell.style.background = k < 0 ? T.empty : SEQ[k];
      cell.addEventListener("mousemove", (e) => showTip(e, `<div class="t">${esc(rowLabel ? rowLabel(r) : r)} · ${esc(colLabel ? colLabel(c) : c)}</div><div class="r"><span>Count</span><b>${v}${esc(unit || "")}</b></div>`));
      cell.addEventListener("mouseleave", hideTip);
      wrap.appendChild(cell);
    });
  });
  wrap.appendChild(lab(""));
  cols.forEach((c, j) => { const d = lab(j % 3 === 0 ? (colLabel ? colLabel(c) : c) : ""); d.style.textAlign = "center"; wrap.appendChild(d); });
  container.appendChild(wrap);
}

// ----------------------------------------------------------------- gauge
export function gauge(container, { value, text, label, color, size }) {
  const S = size || 120, r = S / 2 - 9, c = 2 * Math.PI * r, v = Math.max(0, Math.min(1, value ?? 0));
  container.innerHTML = "";
  const wrap = document.createElement("div"); wrap.className = "gauge";
  const svg = el("svg", { viewBox: `0 0 ${S} ${S}`, width: S, height: S }, wrap);
  el("circle", { cx: S / 2, cy: S / 2, r, fill: "none", stroke: T.line, "stroke-width": 7 }, svg);
  const arc = el("circle", { cx: S / 2, cy: S / 2, r, fill: "none", stroke: color || T.accent, "stroke-width": 7, "stroke-linecap": "round",
    "stroke-dasharray": `${c * v} ${c}`, transform: `rotate(-90 ${S / 2} ${S / 2})` }, svg);
  arc.style.filter = T.light ? "none" : `drop-shadow(0 0 6px ${color || T.accent})`;
  const t = el("text", { x: S / 2, y: S / 2 + 6, "text-anchor": "middle", fill: T.text, "font-size": S / 5.6, "font-weight": 650, "font-family": "var(--display)", style: "font-variant-numeric: tabular-nums" }, svg);
  t.textContent = text ?? (value === null || value === undefined ? "–" : `${(v * 100).toFixed(1)}%`);
  if (label) { const cap = document.createElement("div"); cap.className = "cap"; cap.textContent = label; wrap.appendChild(cap); }
  container.appendChild(wrap);
}

export function legend(items) {
  return `<div class="legend">${items.map((it) => `<span><i class="${it.line ? "line" : ""}" style="background:${it.color}"></i>${esc(it.name)}</span>`).join("")}</div>`;
}
