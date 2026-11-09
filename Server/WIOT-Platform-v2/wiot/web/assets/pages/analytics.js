// Data science: fleet analysis, reliability, power, sensors, commands, ML model, what-if, project.
import { api, state, toast, ICONS, $, $$ } from "../api.js";
import { esc, lineChart, barChart, hbarChart, histogram, heatmap, gauge, legend, fmtNum, fmtDateTime, PALETTE, showTip, hideTip, riskColor, T } from "../charts.js";
import { contributionsHtml } from "./commands.js";

const TABS = [["overview", "Overview"], ["reliability", "Link reliability"], ["power", "Power & energy"], ["sensors", "Sensors"],
  ["commands", "Commands"], ["model", "Delivery model"], ["whatif", "What-if"], ["project", "Firmware & project"]];
const cache = {};
async function art(name) {
  if (!cache[name]) cache[name] = api(`/analytics/${name}`).catch((e) => { delete cache[name]; throw e; });
  return cache[name];
}
const pct = (v, d = 1) => v === null || v === undefined ? "–" : `${(v * 100).toFixed(d)}%`;
const num = (v, d = 3) => v === null || v === undefined ? "–" : (+v).toFixed(d);
const panel = (title, body, meta = "", cls = "") => `<section class="panel ${cls}"><header><h2>${title}</h2><span class="meta">${meta}</span></header><div class="body">${body}</div></section>`;
const keyOf = (r) => r.key || `${r.company}/N${r.node_id}`;

export async function render(root) {
  let tab = (location.hash.split("?")[1] || "").replace("tab=", "") || "overview";
  root.innerHTML = `
    <div class="row" style="margin-bottom:6px"><div class="tabs grow" id="tabs">${TABS.map(([k, l]) => `<button data-t="${k}" class="${k === tab ? "on" : ""}">${l}</button>`).join("")}</div>
      ${state.user.permissions.supervisor ? `<button class="btn sm" id="retrain">Re-run pipeline</button>` : ""}<a class="btn sm" href="/api/v2/analytics/report" target="_blank">Report (MD)</a></div>
    <div id="tab"></div>`;
  $$("#tabs button", root).forEach((b) => b.addEventListener("click", () => { tab = b.dataset.t; $$("#tabs button", root).forEach((x) => x.classList.toggle("on", x === b)); history.replaceState(null, "", `#/analytics?tab=${tab}`); show(); }));
  $("#retrain", root)?.addEventListener("click", async () => {
    const j = await api("/analytics/retrain", { method: "POST" }); toast(`Pipeline ${j.state}`, "ok");
    const poll = setInterval(async () => { const s = (await api("/analytics")).job; if (s.state !== "running") { clearInterval(poll); Object.keys(cache).forEach((k) => delete cache[k]); toast(`Pipeline ${s.state}`, s.state === "succeeded" ? "ok" : "error"); show(); } }, 4000);
  });
  async function show() {
    const box = $("#tab", root); box.innerHTML = `<div class="empty">Loading…</div>`;
    try { await VIEWS[tab](box); }
    catch (err) { box.innerHTML = `<div class="panel"><div class="empty">${esc(err.status === 404 ? "Analysis artifacts are not generated yet. Run: python -m wiot analyze" : err.message)}</div></div>`; }
  }
  show();
}

// ---------------------------------------------------------------- overview
async function viewOverview(box) {
  const s = await art("summary");
  const head = Object.values(s.headline || {});
  box.innerHTML = `
    <div class="tiles" style="margin-bottom:16px">${head.slice(0, 6).map((hd, i) => `<div class="tile ${i === 0 ? "hl" : ""}"><div class="label">${esc(hd.label)}</div><div class="v">${esc(typeof hd.value === "number" ? fmtNum(hd.value, 2) : hd.value)}<small>${esc(hd.unit || "")}</small></div></div>`).join("")}</div>
    <div class="grid g-wide">
      ${panel("Key findings", `<ol class="findings">${(s.findings || []).map((f) => `<li>${esc(f)}</li>`).join("")}</ol>`, `${fmtDateTime(s.data_window.start).slice(0, 10)} → ${fmtDateTime(s.data_window.end).slice(0, 10)}`)}
      ${panel("Dataset", `<dl class="kv">${Object.entries(s.counts || {}).map(([k, v]) => `<dt>${esc(k.replace(/_/g, " "))}</dt><dd>${(+v).toLocaleString()}</dd>`).join("")}<dt>Generated</dt><dd>${esc(String(s.generated_at).slice(0, 19))}</dd></dl>
        <p class="note">Bench and field-trial data from the deployed STM32 nodes and gateways, read-only from the production databases.</p>`)}
    </div>
    <section class="panel" style="margin-top:16px"><header><h2>Per-node health</h2><span class="meta">${(s.nodes || []).length} NODES</span></header>
      <div class="table-wrap"><table class="data"><thead><tr><th>Node</th><th class="num">Messages</th><th class="num">Availability</th><th class="num">Median interval</th><th class="num">p95 interval</th><th class="num">Gaps</th>
        <th class="num">Battery last</th><th class="num">Slope mV/day</th><th class="num">WDT</th><th class="num">Power resets</th><th class="num">RTC valid</th><th>Dominant mode</th></tr></thead>
      <tbody>${(s.nodes || []).map((n) => { const modes = Object.entries(n.power_modes || {}).sort((a, b) => b[1] - a[1]);
        return `<tr><td class="mono">${esc(n.company)} · N${n.node_id}</td><td class="num">${(n.messages || 0).toLocaleString()}</td><td class="num">${fmtNum(n.availability_pct, 1)}%</td>
        <td class="num">${fmtNum(n.median_interval_s, 0)} s</td><td class="num">${fmtNum(n.p95_interval_s, 0)} s</td><td class="num">${n.gaps ?? "–"}</td><td class="num">${n.battery_last ? (+n.battery_last).toFixed(2) : "–"}</td>
        <td class="num">${n.battery_slope_mv_per_day === null || n.battery_slope_mv_per_day === undefined ? "–" : (+n.battery_slope_mv_per_day).toFixed(1)}</td><td class="num">${n.wdt_resets ?? "–"}</td><td class="num">${n.power_resets ?? "–"}</td>
        <td class="num">${fmtNum(n.rtc_valid_pct, 0)}%</td><td>${esc(modes[0]?.[0] || "–")}</td></tr>`; }).join("")}</tbody></table></div></section>`;
}

// ------------------------------------------------------------- reliability
async function viewReliability(box) {
  const l = await art("link");
  const nodes = l.per_node || [];
  box.innerHTML = `
    <div class="grid g-2">
      ${panel("Daily uplinks per node", `<div id="daily"></div><div id="daily-lg"></div>`, `${nodes.length} nodes`, "span-2")}
      ${panel("Uplink inter-arrival distribution", `<div class="row" style="margin-bottom:8px"><select class="input" id="node-sel" style="max-width:260px">${nodes.map((n, i) => `<option value="${i}">${esc(keyOf(n))}</option>`).join("")}</select></div><div id="ihist"></div><p class="note">Seconds between consecutive uplinks. Long right tail = missed reports or sleep windows.</p>`)}
      ${panel("Store-and-forward latency", `<div id="sf"></div><div class="table-wrap" style="margin-top:12px"><table class="data"><thead><tr><th>Power mode</th><th class="num">n</th><th class="num">p50</th><th class="num">p90</th><th class="num">p99</th></tr></thead><tbody>${(l.store_forward?.by_mode || []).map((r) => `<tr><td>${esc(r.mode)}</td><td class="num">${r.n}</td><td class="num">${fmtNum(r.p50, 0)} s</td><td class="num">${fmtNum(r.p90, 0)} s</td><td class="num">${fmtNum(r.p99, 0)} s</td></tr>`).join("")}</tbody></table></div><p class="note">received_at − measured_at for samples stamped by a trusted node RTC.</p>`)}
      ${panel("Uplink activity · day × hour", `<div id="heat"></div>`, "", "span-2")}
    </div>`;
  const days = [...new Set(nodes.flatMap((n) => (n.daily || []).map((d) => d.day)))].sort();
  const toT = (d) => Math.floor(new Date(d + "T12:00:00").getTime() / 1000);
  const series = nodes.slice(0, 8).map((n, i) => ({ name: keyOf(n), color: PALETTE[i], points: (n.daily || []).map((d) => [toT(d.day), d.count]), markers: true }));
  lineChart($("#daily", box), { series, xType: "time", height: 240, zero: true, xFormat: (t) => fmtDateTime(t).slice(5, 10) });
  $("#daily-lg", box).innerHTML = legend(series.map((s) => ({ name: s.name, color: s.color, line: true })));
  const drawHist = () => { const n = nodes[+$("#node-sel", box).value]; if (n?.interval_hist) histogram($("#ihist", box), { ...n.interval_hist, color: PALETTE[0], height: 200, unit: " s", xFormat: (v) => fmtNum(v, 0) }); };
  $("#node-sel", box).addEventListener("change", drawHist); drawHist();
  if (l.store_forward?.hist) histogram($("#sf", box), { ...l.store_forward.hist, color: PALETTE[6], height: 170, unit: " s", xFormat: (v) => fmtNum(v, 0) });
  if (l.heatmap) heatmap($("#heat", box), { rows: l.heatmap.days, cols: l.heatmap.hours, values: l.heatmap.counts, rowLabel: (d) => String(d).slice(5), colLabel: (h) => `${String(h).padStart(2, "0")}h`, unit: " uplinks" });
}

// ------------------------------------------------------------------ power
async function viewPower(box) {
  const p = await art("power");
  const em = p.energy_model || {};
  box.innerHTML = `
    <div class="grid g-2">
      ${panel("Battery voltage", `<div id="batt"></div><div id="batt-lg"></div><p class="note">Supply voltage reported by each node. Reset events are listed below.</p>`, "", "span-2")}
      ${panel("Battery-life model", `<div class="row" style="margin-bottom:8px"><label class="label">Capacity</label><select class="input" id="cap" style="max-width:160px">${(em.capacities_mah || []).map((c) => `<option value="${c}">${c} mAh</option>`).join("")}</select></div>
        <div id="life"></div><div id="life-lg"></div><ul class="note" style="padding-left:18px">${(em.assumptions || []).map((a) => `<li>${esc(a)}</li>`).join("")}</ul>`, "DAYS VS REPORT INTERVAL")}
      ${panel("Power modes observed", `<div class="table-wrap"><table class="data"><thead><tr><th>Node</th><th>Mode</th><th>State</th><th class="num">Messages</th></tr></thead><tbody>${(p.modes || []).map((m) => `<tr><td class="mono">${esc(m.key)}</td><td>${esc(m.mode)}</td><td>${esc(m.state)}</td><td class="num">${m.count}</td></tr>`).join("")}</tbody></table></div>
        <div class="section-title" style="margin-top:16px">Reset events (${(p.resets || []).length})</div>
        <div class="table-wrap" style="max-height:220px"><table class="data"><tbody>${(p.resets || []).slice(-60).reverse().map((r) => `<tr><td class="mono dim">${fmtDateTime(r.t)}</td><td>${esc(r.company)} · N${r.node_id}</td><td>${r.kind === "wdt" ? '<span class="badge serious">Watchdog</span>' : '<span class="badge warning">Power-on</span>'}</td></tr>`).join("")}</tbody></table></div>`)}
    </div>`;
  const series = (p.battery || []).slice(0, 8).map((b, i) => ({ name: keyOf(b), color: PALETTE[i], points: b.points }));
  lineChart($("#batt", box), { series, xType: "time", height: 250, unit: " V", yFormat: (v) => v.toFixed(2), refLines: [{ y: 3.45, label: "low-battery threshold", color: T.ref }] });
  $("#batt-lg", box).innerHTML = legend(series.map((s) => ({ name: s.name, color: s.color, line: true })));
  const drawLife = () => {
    const cap = $("#cap", box).value, cfgs = em.configs || [];
    const s2 = cfgs.slice(0, 8).map((c, i) => ({ name: c.name, color: PALETTE[i], markers: true,
      points: (em.intervals_s || []).map((iv) => [Math.log10(iv), em.life_days?.[c.name]?.[iv]?.[cap] ?? null]) }));
    lineChart($("#life", box), { series: s2, height: 250, unit: " days", zero: true, xFormat: (v) => { const s = 10 ** v; return s >= 3600 ? `${(s / 3600).toFixed(0)} h` : s >= 60 ? `${(s / 60).toFixed(0)} min` : `${s.toFixed(0)} s`; } });
    $("#life-lg", box).innerHTML = legend(s2.map((s) => ({ name: s.name, color: s.color, line: true })));
  };
  if ($("#cap", box)) { $("#cap", box).addEventListener("change", drawLife); drawLife(); }
}

// ---------------------------------------------------------------- sensors
async function viewSensors(box) {
  const s = await art("sensors");
  const ch = s.channels || [];
  box.innerHTML = `
    <div class="grid g-2">
      ${panel("Sensor channels", `<div class="table-wrap"><table class="data"><thead><tr><th>Channel</th><th class="num">n</th><th class="num">Mean</th><th class="num">Std</th><th class="num">Min</th><th class="num">Median</th><th class="num">Max</th></tr></thead>
        <tbody>${ch.map((c, i) => `<tr class="clickable" data-i="${i}"><td>${esc(c.name)} <span class="muted">${esc(c.unit || "")}</span></td><td class="num">${c.n}</td><td class="num">${fmtNum(c.mean)}</td><td class="num">${fmtNum(c.std)}</td><td class="num">${fmtNum(c.min)}</td><td class="num">${fmtNum(c.p50)}</td><td class="num">${fmtNum(c.max)}</td></tr>`).join("")}</tbody></table></div>
        <div class="section-title" style="margin-top:14px" id="hist-title"></div><div id="chist"></div>`)}
      ${panel("Spearman correlation", `<div id="corr"></div><p class="note">Blue = positive, red = negative, gray ≈ 0. Hover a cell for ρ.</p>`)}
      ${panel("Top anomalies", `<div class="table-wrap" style="max-height:360px"><table class="data"><thead><tr><th>When</th><th>Node</th><th>Driver channel</th><th class="num">Value</th><th class="num">Expected</th><th class="num">Score</th></tr></thead><tbody>${(s.anomalies || []).map((a) => `<tr><td class="mono dim">${fmtDateTime(a.t)}</td><td>${esc(a.company)} · N${a.node_id}</td><td>${esc(a.channel)}</td><td class="num">${fmtNum(a.value)}</td><td class="num">${fmtNum(a.expected)}</td><td class="num">${fmtNum(a.score, 3)}</td></tr>`).join("")}</tbody></table></div>`, "ISOLATION FOREST", "span-2")}
      ${panel("Data quality", `<dl class="kv">${Object.entries(s.quality || {}).map(([k, v]) => `<dt>${esc(k.replace(/_/g, " "))}</dt><dd>${esc(typeof v === "object" ? JSON.stringify(v) : (typeof v === "number" && v <= 1 && v >= 0 && k.match(/share|rate|pct|frac/) ? pct(v) : v))}</dd>`).join("")}</dl>`, "", "span-2")}
    </div>`;
  const drawHist = (i) => { const c = ch[i]; if (!c?.hist) return; $("#hist-title", box).textContent = `Distribution · ${c.name}`; histogram($("#chist", box), { ...c.hist, color: PALETTE[i % 8], height: 180, unit: c.unit ? ` ${c.unit}` : "" }); };
  $$("tr[data-i]", box).forEach((tr) => tr.addEventListener("click", () => drawHist(+tr.dataset.i)));
  drawHist(0);
  const c = s.correlation;
  if (c?.channels?.length) {
    const n = c.channels.length, el = $("#corr", box);
    const color = (v) => { if (v === null || v === undefined) return T.empty; const a = Math.min(1, Math.abs(v)); return v >= 0 ? `rgba(57,135,229,${0.12 + 0.85 * a})` : `rgba(230,103,103,${0.12 + 0.85 * a})`; };
    el.innerHTML = `<div class="heat" style="grid-template-columns:110px repeat(${n}, minmax(18px,1fr))">${c.channels.map((r, i) => `<div style="font:10px var(--mono);color:var(--muted);align-self:center">${esc(r)}</div>${c.matrix[i].map((v, j) => `<div data-i="${i}" data-j="${j}" style="aspect-ratio:1;background:${color(v)}"></div>`).join("")}`).join("")}</div>`;
    $$("[data-j]", el).forEach((cell) => { const i = +cell.dataset.i, j = +cell.dataset.j, v = c.matrix[i][j];
      cell.addEventListener("mousemove", (e) => showTip(e, `<div class="t">${esc(c.channels[i])} × ${esc(c.channels[j])}</div><div class="r"><span>ρ</span><b>${v === null ? "–" : v.toFixed(2)}</b></div>`));
      cell.addEventListener("mouseleave", hideTip); });
  }
}

// --------------------------------------------------------------- commands
async function viewCommands(box) {
  const c = await art("commands");
  const types = (c.by_type || []).slice().sort((a, b) => b.n - a.n);
  box.innerHTML = `
    <div class="tiles" style="margin-bottom:16px">${Object.entries(c.totals || {}).map(([k, v], i) => `<div class="tile ${i === 0 ? "hl" : ""}"><div class="label">${esc(k.replace(/_/g, " "))}</div><div class="v">${(+v).toLocaleString()}</div></div>`).join("")}
      <div class="tile"><div class="label">ACK latency p50</div><div class="v">${fmtNum(c.ack_latency?.p50, 0)}<small>s</small></div><div class="s">p90 ${fmtNum(c.ack_latency?.p90, 0)} s</div></div>
      <div class="tile"><div class="label">Late ACK share</div><div class="v">${pct(c.late_share)}</div><div class="s">after the 30 s deadline</div></div></div>
    <div class="grid g-2">
      ${panel("Delivery rate by command type", `<div id="bytype"></div><p class="note">Bars = acknowledged share of resolved commands; whiskers = Wilson 95% CI.</p>`)}
      ${panel("Daily command volume", `<div id="daily"></div>${legend([{ name: "Acknowledged", color: PALETTE[0] }, { name: "Not acknowledged", color: PALETTE[7] }])}`)}
      ${panel("Node ACK latency", `<div id="lat"></div><p class="note">acknowledged_at − submitted_at.</p>`)}
      ${panel("Delivery by power mode at submission", `<div class="table-wrap"><table class="data"><thead><tr><th>Mode</th><th class="num">n</th><th class="num">ACK rate</th></tr></thead><tbody>${(c.by_power_mode || []).map((r) => `<tr><td>${esc(r.mode ?? r.power_mode ?? r.name)}</td><td class="num">${r.n}</td><td class="num">${pct(r.ack_rate)}</td></tr>`).join("")}</tbody></table></div>
        <div class="section-title" style="margin-top:14px">By node</div><div class="table-wrap"><table class="data"><thead><tr><th>Node</th><th class="num">n</th><th class="num">ACK rate</th></tr></thead><tbody>${(c.by_node || []).map((r) => `<tr><td>${esc(r.key || `${r.company} · N${r.node_id}`)}</td><td class="num">${r.n}</td><td class="num">${pct(r.ack_rate)}</td></tr>`).join("")}</tbody></table></div>`)}
    </div>`;
  hbarChart($("#bytype", box), { rows: types.map((t) => ({ label: `${t.cmd_type} (n=${t.n})`, value: t.ack_rate ?? 0, ci: t.ci_low !== undefined ? [t.ci_low, t.ci_high] : null })), max: 1, format: (v) => pct(v, 0), valueLabel: "ACK rate", labelWidth: 190 });
  const daily = c.daily || [];
  barChart($("#daily", box), { height: 220, stacked: true, categories: daily.map((d) => d.day), catLabel: (d) => String(d).slice(5),
    series: [{ name: "Acknowledged", values: daily.map((d) => d.acked), color: PALETTE[0] }, { name: "Not acknowledged", values: daily.map((d) => d.count - d.acked), color: PALETTE[7] }] });
  if (c.ack_latency?.hist) histogram($("#lat", box), { ...c.ack_latency.hist, color: PALETTE[2], height: 200, unit: " s", xFormat: (v) => fmtNum(v, 0) });
}

// ------------------------------------------------------------------ model
async function viewModel(box) {
  const m = await art("model");
  const H = m.holdout || {}, mm = H.model || {}, bb = H.baseline || {};
  const order = ["pr_auc", "roc_auc", "f1", "precision", "recall", "accuracy", "specificity", "brier"];
  const keys = order.filter((k) => mm[k]).concat(Object.keys(mm).filter((k) => !order.includes(k)));
  const lowerBetter = (k) => k.includes("brier") || k.includes("fpr") || k.includes("fnr");
  const cmHtml = (c, title) => c ? `<div><div class="label" style="margin-bottom:8px">${title}</div><div class="cm"><div class="h"></div><div class="h">PRED NO ACK</div><div class="h">PRED ACK</div>
    <div class="h" style="align-self:center">TRUE NO ACK</div><div class="tn"><b>${c.tn}</b>TN</div><div class="fp"><b>${c.fp}</b>FP</div>
    <div class="h" style="align-self:center">TRUE ACK</div><div class="fn"><b>${c.fn}</b>FN</div><div class="tp"><b>${c.tp}</b>TP</div></div></div>` : "";
  box.innerHTML = `
    <section class="panel"><header><h2>Model performance · temporal hold-out</h2><span class="meta">${esc(m.selected?.name || "")}</span></header><div class="body">
      <p style="margin:0 0 14px;color:var(--text-2);font-size:13px">${esc(m.task || "")} Evaluated on <b>${m.n_test}</b> held-out commands (${m.pos_test} delivered), submitted from ${esc(typeof m.split?.test_start === "number" ? fmtDateTime(m.split.test_start).slice(0, 16) : String(m.split?.test_start || "").slice(0, 16))} and never used for training, model selection, calibration or thresholds. Baseline: ${esc(H.baseline_definition || "")}</p>
      <div class="tiles">${keys.map((k, i) => { const v = mm[k], b = bb[k]; const better = b && v ? (lowerBetter(k) ? v.value < b.value : v.value > b.value) : null;
        return `<div class="metric ${i === 0 ? "hl" : ""}"><div class="label">${esc(k.replace(/_/g, "-").toUpperCase())}</div><div class="v">${num(v.value)}</div>
          ${v.ci_low !== undefined && v.ci_low !== null ? `<div class="ci">95% CI ${num(v.ci_low)}–${num(v.ci_high)}</div>` : ""}
          ${b ? `<div class="base">baseline <span class="delta ${better ? "up" : "down"}">${num(b.value)}</span></div>` : ""}</div>`; }).join("")}</div>
    </div></section>
    <section class="panel" style="margin-top:16px"><header><h2>Risk tiers · what the operator sees</h2><span class="meta">UNLIKELY &lt; ${num(m.selected?.tiers?.unlikely, 2)} ≤ UNCERTAIN &lt; ${num(m.selected?.tiers?.likely, 2)} ≤ LIKELY</span></header><div class="body">
      <div class="grid g-2"><div><div class="label" style="margin-bottom:8px">Hold-out · observed delivery rate per tier</div><div id="tiers-ho"></div></div>
      <div><div class="label" style="margin-bottom:8px">Training out-of-fold · observed delivery rate per tier</div><div id="tiers-oof"></div></div></div>
      <p class="note">Tier cut-offs were fixed on training out-of-fold predictions (precision / negative predictive value ≥ 0.80) before the hold-out was scored.</p></div></section>
    <div class="grid g-3" style="margin-top:16px">
      ${panel("Confusion matrices", `<div class="grid" style="gap:18px">${cmHtml(m.confusion?.model, `Model @ p ≥ ${num(m.selected?.threshold, 2)}`)}${cmHtml(m.confusion?.baseline, "Rule baseline")}</div>`)}
      ${panel("Precision–recall (hold-out)", `<div id="pr"></div>${legend([{ name: "Model", color: PALETTE[0], line: true }, { name: "Baseline", color: PALETTE[1], line: true }])}`)}
      ${panel("ROC (hold-out)", `<div id="roc"></div>${legend([{ name: "Model", color: PALETTE[0], line: true }, { name: "Baseline", color: PALETTE[1], line: true }])}`)}
    </div>
    <div class="grid g-2" style="margin-top:16px">
      ${panel("Candidate models · cross-validated PR-AUC", `<div id="cand"></div><div class="table-wrap" style="margin-top:12px"><table class="data"><thead><tr><th>Model</th><th class="num">PR-AUC</th><th class="num">ROC-AUC</th><th class="num">Brier</th><th class="num">best F1</th></tr></thead><tbody>${(m.candidates || []).map((c) => `<tr ${c.name === m.selected?.name ? 'class="sel"' : ""}><td>${esc(c.name)}</td><td class="num">${num(c.cv_pr_auc)}±${num(c.cv_pr_auc_std)}</td><td class="num">${num(c.cv_roc_auc)}</td><td class="num">${num(c.cv_brier)}</td><td class="num">${num(c.best_f1)}</td></tr>`).join("")}</tbody></table></div>
        <p class="note">${esc(m.selected?.why || "")}</p>`, "TRAIN ONLY · GROUPED CV")}
      ${panel("Explainability · global SHAP importance", `<div id="shap"></div><p class="note">mean |SHAP| (log-odds) on training commands.</p>`)}
      ${panel("Calibration (train out-of-fold)", `<div id="cal"></div><p class="note">Points on the dashed diagonal = calibrated probabilities.</p>`)}
      ${panel("Feature-set experiments", `<div id="fexp"></div><div class="section-title" style="margin-top:14px">Caveats</div><ul style="margin:0;padding-left:18px;color:var(--text-2);font-size:12.5px">${(m.notes || []).map((n) => `<li style="margin-bottom:6px">${esc(n)}</li>`).join("")}</ul>`)}
    </div>`;
  const tierRows = (t) => (t || []).map((r) => ({ label: `${r.tier} (n=${r.n}, ${pct(r.share, 0)} of commands)`, value: r.observed_ack_rate,
    color: riskColor(r.tier) }));
  hbarChart($("#tiers-ho", box), { rows: tierRows(m.selected?.tier_table_holdout), min: 0, max: 1, format: (v) => pct(v, 0), valueLabel: "delivered", labelWidth: 260, rowHeight: 34 });
  hbarChart($("#tiers-oof", box), { rows: tierRows(m.selected?.tier_table_oof), min: 0, max: 1, format: (v) => pct(v, 0), valueLabel: "delivered", labelWidth: 260, rowHeight: 34 });
  const curve = (el, model, base, xl, diag) => lineChart(el, { height: 230, xDomain: [0, 1], yDomain: [0, 1], series: [{ name: "Model", color: PALETTE[0], points: model || [] }, { name: "Baseline", color: PALETTE[1], points: base || [], dash: "5 4" }, ...(diag ? [{ name: "Chance", color: T.chance, points: [[0, 0], [1, 1]], width: 1, dash: "2 4" }] : [])], xFormat: (v) => v.toFixed(2), xTipFormat: (v) => `${xl} ${v.toFixed(3)}`, yFormat: (v) => v.toFixed(2) });
  curve($("#pr", box), m.curves?.pr?.model, m.curves?.pr?.baseline, "recall");
  curve($("#roc", box), m.curves?.roc?.model, m.curves?.roc?.baseline, "FPR", true);
  const cands = (m.candidates || []).slice().sort((a, b) => b.cv_pr_auc - a.cv_pr_auc);
  hbarChart($("#cand", box), { rows: cands.map((c) => ({ label: c.name, value: c.cv_pr_auc, ci: c.cv_pr_auc_std ? [c.cv_pr_auc - c.cv_pr_auc_std, c.cv_pr_auc + c.cv_pr_auc_std] : null, highlight: c.name === m.selected?.name, muted: /baseline/i.test(c.name) })), min: 0, max: 1, format: (v) => v.toFixed(3), valueLabel: "PR-AUC", labelWidth: 200 });
  hbarChart($("#shap", box), { rows: (m.shap_global || []).slice(0, 15).map((s, i) => ({ label: s.label || s.feature, value: s.mean_abs_shap, color: i === 0 ? T.accent : PALETTE[1], highlight: i === 0 })), format: (v) => v.toFixed(3), valueLabel: "mean |SHAP|", labelWidth: 200 });
  const cal = m.calibration || [];
  lineChart($("#cal", box), { height: 220, xDomain: [0, 1], yDomain: [0, 1], series: [{ name: "Observed delivery rate", color: PALETTE[0], points: cal.map((c) => [c.mean_pred, c.frac_pos]), markers: true }, { name: "Perfect", color: T.chance, points: [[0, 0], [1, 1]], dash: "4 4", width: 1 }], xFormat: (v) => v.toFixed(1), yFormat: (v) => v.toFixed(1) });
  hbarChart($("#fexp", box), { rows: (m.feature_set_experiments || []).map((f) => ({ label: `${f.name} (n=${f.n_features})`, value: f.cv_pr_auc, ci: f.cv_pr_auc_std ? [f.cv_pr_auc - f.cv_pr_auc_std, f.cv_pr_auc + f.cv_pr_auc_std] : null })), min: 0, max: 1, format: (v) => v.toFixed(3), labelWidth: 230 });
}

// ---------------------------------------------------------------- what-if
async function viewWhatIf(box) {
  const { features } = await api("/analytics/model/schema");
  box.innerHTML = `<div class="grid g-wide">
    ${panel("Ask “what if?” — edit the inputs and watch the delivery probability respond", `<form id="wf"><div class="form-grid">${features.map((f) => `<div class="field"><label title="${esc(f.name)}">${esc(f.label || f.name)}</label>${f.type === "category"
      ? `<select class="input" name="${esc(f.name)}">${(f.options || []).map((o) => `<option ${String(o) === String(f.default) ? "selected" : ""}>${esc(o)}</option>`).join("")}</select>`
      : `<input class="input" name="${esc(f.name)}" type="number" step="${f.step ?? "any"}" ${f.min !== undefined && f.min !== null ? `min="${f.min}"` : ""} ${f.max !== undefined && f.max !== null ? `max="${f.max}"` : ""} value="${f.default ?? 0}">`}</div>`).join("")}</div>
      <div class="row"><button class="btn" type="button" id="wf-reset">Reset</button><button class="btn primary" type="submit">Run prediction</button></div></form>`, "POST /api/v2/analytics/predict")}
    ${panel("Model output", `<div class="row" style="justify-content:center;gap:28px" id="wo-g"></div><div id="wo-c" style="margin-top:14px"></div>`)}
  </div>`;
  const form = $("#wf", box);
  async function run() {
    const fd = Object.fromEntries(new FormData(form));
    features.forEach((f) => { if (f.type !== "category") fd[f.name] = Number(fd[f.name]); });
    try {
      const r = await api("/analytics/predict", { method: "POST", body: { features: fd } });
      const color = riskColor(r.tier);
      $("#wo-g", box).innerHTML = `<div id="g1"></div><div><div class="label">Tier</div><div style="margin:8px 0"><span class="badge ${r.tier === "LIKELY" ? "good" : r.tier === "UNCERTAIN" ? "warning" : "critical"}">${esc(r.tier)}</span></div><div class="label">Threshold</div><div class="mono">${num(r.threshold, 3)}</div></div>`;
      gauge($("#g1", box), { value: r.probability, label: "P(delivered)", color, size: 150 });
      $("#wo-c", box).innerHTML = `<div class="section-title">Most influential features (SHAP)</div>${contributionsHtml(r.contributions)}`;
    } catch (err) { toast(err.message, "error"); }
  }
  form.addEventListener("submit", (e) => { e.preventDefault(); run(); });
  form.addEventListener("change", run);
  $("#wf-reset", box).addEventListener("click", () => { form.reset(); run(); });
  run();
}

// ---------------------------------------------------------------- project
function guardTable(title, data) {
  const rows = Object.entries(data || {});
  if (!rows.length) return "";
  const cols = [...new Set(rows.flatMap(([, v]) => (v && typeof v === "object") ? Object.keys(v) : ["count"]))];
  return `<div class="label" style="margin:14px 0 6px">${esc(title)}</div><table class="data"><thead><tr><th></th>${cols.map((c) => `<th class="num">${esc(c)}</th>`).join("")}</tr></thead>
    <tbody>${rows.map(([k, v]) => `<tr><td class="mono">${esc(k)}</td>${cols.map((c) => `<td class="num">${esc(String(v && typeof v === "object" ? v[c] ?? "–" : v))}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
}

async function viewProject(box) {
  const [fw, pj] = await Promise.all([art("firmware").catch(() => ({})), art("project").catch(() => ({}))]);
  const prof = (fw.profiles || []).slice().sort((a, b) => (b.flash_bytes || 0) - (a.flash_bytes || 0));
  const pg = fw.power_guard || {};
  const comps = (pj.components || []).slice().sort((a, b) => b.lines - a.lines);
  box.innerHTML = `
    <div class="tiles" style="margin-bottom:16px">
      <div class="tile hl"><div class="label">Lines of code</div><div class="v">${(pj.totals?.lines || 0).toLocaleString()}</div><div class="s">${(pj.totals?.files || 0).toLocaleString()} source files, excl. generated/backups</div></div>
      <div class="tile"><div class="label">Firmware profiles</div><div class="v">${prof.length}</div><div class="s">verified builds</div></div>
      <div class="tile"><div class="label">Power-config guard</div><div class="v">${pg.accepted ?? "–"}<small>/ ${pg.total ?? "–"}</small></div><div class="s">${pg.all_passed ? "all cases matched expectation" : "see details"}</div></div>
      <div class="tile"><div class="label">Automated tests</div><div class="v">${pj.tests?.functions ?? "–"}</div><div class="s">${pj.tests?.files ?? "–"} test files</div></div>
    </div>
    <div class="grid g-2">
      ${panel("Firmware memory footprint by build profile", `<div id="flash"></div>${legend([{ name: "Flash used", color: PALETTE[0] }, { name: "RAM used", color: PALETTE[2] }])}<p class="note">STM32F401: 256 KB flash · 64 KB RAM.</p>`)}
      ${panel("Codebase by component", `<div id="loc"></div>`)}
      ${panel("Power-configuration guard (compile-time)", `<dl class="kv"><dt>Total cases</dt><dd>${pg.total ?? "–"}</dd><dt>Accepted</dt><dd>${pg.accepted ?? "–"}</dd><dt>Rejected by #error</dt><dd>${pg.rejected ?? "–"}</dd><dt>All as expected</dt><dd>${pg.all_passed}</dd></dl>
        ${guardTable("By role", pg.by_role)}${guardTable("By transport", pg.by_transport)}`)}
      ${panel("Build trend", `<div id="trend"></div><div id="trend-lg"></div>`, "FLASH BYTES OVER BUILDS")}
    </div>`;
  barChart($("#flash", box), { height: 240, rotate: true, categories: prof.map((p) => p.name), series: [{ name: "Flash %", values: prof.map((p) => p.flash_pct || 0), color: PALETTE[0] }, { name: "RAM %", values: prof.map((p) => p.ram_pct || 0), color: PALETTE[2] }], yMax: 100, yFormat: (v) => `${v}%`, tipFormat: (v) => `${(+v).toFixed(1)}%` });
  hbarChart($("#loc", box), { rows: comps.map((c) => ({ label: c.name, value: c.lines, extra: `<div class="r"><span>files</span><b>${c.files}</b></div><div class="r"><span>language</span><b>${esc(c.language || "")}</b></div>` })), format: (v) => fmtNum(v, 0), valueLabel: "lines", labelWidth: 210 });
  const trend = fw.trend || [], builds = [...new Set(trend.map((t) => t.build))].sort();
  const profiles = [...new Set(trend.map((t) => t.profile))].slice(0, 8);
  const series = profiles.map((p, i) => ({ name: p, color: PALETTE[i], markers: true, points: builds.map((b, j) => [j, trend.find((t) => t.build === b && t.profile === p)?.flash_bytes ?? null]) }));
  lineChart($("#trend", box), { series, height: 230, xFormat: (j) => String(builds[Math.round(j)] || "").replace(/^\D+/, "").slice(-8), yFormat: (v) => `${fmtNum(v / 1024, 0)} KB` });
  $("#trend-lg", box).innerHTML = legend(series.map((s) => ({ name: s.name, color: s.color, line: true })));
}

const VIEWS = { overview: viewOverview, reliability: viewReliability, power: viewPower, sensors: viewSensors, commands: viewCommands, model: viewModel, whatif: viewWhatIf, project: viewProject };
