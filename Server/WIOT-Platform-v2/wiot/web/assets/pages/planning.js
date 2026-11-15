// Irrigation planning: per field crop calendar (FAO-56 Kc), soil water-holding capacity, salinity (FAO-29),
// deficit programme and a 7-day soil-moisture forecast with the next irrigation; schedules and canal rotations.
import { api, state, ago, badge, toast, ICONS, $, $$ } from "../api.js";
import { esc, fmtNum, lineChart, PALETTE, T, legend } from "../charts.js";
import { formHtml, readForm } from "../forms.js";

const STAGE = { initial: "Initial", development: "Development", "mid-season": "Mid-season", "late season": "Late season",
  harvested: "Harvested", "before planting": "Before planting", perennial: "Perennial", unknown: "Not set" };
const DAYS = [["0", "Mon"], ["1", "Tue"], ["2", "Wed"], ["3", "Thu"], ["4", "Fri"], ["5", "Sat"], ["6", "Sun"]];
const toT = (d) => Math.floor(new Date(`${d}T12:00:00`).getTime() / 1000);

export async function render(root) {
  const canWrite = state.user.permissions.command;
  const Q = () => ({ company: state.company });
  const [cat, list] = await Promise.all([api("/water/catalog"), api("/water/fields", { params: Q() })]);
  if (!list.configured) {
    root.innerHTML = `<div class="panel"><div class="empty">This company has no farm layout yet. Draw its fields on the Smart farm page first.</div></div>`;
    return undefined;
  }
  let current = list.fields[0]?.id;
  root.innerHTML = `<div class="ops">
    <section class="panel"><header><h2><span class="ico">${ICONS.farm}</span>Fields</h2><span class="meta">${list.fields.length}</span></header>
      <div class="table-wrap"><table class="data"><thead><tr><th>Field</th><th>Crop</th><th>Stage</th><th class="num">Kc</th><th>Soil</th><th>Programme</th><th class="num">Area</th></tr></thead><tbody id="pl-fields"></tbody></table></div></section>
    <div class="grid g-wide">
      <section class="panel"><header><h2><span class="ico">${ICONS.drop}</span><span id="pl-title">Field plan</span></h2><span class="meta" id="pl-meta"></span></header>
        <div class="body"><div class="tiles" id="pl-kpis"></div><div id="pl-advice" style="margin-top:14px"></div>
          <div class="section-title" style="margin-top:16px">Soil moisture forecast · 7 days</div><div id="pl-chart"></div><div id="pl-lg"></div>
          <div class="section-title" style="margin-top:16px">Crop coefficient over the season</div><div id="pl-kc"></div></div></section>
      <section class="panel" id="pl-profile"></section>
    </div>
    <div class="ed-split">
      <section class="panel"><header><h2><span class="ico">${ICONS.clock}</span>Irrigation schedules</h2><span class="meta" id="sc-meta"></span></header>
        <div class="table-wrap"><table class="data"><thead><tr><th>Schedule</th><th>Field</th><th>Days · time</th><th>Next runs</th><th>Last result</th><th>Status</th></tr></thead><tbody id="sc-rows"></tbody></table></div>
        <div class="body"><p class="note">Schedules open the field's valve at the start time and close it after the duration, through the command journal (sleeping nodes get the command at their next wake). A run is skipped and logged when the forecast rain in 24 h reaches the set amount, outside the field's canal rotation window or when its water quota is used up.</p></div></section>
      ${canWrite ? `<section class="panel" id="sc-editor"></section>` : ""}
    </div>
    <div class="ed-split">
      <section class="panel"><header><h2><span class="ico">${ICONS.refresh}</span>Canal rotations</h2></header>
        <div class="table-wrap"><table class="data"><thead><tr><th>Rotation</th><th>Fields</th><th>Cycle</th><th>Hours</th><th>Now</th></tr></thead><tbody id="ro-rows"></tbody></table></div>
        <div class="body"><p class="note">Irrigation water from a canal arrives in turns (for example 5 days on, 10 days off). Schedules and advice respect the window; the day count starts at the anchor date.</p></div></section>
      ${canWrite ? `<section class="panel" id="ro-editor"></section>` : ""}
    </div>
  </div>`;

  const fieldName = (id) => list.fields.find((f) => f.id === id)?.name || id;
  function paintFields() {
    $("#pl-fields", root).innerHTML = list.fields.map((f) => `<tr class="clickable ${f.id === current ? "sel" : ""}" data-f="${esc(f.id)}">
      <td><b data-i18n-skip>${esc(f.name)}</b>${f.node_id ? `<div class="nh-sub mono" data-i18n-skip>NODE-${String(f.node_id).padStart(3, "0")}</div>` : ""}</td>
      <td>${esc(cat.crops[f.crop]?.name || f.crop || "–")}</td><td>${esc(STAGE[f.stage] || f.stage || "–")}</td><td class="num">${fmtNum(f.kc, 2)}</td>
      <td>${esc(cat.soils[f.soil]?.name || "Sandy loam (default)")}</td><td>${esc(cat.deficit[f.deficit]?.name || "Full irrigation")}</td>
      <td class="num">${fmtNum(f.area_ha, 1)} ha</td></tr>`).join("");
    $$("[data-f]", root).forEach((tr) => tr.addEventListener("click", () => { current = tr.dataset.f; paintFields(); loadPlan(); }));
  }

  async function loadPlan() {
    if (!current) return;
    const p = await api(`/water/fields/${encodeURIComponent(current)}`, { params: Q() });
    $("#pl-title", root).textContent = p.zone.name;
    $("#pl-meta", root).textContent = p.crop_name || "crop not set";
    const sal = p.salinity, s = p.soil;
    $("#pl-kpis", root).innerHTML = [
      ["Growth stage", esc(STAGE[p.stage.stage] || p.stage.stage), p.stage.harvest ? `harvest ${p.stage.harvest}` : p.stage.stage === "unknown" && p.crop ? "set the planting date" : ""],
      ["Crop coefficient", fmtNum(p.stage.kc, 2), p.deficit.factor < 1 ? `× ${fmtNum(p.deficit.factor, 2)} deficit` : "full ETc"],
      ["Soil moisture", p.moisture === null ? "–" : `${fmtNum(p.moisture, 1)} <small>%</small>`, `refill ${fmtNum(s.refill, 1)} % · capacity ${fmtNum(s.fc, 1)} %`],
      ["Water held (TAW)", `${fmtNum(s.taw_mm, 0)} <small>mm</small>`, `${fmtNum(s.raw_mm, 0)} mm usable before stress`],
      ["Salinity", sal?.ece_dsm !== undefined ? `${fmtNum(sal.ece_dsm, 2)} <small>dS/m</small>` : "–", sal ? `${sal.yield_potential_pct !== undefined ? `${fmtNum(sal.yield_potential_pct, 0)} % yield potential · ` : ""}threshold ${fmtNum(sal.threshold_dsm, 1)}` : p.crop ? "no EC reading or water EC set" : "set the crop"],
    ].map(([k, v, sub]) => `<div class="tile"><div class="label">${k}</div><div class="v">${v}</div><div class="s">${esc(sub)}</div></div>`).join("");
    const n = p.next_irrigation, lr = sal?.leaching_requirement;
    $("#pl-advice", root).innerHTML = `<div class="inv-link">${n
      ? `<b>Next irrigation by ${esc(n.date)}:</b> ${fmtNum(n.gross_mm, 1)} mm (≈${n.runtime_min} min)${n.leaching_mm ? `, including ${fmtNum(n.leaching_mm, 1)} mm to leach salts` : ""}.`
      : p.moisture === null ? "No valid soil-moisture reading from this field's node — the forecast needs one."
      : !p.weather ? "Weather forecast unavailable — the forecast needs ET0." : "<b>No irrigation needed in the next 7 days</b> at the forecast weather."}
      ${p.deficit.phase ? `<div class="nh-sub">Deficit programme: ${esc(p.deficit.phase)} — ${fmtNum(p.deficit.factor * 100, 0)} % of full crop water use.</div>` : ""}
      ${lr ? `<div class="nh-sub">Leaching requirement for the irrigation water: ${fmtNum(lr * 100, 1)} % extra (FAO-29).</div>` : ""}
      ${Math.abs(p.suggested_band[0] - p.zone.band[0]) > 2 ? `<div class="nh-sub">The soil profile suggests a target band of ${fmtNum(p.suggested_band[0], 0)}–${fmtNum(p.suggested_band[1], 0)} %; the field is set to ${p.zone.band[0]}–${p.zone.band[1]} % on the Smart farm page.</div>` : ""}</div>`;
    const pts = p.forecast.map((d) => [toT(d.date), d.moisture]);
    lineChart($("#pl-chart", root), { series: [{ name: "Forecast moisture", color: PALETTE[0], points: pts, markers: true }], xType: "time", height: 200,
      unit: " %", refLines: [{ y: s.refill, label: "refill point", color: T.warn }, { y: s.fc, label: "field capacity", color: T.ref }],
      xFormat: (t) => new Date(t * 1000).toISOString().slice(5, 10), empty: "Forecast needs a moisture reading and the weather forecast" });
    $("#pl-lg", root).innerHTML = pts.length ? legend([{ name: "Forecast moisture", color: PALETTE[0], line: true }]) : "";
    const kc = p.kc_curve.map((d) => [toT(d.date), d.kc]);
    lineChart($("#pl-kc", root), { series: [{ name: "Kc", color: PALETTE[2], points: kc }], xType: "time", height: 160, zero: true,
      xFormat: (t) => new Date(t * 1000).toISOString().slice(0, 7), empty: "Set the crop to see its calendar" });
    profileEditor(p);
  }

  function profileEditor(p) {
    const box = $("#pl-profile", root);
    const prof = p.profile || {}, soil = prof.soil || {};
    const fields = [
      { k: "crop", label: "Crop", type: "select", options: [["", "— not set —"], ...Object.entries(cat.crops).map(([k, c]) => [k, c.name])] },
      { k: "planting_date", label: "Planting date", type: "date", hint: "Annual crops: the calendar and Kc follow from it" },
      { k: "texture", label: "Soil texture", type: "select", options: [...Object.entries(cat.soils).map(([k, x]) => [k, `${x.name} (FC ${fmtNum(x.fc, 0)} %, WP ${fmtNum(x.wp, 0)} %)`]), ["custom", "Lab values"]] },
      { k: "fc", label: "Field capacity (% vol, lab)", type: "number", step: "0.1", min: 1, max: 60 },
      { k: "wp", label: "Wilting point (% vol, lab)", type: "number", step: "0.1", min: 0, max: 60 },
      { k: "root_depth_m", label: "Root depth (m)", type: "number", step: "0.05", min: 0.1, max: 4, hint: "Empty = crop default" },
      { k: "ecw_dsm", label: "Irrigation water EC (dS/m)", type: "number", step: "0.01", min: 0, max: 20, hint: "Sets the leaching requirement" },
      { k: "ec_factor", label: "Probe EC → ECe factor", type: "number", step: "0.05", min: 0.1, max: 10, hint: "1 unless calibrated against a lab ECe" },
      { k: "deficit", label: "Deficit programme", type: "select", full: true, options: [["", "Full irrigation"], ...Object.entries(cat.deficit).map(([k, d]) => [k, d.name])] },
    ];
    const values = { crop: prof.crop || p.crop || "", planting_date: prof.planting_date || "", texture: soil.texture || "sandy loam", fc: soil.fc ?? "",
      wp: soil.wp ?? "", root_depth_m: soil.root_depth_m ?? "", ecw_dsm: prof.salinity?.ecw_dsm ?? "", ec_factor: prof.salinity?.ec_factor ?? "",
      deficit: prof.deficit || "" };
    box.innerHTML = `<header><h2><span class="ico">${ICONS.edit}</span>Field profile</h2></header>
      <form class="body" id="pf-form">${formHtml(fields, values)}${canWrite ? `<button class="btn primary" type="submit">Save profile</button>` : ""}
      <p class="note">Crop stages and coefficients: FAO-56. Salt tolerance and leaching: FAO-29 (Ayers &amp; Westcot). Lab values override the texture.</p></form>`;
    if (!canWrite) { $$("input,select", box).forEach((i) => { i.disabled = true; }); return; }
    $("#pf-form", box).addEventListener("submit", async (e) => {
      e.preventDefault();
      const v = readForm(e.target, fields);
      const body = { crop: v.crop || null, planting_date: v.planting_date || null, deficit: v.deficit || null,
        soil: { texture: v.texture, ...(v.texture === "custom" || v.fc !== null ? { fc: v.fc, wp: v.wp } : {}), root_depth_m: v.root_depth_m },
        salinity: { ecw_dsm: v.ecw_dsm, ec_factor: v.ec_factor } };
      try {
        await api(`/water/fields/${encodeURIComponent(current)}`, { method: "PUT", params: Q(), body });
        toast("Field profile saved", "ok");
        const l = await api("/water/fields", { params: Q() }); list.fields = l.fields; paintFields(); loadPlan();
      } catch (err) { toast(err.message, "error"); }
    });
  }

  // ------------------------------------------------------------- schedules
  let schedules = [];
  const schFields = [
    { k: "name", label: "Name", required: true, maxlength: 80, placeholder: "e.g. Morning cycle" },
    { k: "zone_id", label: "Field", type: "select", options: list.fields.map((f) => [f.id, f.name]) },
    { k: "days", label: "Days", type: "checks", options: DAYS, full: true },
    { k: "start", label: "Start time", type: "time", required: true },
    { k: "duration_min", label: "Duration (minutes)", type: "number", min: 5, max: 1440, required: true },
    { k: "skip_rain_mm", label: "Skip if rain in 24 h ≥ (mm)", type: "number", step: "0.5", min: 0, max: 200 },
    { k: "respect_rotation", label: "Rotation", type: "check", text: "Only inside the canal rotation window" },
    { k: "respect_quota", label: "Quota", type: "check", text: "Skip when the water quota is used up" },
    { k: "enabled", label: "Status", type: "check", text: "Schedule is active" },
  ];
  function schEditor(s) {
    const box = $("#sc-editor", root); if (!box) return;
    const v = s ? { ...s, days: s.days.map(String) } : { zone_id: current, days: ["0", "2", "4"], start: "06:00", duration_min: 60, skip_rain_mm: 5, respect_rotation: true, respect_quota: true, enabled: true };
    box.innerHTML = `<header><h2><span class="ico">${ICONS.edit}</span>${s ? `Edit · ${esc(s.name)}` : "New schedule"}</h2></header>
      <form class="body" id="sc-form">${formHtml(schFields, v)}<div class="row"><button class="btn primary" type="submit">${s ? "Save changes" : "Create schedule"}</button>
      ${s ? `<button class="btn ghost" type="button" id="sc-new">New</button><button class="btn danger" type="button" id="sc-del" style="margin-inline-start:auto">Delete</button>` : ""}</div>
      ${s ? `<div class="section-title" style="margin-top:14px">Run log</div><ul class="log-list" id="sc-log"></ul>` : ""}</form>`;
    $("#sc-form", box).addEventListener("submit", async (e) => {
      e.preventDefault();
      const body = readForm(e.target, schFields);
      body.days = body.days.map(Number);
      try { await api(s ? `/water/schedules/${s.id}` : "/water/schedules", { method: s ? "PATCH" : "POST", params: Q(), body }); toast("Schedule saved", "ok"); loadSchedules(); }
      catch (err) { toast(err.message, "error"); }
    });
    $("#sc-new", box)?.addEventListener("click", () => schEditor(null));
    $("#sc-del", box)?.addEventListener("click", async () => {
      if (!confirm("Delete this schedule?")) return;
      try { await api(`/water/schedules/${s.id}`, { method: "DELETE", params: Q() }); loadSchedules(); schEditor(null); } catch (err) { toast(err.message, "error"); }
    });
    if (s) api(`/water/schedules/${s.id}/log`, { params: Q() }).then((d) => {
      $("#sc-log", box).innerHTML = d.log.map((l) => `<li><span>${esc(ago(l.ts))}</span>${badge([l.action === "skipped" ? "warning" : l.action === "refused" ? "critical" : "good", l.action])}<span class="dim">${esc(l.detail)}</span></li>`).join("")
        || `<li><span class="dim">Not run yet.</span></li>`;
    });
  }
  async function loadSchedules() {
    schedules = (await api("/water/schedules", { params: Q() })).items;
    $("#sc-meta", root).textContent = `${schedules.length}`;
    $("#sc-rows", root).innerHTML = schedules.map((s) => `<tr class="clickable" data-s="${s.id}"><td><b>${esc(s.name)}</b></td><td data-i18n-skip>${esc(fieldName(s.zone_id))}</td>
      <td>${esc(s.days.map((d) => DAYS[d][1]).join(" "))} · ${esc(s.start)} · ${s.duration_min} min</td>
      <td class="mono sm">${esc((s.next_runs || []).slice(0, 2).join(", ") || "–")}</td><td>${esc(s.state?.last_result || "–")}</td>
      <td>${s.enabled ? badge(["good", "Active"]) : badge(["neutral", "Paused"])}</td></tr>`).join("")
      || `<tr><td colspan="6"><div class="empty">No schedules yet.</div></td></tr>`;
    $$("[data-s]", root).forEach((tr) => tr.addEventListener("click", () => schEditor(schedules.find((x) => x.id === +tr.dataset.s))));
  }

  // ------------------------------------------------------------- rotations
  let rotations = [];
  const roFields = [
    { k: "name", label: "Name", required: true, maxlength: 80, placeholder: "e.g. Canal 7 rotation" },
    { k: "anchor_date", label: "First day of an \"on\" period", type: "date", required: true },
    { k: "on_days", label: "Days on", type: "number", min: 1, max: 60 }, { k: "off_days", label: "Days off", type: "number", min: 0, max: 60 },
    { k: "from", label: "Water from", type: "time" }, { k: "to", label: "Water until", type: "time" },
    { k: "zone_ids", label: "Fields", type: "checks", options: list.fields.map((f) => [f.id, f.name]), full: true },
    { k: "enabled", label: "Status", type: "check", text: "Rotation is active" },
  ];
  function roEditor(r) {
    const box = $("#ro-editor", root); if (!box) return;
    const v = r || { on_days: 5, off_days: 10, from: "06:00", to: "18:00", anchor_date: new Date().toISOString().slice(0, 10), zone_ids: [], enabled: true };
    box.innerHTML = `<header><h2><span class="ico">${ICONS.edit}</span>${r ? `Edit · ${esc(r.name)}` : "New rotation"}</h2></header>
      <form class="body" id="ro-form">${formHtml(roFields, v)}<div class="row"><button class="btn primary" type="submit">${r ? "Save changes" : "Create rotation"}</button>
      ${r ? `<button class="btn ghost" type="button" id="ro-new">New</button><button class="btn danger" type="button" id="ro-del" style="margin-inline-start:auto">Delete</button>` : ""}</div></form>`;
    $("#ro-form", box).addEventListener("submit", async (e) => {
      e.preventDefault();
      try { await api(r ? `/water/rotations/${r.id}` : "/water/rotations", { method: r ? "PATCH" : "POST", params: Q(), body: readForm(e.target, roFields) }); toast("Rotation saved", "ok"); loadRotations(); }
      catch (err) { toast(err.message, "error"); }
    });
    $("#ro-new", box)?.addEventListener("click", () => roEditor(null));
    $("#ro-del", box)?.addEventListener("click", async () => {
      if (!confirm("Delete this rotation?")) return;
      try { await api(`/water/rotations/${r.id}`, { method: "DELETE", params: Q() }); loadRotations(); roEditor(null); } catch (err) { toast(err.message, "error"); }
    });
  }
  async function loadRotations() {
    rotations = (await api("/water/rotations", { params: Q() })).items;
    $("#ro-rows", root).innerHTML = rotations.map((r) => `<tr class="clickable" data-r="${r.id}"><td><b>${esc(r.name)}</b></td>
      <td data-i18n-skip>${esc(r.zone_ids.map(fieldName).join(", "))}</td><td>${r.on_days} on · ${r.off_days} off</td><td class="mono">${esc(r.from)}–${esc(r.to)}</td>
      <td>${r.window.open ? badge(["good", "Water available"]) : `${badge(["neutral", "Closed"])}<div class="nh-sub">next ${esc(r.window.next_window)}</div>`}</td></tr>`).join("")
      || `<tr><td colspan="5"><div class="empty">No canal rotations. Fields fed from wells or a reservoir need none.</div></td></tr>`;
    $$("[data-r]", root).forEach((tr) => tr.addEventListener("click", () => roEditor(rotations.find((x) => x.id === +tr.dataset.r))));
  }

  paintFields();
  await Promise.all([loadPlan(), loadSchedules(), loadRotations()]);
  schEditor(null); roEditor(null);
  return undefined;
}
