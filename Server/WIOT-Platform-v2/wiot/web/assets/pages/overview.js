// Fleet overview: node tracking, per-node telemetry, live uplinks and events.
import { api, state, onEvent, scoped, ago, badge, LINK_BADGE, batteryPct, ICONS, $, $$, h } from "../api.js";
import { esc, lineChart, barChart, gauge, fmtNum, fmtTime, fmtDateTime, PALETTE, legend, riskColor, T } from "../charts.js";
import { fmtU, fmtUs, conv, unit } from "../units.js";

// Series colours are palette slots (resolved at draw time so Night/Day both apply).
const METRICS = {
  flow: { label: "Flow rate", unitKind: "flow", series: [["flow", "Flow", 0, "flow"]] },
  battery: { label: "Battery", unit: " V", series: [["battery_voltage", "Battery", 2]] },
  soil: { label: "Soil (HNDA)", unit: "", series: [["soil_moisture", "Moisture %", 0], ["soil_temperature", "Temperature °C", 1, "temp"]] },
  ec: { label: "Sondas EC", unit: " µS/cm", series: [["electrical_conductivity", "Conductivity", 6]] },
};
const RANGES = { "6H": 6, "24H": 24, "7D": 168, "30D": 720 };
const SENSOR_BITS = [[1, "TUF"], [2, "HNDA"], [4, "Sondas"], [8, "Supmea"]];

export async function render(root) {
  let fleet = [], selected = null, metric = "flow", range = "24H", filter = "ALL", refreshTimer = null;
  root.innerHTML = `
    <div class="tiles" id="kpis" style="margin-bottom:16px"></div>
    <div class="grid g-main">
      <section class="panel">
        <header><h2><span class="ico">${ICONS.node}</span>Fleet Tracking &amp; Status</h2><span class="meta" id="fleet-meta"></span></header>
        <div class="body" style="padding:10px 14px"><div class="seg" id="flt">${["ALL", "ONLINE", "LATE", "OFFLINE"].map((f) => `<button data-f="${f}" class="${f === "ALL" ? "on" : ""}">${f}</button>`).join("")}</div></div>
        <div class="node-list" id="nodes"></div>
      </section>
      <section class="panel" id="detail"><div class="empty">Select a node</div></section>
    </div>
    <div class="grid g-wide" style="margin-top:16px">
      <section class="panel"><header><h2><span class="ico">${ICONS.analytics}</span>Fleet uplinks · last 48 h</h2><span class="meta" id="up-meta"></span></header><div class="body"><div id="uplinks"></div></div></section>
      <section class="panel"><header><h2><span class="ico">${ICONS.system}</span>Live event stream</h2><span class="meta"><span class="dot pulse" style="background:var(--good)"></span> LIVE</span></header><div class="console" id="console"></div></section>
    </div>`;

  $$("#flt button", root).forEach((b) => b.addEventListener("click", () => {
    filter = b.dataset.f; $$("#flt button", root).forEach((x) => x.classList.toggle("on", x === b)); paintList();
  }));

  async function loadFleet() {
    const data = await api("/fleet", { params: scoped() });
    fleet = data.nodes;
    $("#fleet-meta", root).textContent = `${data.summary.nodes} nodes`;
    if (!selected || !fleet.find((n) => n.node_id === selected)) selected = fleet[0]?.node_id ?? null;
    paintList();
    return data;
  }
  function paintList() {
    const list = $("#nodes", root);
    const rows = fleet.filter((n) => filter === "ALL" || n.link_state === filter.toLowerCase());
    if (!rows.length) { list.innerHTML = `<div class="empty">No nodes ${filter === "ALL" ? "have reported in this region" : "in this state"}</div>`; return; }
    list.innerHTML = rows.map((n) => {
      const bars = n.link_state === "online" ? 4 : n.link_state === "late" ? 2 : 0;
      return `<div class="node-item ${n.node_id === selected ? "sel" : ""}" data-id="${n.node_id}" role="button" tabindex="0">
        <div class="sig" aria-hidden="true">${[5, 8, 11, 14].map((hh, i) => `<i style="height:${hh}px" class="${i < bars ? "on" : ""}"></i>`).join("")}</div>
        <div><div class="id">NODE-${String(n.node_id).padStart(3, "0")}${n.node_type ? ` <span class="ntype ${n.node_type}">${n.node_type === "control" ? "Control" : "Monitoring"}</span>` : ""}</div>${n.name ? `<div class="sub" style="color:var(--text-2)">${esc(n.name)}</div>` : ""}
          <div class="sub">${esc(n.power_mode_name)} · ${esc(n.flow_meter_name || "no meter")} · ${ago(n.timestamp)}</div></div>
        <div class="right">${badge(LINK_BADGE[n.link_state])}<div class="dim" style="margin-top:4px">${n.battery_voltage ? n.battery_voltage.toFixed(2) + " V" : "–"}</div></div>
      </div>`;
    }).join("");
    $$(".node-item", list).forEach((el) => {
      const pick = () => { selected = +el.dataset.id; paintList(); loadDetail(); };
      el.addEventListener("click", pick);
      el.addEventListener("keydown", (e) => { if (e.key === "Enter") pick(); });
    });
  }

  async function loadKpis(data) {
    let live = null;
    try { live = await api("/analytics/live", { params: { company: state.company } }); } catch { /* optional */ }
    const s = data.summary;
    const batt = fleet.map((n) => n.battery_voltage).filter((v) => v > 0);
    const low = batt.filter((v) => v < 3.45).length;
    const ack = live?.commands_7d?.ack_rate;
    $("#kpis", root).innerHTML = [
      ["Nodes online", `${s.online}<small>/ ${s.nodes}</small>`, `${s.late} late · ${s.offline} offline`, true],
      ["Uplinks · 24 h", fmtNum(s.uplinks_24h, 0), `${live?.activity?.telemetry ?? 0} telemetry frames`],
      ["Command delivery · 7 d", ack === null || ack === undefined ? "–" : `${(ack * 100).toFixed(1)}<small>%</small>`, `${live?.commands_7d?.total ?? 0} commands issued`],
      ["Mean battery", batt.length ? `${(batt.reduce((a, b) => a + b, 0) / batt.length).toFixed(2)}<small>V</small>` : "–", low ? `${low} node(s) below 3.45 V` : "all nodes above 3.45 V"],
      ["Watchdog resets", fmtNum(fleet.reduce((a, n) => a + (n.wdt_reset_count || 0), 0), 0), "cumulative, last report per node"],
    ].map(([k, v, sub, hl]) => `<div class="tile ${hl ? "hl" : ""}"><div class="label">${k}</div><div class="v">${v}</div><div class="s">${esc(sub)}</div></div>`).join("");
    const hourly = live?.hourly_uplinks || [];
    $("#up-meta", root).textContent = `${hourly.reduce((a, r) => a + r[1], 0).toLocaleString("en-US")} uplinks`;
    barChart($("#uplinks", root), {
      height: 190, categories: hourly.map((r) => r[0]), series: [{ name: "Uplinks", values: hourly.map((r) => r[1]), color: PALETTE[0] }],
      catLabel: (t) => fmtTime(t), empty: "No uplinks in the last 48 hours — historical data is on the Data science page",
    });
  }

  async function loadDetail() {
    const box = $("#detail", root);
    if (selected === null) { box.innerHTML = `<div class="empty">No nodes have reported in ${esc(state.region)} for ${esc(state.company)}</div>`; return; }
    const n = fleet.find((x) => x.node_id === selected);
    const sensors = SENSOR_BITS.filter(([b]) => (n.sensor_mask || 0) & b).map(([, s]) => s).join(" · ") || "none";
    const valve = { 0: ["neutral", "Closed"], 1: ["good", "Open"], 2: ["warning", "Unknown"], 3: ["critical", "Fault"] }[n.node_status] || ["neutral", "–"];
    box.innerHTML = `
      <header><h2><span class="ico">${ICONS.drop}</span>Node Telemetry · NODE-${String(n.node_id).padStart(3, "0")}</h2>
        <span class="meta">${esc(n.power_mode_name)} · ${esc(n.power_state_name)} · ${ago(n.timestamp)}</span></header>
      <div class="body">
        <div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(140px,1fr));align-items:center;gap:12px">
          <div id="g-batt"></div><div id="g-risk"></div>
          <div class="tile"><div class="label">Flow</div><div class="v">${fmtUs(n.flow, "flow", 2)}</div><div class="s">${fmtNum(n.velocity)} m/s · ${esc(n.flow_meter_name)}</div></div>
          <div class="tile"><div class="label">Today</div><div class="v">${fmtUs(n.flow_day, "volume", 2)}</div><div class="s">month ${fmtU(n.flow_month, "volume", 2)}</div></div>
          <div class="tile"><div class="label">Valve</div><div class="v" style="font-size:16px;margin-top:10px">${n.node_type === "monitoring" ? badge(["neutral", "No valve"]) : badge(valve)}</div><div class="s">${n.node_type === "monitoring" ? "monitoring node · sensors only" : "commanded state"}</div></div>
          <div class="tile"><div class="label">Resets</div><div class="v">${n.wdt_reset_count ?? 0}<small>wdt</small> ${n.power_reset_count ?? 0}<small>pwr</small></div><div class="s">watchdog · power-on</div></div>
        </div>
        <div class="row" style="margin:16px 0 8px">
          <div class="seg" id="met">${Object.entries(METRICS).map(([k, m]) => `<button data-m="${k}" class="${k === metric ? "on" : ""}">${m.label}</button>`).join("")}</div>
          <div class="grow"></div>
          <div class="seg" id="rng">${Object.keys(RANGES).map((r) => `<button data-r="${r}" class="${r === range ? "on" : ""}">${r}</button>`).join("")}</div>
        </div>
        <div id="series"></div><div id="series-legend"></div>
        <p class="note" id="series-note"></p>
        <div class="grid g-2" style="margin-top:12px">
          <dl class="kv"><dt>Sensors</dt><dd>${esc(sensors)}</dd><dt>Soil (HNDA)</dt><dd>${n.soil_moisture_temp_valid ? `${fmtNum(n.soil_moisture)} % · ${fmtU(n.soil_temperature, "temp")}` : "–"}</dd>
            <dt>Sondas EC</dt><dd>${n.soil_moisture_temp_ec_valid ? `${fmtNum(n.electrical_conductivity, 0)} µS/cm · ${fmtNum(n.ec_moisture)} %` : "–"}</dd></dl>
          <dl class="kv"><dt>Time source</dt><dd>${esc(n.time_source)}</dd><dt>Report interval</dt><dd>${n.median_interval_s ? `${n.median_interval_s} s (median)` : "–"}</dd>
            <dt>Uplinks 24 h</dt><dd>${n.uplinks_24h ?? 0} · total ${n.uplinks_total ?? "–"}</dd></dl>
        </div>
      </div>`;
    gauge($("#g-batt", box), { value: batteryPct(n.battery_voltage), text: n.battery_voltage ? `${n.battery_voltage.toFixed(2)}V` : "–", label: "Battery", color: PALETTE[2] });
    $$("#met button", box).forEach((b) => b.addEventListener("click", () => { metric = b.dataset.m; loadDetail(); }));
    $$("#rng button", box).forEach((b) => b.addEventListener("click", () => { range = b.dataset.r; loadDetail(); }));
    loadRisk(n);
    loadSeries(n);
  }

  async function loadRisk(n) {
    const el = $("#g-risk", root); if (!el) return;
    try {
      const r = await api("/commands/risk", { method: "POST", body: { ...scoped(), node_id: n.node_id, cmd_type: "GOSTM" } });
      gauge(el, { value: r.probability, label: "P(command delivered now)", color: riskColor(r.tier) });
    } catch { gauge(el, { value: null, text: "n/a", label: "Delivery model", color: T.muted }); }
  }

  async function loadSeries(n) {
    const hours = RANGES[range];
    const offline = Date.now() / 1000 - n.timestamp > hours * 3600 * 0.5;
    const end = offline ? n.timestamp + 60 : undefined;
    const m = METRICS[metric];
    const results = await Promise.all(m.series.map(([key]) => api(`/nodes/${n.node_id}/series`, { params: scoped({ metric: key, hours, points: 240, end }) }).catch(() => null)));
    const cv = (i, v) => (m.series[i][3] ? conv(v, m.series[i][3]) : v);  // display units (company profile)
    const series = results.map((r, i) => r && ({ name: m.series[i][1].replace("°C", unit("temp")), color: PALETTE[m.series[i][2]], points: r.points.map((p) => [p[0], cv(i, p[1])]), band: r.points.map((p) => [p[0], cv(i, p[2]), cv(i, p[3])]) })).filter(Boolean);
    const target = $("#series", root); if (!target) return;
    lineChart(target, { series, xType: "time", height: 230, area: series.length === 1, unit: m.unitKind ? ` ${unit(m.unitKind)}` : m.unit, empty: `No valid ${m.label.toLowerCase()} samples in this window` });
    $("#series-legend", root).innerHTML = series.length > 1 ? legend(series.map((s) => ({ name: s.name, color: s.color, line: true }))) : "";
    $("#series-note", root).textContent = offline
      ? `Node last reported ${fmtDateTime(n.timestamp)}; window anchored on its last uplink. Shaded band = min–max per bucket.`
      : "Shaded band = min–max per bucket; line = bucket mean. Only samples whose validity flag is set are plotted.";
  }

  const consoleEl = $("#console", root);
  function logLine(entry) {
    const div = h(`<div class="${esc(entry.level || "")}"><span class="t">${esc(entry.time || new Date().toLocaleTimeString([], { hour12: false }))}</span> ${esc(entry.message)}</div>`);
    consoleEl.prepend(div);
    while (consoleEl.children.length > 200) consoleEl.lastChild.remove();
  }
  try { (await api("/system/logs", { params: { limit: 60 } })).lines.forEach(logLine); } catch { /* optional */ }

  const off = onEvent((m) => {
    if (m.type === "log") logLine(m.data);
    if (m.type === "telemetry" && m.company === state.company && m.data.region === state.region) {
      const d = m.data;
      logLine({ time: new Date().toLocaleTimeString([], { hour12: false }), message: `[${d.type.toUpperCase()}] node ${d.node_id} · flow ${fmtU(d.flow, "flow", 2)} · ${d.battery_voltage ? d.battery_voltage.toFixed(2) + " V" : ""} · ${d.power_mode_name}` });
      clearTimeout(refreshTimer);
      refreshTimer = setTimeout(async () => { const data = await loadFleet(); loadKpis(data); if (d.node_id === selected) loadDetail(); }, 1200);
    }
  });

  const data = await loadFleet();
  loadKpis(data);
  loadDetail();
  return () => { off(); clearTimeout(refreshTimer); };
}
