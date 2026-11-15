// Node health: one score per node from the last 7 days of uplinks and 30 days of commands —
// battery trend, resets, reporting regularity, store-and-forward share, clock, command success
// and configuration drift. Nothing here needs a firmware change.
import { api, state, ago, badge, ICONS, $ } from "../api.js";
import { esc, fmtNum } from "../charts.js";

const nodeTag = (id) => `NODE-${String(id).padStart(3, "0")}`;
const GRADE = { good: ["good", "Good"], fair: ["warning", "Fair"], poor: ["critical", "Poor"] };
const pct = (v) => (v === null || v === undefined ? "–" : `${fmtNum(v * 100, 0)} %`);

function scoreCell(n) {
  const cls = n.grade === "good" ? "good" : n.grade === "fair" ? "warn" : "bad";
  return `<div class="nh-score ${cls}"><b>${n.score}</b><span><i style="width:${n.score}%"></i></span></div>`;
}
function batteryCell(n) {
  if (n.battery_v === null || n.battery_v === undefined) return "–";
  const slope = n.battery_slope_v_per_day;
  const trend = slope === null || slope === undefined ? "trend: not enough data"
    : `${slope >= 0 ? "+" : ""}${fmtNum(slope * 1000, 1)} mV/day`;
  const left = n.battery_days_left !== null && n.battery_days_left !== undefined
    ? `<div class="nh-sub ${n.battery_days_left < 30 ? "warn" : ""}">3.3 V in ${fmtNum(n.battery_days_left, 0)} days</div>` : "";
  return `<b class="mono">${fmtNum(n.battery_v, 2)} V</b><div class="nh-sub">${esc(trend)}</div>${left}`;
}
function configCell(c) {
  if (!c) return "–";
  const one = (label, v) => v.desired === null ? "" : v.reported == null
    ? `<div>${label} set ${v.desired} s <small class="dim">(not reported yet)</small></div>`
    : `<div class="${v.drift ? "nh-drift" : ""}">${label} ${v.reported} s${v.drift ? ` <small>(set ${v.desired} s)</small>` : ""}</div>`;
  return one("Sampling", c.sampling_s) + one("Report", c.report_s) || `<span class="dim">not set from WIOT</span>`;
}

export async function render(root) {
  root.innerHTML = `<div class="ops">
    <div class="tiles" id="nh-kpis"></div>
    <section class="panel">
      <header><h2><span class="ico">${ICONS.node}</span>Node health</h2><span class="meta" id="nh-meta"></span></header>
      <div class="table-wrap"><table class="data nh-table"><thead><tr>
        <th>Node</th><th>Score</th><th>Battery</th><th class="num">Resets · 7 d</th><th class="num">Uplinks · 24 h</th>
        <th class="num">From store</th><th class="num">Clock trusted</th><th class="num">Commands · 30 d</th><th>Intervals</th><th>Findings</th>
      </tr></thead><tbody id="nh-rows"></tbody></table></div>
      <div class="body"><p class="note">The score starts at 100 and loses points for a battery that will reach 3.3 V within 30 days, watchdog or power resets, missed uplinks, a node clock that is not trusted, commands that were not acknowledged and a reported interval that differs from the one set. Good is 80 or more, fair 60 to 79.</p>
        <p class="note">Uplinks · 24 h compares what arrived with what the node's interval predicts. From store is the share of samples the node delivered late from its memory (store-and-forward).</p></div>
    </section></div>`;

  let timer = null;
  async function load() {
    const d = await api("/fleet/health", { params: { company: state.company, region: state.region } });
    const g = d.grades;
    $("#nh-kpis", root).innerHTML = [
      ["Nodes", d.nodes.length, "with uplinks or registered", ""],
      ["Good", g.good, "score 80 or more", ""],
      ["Fair", g.fair, "score 60 to 79", g.fair ? "warn" : ""],
      ["Poor", g.poor, "score below 60", g.poor ? "crit" : ""],
    ].map(([k, v, s, cls]) => `<div class="tile ${cls}"><div class="label">${k}</div><div class="v">${fmtNum(v, 0)}</div><div class="s">${esc(s)}</div></div>`).join("");
    $("#nh-meta", root).textContent = `${d.nodes.length} nodes`;
    $("#nh-rows", root).innerHTML = d.nodes.map((n) => `<tr>
        <td><b class="mono" data-i18n-skip>${nodeTag(n.node_id)}</b><div class="nh-sub" data-i18n-skip>${esc(n.name)}</div>${n.last_seen_age_s !== undefined ? `<div class="nh-sub">${esc(ago(Math.floor(Date.now() / 1000) - n.last_seen_age_s))}</div>` : ""}</td>
        <td>${scoreCell(n)}${badge(GRADE[n.grade])}</td>
        <td>${batteryCell(n)}</td>
        <td class="num">${n.wdt_resets_7d === undefined ? "–" : `${n.wdt_resets_7d} WDT · ${n.power_resets_7d} power`}</td>
        <td class="num">${pct(n.regularity_24h)}</td>
        <td class="num">${pct(n.store_forward_share)}</td>
        <td class="num">${pct(n.clock_trusted_share)}</td>
        <td class="num">${n.command_success === null || n.command_success === undefined ? "–" : `${pct(n.command_success)} <div class="nh-sub">${n.commands_30d} final</div>`}</td>
        <td>${configCell(n.config)}</td>
        <td><ul class="nh-find">${n.findings.map((f) => `<li>${esc(f)}</li>`).join("")}</ul></td></tr>`).join("")
      || `<tr><td colspan="10"><div class="empty">No nodes in this region yet.</div></td></tr>`;
  }
  await load();
  timer = setInterval(load, 60000);
  return () => clearInterval(timer);
}
