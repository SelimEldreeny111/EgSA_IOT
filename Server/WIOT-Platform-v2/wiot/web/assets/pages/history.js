// Message history browser with filters, paging and CSV export.
import { api, state, ICONS, $ } from "../api.js";
import { esc, fmtNum, fmtDateTime } from "../charts.js";

export async function render(root) {
  const all = state.user.permissions.global_read;
  const f = { type: "", node_id: "", start: "", end: "", page: 1, page_size: 50, scope: state.company };
  root.innerHTML = `
    <section class="panel">
      <header><h2><span class="ico">${ICONS.history}</span>Message history</h2><span class="meta" id="h-meta"></span></header>
      <form class="body row" id="h-form" style="align-items:flex-end">
        ${all ? `<div class="field" style="margin:0"><label>Scope</label><select class="input" id="h-scope"><option value="${esc(state.company)}">${esc(state.company)}</option><option value="">All companies</option></select></div>` : ""}
        <div class="field" style="margin:0"><label>Type</label><select class="input" id="h-type"><option value="">All</option><option>Status</option><option>Telemetry</option><option>Command</option></select></div>
        <div class="field" style="margin:0;width:110px"><label>Node</label><input class="input" id="h-node" type="number" min="1" max="65535" placeholder="any"></div>
        <div class="field" style="margin:0"><label>From</label><input class="input" id="h-start" type="datetime-local"></div>
        <div class="field" style="margin:0"><label>To</label><input class="input" id="h-end" type="datetime-local"></div>
        <button class="btn primary" type="submit">Apply</button>
        <div class="grow"></div>
        <a class="btn" id="h-csv" href="#">Export CSV</a>
      </form>
      <div class="table-wrap" style="max-height:640px"><table class="data"><thead><tr>
        <th>Received</th><th>Type</th>${all ? "<th>Company</th>" : ""}<th>Node</th><th class="num">Flow m³/h</th><th class="num">Velocity</th><th class="num">Today m³</th>
        <th class="num">Battery V</th><th class="num">Soil %</th><th class="num">EC µS</th><th>Power</th><th>Time source</th><th>Details</th></tr></thead><tbody id="h-rows"></tbody></table></div>
      <div class="pager"><span class="dim" id="h-count"></span><div class="row"><button class="btn sm" id="h-prev">Prev</button><span class="mono" id="h-page"></span><button class="btn sm" id="h-next">Next</button></div></div>
    </section>`;
  const toEpoch = (v) => v ? Math.floor(new Date(v).getTime() / 1000) : "";
  const params = () => ({ company: f.scope, region: state.region, type: f.type, node_id: f.node_id, start: f.start, end: f.end, page: f.page, page_size: f.page_size });
  function csvHref() {
    const q = new URLSearchParams(Object.entries({ company: f.scope, region: state.region, start: f.start, end: f.end }).filter(([, v]) => v !== "" && v !== null));
    $("#h-csv", root).href = `/api/v2/export.csv?${q}`;
  }
  async function load() {
    const d = await api("/messages", { params: params() });
    $("#h-meta", root).textContent = `${d.total.toLocaleString("en-US")} messages`;
    $("#h-count", root).textContent = `${((d.page - 1) * d.page_size + 1).toLocaleString()}–${Math.min(d.total, d.page * d.page_size).toLocaleString()} of ${d.total.toLocaleString()}`;
    $("#h-page", root).textContent = `${d.page} / ${d.total_pages}`;
    $("#h-prev", root).disabled = d.page <= 1; $("#h-next", root).disabled = d.page >= d.total_pages;
    $("#h-rows", root).innerHTML = d.rows.map((r) => {
      const isCmd = r.type === "Command";
      return `<tr><td class="mono dim">${fmtDateTime(r.timestamp)}</td><td>${esc(r.type)}</td>${all ? `<td>${esc(r.company)}</td>` : ""}<td class="mono">${r.node_id}</td>
        <td class="num">${isCmd ? "–" : fmtNum(r.flow)}</td><td class="num">${isCmd ? "–" : fmtNum(r.velocity)}</td><td class="num">${isCmd ? "–" : fmtNum(r.flow_day)}</td>
        <td class="num">${r.battery_voltage ? r.battery_voltage.toFixed(2) : "–"}</td><td class="num">${r.soil_moisture_temp_valid ? fmtNum(r.soil_moisture) : r.soil_moisture_temp_ec_valid ? fmtNum(r.ec_moisture) : "–"}</td>
        <td class="num">${r.soil_moisture_temp_ec_valid ? fmtNum(r.electrical_conductivity, 0) : "–"}</td><td class="dim">${isCmd ? "–" : esc(r.power_mode_name)}</td><td class="dim">${esc(r.time_source)}</td>
        <td class="dim" style="max-width:340px;overflow:hidden;text-overflow:ellipsis" title="${esc(r.details)}">${esc(r.details)}</td></tr>`;
    }).join("") || `<tr><td colspan="13"><div class="empty">No messages match these filters</div></td></tr>`;
    csvHref();
  }
  $("#h-form", root).addEventListener("submit", (e) => {
    e.preventDefault();
    Object.assign(f, { type: $("#h-type", root).value, node_id: $("#h-node", root).value, start: toEpoch($("#h-start", root).value), end: toEpoch($("#h-end", root).value), page: 1 });
    if (all) f.scope = $("#h-scope", root).value;
    load();
  });
  $("#h-prev", root).addEventListener("click", () => { f.page--; load(); });
  $("#h-next", root).addEventListener("click", () => { f.page++; load(); });
  await load();
}
