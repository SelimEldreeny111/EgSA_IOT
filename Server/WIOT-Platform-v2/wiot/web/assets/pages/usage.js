// Usage: what each company used per month and per day — uplinks, air-time bytes, commands, API calls,
// exports, active nodes and storage. The basis for service plans and billing; CSV for accounting.
import { api, state, ICONS, $ } from "../api.js";
import { esc, fmtNum, barChart } from "../charts.js";
import { bytes } from "./system.js";

export async function render(root) {
  const sup = state.user.permissions.supervisor;
  let scope = sup ? "" : state.company;
  root.innerHTML = `<div class="ops">
    <section class="panel"><header><h2><span class="ico">${ICONS.analytics}</span>Usage by month</h2>
      <div class="row" style="margin-inline-start:auto;gap:8px">
        ${sup ? `<div class="seg" id="us-scope"><button data-s="" class="on">All companies</button><button data-s="${esc(state.company)}" data-i18n-skip>${esc(state.profiles[state.company]?.display_name || state.company)}</button></div>` : ""}
        <a class="btn sm" id="us-csv">${ICONS.download}<span>Daily CSV</span></a></div></header>
      <div class="table-wrap"><table class="data"><thead><tr><th>Month</th><th>Company</th><th class="num">Uplinks</th><th class="num">Air-time data</th>
        <th class="num">Commands</th><th class="num">API calls</th><th class="num">Exports</th><th class="num">Active nodes (max)</th><th class="num">Storage</th></tr></thead>
        <tbody id="us-rows"></tbody></table></div></section>
    <section class="panel"><header><h2><span class="ico">${ICONS.history}</span>Uplinks per day · last 90 days</h2></header><div class="body"><div id="us-chart" style="height:240px"></div></div>
      <div class="body"><p class="note">Counted as messages arrive and saved every 10 minutes. Air-time data is the encrypted frame size on the radio, cellular or satellite link. Days are UTC.</p></div></section>
  </div>`;

  async function load() {
    const params = scope ? { company: scope } : {};
    const d = await api("/usage", { params: { ...params, days: 90 } });
    $("#us-csv", root).href = `/api/v2/usage?${new URLSearchParams({ ...params, days: 400, format: "csv" })}`;
    $("#us-rows", root).innerHTML = [...d.months].reverse().map((m) => `<tr><td class="mono">${esc(m.month)}</td><td data-i18n-skip>${esc(state.profiles[m.company]?.display_name || m.company)}</td>
      <td class="num">${fmtNum(m.messages, 0)}</td><td class="num">${bytes(m.bytes)}</td><td class="num">${fmtNum(m.commands, 0)}</td>
      <td class="num">${fmtNum(m.api_calls, 0)}</td><td class="num">${fmtNum(m.exports, 0)}</td><td class="num">${m.nodes_active_max}</td><td class="num">${bytes(m.storage_bytes)}</td></tr>`).join("")
      || `<tr><td colspan="9"><div class="empty">No usage recorded yet.</div></td></tr>`;
    const perDay = {};
    for (const r of d.days) perDay[r.day] = (perDay[r.day] || 0) + r.messages;
    const days = Object.keys(perDay).sort();
    if (!days.some((x) => perDay[x] > 0)) { $("#us-chart", root).innerHTML = `<div class="empty">No uplinks counted in the last 90 days.</div>`; return; }
    barChart($("#us-chart", root), { categories: days, series: [{ name: "Uplinks", values: days.map((x) => perDay[x]) }], height: 240,
      catLabel: (x) => x.slice(5), empty: "No usage recorded yet" });
  }
  $("#us-scope", root)?.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
    scope = b.dataset.s; $("#us-scope", root).querySelectorAll("button").forEach((x) => x.classList.toggle("on", x === b)); load();
  }));
  await load();
  return undefined;
}
