// Water accounts: quotas, wells against their licence, water and pumping cost per field, and utility
// district balances (non-revenue water) with a billing statement.
import { api, state, badge, toast, ICONS, $, $$ } from "../api.js";
import { esc, fmtNum } from "../charts.js";
import { formHtml, readForm } from "../forms.js";

const STATUS = { ok: ["good", "Within limit"], near: ["warning", "Near the limit"], exceeded: ["critical", "Exceeded"] };
const bar = (share, status) => `<div class="nh-score ${status === "ok" ? "good" : status === "near" ? "warn" : "bad"}" style="min-width:160px"><b>${fmtNum(Math.min(share, 9.99) * 100, 0)}%</b><span><i style="width:${Math.min(100, share * 100)}%"></i></span></div>`;
const ids = (s) => (s || "").split(/[\s,;]+/).filter(Boolean).map(Number);

export async function render(root) {
  const canWrite = state.user.permissions.command;
  const Q = () => ({ company: state.company });
  const fields = (await api("/water/fields", { params: Q() })).fields;
  const fname = (id) => fields.find((f) => f.id === id)?.name || id;
  const month = new Date().toISOString().slice(0, 7);
  root.innerHTML = `<div class="ops">
    <div class="ed-split ed-wide">
      <section class="panel"><header><h2><span class="ico">${ICONS.drop}</span>Water quotas</h2></header>
        <div class="table-wrap"><table class="data"><thead><tr><th>Quota</th><th>Fields</th><th>Period</th><th class="num">Used / quota</th><th>Share</th><th>Projected</th></tr></thead><tbody id="q-rows"></tbody></table></div></section>
      ${canWrite ? `<section class="panel" id="q-ed"></section>` : ""}
    </div>
    <div class="ed-split ed-wide">
      <section class="panel"><header><h2><span class="ico">${ICONS.tower}</span>Groundwater wells</h2></header>
        <div class="table-wrap"><table class="data"><thead><tr><th>Well</th><th>Licence year</th><th class="num">Pumped / licensed</th><th>Share</th><th class="num">Per day</th><th>Projection</th></tr></thead><tbody id="w-rows"></tbody></table></div>
        <div class="body"><p class="note">Pumped volume comes from the flow meter on the well's node. An alert opens at 90 % of the licence or when the current rate would exceed it before the licence year ends. Water level needs a level sensor in the node (Track G).</p></div></section>
      ${canWrite ? `<section class="panel" id="w-ed"></section>` : ""}
    </div>
    <div class="ed-split ed-wide">
      <section class="panel"><header><h2><span class="ico">${ICONS.analytics}</span>Water and pumping cost per field</h2><span class="meta" id="c-meta"></span></header>
        <div class="table-wrap"><table class="data"><thead><tr><th>Field</th><th>Since</th><th class="num">Water m³</th><th class="num">mm</th><th class="num">Pump hours</th><th class="num">Energy kWh</th><th class="num">Water cost</th><th class="num">Energy cost</th><th class="num">Total</th><th class="num">Per ha</th></tr></thead><tbody id="c-rows"></tbody></table></div>
        <div class="body"><p class="note">Season from the planting date (field profile) or 1 January. Pump hours = volume ÷ the pivot flow on the Smart farm page.</p></div></section>
      ${canWrite ? `<section class="panel" id="t-ed"></section>` : ""}
    </div>
    <div class="ed-split ed-wide">
      <section class="panel"><header><h2><span class="ico">${ICONS.region}</span>Utility districts · water balance</h2>
        <label class="tb-select" style="margin-inline-start:auto"><span>Month</span><input class="input" type="month" id="d-month" value="${month}" style="height:30px;border:0;background:transparent"></label></header>
        <div class="body" id="d-body"></div></section>
      ${canWrite ? `<section class="panel" id="d-ed"></section>` : ""}
    </div>
  </div>`;

  function editor(box, title, flds, values, path, onDone, item) {
    if (!box) return;
    box.innerHTML = `<header><h2><span class="ico">${ICONS.edit}</span>${esc(item ? `Edit · ${item.name}` : title)}</h2></header>
      <form class="body">${formHtml(flds, values)}<div class="row"><button class="btn primary" type="submit">${item ? "Save changes" : "Create"}</button>
      ${item ? `<button class="btn ghost" type="button" data-new>New</button><button class="btn danger" type="button" data-del style="margin-inline-start:auto">Delete</button>` : ""}</div></form>`;
    const form = $("form", box);
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const v = readForm(form, flds);
      for (const f of flds) if (f.ids) v[f.k] = ids(v[f.k]);
      try { await api(item ? `${path}/${item.id}` : path, { method: item ? "PATCH" : "POST", params: Q(), body: v }); toast("Saved", "ok"); onDone(); }
      catch (err) { toast(err.message, "error"); }
    });
    $("[data-new]", box)?.addEventListener("click", () => onDone(true));
    $("[data-del]", box)?.addEventListener("click", async () => {
      if (!confirm("Delete this entry?")) return;
      try { await api(`${path}/${item.id}`, { method: "DELETE", params: Q() }); onDone(true); } catch (err) { toast(err.message, "error"); }
    });
  }

  // ---------------------------------------------------------------- quotas
  const qFields = [{ k: "name", label: "Name", required: true, maxlength: 80 },
    { k: "period", label: "Period", type: "select", options: [["month", "Calendar month"], ["season", "Season (from a start date)"], ["year", "Year (from a start date)"]] },
    { k: "volume_m3", label: "Quota (m³)", type: "number", min: 1, required: true }, { k: "start_date", label: "Start date", type: "date" },
    { k: "season_days", label: "Season length (days)", type: "number", min: 30, max: 366 },
    { k: "zone_ids", label: "Fields (none ticked = whole farm)", type: "checks", options: fields.map((f) => [f.id, f.name]), full: true },
    { k: "enabled", label: "Status", type: "check", text: "Active" }];
  async function quotas(reset) {
    const items = (await api("/water/quotas", { params: Q() })).items;
    $("#q-rows", root).innerHTML = items.map((q) => `<tr class="clickable" data-q="${q.id}"><td><b>${esc(q.name)}</b></td>
      <td data-i18n-skip>${q.zone_ids ? esc(q.zone_ids.map(fname).join(", ")) : "whole farm"}</td><td>${esc(q.status.start)} → ${esc(q.status.end)}</td>
      <td class="num">${fmtNum(q.status.used_m3, 0)} / ${fmtNum(q.quota_m3 ?? q.volume_m3, 0)}</td><td>${bar(q.status.share, q.status.status)}</td>
      <td>${badge(STATUS[q.status.status])}<div class="nh-sub">${fmtNum(q.status.projected_m3, 0)} m³ at this rate</div></td></tr>`).join("")
      || `<tr><td colspan="6"><div class="empty">No quotas. Add the farm's allocation from the irrigation authority.</div></td></tr>`;
    const open = (q) => editor($("#q-ed", root), "New quota", qFields, q || { period: "month", enabled: true, season_days: 120 }, "/water/quotas", (r) => quotas(r), q);
    $$("[data-q]", root).forEach((tr) => tr.addEventListener("click", () => open(items.find((x) => x.id === +tr.dataset.q))));
    if (reset !== false) open(null);
  }

  // ----------------------------------------------------------------- wells
  const wFields = [{ k: "name", label: "Name", required: true, maxlength: 80 }, { k: "licence_no", label: "Licence number", maxlength: 40 },
    { k: "node_id", label: "Node with the flow meter", type: "number", min: 1, max: 65535, required: true },
    { k: "region", label: "Region", type: "select", options: state.regions.map((r) => [r, r]) },
    { k: "licence_m3_year", label: "Licensed volume (m³ / year)", type: "number", min: 1, required: true },
    { k: "licence_start_month", label: "Licence year starts in", type: "select", options: [...Array(12)].map((_, i) => [String(i + 1), new Date(2026, i, 1).toLocaleString(undefined, { month: "long" })]) },
    { k: "pump_kw", label: "Pump power (kW)", type: "number", step: "0.1", min: 0 }, { k: "enabled", label: "Status", type: "check", text: "Active" }];
  async function wells(reset) {
    const items = (await api("/water/wells", { params: Q() })).items;
    $("#w-rows", root).innerHTML = items.map((w) => `<tr class="clickable" data-w="${w.id}"><td><b>${esc(w.name)}</b><div class="nh-sub mono" data-i18n-skip>NODE-${String(w.node_id).padStart(3, "0")}${w.licence_no ? ` · ${esc(w.licence_no)}` : ""}</div></td>
      <td>${esc(w.status.year_start)} → ${esc(w.status.year_end)}</td><td class="num">${fmtNum(w.status.pumped_m3, 0)} / ${fmtNum(w.status.licence_m3, 0)}</td>
      <td>${bar(w.status.share, w.status.status)}</td><td class="num">${fmtNum(w.status.avg_day_m3, 0)} m³</td>
      <td>${badge(STATUS[w.status.status])}<div class="nh-sub">${w.status.days_left !== null ? `licence lasts ≈${w.status.days_left} more days` : `${fmtNum(w.status.projected_m3, 0)} m³ projected`}</div></td></tr>`).join("")
      || `<tr><td colspan="6"><div class="empty">No wells registered.</div></td></tr>`;
    const open = (w) => editor($("#w-ed", root), "New well", wFields, w ? { ...w, licence_start_month: String(w.licence_start_month) } : { region: state.region, licence_start_month: "1", enabled: true }, "/water/wells", (r) => wells(r), w);
    $$("[data-w]", root).forEach((tr) => tr.addEventListener("click", () => open(items.find((x) => x.id === +tr.dataset.w))));
    if (reset !== false) open(null);
  }

  // ----------------------------------------------------------------- costs
  async function costs() {
    const c = await api("/water/costs", { params: Q() });
    const cur = c.currency;
    $("#c-meta", root).textContent = `${fmtNum(c.total_cost, 0)} ${cur} · ${fmtNum(c.water_m3, 0)} m³`;
    $("#c-rows", root).innerHTML = c.fields.map((r) => `<tr><td data-i18n-skip><b>${esc(r.name)}</b></td><td class="mono sm">${esc(r.from)}</td>
      <td class="num">${fmtNum(r.water_m3, 0)}</td><td class="num">${r.mm === null ? "–" : fmtNum(r.mm, 0)}</td><td class="num">${fmtNum(r.pump_hours, 1)}</td>
      <td class="num">${fmtNum(r.energy_kwh, 0)}</td><td class="num">${fmtNum(r.water_cost, 0)}</td><td class="num">${fmtNum(r.energy_cost, 0)}</td>
      <td class="num"><b>${fmtNum(r.total_cost, 0)} ${esc(cur)}</b></td><td class="num">${r.cost_per_ha === null ? "–" : fmtNum(r.cost_per_ha, 0)}</td></tr>`).join("")
      || `<tr><td colspan="10"><div class="empty">No fields.</div></td></tr>`;
    const box = $("#t-ed", root);
    if (!box) return;
    const tf = [{ k: "currency", label: "Currency", maxlength: 8 }, { k: "water_price_m3", label: "Water price per m³", type: "number", step: "0.001", min: 0 },
      { k: "energy_price_kwh", label: "Energy price per kWh", type: "number", step: "0.001", min: 0 }, { k: "pump_kw", label: "Pivot pump power (kW)", type: "number", step: "0.1", min: 0 }];
    box.innerHTML = `<header><h2><span class="ico">${ICONS.edit}</span>Tariffs</h2></header><form class="body">${formHtml(tf, c.tariffs)}<button class="btn primary" type="submit">Save tariffs</button></form>`;
    $("form", box).addEventListener("submit", async (e) => {
      e.preventDefault();
      try { await api("/water/tariffs", { method: "PUT", params: Q(), body: readForm(e.target, tf) }); toast("Tariffs saved", "ok"); costs(); }
      catch (err) { toast(err.message, "error"); }
    });
  }

  // ------------------------------------------------------------- districts
  const dFields = [{ k: "name", label: "District name", required: true, maxlength: 80 },
    { k: "region", label: "Region", type: "select", options: state.regions.map((r) => [r, r]) },
    { k: "inlet_nodes", label: "Inlet meters (node ids)", placeholder: "e.g. 10", ids: true, full: true },
    { k: "customer_nodes", label: "Customer meters (node ids)", placeholder: "e.g. 11, 12, 13", ids: true, full: true },
    { k: "enabled", label: "Status", type: "check", text: "Active" }];
  async function districts(reset) {
    const items = (await api("/water/districts", { params: Q() })).items;
    const m = $("#d-month", root).value;
    const body = $("#d-body", root);
    if (!items.length) body.innerHTML = `<div class="empty">No districts. A district (DMA) compares the water entering through its inlet meters with what its customer meters record.</div>`;
    else {
      const bals = await Promise.all(items.map((d) => api(`/water/districts/${d.id}/balance`, { params: { ...Q(), month: m } })));
      body.innerHTML = bals.map((b, i) => `<div class="section-title clickable" data-d="${items[i].id}">${esc(b.dma)}</div>
        <div class="tiles"><div class="tile"><div class="label">System input</div><div class="v">${fmtNum(b.system_input_m3, 0)} <small>m³</small></div><div class="s">${b.inlets_reporting}/${b.inlets} inlet meters</div></div>
          <div class="tile"><div class="label">Billed consumption</div><div class="v">${fmtNum(b.billed_m3, 0)} <small>m³</small></div><div class="s">${b.customers_reporting}/${b.customers.length} customer meters</div></div>
          <div class="tile ${b.non_revenue_pct > 25 ? "crit" : b.non_revenue_pct > 15 ? "warn" : ""}"><div class="label">Non-revenue water</div><div class="v">${b.non_revenue_pct === null ? "–" : `${fmtNum(b.non_revenue_pct, 1)} <small>%</small>`}</div><div class="s">${fmtNum(b.non_revenue_m3, 0)} m³ lost or unbilled</div></div></div>
        <div class="row" style="margin:10px 0 18px"><a class="btn sm" href="/api/v2/water/districts/${items[i].id}/balance?${new URLSearchParams({ ...Q(), month: m, format: "xlsx" })}">${ICONS.download}<span>Billing statement (Excel)</span></a></div>`).join("");
      $$("[data-d]", root).forEach((el) => el.addEventListener("click", () => open(items.find((x) => x.id === +el.dataset.d))));
    }
    const open = (d) => editor($("#d-ed", root), "New district", dFields, d ? { ...d, inlet_nodes: d.inlet_nodes.join(", "), customer_nodes: d.customer_nodes.join(", ") } : { region: state.region, enabled: true }, "/water/districts", (r) => districts(r), d);
    if (reset !== false) open(null);
  }
  $("#d-month", root).addEventListener("change", () => districts(false));

  await Promise.all([quotas(), wells(), costs(), districts()]);
  return undefined;
}
