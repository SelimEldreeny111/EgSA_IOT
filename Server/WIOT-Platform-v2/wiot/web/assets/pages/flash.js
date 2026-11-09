// Flash data: the node's SPI-flash telemetry log — memory health, 24 h retention window,
// logging quality, live-gap recovery, archived-sample analysis, downloads and records.
import { api, state, onEvent, scoped, ago, badge, toast, ICONS, $, $$ } from "../api.js";
import { esc, lineChart, fmtNum as fmtNumBase, fmtTime, fmtDateTime, PALETTE, legend } from "../charts.js";
import { conv, unit } from "../units.js";

// Counts are exact ("14,322", not "14.3k"); measured values keep the shared formatter.
const fmtNum = (v, d = 2) => (d === 0 && v !== null && v !== undefined && Number.isFinite(+v) ? Math.round(+v).toLocaleString("en-US") : fmtNumBase(v, d));
// "11-04 14:06" — compact local date+time for ranges
const fmtShort = (t) => fmtDateTime(t).replace(/^\d{4}-/, "").replace(/:\d{2}$/, "");
const sameDay = (a, b) => fmtDateTime(a).slice(0, 10) === fmtDateTime(b).slice(0, 10);
const range = (a, b) => (!a ? "–" : b > a ? `${fmtShort(a)} → ${sameDay(a, b) ? fmtTime(b) : fmtShort(b)}` : fmtShort(a));

const NODE_KEY = "wiot.flashNode";
const PAGE = 200;
// unit kind from the analysis → [units.js kind | null, fixed unit]
const KIND = { flow: ["flow", ""], velocity: [null, "m/s"], volt: [null, "V"], pct: [null, "%"], temp: ["temp", ""], ec: [null, "µS/cm"] };
const disp = (v, kind) => (v === null || v === undefined ? null : KIND[kind]?.[0] ? conv(v, KIND[kind][0]) : v);
const uLabel = (kind) => (KIND[kind]?.[0] ? unit(KIND[kind][0]) : KIND[kind]?.[1] ?? "");
const DIGITS = { flow: 2, velocity: 2, volt: 2, pct: 1, temp: 1, ec: 0 };
const genColor = (g) => PALETTE[((g - 1) % PALETTE.length + PALETTE.length) % PALETTE.length];
const nodeName = (id) => `NODE-${String(id).padStart(3, "0")}`;
const CHIP_STATE = { Ready: "good", Full: "warning", Recovering: "info", Unformatted: "warning", Missing: "critical", Fault: "critical", Disabled: "neutral" };

function fmtBytes(b) {
  if (b === null || b === undefined) return "–";
  if (b >= 1048576) return `${(b / 1048576).toFixed(1)} MB`;
  if (b >= 1024) return `${(b / 1024).toFixed(1)} KB`;
  return `${b} B`;
}
function dur(s) {
  if (s === null || s === undefined) return "–";
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.max(0, Math.floor((s % 3600) / 60));
  return d ? `${d} d ${h} h` : h ? `${h} h ${m} min` : `${m} min`;
}
const spacing = (s) => (!s ? "–" : s < 120 ? `${Math.round(s)} s` : dur(s));
const pct = (v, d = 1) => (v === null || v === undefined ? "–" : `${(+v).toFixed(d)} %`);
const val = (v, kind) => (v === null || v === undefined ? "–" : `${fmtNum(disp(v, kind), DIGITS[kind] ?? 2)} ${uLabel(kind)}`.trim());

// Horizontal meter: segments [{ v (0-100), color, cls, label }] on one track, optional marker.
function meter(segs, { marker, height = 12 } = {}) {
  let left = 0;
  const parts = segs.map((s) => {
    const w = Math.max(0, Math.min(100 - left, s.v)); const at = left; left += w;
    return `<i class="${s.cls || ""}" style="left:${at}%;width:${w > 0 ? `max(${w}%, 3px)` : 0};${s.color ? `background:${s.color}` : ""}" title="${esc(s.label || "")}"></i>`;
  }).join("");
  return `<div class="fl-meter" style="height:${height}px">${parts}${marker !== undefined ? `<b class="fl-mark" style="left:${Math.max(0, Math.min(100, marker))}%"></b>` : ""}</div>`;
}

export async function render(root) {
  const canSend = state.user.permissions.command;
  let node = null, metric = null, xMode = null, offset = 0, data = null, timer = null, nodes = [];

  root.innerHTML = `
    <section class="panel fl-toolbar">
      <div class="body row">
        <div class="fl-pick"><span class="ico">${ICONS.chip}</span>
          <div><label for="fl-node" class="label">Node</label><select class="input" id="fl-node"></select></div></div>
        <div class="fl-age" id="fl-age"></div>
        <div class="grow"></div>
        <div class="fl-actions">
          <button class="btn" data-cmd="FLASH_STATUS" title="Ask the node for its memory counters">${ICONS.refresh}Read status</button>
          <button class="btn primary" data-cmd="FLASH_TODAY" title="Download every sample logged in the node's current 24 h window">${ICONS.download}Download today</button>
          <button class="btn" data-cmd="FLASH_LAST" title="Fetch only the most recent stored sample">Latest sample</button>
          <button class="btn ghost" data-cmd="FLASH_CANCEL" title="Stop a history download in progress">Cancel download</button>
          <a class="btn ghost" id="fl-csv" href="#">${ICONS.download}Export CSV</a>
          <button class="btn danger" data-cmd="CLEAR_FLASH" title="Erase the node's flash log">Erase log</button>
        </div>
      </div>
    </section>
    <div class="tiles fl-kpis" id="fl-kpis"></div>
    <div class="grid fl-g2">
      <section class="panel"><header><h2><span class="ico">${ICONS.chip}</span>Capacity &amp; 24-hour log window</h2><span class="meta" id="fl-cap-meta"></span></header><div class="body" id="fl-cap"></div></section>
      <section class="panel"><header><h2><span class="ico">${ICONS.analytics}</span>Logging quality &amp; gap recovery</h2><span class="meta" id="fl-q-meta"></span></header><div class="body" id="fl-q"></div></section>
    </div>
    <section class="panel fl-block"><header><h2><span class="ico">${ICONS.drop}</span>Archived samples</h2><span class="meta" id="fl-s-meta"></span></header>
      <div class="body"><div class="row fl-chart-tools"><div class="seg" id="fl-met"></div><div class="grow"></div><div class="seg" id="fl-x"></div></div>
        <div id="fl-chart"></div><div id="fl-legend"></div><div class="tiles fl-stats" id="fl-stats"></div>
        <p class="note">Only values whose validity flag was set when the node stored the sample are plotted. Colours follow the log generation (the node starts a new generation each time the log is cleared).</p></div></section>
    <div class="grid fl-g2 fl-gt">
      <section class="panel"><header><h2><span class="ico">${ICONS.history}</span>Log generations</h2><span class="meta" id="fl-g-meta"></span></header><div class="table-wrap"><table class="data"><thead><tr><th>Generation</th><th>Samples taken</th><th class="num">On node</th><th class="num">On server</th><th>Sequence</th><th>Completeness</th><th class="num">Spacing</th></tr></thead><tbody id="fl-gens"></tbody></table></div></section>
      <section class="panel"><header><h2><span class="ico">${ICONS.download}</span>History downloads</h2><span class="meta" id="fl-t-meta"></span></header><div class="table-wrap"><table class="data"><thead><tr><th>Request</th><th class="num">Gen.</th><th>Progress</th><th>Outcome</th><th>Last row</th></tr></thead><tbody id="fl-tr"></tbody></table></div></section>
    </div>
    <section class="panel fl-block"><header><h2><span class="ico">${ICONS.history}</span>Archived records</h2><span class="meta" id="fl-r-meta"></span></header>
      <div class="table-wrap"><table class="data"><thead><tr><th>Gen / seq</th><th>Sample time</th><th class="num">Flow</th><th class="num">Velocity</th><th class="num">Battery</th><th>Soil (HNDA)</th><th>Sondas EC</th><th class="num">Forward total</th><th>Flags</th></tr></thead><tbody id="fl-rows"></tbody></table></div>
      <div class="pager"><span class="dim" id="fl-page"></span><div class="row"><button class="btn sm" id="fl-prev">Previous</button><button class="btn sm" id="fl-next">Next</button></div></div></section>`;

  // ------------------------------------------------------------- node picker
  async function loadNodes() {
    const [fleet, fl] = await Promise.all([api("/fleet", { params: scoped() }).catch(() => ({ nodes: [] })), api("/flash/nodes", { params: scoped() }).catch(() => ({ nodes: [] }))]);
    const names = new Map(fleet.nodes.map((n) => [n.node_id, n.name]));
    nodes = [...new Set([...fl.nodes, ...fleet.nodes.map((n) => n.node_id)])].sort((a, b) => a - b);
    let saved = null; try { saved = +sessionStorage.getItem(NODE_KEY); } catch { /* optional */ }
    node = nodes.includes(node) ? node : nodes.includes(saved) ? saved : fl.nodes[0] ?? nodes[0] ?? null;
    $("#fl-node", root).innerHTML = nodes.map((id) => `<option value="${id}" ${id === node ? "selected" : ""}>${nodeName(id)}${names.get(id) ? ` · ${esc(names.get(id))}` : ""}${fl.nodes.includes(id) ? " · flash data" : ""}</option>`).join("") || `<option>No nodes in this region</option>`;
  }
  $("#fl-node", root).addEventListener("change", (e) => { node = +e.target.value; offset = 0; xMode = null; try { sessionStorage.setItem(NODE_KEY, node); } catch { /* optional */ } load(); });

  // ----------------------------------------------------------------- actions
  $$("[data-cmd]", root).forEach((b) => {
    b.disabled = !canSend;
    b.addEventListener("click", async () => {
      if (node === null) return;
      const type = b.dataset.cmd;
      if (type === "CLEAR_FLASH" && !confirm(`Erase the flash log of ${nodeName(node)}? Samples not yet downloaded are lost. This cannot be undone.`)) return;
      const body = { ...scoped(), node_id: node, cmd_type: type, delivery: "now", broadcast: false };
      if (type === "FLASH_TODAY") body.cmd_data = 0;
      b.disabled = true;
      try {
        const r = await api("/commands", { method: "POST", body });
        toast(`${type} #${r.request_id} sent to ${nodeName(node)} — results appear here as the node replies`, "ok");
      } catch (err) { toast(err.message, "error"); } finally { b.disabled = !canSend; }
    });
  });
  if (!canSend) $(".fl-actions", root).insertAdjacentHTML("afterbegin", `<span class="badge warning">Read-only role</span>`);

  // ------------------------------------------------------------------ render
  function paintKpis() {
    const m = data.memory, r = data.retention, q = data.quality;
    const gens = data.generations.length;
    const tiles = [
      ["Flash chip", m ? `<span class="badge ${CHIP_STATE[m.state_name] || "neutral"} fl-state">${esc(m.state_name)}</span>` : "–",
        m ? `${Math.round((m.capacity_bytes * 8) / 1048576)} Mbit · JEDEC ${m.jedec_hex}` : "no status received yet"],
      ["Records in log", m ? `${fmtNum(m.record_count, 0)}<small>/ ${fmtNum(m.maximum_records, 0)}</small>` : "–",
        m ? `generation ${m.generation} · latest seq ${m.latest_sequence}` : "send Read status"],
      ["Storage used", m ? fmtBytes(m.used_bytes) : "–", m ? `of ${fmtBytes(m.usable_bytes)} usable · ${pct(m.bytes_pct, 2)}` : ""],
      ["Samples not logged", q ? fmtNum(q.not_logged, 0) : "–", q ? `${pct(q.not_logged_pct)} of attempts · RTC ${q.rtc_trusted ? "trusted" : "NOT trusted"}` : "", q && q.not_logged_pct > 20 ? "warn" : ""],
      ["Log clears in", r ? dur(r.clears_in_s) : "–", r ? `window opened ${fmtDateTime(r.started)}` : ""],
      ["Archived on server", `${fmtNum(data.archived_total, 0)}<small>samples</small>`, `${gens} generation${gens === 1 ? "" : "s"} · ${data.transfers.length} download${data.transfers.length === 1 ? "" : "s"}`, "hl"],
    ];
    $("#fl-kpis", root).innerHTML = tiles.map(([k, v, s, cls]) => `<div class="tile ${cls || ""}"><div class="label">${k}</div><div class="v">${v}</div><div class="s">${esc(s)}</div></div>`).join("");
    $("#fl-age", root).innerHTML = m ? `<span class="dot" style="background:var(--${m.age_s < 900 ? "good" : "warning"})"></span> Status received ${ago(m.received_at)}` : `<span class="dot" style="background:var(--muted)"></span> No status from this node yet`;
  }

  function paintCapacity() {
    const m = data.memory, r = data.retention, box = $("#fl-cap", root);
    if (!m) { box.innerHTML = `<div class="empty">No flash status for ${nodeName(node)} yet. Press <b>Read status</b>; the node replies with its chip state, record counters and log window.</div>`; $("#fl-cap-meta", root).textContent = ""; return; }
    $("#fl-cap-meta", root).textContent = `${fmtBytes(m.capacity_bytes)} chip`;
    const fill = m.fill_pct || 0, proj = r?.projected_pct;
    const projText = !r?.records_per_hour ? "Too early in the window to project the fill rate."
      : r.overflow_at ? `At ${fmtNum(r.records_per_hour, 0)} records/h the log reaches its ${fmtNum(m.maximum_records, 0)}-record limit at ${fmtDateTime(r.overflow_at)}, before the daily clear — later samples will not be logged.`
      : `At ${fmtNum(r.records_per_hour, 0)} records/h the log will hold about ${fmtNum(r.projected_records, 0)} records (${pct(proj, 0)}) when it clears — no overflow expected.`;
    box.innerHTML = `
      <div class="fl-row"><div class="fl-row-h"><b>Record capacity</b><span class="dim">${fmtNum(m.record_count, 0)} now · ${r?.projected_records ? `≈${fmtNum(r.projected_records, 0)} at clear` : "projection pending"} · ${fmtNum(m.maximum_records, 0)} max</span></div>
        ${meter([{ v: fill, color: PALETTE[0], label: `Stored now ${pct(fill, 2)}` }, { v: Math.max(0, Math.min(100, (proj || 0)) - fill), cls: "proj", label: `Projected by clear ${pct(proj, 0)}` }], { height: 14 })}
        <div class="fl-scale"><span>0 %</span><span>50 %</span><span>100 %</span></div>
        <div class="legend"><span><i style="background:${PALETTE[0]}"></i>Stored now ${pct(fill, 2)}</span><span><i class="proj"></i>Projected by next clear ${pct(proj, 0)}</span></div>
        <p class="note ${r?.overflow_at ? "fl-warn" : ""}">${esc(projText)}</p></div>
      ${r ? `<div class="fl-row"><div class="fl-row-h"><b>24-hour log window</b><span class="dim">${pct(r.elapsed_pct)} elapsed</span></div>
        ${meter([{ v: r.elapsed_pct, color: PALETTE[2], label: "Elapsed" }], { marker: r.elapsed_pct, height: 10 })}
        <div class="fl-scale"><span>${fmtDateTime(r.started)}</span><span>clears ${fmtDateTime(r.next_clear)}</span></div></div>` : ""}
      <dl class="kv fl-kv">
        <dt>Usable for records</dt><dd>${fmtBytes(m.usable_bytes)} · ${fmtNum(m.maximum_records, 0)} × ${data.record_bytes} B slots</dd>
        <dt>Reserved</dt><dd>${fmtBytes(m.reserved_bytes)} (not used for sample records)</dd>
        <dt>Free</dt><dd>${fmtBytes(m.free_bytes)}</dd>
        <dt>Erase</dt><dd>${m.clear_sectors_remaining ? `${m.clear_sectors_remaining} sectors left to erase` : "idle"}${m.busy ? " · journal busy" : ""}</dd>
        <dt>Corrupt records</dt><dd>${m.corrupt_records ? badge(["critical", String(m.corrupt_records)]) : "0"}</dd>
        <dt>Clock</dt><dd>${m.rtc_trusted ? "RTC trusted — sample times are real" : badge(["warning", "RTC not trusted — samples are skipped until time is set"])}</dd>
      </dl>`;
  }

  function paintQuality() {
    const q = data.quality, rec = data.recovery, box = $("#fl-q", root);
    const parts = [];
    if (q) {
      const tot = q.stored + q.not_logged || 1;
      parts.push(`<div class="fl-row"><div class="fl-row-h"><b>Sampling outcome in this window</b><span class="dim">${fmtNum(q.stored + q.not_logged, 0)} attempts</span></div>
        ${meter([{ v: (100 * q.stored) / tot, color: "var(--good)", label: "Stored" }, { v: (100 * q.not_logged) / tot, color: "var(--warning)", label: "Not logged" }], { height: 14 })}
        <div class="legend"><span><i style="background:var(--good)"></i>Stored ${fmtNum(q.stored, 0)}</span><span><i style="background:var(--warning)"></i>Not logged ${fmtNum(q.not_logged, 0)} (${pct(q.not_logged_pct)})</span>${q.corrupt ? `<span><i style="background:var(--critical)"></i>Corrupt ${q.corrupt}</span>` : ""}</div>
        <p class="note">A sample is not logged while the node's clock is untrusted or the log window has not started (after boot, before time sync), or when the write queue is busy or the log is full. The counter includes skips since the node last booted.</p></div>`);
    }
    if (rec.archived) {
      const covPct = (100 * rec.covered) / rec.archived;
      parts.push(`<div class="fl-row"><div class="fl-row-h"><b>Archived samples vs live uplinks</b><span class="dim">${fmtNum(rec.archived, 0)} archived samples</span></div>
        ${meter([{ v: covPct, color: PALETTE[0], label: "Also received live" }, { v: 100 - covPct, color: PALETTE[3], label: "Only in flash" }], { height: 14 })}
        <div class="legend"><span><i style="background:${PALETTE[0]}"></i>Also received live ${fmtNum(rec.covered, 0)}</span><span><i style="background:${PALETTE[3]}"></i>Only in flash (gap fill) ${fmtNum(rec.recovered, 0)} · ${pct(rec.recovered_pct)}</span></div>
        <p class="note">A sample counts as covered when a live uplink from the node reached the server within ±${rec.tolerance_s} s of it. Gap-fill samples were taken while the radio link was silent: data the server only has because of the flash log.</p>
        ${rec.recovered_windows.length ? `<div class="section-title" style="margin-top:6px">Silent link periods filled from flash</div><div class="fl-wins">${rec.recovered_windows.slice(-5).reverse().map((w) => `<div><span>${range(w.start, w.end)}</span><b>${w.samples} sample${w.samples === 1 ? "" : "s"}</b></div>`).join("")}</div>` : ""}</div>`);
    }
    box.innerHTML = parts.join("") || `<div class="empty">No logging statistics yet. Press <b>Read status</b>, then <b>Download today</b> to analyse the node's log.</div>`;
    $("#fl-q-meta", root).textContent = q ? (q.rtc_trusted ? "RTC trusted" : "RTC not trusted") : "";
  }

  function paintSeries() {
    const mets = data.metrics;
    $("#fl-s-meta", root).textContent = data.series.length ? `${fmtNum(data.series.length, 0)} samples · ${fmtDateTime(data.series[0].t)} → ${fmtDateTime(data.series[data.series.length - 1].t)}` : "";
    if (!mets.length) {
      $("#fl-met", root).innerHTML = ""; $("#fl-x", root).innerHTML = ""; $("#fl-legend", root).innerHTML = ""; $("#fl-stats", root).innerHTML = "";
      $("#fl-chart", root).innerHTML = `<div class="empty">No archived samples on the server for ${nodeName(node)}. Press <b>Download today</b> — the node sends every sample in its current log window, one acknowledged row at a time.</div>`;
      return;
    }
    if (!mets.find((m) => m.key === metric)) metric = mets[0].key;
    $("#fl-met", root).innerHTML = mets.map((m) => `<button data-m="${m.key}" class="${m.key === metric ? "on" : ""}">${esc(m.label)}</button>`).join("");
    $$("#fl-met button", root).forEach((b) => b.addEventListener("click", () => { metric = b.dataset.m; paintSeries(); }));
    const m = mets.find((x) => x.key === metric);
    const all = data.series;
    // Downloads are often days apart: "sample order" removes the empty stretches, "timeline" keeps real spacing.
    if (!xMode) xMode = all.some((p, i) => i && p.t - all[i - 1].t > 6 * 3600) ? "order" : "time";
    $("#fl-x", root).innerHTML = [["order", "Sample order"], ["time", "Timeline"]].map(([k, l]) => `<button data-x="${k}" class="${k === xMode ? "on" : ""}">${l}</button>`).join("");
    $$("#fl-x button", root).forEach((b) => b.addEventListener("click", () => { xMode = b.dataset.x; paintSeries(); }));
    const order = xMode === "order";
    const gens = [...new Set(all.map((p) => p.gen))].sort((a, b) => a - b);
    const series = gens.map((g) => {
      const pts = all.map((p, i) => [order ? i : p.t, p]).filter(([, p]) => p.gen === g && p[metric] !== null).map(([x, p]) => [x, disp(p[metric], m.unit)]);
      const out = [];
      if (order) out.push(...pts);
      else {
        const gaps = pts.slice(1).map((p, i) => p[0] - pts[i][0]).sort((a, b) => a - b);
        const brk = Math.max(900, 4 * (gaps[Math.floor(gaps.length / 2)] || 0));
        pts.forEach((p, i) => { if (i && p[0] - pts[i - 1][0] > brk) out.push([pts[i - 1][0] + 1, null]); out.push(p); });
      }
      return { name: `Generation ${g}`, color: genColor(g), points: out, markers: true };
    }).filter((s) => s.points.length);
    const at = (i) => all[Math.min(all.length - 1, Math.max(0, Math.round(i)))];
    lineChart($("#fl-chart", root), {
      series, height: 250, unit: ` ${uLabel(m.unit)}`, yFormat: (v) => fmtNum(v, DIGITS[m.unit] ?? 2), empty: `No valid ${m.label.toLowerCase()} values in the archive`,
      ...(order ? { margin: { r: 40 }, xFormat: (i) => fmtShort(at(i).t), xTipFormat: (i) => `${fmtDateTime(at(i).t)} · gen ${at(i).gen} / seq ${at(i).seq}` } : { xType: "time" }),
    });
    $("#fl-legend", root).innerHTML = series.length > 1 ? legend(series.map((s) => ({ name: s.name, color: s.color, line: true }))) : "";
    $("#fl-stats", root).innerHTML = [["Valid samples", fmtNum(m.samples, 0)], ["Minimum", val(m.min, m.unit)], ["Mean", val(m.mean, m.unit)], ["Maximum", val(m.max, m.unit)]]
      .map(([k, v]) => `<div class="tile"><div class="label">${k}</div><div class="v">${esc(v)}</div></div>`).join("");
  }

  function paintGenerations() {
    const m = data.memory, rows = [...data.generations];
    if (m && !rows.find((g) => g.generation === m.generation)) rows.unshift({ generation: m.generation, records: 0, current: true });
    $("#fl-g-meta", root).textContent = rows.length ? `${rows.length} generation${rows.length === 1 ? "" : "s"}` : "";
    $("#fl-gens", root).innerHTML = rows.map((g) => {
      const onNode = g.current && m ? m.record_count : null;
      const notDl = onNode !== null ? Math.max(0, onNode - g.records) : 0;
      return `<tr><td><span class="fl-gen" style="--c:${genColor(g.generation)}"></span><b>${g.generation}</b>${g.current ? ` <span class="badge info">current</span>` : ""}</td>
        <td class="dim nowrap">${range(g.first_epoch, g.last_epoch)}</td>
        <td class="num">${onNode !== null ? fmtNum(onNode, 0) : "<span class='dim'>cleared</span>"}</td>
        <td class="num">${fmtNum(g.records, 0)}${notDl ? `<div class="fl-sub warn">${fmtNum(notDl, 0)} not downloaded</div>` : ""}</td>
        <td class="mono">${g.first_sequence ? `${g.first_sequence}–${g.last_sequence}` : "–"}</td>
        <td>${g.completeness_pct !== undefined ? `<div class="fl-comp">${meter([{ v: g.completeness_pct, color: genColor(g.generation) }], { height: 6 })}<span>${pct(g.completeness_pct, 0)}</span></div>${g.missing_in_range ? `<div class="fl-sub">${g.missing_in_range} missing in range</div>` : ""}` : "<span class='dim'>not downloaded</span>"}</td>
        <td class="num">${spacing(g.median_spacing_s)}</td></tr>`;
    }).join("") || `<tr><td colspan="8"><div class="empty">No log generations known yet</div></td></tr>`;
  }

  function paintTransfers() {
    const tr = data.transfers;
    $("#fl-t-meta", root).textContent = tr.length ? `${tr.length} latest` : "";
    $("#fl-tr", root).innerHTML = tr.map((t) => `<tr>
        <td class="mono">#${t.request}</td><td class="num">${t.generation || "–"}</td>
        <td><div class="fl-comp">${meter([{ v: t.progress_pct || 0, color: t.complete ? "var(--good)" : t.state_class === "critical" ? "var(--critical)" : PALETTE[0] }], { height: 6 })}<span class="mono">${t.received}/${t.total || "?"}</span></div></td>
        <td>${badge([t.state_class, t.state])}</td><td class="dim">${ago(t.updated)}</td></tr>`).join("")
      || `<tr><td colspan="5"><div class="empty">No history downloads yet</div></td></tr>`;
  }

  async function loadRecords() {
    if (node === null) return;
    const res = await api("/flash/records", { params: scoped({ node_id: node, offset }) });
    const rows = res.records, total = data?.archived_total ?? rows.length;
    $("#fl-rows", root).innerHTML = rows.map((r) => {
      const d = r.data;
      const flags = [d.rtc_valid && "RTC", d.flow_live_valid && "flow", d.soil_moisture_temp_valid && "HNDA", d.soil_moisture_temp_ec_valid && "Sondas"].filter(Boolean);
      return `<tr><td class="mono"><span class="fl-gen" style="--c:${genColor(r.generation)}"></span>${r.generation} / ${r.sequence}</td>
        <td class="dim">${fmtDateTime(r.epoch)}</td>
        <td class="num">${d.flow_live_valid ? val(d.flow_rate, "flow") : "–"}</td>
        <td class="num">${d.flow_live_valid ? val(d.velocity, "velocity") : "–"}</td>
        <td class="num">${d.battery_voltage ? val(d.battery_voltage, "volt") : "–"}</td>
        <td>${d.soil_moisture_temp_valid ? `${val(d.soil_moisture, "pct")} · ${val(d.soil_temperature, "temp")}` : "–"}</td>
        <td>${d.soil_moisture_temp_ec_valid ? `${val(d.ec_moisture, "pct")} · ${fmtNum(d.electrical_conductivity, 0)} µS/cm` : "–"}</td>
        <td class="num">${+d.forward_total_liters ? `${fmtNum(+d.forward_total_liters, 0)} L` : "–"}</td>
        <td>${flags.map((f) => `<span class="chip">${f}</span>`).join(" ") || "–"}</td></tr>`;
    }).join("") || `<tr><td colspan="9"><div class="empty">No archived records on the server</div></td></tr>`;
    $("#fl-r-meta", root).textContent = total ? `${fmtNum(total, 0)} stored on server` : "";
    $("#fl-page", root).textContent = rows.length ? `${offset + 1}–${offset + rows.length} of ${fmtNum(total, 0)}` : "";
    $("#fl-prev", root).disabled = offset === 0;
    $("#fl-next", root).disabled = offset + rows.length >= total;
  }
  $("#fl-prev", root).addEventListener("click", () => { offset = Math.max(0, offset - PAGE); loadRecords(); });
  $("#fl-next", root).addEventListener("click", () => { offset += PAGE; loadRecords(); });

  async function load() {
    if (node === null) { $("#fl-kpis", root).innerHTML = ""; $("#fl-cap", root).innerHTML = `<div class="empty">No nodes in ${esc(state.region)} for ${esc(state.company)}</div>`; return; }
    $("#fl-csv", root).href = `/api/v2/flash/records?${new URLSearchParams({ ...scoped(), node_id: node, format: "csv" })}`;
    data = await api("/flash/analysis", { params: scoped({ node_id: node }) });
    paintKpis(); paintCapacity(); paintQuality(); paintSeries(); paintGenerations(); paintTransfers();
    loadRecords();
  }

  // Live: every persisted flash reply (status, history row, end-of-transfer) refreshes the view.
  const off = onEvent((m) => {
    if (m.type !== "flash" || m.company !== state.company) return;
    const ev = m.data || {};
    if (ev.Region && ev.Region !== state.region) return;
    if (!nodes.includes(+ev["Node ID"])) { loadNodes(); }
    if (+ev["Node ID"] !== node) return;
    clearTimeout(timer); timer = setTimeout(load, 700);
  });
  const tick = setInterval(() => { if (data?.memory) $("#fl-age", root).innerHTML = `<span class="dot" style="background:var(--${Date.now() / 1000 - data.memory.received_at < 900 ? "good" : "warning"})"></span> Status received ${ago(data.memory.received_at)}`; }, 15000);

  await loadNodes();
  await load();
  return () => { off(); clearTimeout(timer); clearInterval(tick); };
}
