// Regional dashboard: water use and crop health aggregated per area for ministries and water authorities.
// No farm-level data: areas with fewer farms than the server's minimum are suppressed.
import { api, ICONS, $ } from "../api.js";
import { esc, fmtNum } from "../charts.js";

const pct = (v) => (v === null || v === undefined ? "–" : `${fmtNum(v * 100, 0)} %`);

export async function render(root) {
  const d = await api("/regional");
  root.innerHTML = `<div class="ops">
    <div class="tiles">
      <div class="tile"><div class="label">Areas</div><div class="v">${d.totals.areas}</div><div class="s">${esc(d.month)}</div></div>
      <div class="tile"><div class="label">Farms</div><div class="v">${d.totals.farms}</div><div class="s">with mapped fields</div></div>
      <div class="tile"><div class="label">Irrigated area</div><div class="v">${fmtNum(d.totals.area_ha, 0)} <small>ha</small></div><div class="s">areas shown</div></div>
      <div class="tile"><div class="label">Water this month</div><div class="v">${fmtNum(d.totals.water_month_m3 / 1000, 1)} <small>thousand m³</small></div><div class="s">metered at the fields</div></div>
    </div>
    <section class="panel"><header><h2><span class="ico">${ICONS.world}</span>Water use and crop health by area</h2><span class="meta">at least ${d.min_farms} farms per area</span></header>
      <div class="table-wrap"><table class="data"><thead><tr><th>Area</th><th class="num">Farms</th><th class="num">Fields</th><th class="num">Area ha</th><th class="num">Water m³</th>
        <th class="num">Depth mm</th><th class="num">Soil moisture</th><th class="num">Under-irrigated</th><th class="num">Over-irrigated</th><th class="num">NDVI</th><th class="num">Open alerts</th></tr></thead>
        <tbody id="rg-rows"></tbody></table></div>
      <div class="body"><p class="note">Totals of every farm in an area, this calendar month. Areas with fewer than ${d.min_farms} farms are not detailed so that no single farm can be identified. Irrigation shares use the 7-day index (applied water against crop need).</p></div></section>
  </div>`;
  $("#rg-rows", root).innerHTML = d.areas.map((a) => a.suppressed
    ? `<tr><td data-i18n-skip><b>${esc(a.area)}</b></td><td class="num">${a.farms}</td><td colspan="9" class="dim">Fewer than ${d.min_farms} farms — not shown</td></tr>`
    : `<tr><td data-i18n-skip><b>${esc(a.area)}</b></td><td class="num">${a.farms}</td><td class="num">${a.fields}</td><td class="num">${fmtNum(a.area_ha, 0)}</td>
      <td class="num">${fmtNum(a.water_month_m3, 0)}</td><td class="num">${a.water_month_mm === null ? "–" : fmtNum(a.water_month_mm, 0)}</td>
      <td class="num">${a.moisture_mean === null ? "–" : `${fmtNum(a.moisture_mean, 1)} %`}</td><td class="num">${pct(a.under_share)}</td><td class="num">${pct(a.over_share)}</td>
      <td class="num">${a.ndvi_mean === null ? "–" : fmtNum(a.ndvi_mean, 2)}</td><td class="num">${a.open_alerts}</td></tr>`).join("")
    || `<tr><td colspan="11"><div class="empty">No farms with mapped fields yet.</div></td></tr>`;
  return undefined;
}
