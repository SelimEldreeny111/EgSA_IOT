// Crop care: degree days and disease / pest risk per field, the farm diary with GlobalG.A.P. traceability,
// yields and water productivity, and FAO WaPOR evapotranspiration against water applied.
import { api, state, badge, toast, ICONS, $, $$ } from "../api.js";
import { esc, fmtNum } from "../charts.js";
import { formHtml, readForm } from "../forms.js";

const TYPES = [["sowing", "Sowing / planting"], ["irrigation", "Irrigation"], ["fertiliser", "Fertiliser"],
  ["plant_protection", "Plant protection"], ["harvest", "Harvest"], ["maintenance", "Maintenance"], ["other", "Other"]];
const LEVEL = { high: ["critical", "High"], moderate: ["warning", "Moderate"], low: ["info", "Low"] };

export async function render(root) {
  const canWrite = state.user.permissions.command;
  const Q = () => ({ company: state.company });
  const fields = (await api("/water/fields", { params: Q() })).fields;
  if (!fields.length) { root.innerHTML = `<div class="panel"><div class="empty">This company has no fields yet. Draw them on the Smart farm page first.</div></div>`; return undefined; }
  const fname = (id) => fields.find((f) => f.id === id)?.name || id;
  const year = new Date().getFullYear();
  root.innerHTML = `<div class="ops">
    <section class="panel"><header><h2><span class="ico">${ICONS.thermo}</span>Degree days and disease risk</h2><span class="meta">next 72 h forecast</span></header>
      <div class="table-wrap"><table class="data"><thead><tr><th>Field</th><th>Crop</th><th class="num">Degree days</th><th>Since</th><th>Risk</th></tr></thead><tbody id="cc-risk"></tbody></table></div>
      <div class="body"><p class="note">Degree days accumulate the daily mean temperature above the crop's base temperature from the planting date (field profile). Risk models: late blight (Hutton criteria), yellow rust, powdery mildew (Gubler-Thomas), downy mildew (10-10-24) and olive fruit fly — indicators to plan scouting and sprays, not a diagnosis.</p></div></section>
    <div class="ed-split ed-wide">
      <section class="panel"><header><h2><span class="ico">${ICONS.edit}</span>Farm diary</h2>
        <select class="input" id="dy-field" style="margin-inline-start:auto;max-width:220px;height:32px"><option value="">All fields</option>${fields.map((f) => `<option value="${esc(f.id)}">${esc(f.name)}</option>`).join("")}</select></header>
        <div class="table-wrap" style="max-height:440px"><table class="data"><thead><tr><th>Date</th><th>Field</th><th>Operation</th><th>Details</th><th>Operator</th><th></th></tr></thead><tbody id="dy-rows"></tbody></table></div></section>
      ${canWrite ? `<section class="panel" id="dy-ed"></section>` : ""}
    </div>
    <section class="panel"><header><h2><span class="ico">${ICONS.shield}</span>Traceability record (GlobalG.A.P.)</h2></header>
      <form class="body row" id="tr-form" style="gap:10px;align-items:flex-end">
        <div class="field" style="margin:0"><label for="tr-f">Field</label><select class="input" id="tr-f">${fields.map((f) => `<option value="${esc(f.id)}">${esc(f.name)}</option>`).join("")}</select></div>
        <div class="field" style="margin:0"><label for="tr-s">From</label><input class="input" type="date" id="tr-s" value="${year}-01-01"></div>
        <div class="field" style="margin:0"><label for="tr-e">To</label><input class="input" type="date" id="tr-e" value="${year}-12-31"></div>
        <button class="btn primary" type="submit">Check</button><a class="btn" id="tr-x">${ICONS.download}<span>Excel</span></a><a class="btn" id="tr-p">${ICONS.download}<span>PDF</span></a></form>
      <div class="body" id="tr-out"></div></section>
    <div class="grid g-2">
      <section class="panel"><header><h2><span class="ico">${ICONS.analytics}</span>Yield and water productivity</h2></header>
        <div class="table-wrap"><table class="data"><thead><tr><th>Field</th><th>Season</th><th class="num">Yield</th><th class="num">Water m³</th><th class="num">kg / m³ applied</th><th class="num">kg / m³ ETc</th></tr></thead><tbody id="wp-rows"></tbody></table></div>
        <div class="body"><p class="note">Yield comes from harvest entries in the diary; applied water from the field's flow meter; ETc from the stored weather and the crop calendar.</p></div></section>
      <section class="panel"><header><h2><span class="ico">${ICONS.world}</span>WaPOR evapotranspiration</h2>
        ${canWrite ? `<label class="btn sm" style="margin-inline-start:auto">${ICONS.upload}<span>Import CSV</span><input type="file" id="wa-file" accept=".csv,text/csv" hidden></label>` : ""}</header>
        <div class="table-wrap"><table class="data"><thead><tr><th>Field</th><th>Month</th><th class="num">AETI mm</th><th class="num">Applied mm</th><th class="num">ETc mm</th><th class="num">Applied / AETI</th></tr></thead><tbody id="wa-rows"></tbody></table></div>
        <div class="body"><p class="note">Monthly actual evapotranspiration and interception (AETI) from the FAO WaPOR portal: export the field values as CSV with the columns field, month (YYYY-MM) and aeti_mm. A ratio well above 1 means more water was applied than the crop used.</p></div></section>
    </div>
  </div>`;

  async function risks() {
    const d = await api("/crop/status", { params: Q() });
    $("#cc-risk", root).innerHTML = d.fields.map((f) => `<tr><td data-i18n-skip><b>${esc(f.name)}</b></td><td>${esc(f.crop || "–")}</td>
      <td class="num">${f.gdd === null ? "–" : `${fmtNum(f.gdd, 0)} °C·d`}${f.gdd_base_c !== null && f.gdd_base_c !== undefined ? `<div class="nh-sub">base ${f.gdd_base_c} °C · ${f.gdd_days} days of weather</div>` : ""}</td>
      <td class="mono sm">${esc(f.since)}</td>
      <td>${f.risks.length ? f.risks.map((r) => `<div>${badge(LEVEL[r.level])} <b>${esc(r.risk)}</b><div class="nh-sub">${esc(r.why)}</div></div>`).join("") : `<span class="dim">No risk indicated</span>`}</td></tr>`).join("");
  }

  const dyFields = [
    { k: "zone_id", label: "Field", type: "select", options: fields.map((f) => [f.id, f.name]) },
    { k: "date", label: "Date", type: "date", required: true },
    { k: "type", label: "Operation", type: "select", options: TYPES },
    { k: "operator", label: "Operator", maxlength: 80 },
    { k: "product", label: "Product", maxlength: 120, placeholder: "trade name" },
    { k: "active_ingredient", label: "Active ingredient", maxlength: 120 },
    { k: "dose", label: "Dose", type: "number", step: "any", min: 0 }, { k: "unit", label: "Unit", maxlength: 20, placeholder: "kg/ha, L/ha" },
    { k: "phi_days", label: "Pre-harvest interval (days)", type: "number", min: 0, max: 365 },
    { k: "quantity_kg", label: "Harvested (kg)", type: "number", step: "any", min: 0 },
    { k: "lot", label: "Lot / batch", maxlength: 60 }, { k: "notes", label: "Notes", type: "textarea", full: true, maxlength: 1000 },
  ];
  function dyEditor() {
    const box = $("#dy-ed", root); if (!box) return;
    box.innerHTML = `<header><h2><span class="ico">${ICONS.edit}</span>New diary entry</h2></header>
      <form class="body" id="dy-form">${formHtml(dyFields, { date: new Date().toISOString().slice(0, 10), type: "plant_protection", zone_id: $("#dy-field", root).value || fields[0].id })}
      <button class="btn primary" type="submit">Add to diary</button></form>`;
    $("#dy-form", box).addEventListener("submit", async (e) => {
      e.preventDefault();
      const v = readForm(e.target, dyFields);
      const body = Object.fromEntries(Object.entries(v).filter(([, x]) => x !== "" && x !== null));
      try { await api("/crop/diary", { method: "POST", params: Q(), body }); toast("Entry added", "ok"); diary(); productivity(); }
      catch (err) { toast(err.message, "error"); }
    });
  }
  async function diary() {
    const rows = (await api("/crop/diary", { params: { ...Q(), zone_id: $("#dy-field", root).value } })).entries;
    $("#dy-rows", root).innerHTML = rows.map((r) => `<tr><td class="mono">${esc(r.date)}</td><td data-i18n-skip>${esc(fname(r.zone_id))}</td>
      <td>${esc(TYPES.find((t) => t[0] === r.type)?.[1] || r.type)}</td>
      <td class="sm">${esc([r.product, r.active_ingredient, r.dose !== undefined ? `${r.dose} ${r.unit || ""}` : "", r.phi_days !== undefined ? `PHI ${r.phi_days} d` : "",
        r.quantity_kg !== undefined ? `${fmtNum(r.quantity_kg, 0)} kg` : "", r.notes].filter(Boolean).join(" · "))}</td>
      <td data-i18n-skip>${esc(r.operator || "")}</td><td class="num">${canWrite ? `<button class="btn sm ghost" data-del="${r.id}">Delete</button>` : ""}</td></tr>`).join("")
      || `<tr><td colspan="6"><div class="empty">No diary entries yet.</div></td></tr>`;
    $$("[data-del]", root).forEach((b) => b.addEventListener("click", async () => {
      if (!confirm("Delete this diary entry?")) return;
      try { await api(`/crop/diary/${b.dataset.del}`, { method: "DELETE", params: Q() }); diary(); } catch (err) { toast(err.message, "error"); }
    }));
  }
  $("#dy-field", root).addEventListener("change", () => { diary(); dyEditor(); });

  async function trace(e) {
    e?.preventDefault();
    const p = { ...Q(), zone_id: $("#tr-f", root).value, start: $("#tr-s", root).value, end: $("#tr-e", root).value };
    $("#tr-x", root).href = `/api/v2/crop/traceability?${new URLSearchParams({ ...p, format: "xlsx" })}`;
    $("#tr-p", root).href = `/api/v2/crop/traceability?${new URLSearchParams({ ...p, format: "pdf" })}`;
    try {
      const r = await api("/crop/traceability", { params: p });
      $("#tr-out", root).innerHTML = `<div class="tiles"><div class="tile"><div class="label">Operations</div><div class="v">${r.operations.length}</div></div>
        <div class="tile"><div class="label">Water applied</div><div class="v">${fmtNum(r.water_m3, 0)} <small>m³</small></div></div>
        <div class="tile"><div class="label">Harvested</div><div class="v">${fmtNum(r.harvest_kg, 0)} <small>kg</small></div></div>
        <div class="tile ${r.phi_ok ? "" : "crit"}"><div class="label">Pre-harvest intervals</div><div class="v">${r.phi_ok ? "Respected" : "Violated"}</div>
          <div class="s">${r.phi_checks.filter((c) => !c.ok).map((c) => `harvest ${c.harvest} < ${c.safe_from} (${c.product})`).join("; ") || `${r.phi_checks.length} checks`}</div></div></div>`;
    } catch (err) { $("#tr-out", root).innerHTML = `<div class="empty">${esc(err.message)}</div>`; }
  }
  $("#tr-form", root).addEventListener("submit", trace);

  async function productivity() {
    const rows = (await api("/crop/productivity", { params: Q() })).fields;
    $("#wp-rows", root).innerHTML = rows.map((r) => `<tr><td data-i18n-skip><b>${esc(r.name)}</b><div class="nh-sub">${esc(r.crop || "")}</div></td>
      <td class="mono sm">${esc(r.from)} → ${esc(r.to)}</td><td class="num">${r.yield_kg ? `${fmtNum(r.yield_kg / 1000, 1)} t${r.yield_t_ha ? `<div class="nh-sub">${fmtNum(r.yield_t_ha, 1)} t/ha</div>` : ""}` : "–"}</td>
      <td class="num">${fmtNum(r.water_m3, 0)}</td><td class="num">${r.wp_kg_m3 === null ? "–" : fmtNum(r.wp_kg_m3, 2)}</td><td class="num">${r.wp_etc_kg_m3 === null ? "–" : fmtNum(r.wp_etc_kg_m3, 2)}</td></tr>`).join("");
  }
  async function wapor() {
    const rows = (await api("/crop/wapor", { params: Q() })).rows;
    $("#wa-rows", root).innerHTML = rows.map((r) => `<tr><td data-i18n-skip>${esc(r.field)}</td><td class="mono">${esc(r.month)}</td><td class="num">${fmtNum(r.aeti_mm, 1)}</td>
      <td class="num">${r.applied_mm === null ? "–" : fmtNum(r.applied_mm, 1)}</td><td class="num">${r.etc_mm === null ? "–" : fmtNum(r.etc_mm, 1)}</td>
      <td class="num">${r.ratio_applied_to_aeti === null ? "–" : fmtNum(r.ratio_applied_to_aeti, 2)}</td></tr>`).join("")
      || `<tr><td colspan="6"><div class="empty">No WaPOR values imported yet.</div></td></tr>`;
  }
  $("#wa-file", root)?.addEventListener("change", async (e) => {
    const file = e.target.files[0]; if (!file) return;
    try {
      const res = await fetch(`/api/v2/crop/wapor/import?${new URLSearchParams(Q())}`, { method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "text/csv", "X-CSRF-Token": decodeURIComponent((document.cookie.split("; ").find((c) => c.startsWith("wiot_csrf=")) || "=").split("=")[1]) },
        body: await file.text() });
      const d = await res.json();
      if (!res.ok) throw new Error(d.detail || "Import failed");
      toast(`${d.imported} rows imported`, "ok"); wapor();
    } catch (err) { toast(err.message, "error"); }
    e.target.value = "";
  });

  dyEditor();
  await Promise.all([risks(), diary(), trace(), productivity(), wapor()]);
  return undefined;
}
