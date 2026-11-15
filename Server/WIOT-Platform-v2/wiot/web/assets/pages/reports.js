// Reports: monthly operations report per company — preview, Excel / PDF download, archive and e-mail.
import { api, state, ago, toast, ICONS, $, $$ } from "../api.js";
import { esc, fmtNum, barChart } from "../charts.js";

function months(n = 13) {
  const out = [], d = new Date();
  d.setDate(1);
  for (let i = 0; i < n; i++) {
    out.push(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`);
    d.setMonth(d.getMonth() - 1);
  }
  return out;
}
const monthName = (m) => new Date(`${m}-01T12:00:00`).toLocaleDateString(undefined, { month: "long", year: "numeric" });
const tag = (id) => `NODE-${String(id).padStart(3, "0")}`;
const v = (x, d = 2) => (x === null || x === undefined ? "–" : fmtNum(x, d));

export async function render(root) {
  const canWrite = state.user.permissions.command;
  const idx = await api("/reports", { params: { company: state.company } });
  let month = idx.default_month;
  root.innerHTML = `<div class="ops">
    <section class="panel"><header><h2><span class="ico">${ICONS.analytics}</span>Monthly report</h2>
      <div class="row" style="margin-inline-start:auto;gap:8px">
        <label class="tb-select"><span>Month</span><select id="rp-month" data-i18n-skip>${months().map((m) => `<option value="${m}" ${m === month ? "selected" : ""}>${esc(monthName(m))}</option>`).join("")}</select></label>
        <a class="btn sm" id="rp-xlsx">${ICONS.download}<span>Excel</span></a><a class="btn sm" id="rp-pdf">${ICONS.download}<span>PDF</span></a>
        ${canWrite ? `<button class="btn sm primary" id="rp-send">Send to report channels</button>` : ""}</div></header>
      <div class="body"><div class="tiles" id="rp-kpis"></div></div></section>
    <div class="grid g-wide">
      <section class="panel"><header><h2><span class="ico">${ICONS.node}</span>Nodes</h2><span class="meta" id="rp-meta"></span></header>
        <div class="table-wrap"><table class="data"><thead><tr><th>Node</th><th class="num">Uplinks</th><th class="num">Days</th><th class="num">Battery min</th>
          <th class="num">Water m³</th><th class="num">Soil moisture</th><th class="num">EC µS/cm</th><th class="num">Alerts</th></tr></thead><tbody id="rp-rows"></tbody></table></div></section>
      <section class="panel"><header><h2><span class="ico">${ICONS.drop}</span>Water per day</h2></header><div class="body"><div id="rp-water" style="height:230px"></div></div></section>
    </div>
    <section class="panel"><header><h2><span class="ico">${ICONS.history}</span>Archive</h2></header>
      <div class="body" id="rp-archive"></div>
      <div class="body"><p class="note">${idx.auto ? "On the 1st of each month the server builds last month's report for every company, keeps it here and e-mails it to channels subscribed to \"Monthly report\" (Rules & notifications)." : "Automatic monthly reports are off on this server (WIOT_REPORTS_AUTO)."}</p></div></section>
  </div>`;

  async function load() {
    const params = { company: state.company, month };
    const rep = await api("/reports/monthly", { params });
    const qs = (f) => `/api/v2/reports/monthly?${new URLSearchParams({ ...params, format: f })}`;
    $("#rp-xlsx", root).href = qs("xlsx"); $("#rp-pdf", root).href = qs("pdf");
    const s = rep.summary;
    $("#rp-kpis", root).innerHTML = [
      ["Nodes reporting", fmtNum(s.nodes_reporting, 0), monthName(month)],
      ["Uplinks", fmtNum(s.uplinks, 0), "Status and telemetry"],
      ["Water delivered", `${fmtNum(s.water_m3, 1)} <small>m³</small>`, "meter month totals"],
      ["Alerts opened", fmtNum(s.alerts, 0), Object.keys(rep.alerts_by_kind).length ? `${Object.keys(rep.alerts_by_kind).length} kinds` : "none"],
      ["Commands", `${fmtNum(s.commands_acknowledged, 0)} <small>/ ${fmtNum(s.commands, 0)}</small>`, "acknowledged / sent"],
    ].map(([k, val, sub]) => `<div class="tile"><div class="label">${k}</div><div class="v">${val}</div><div class="s">${esc(sub)}</div></div>`).join("");
    $("#rp-meta", root).textContent = `${rep.nodes.length}`;
    $("#rp-rows", root).innerHTML = rep.nodes.map((n) => `<tr><td><b class="mono" data-i18n-skip>${tag(n.node_id)}</b>${n.name ? `<div class="nh-sub" data-i18n-skip>${esc(n.name)}</div>` : ""}</td>
      <td class="num">${fmtNum(n.uplinks, 0)}</td><td class="num">${n.days_with_data}</td><td class="num">${v(n.battery_min_v)}</td>
      <td class="num">${v(n.water_m3, 1)}</td><td class="num">${n.soil_moisture_avg === null ? "–" : `${fmtNum(n.soil_moisture_avg, 1)} %`}</td>
      <td class="num">${v(n.ec_avg)}</td><td class="num">${n.alerts}</td></tr>`).join("")
      || `<tr><td colspan="8"><div class="empty">No uplinks in ${esc(monthName(month))}.</div></td></tr>`;
    const days = Object.entries(rep.water_per_day);
    const el = $("#rp-water", root);
    if (days.length) barChart(el, { categories: days.map(([d]) => d), series: [{ name: "Water", values: days.map(([, x]) => x) }],
      height: 230, catLabel: (d) => d.slice(8), tipFormat: (x) => `${fmtNum(x, 1)} m³` });
    else el.innerHTML = `<div class="empty">No meter day totals this month.</div>`;
  }
  async function archive() {
    const a = (await api("/reports", { params: { company: state.company } })).archive;
    $("#rp-archive", root).innerHTML = a.length ? `<div class="row" style="gap:8px">${a.map((r) => `<button class="btn sm" data-m="${r.month}">${esc(monthName(r.month))}</button>`).join("")}</div>`
      : `<div class="dim">No archived reports yet.</div>`;
    $$("[data-m]", root).forEach((b) => b.addEventListener("click", () => { month = b.dataset.m; $("#rp-month", root).value = month; load(); }));
  }
  $("#rp-month", root).addEventListener("change", (e) => { month = e.target.value; load(); });
  $("#rp-send", root)?.addEventListener("click", async (e) => {
    e.currentTarget.disabled = true;
    try { const r = await api("/reports/monthly/send", { method: "POST", params: { company: state.company, month } }); toast(r.channels ? `Report sent to ${r.channels} channel(s)` : "Report saved; no channel subscribes to monthly reports", "ok"); archive(); }
    catch (err) { toast(err.message, "error"); }
    e.currentTarget.disabled = false;
  });
  await Promise.all([load(), archive()]);
  return undefined;
}
