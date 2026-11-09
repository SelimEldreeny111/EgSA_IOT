// Organization: companies (tenants), regions, nodes, gateways and integrations (API tokens, webhooks).
import { api, state, toast, ICONS, ago, badge, LINK_BADGE, $, $$ } from "../api.js";
import { esc, fmtDateTime } from "../charts.js";
import { t, I18N } from "../i18n.js";

// Two node types. Monitoring nodes only report sensors; control nodes also drive a valve.
export const NODE_TYPES = {
  monitoring: { label: "Monitoring node", short: "Monitoring", desc: "Sensors only — reports soil, flow and salinity readings. Cannot receive valve commands.", badge: "info" },
  control: { label: "Control node", short: "Control", desc: "Sensors + valve — reports readings and opens / closes its valve (manual commands and automatic irrigation).", badge: "good" },
};
// Sensors the WIOT firmware reports (sensor_mask bits 1, 2, 4, 8).
export const SENSORS = {
  hnda: { label: "HNDA soil moisture & temperature", short: "HNDA soil" },
  sondas: { label: "Sondas EC (salinity) probe", short: "Sondas EC" },
  tuf: { label: "TUF-2000B ultrasonic flow meter", short: "TUF flow" },
  supmea: { label: "Supmea electromagnetic flow meter", short: "Supmea flow" },
};
export const typeBadge = (type) => (type ? badge([NODE_TYPES[type]?.badge || "neutral", NODE_TYPES[type]?.short || type]) : badge(["neutral", "Unregistered"]));
export const sensorChips = (list) => (list?.length ? list.map((k) => `<span class="chip">${esc(t(SENSORS[k]?.short || k))}</span>`).join(" ") : `<span class="muted">–</span>`);
const BACKHAUL = { lora: "LoRa", wifi: "Wi-Fi", cellular: "Cellular", satellite: "Satellite", ethernet: "Ethernet" };
const EVENTS = { telemetry: "Telemetry", command: "Command updates", automation: "Irrigation automation", alert: "Alerts (offline / online / low battery)", flash: "Flash archive" };
// ISO 3166-1 alpha-2; names come from the browser (Intl.DisplayNames) in the active language.
const COUNTRIES = "AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI BJ BL BM BN BO BQ BR BS BT BV BW BY BZ CA CC CD CF CG CH CI CK CL CM CN CO CR CU CV CW CX CY CZ DE DJ DK DM DO DZ EC EE EG EH ER ES ET FI FJ FK FM FO FR GA GB GD GE GF GG GH GI GL GM GN GP GQ GR GS GT GU GW GY HK HM HN HR HT HU ID IE IL IM IN IO IQ IR IS IT JE JM JO JP KE KG KH KI KM KN KP KR KW KY KZ LA LB LC LI LK LR LS LT LU LV LY MA MC MD ME MF MG MH MK ML MM MN MO MP MQ MR MS MT MU MV MW MX MY MZ NA NC NE NF NG NI NL NO NP NR NU NZ OM PA PE PF PG PH PK PL PM PN PR PS PT PW PY QA RE RO RS RU RW SA SB SC SD SE SG SH SI SJ SK SL SM SN SO SR SS ST SV SX SY SZ TC TD TF TG TH TJ TK TL TM TN TO TR TT TV TW TZ UA UG UM US UY UZ VA VC VE VG VI VN VU WF WS YE YT ZA ZM ZW".split(" ");

// Country-code chip (emoji flags do not render on Windows).
export const flag = (cc) => (cc && /^[A-Z]{2}$/.test(cc) ? `<span class="cc" title="${esc(countryName(cc))}">${cc}</span>` : `<span class="cc none">··</span>`);
export function countryName(cc) {
  if (!cc) return "";
  try { return new Intl.DisplayNames([I18N.lang], { type: "region" }).of(cc) || cc; } catch { return cc; }
}
const zones = () => { try { return Intl.supportedValuesOf("timeZone"); } catch { return ["Africa/Cairo", "UTC"]; } };
const localTime = (tz) => { try { return new Date().toLocaleTimeString("en-GB", { timeZone: tz, hour: "2-digit", minute: "2-digit", hourCycle: "h23" }); } catch { return "–"; } };
const where = (lat, lon) => (lat === null || lat === undefined ? `<span class="muted">${t("not set")}</span>` : `<span class="mono">${(+lat).toFixed(4)}, ${(+lon).toFixed(4)}</span>`);

export async function render(root) {
  const P = state.user.permissions, sup = P.supervisor, canWrite = P.command;
  const tabs = [["companies", "Companies"], ["regions", "Regions"], ["nodes", "Nodes"], ["gateways", "Gateways"]];
  if (canWrite) tabs.push(["integrations", "API & webhooks"]);
  const remember = (v) => { try { if (v === undefined) return sessionStorage.getItem("wiot.orgTab"); sessionStorage.setItem("wiot.orgTab", v); } catch { /* storage blocked */ } return null; };
  let tab = remember() || "nodes";
  if (!tabs.some(([k]) => k === tab)) tab = "nodes";

  root.innerHTML = `<section class="panel org-head"><div class="body row">
      <div class="org-title"><span class="ico">${ICONS.org}</span><div><h2>${t("Organization")}</h2>
        <div class="dim">${t("Companies, regions, nodes, gateways and integrations")} · <b>${esc(state.company)}</b></div></div></div>
      <div class="seg org-tabs" role="tablist">${tabs.map(([k, l]) => `<button role="tab" data-tab="${k}" class="${k === tab ? "on" : ""}">${t(l)}</button>`).join("")}</div>
    </div></section>
    <div id="org-body" style="margin-top:16px"></div>`;
  $$(".org-tabs button", root).forEach((b) => b.addEventListener("click", () => { tab = b.dataset.tab; remember(tab); show(); }));
  const body = $("#org-body", root);
  const Q = () => ({ company: state.company });

  async function show() {
    $$(".org-tabs button", root).forEach((b) => b.classList.toggle("on", b.dataset.tab === tab));
    body.innerHTML = `<div class="panel"><div class="empty">${t("Loading…")}</div></div>`;
    try { await ({ companies, regions, nodes, gateways, integrations })[tab](); }
    catch (err) { body.innerHTML = `<div class="panel"><div class="empty">${esc(err.message)}</div></div>`; }
  }

  // ------------------------------------------------------------ form kit
  // fields: {k, label, type, options:[[value,label]], required, placeholder, hint, disabled, step, min, max, full}
  function form(fields, values = {}) {
    return `<div class="form-grid">${fields.map((f) => {
      const v = values[f.k] ?? f.value ?? "";
      const attrs = `name="${f.k}" ${f.required ? "required" : ""} ${f.disabled ? "disabled" : ""} ${f.placeholder ? `placeholder="${esc(f.placeholder)}"` : ""}`;
      let input;
      if (f.type === "select") input = `<select class="input" ${attrs}>${f.options.map(([ov, ol]) => `<option value="${esc(ov)}" ${String(ov) === String(v) ? "selected" : ""}>${esc(ol)}</option>`).join("")}</select>`;
      else if (f.type === "check") input = `<label class="check"><input type="checkbox" name="${f.k}" ${v ? "checked" : ""} ${f.disabled ? "disabled" : ""}> ${esc(t(f.text || f.label))}</label>`;
      else if (f.type === "checks") input = `<div class="check-grid">${f.options.map(([ov, ol]) => `<label class="check"><input type="checkbox" name="${f.k}" value="${ov}" ${(v || []).includes(ov) ? "checked" : ""}> ${esc(t(ol))}</label>`).join("")}</div>`;
      else if (f.type === "textarea") input = `<textarea class="input" rows="3" ${attrs}>${esc(v)}</textarea>`;
      else if (f.type === "typecards") input = `<div class="type-cards">${Object.entries(NODE_TYPES).map(([k, d]) => `<label class="type-card ${k}">
          <input type="radio" name="${f.k}" value="${k}" ${v === k ? "checked" : ""}><span class="tc-ico">${k === "control" ? ICONS.valve : ICONS.sensor}</span>
          <span class="tc-txt"><b>${esc(t(d.label))}</b><small>${esc(t(d.desc))}</small></span></label>`).join("")}</div>`;
      else input = `<input class="input ${f.mono ? "mono" : ""}" type="${f.type || "text"}" ${attrs} value="${esc(v)}" ${f.step ? `step="${f.step}"` : ""} ${f.min !== undefined ? `min="${f.min}"` : ""} ${f.max !== undefined ? `max="${f.max}"` : ""} ${f.maxlength ? `maxlength="${f.maxlength}"` : ""}>`;
      return `<div class="field ${f.full ? "full" : ""}">${f.type === "check" ? `<label>&nbsp;</label>` : `<label>${esc(t(f.label))}</label>`}${input}${f.hint ? `<div class="hint">${esc(t(f.hint))}</div>` : ""}</div>`;
    }).join("")}</div>`;
  }
  function read(formEl, fields) {
    const out = {};
    fields.forEach((f) => {
      if (f.disabled && !f.keep) return;
      if (f.type === "check") out[f.k] = formEl.querySelector(`[name="${f.k}"]`).checked;
      else if (f.type === "checks") out[f.k] = $$(`[name="${f.k}"]:checked`, formEl).map((i) => i.value);
      else if (f.type === "typecards") out[f.k] = formEl.querySelector(`[name="${f.k}"]:checked`)?.value || "monitoring";
      else {
        const raw = formEl.querySelector(`[name="${f.k}"]`).value.trim();
        out[f.k] = f.type === "number" ? (raw === "" ? null : +raw) : raw;
      }
    });
    return out;
  }
  const countryOptions = (blank) => [["", blank], ...COUNTRIES.map((c) => [c, `${countryName(c)} (${c})`]).sort((a, b) => a[1].localeCompare(b[1], I18N.lang))];
  const tzOptions = (blank) => [...(blank ? [["", blank]] : []), ...zones().map((z) => [z, z.replace(/_/g, " ")])];
  async function send(path, method, payload, ok) {
    try { const r = await api(path, { method, params: Q(), body: payload }); toast(t(ok), "ok"); return r; }
    catch (err) { toast(err.message, "error"); throw err; }
  }
  function editor(title, fields, values, { onSave, onDelete, deleteLabel = "Delete", note } = {}) {
    const box = $("#org-form", root);
    if (!canWrite || !box) return;
    box.innerHTML = `<header><h2><span class="ico">${ICONS.edit}</span>${esc(title)}</h2></header><form class="body" id="ed">${form(fields, values)}
      <div class="row" style="margin-top:6px"><button class="btn primary" type="submit">${t(values.__new ? "Create" : "Save changes")}</button>
      ${values.__new ? "" : `<button class="btn ghost" type="button" id="ed-new">${t("New")}</button>`}
      ${onDelete ? `<button class="btn danger" type="button" id="ed-del" style="margin-inline-start:auto">${t(deleteLabel)}</button>` : ""}</div>
      ${note ? `<p class="note">${note}</p>` : ""}</form>`;
    $("#ed", box).addEventListener("submit", async (e) => { e.preventDefault(); try { await onSave(read(e.target, fields)); } catch { /* toast shown */ } });
    $("#ed-new", box)?.addEventListener("click", () => show());
    $("#ed-del", box)?.addEventListener("click", async () => { if (confirm(t("Delete this entry? This cannot be undone."))) { try { await onDelete(); } catch { /* toast shown */ } } });
  }
  const layout = (left) => { body.innerHTML = `<div class="org-grid"><div class="org-main">${left}</div>${canWrite ? `<section class="panel org-form" id="org-form"></section>` : ""}</div>`; };

  // ============================================================ companies
  async function companies() {
    const rows = (await api("/org/companies")).companies;
    layout(`<section class="panel"><header><h2><span class="ico">${ICONS.org}</span>${t("Companies")}</h2><span class="meta">${rows.length}</span></header>
      <div class="table-wrap"><table class="data"><thead><tr><th>${t("Company")}</th><th>${t("Country")}</th><th>${t("Time zone")}</th><th>${t("Units")}</th><th>${t("Language")}</th>
      <th class="num">${t("Regions")}</th><th class="num">${t("Nodes")}</th><th>${t("Status")}</th></tr></thead><tbody>
      ${rows.map((c) => `<tr data-name="${esc(c.name)}" class="${c.name === state.company ? "sel" : ""} clickable">
        <td><b>${esc(c.display_name)}</b><div class="muted mono sm">${esc(c.name)}</div></td>
        <td>${c.country ? `${flag(c.country)} ${esc(countryName(c.country))}` : `<span class="muted">–</span>`}</td>
        <td class="mono sm">${esc(c.timezone)}<div class="muted">${localTime(c.timezone)}</div></td>
        <td>${t(c.units === "imperial" ? "Imperial" : "Metric")}</td><td>${c.language === "ar" ? "العربية" : "English"}</td>
        <td class="num">${c.registered_regions}</td><td class="num">${c.registered_nodes}</td>
        <td>${c.active ? badge(["good", "Active"]) : badge(["neutral", "Archived"])} ${c.strict_nodes ? badge(["info", "Strict"]) : ""}</td></tr>`).join("")}</tbody></table></div>
      <p class="note body">${esc(t("Company IDs are part of the MQTT topic (wiot/<company>/<region>/<node>/…) and cannot be renamed; the display name can change at any time. Archiving stops ingestion and hides the company but keeps its data."))}</p></section>`);
    const fields = (isNew, c = {}) => [
      { k: "name", label: "Company ID (MQTT)", required: true, disabled: !isNew, placeholder: "e.g. Nile_Farms", mono: true, maxlength: 80, hint: "Letters, digits, space, _ or -; used in MQTT topics" },
      { k: "display_name", label: "Display name", placeholder: "e.g. Nile Farms Co.", maxlength: 120 },
      { k: "country", label: "Country", type: "select", options: countryOptions(t("— not set —")) },
      { k: "timezone", label: "Time zone", type: "select", options: tzOptions() },
      { k: "units", label: "Units", type: "select", options: [["metric", t("Metric (m³, ha, °C)")], ["imperial", t("Imperial (gal, ac, °F)")]] },
      { k: "language", label: "Default language", type: "select", options: [["en", "English"], ["ar", "العربية"]] },
      { k: "lat", label: "Headquarters latitude", type: "number", step: "any", min: -90, max: 90 },
      { k: "lon", label: "Headquarters longitude", type: "number", step: "any", min: -180, max: 180 },
      { k: "strict_nodes", label: "Provisioning", type: "check", text: "Strict: accept data only from registered nodes" },
      ...(isNew || !sup ? [] : [{ k: "active", label: "Status", type: "check", text: "Active (uncheck to archive)" }]),
      { k: "notes", label: "Notes", type: "textarea", full: true, maxlength: 500 },
    ];
    const open = (c) => {
      const isNew = !c;
      const values = c ? { ...c, lat: c.lat ?? "", lon: c.lon ?? "" } : { __new: true, timezone: "Africa/Cairo", units: "metric", language: "en", country: "EG" };
      if (isNew && !sup) { $("#org-form", root).innerHTML = `<div class="empty">${t("Select your company to edit its profile.")}</div>`; return; }
      editor(isNew ? t("New company") : `${t("Edit")} · ${c.display_name}`, fields(isNew, c), values, {
        onSave: async (v) => {
          if (isNew) { await send("/org/companies", "POST", v, "Company created"); location.reload(); return; }
          const { name, ...changes } = v;
          await send(`/org/companies/${encodeURIComponent(c.name)}`, "PATCH", changes, "Company updated");
          if (c.name === state.company || changes.active === false) location.reload(); else companies();
        },
      });
    };
    $$("tr[data-name]", body).forEach((tr) => tr.addEventListener("click", () => open(rows.find((r) => r.name === tr.dataset.name))));
    open(sup ? null : rows.find((r) => r.name === state.company));
  }

  // ============================================================== regions
  async function regions() {
    const d = await api("/org/regions", { params: Q() });
    layout(`<section class="panel"><header><h2><span class="ico">${ICONS.region}</span>${t("Regions")} · ${esc(d.company)}</h2><span class="meta">${d.regions.length}</span></header>
      <div class="table-wrap"><table class="data"><thead><tr><th>${t("Region")}</th><th>${t("Country")}</th><th>${t("Time zone")}</th><th>${t("Location")}</th><th class="num">${t("Registered nodes")}</th><th class="num">${t("Online")}</th></tr></thead><tbody>
      ${d.regions.length ? d.regions.map((r) => `<tr data-r="${esc(r.region)}" class="clickable"><td><b>${esc(r.display_name || r.region)}</b><div class="muted mono sm">${esc(r.region)}</div></td>
        <td>${r.country ? `${flag(r.country)} ${esc(countryName(r.country))}` : `<span class="muted">${t("company default")}</span>`}</td>
        <td class="mono sm">${esc(r.timezone || "") || `<span class="muted">${t("company default")}</span>`}</td><td>${where(r.lat, r.lon)}</td>
        <td class="num">${r.registered_nodes}</td><td class="num">${r.online}/${r.seen_nodes}</td></tr>`).join("") : `<tr><td colspan="6"><div class="empty">${t("No regions registered yet.")}</div></td></tr>`}
      </tbody></table></div></section>
      ${d.discovered.length ? `<section class="panel" style="margin-top:16px"><header><h2><span class="ico">${ICONS.node}</span>${t("Discovered in telemetry")}</h2><span class="meta">${d.discovered.length}</span></header>
        <div class="table-wrap"><table class="data"><thead><tr><th>${t("Region")}</th><th class="num">${t("Nodes seen")}</th><th class="num">${t("Online")}</th><th></th></tr></thead><tbody>
        ${d.discovered.map((r) => `<tr><td class="mono">${esc(r.region)}</td><td class="num">${r.seen_nodes}</td><td class="num">${r.online}</td>
          <td class="num">${canWrite ? `<button class="btn sm" data-reg="${esc(r.region)}">${t("Register")}</button>` : ""}</td></tr>`).join("")}</tbody></table></div></section>` : ""}`);
    const fields = (isNew) => [
      { k: "region", label: "Region ID (MQTT)", required: true, disabled: !isNew, mono: true, placeholder: "e.g. Delta_North", maxlength: 40, hint: "Letters, digits, _ or -; used in MQTT topics" },
      { k: "display_name", label: "Display name", placeholder: "e.g. Delta North", maxlength: 80 },
      { k: "country", label: "Country", type: "select", options: countryOptions(t("— company default —")) },
      { k: "timezone", label: "Time zone", type: "select", options: tzOptions(t("— company default —")) },
      { k: "lat", label: "Latitude", type: "number", step: "any", min: -90, max: 90 },
      { k: "lon", label: "Longitude", type: "number", step: "any", min: -180, max: 180 },
      { k: "notes", label: "Notes", type: "textarea", full: true, maxlength: 500 },
    ];
    const open = (r, preset) => editor(r ? `${t("Edit")} · ${r.display_name || r.region}` : t("New region"), fields(!r), r ? { ...r, lat: r.lat ?? "", lon: r.lon ?? "" } : { __new: true, region: preset || "" }, {
      onSave: async (v) => {
        if (!r) await send("/org/regions", "POST", v, "Region created");
        else await send(`/org/regions/${encodeURIComponent(r.region)}`, "PATCH", v, "Region updated");
        regions();
      },
      onDelete: r ? async () => { await send(`/org/regions/${encodeURIComponent(r.region)}`, "DELETE", undefined, "Region removed"); regions(); } : null,
      note: t("Removing a region only removes its registration; stored telemetry is kept."),
    });
    $$("tr[data-r]", body).forEach((tr) => tr.addEventListener("click", () => open(d.regions.find((x) => x.region === tr.dataset.r))));
    $$("[data-reg]", body).forEach((b) => b.addEventListener("click", () => open(null, b.dataset.reg)));
    open(null);
  }

  // ================================================================ nodes
  async function nodes() {
    const [d, rg, gw] = await Promise.all([api("/org/nodes", { params: Q() }), api("/org/regions", { params: Q() }), api("/org/gateways", { params: Q() })]);
    const regionIds = [...new Set([...rg.regions.map((r) => r.region), ...rg.discovered.map((r) => r.region), ...state.regions])].sort();
    let filter = "", regionFilter = "", typeFilter = "";
    const status = (n) => (n.link_state === "pending" ? badge(["neutral", "Awaiting first uplink"]) : badge(LINK_BADGE[n.link_state] || ["neutral", n.link_state || "–"]));
    layout(`<section class="panel"><header><h2><span class="ico">${ICONS.node}</span>${t("Registered nodes")} · ${esc(d.company)}</h2>
        <span class="meta">${d.strict_nodes ? badge(["info", "Strict provisioning"]) : badge(["neutral", "Open provisioning"])}</span></header>
      <div class="body row org-toolbar"><input class="input grow" id="n-q" placeholder="${t("Search name, ID or gateway")}">
        <select class="input" id="n-r" style="width:auto"><option value="">${t("All regions")}</option>${regionIds.map((r) => `<option>${esc(r)}</option>`).join("")}</select>
        <select class="input" id="n-t" style="width:auto"><option value="">${t("All types")}</option>${Object.entries(NODE_TYPES).map(([k, d]) => `<option value="${k}">${esc(t(d.label))}</option>`).join("")}</select>
        <a class="btn" href="/api/v2/org/nodes/export.csv?company=${encodeURIComponent(state.company)}">${ICONS.download}${t("Export CSV")}</a></div>
      <div class="table-wrap" style="max-height:520px"><table class="data"><thead><tr><th>${t("Node")}</th><th>${t("Name")}</th><th>${t("Type")}</th><th>${t("Sensors")}</th><th>${t("Region")}</th><th>${t("Gateway")}</th><th>${t("Status")}</th><th>${t("Last seen")}</th></tr></thead>
      <tbody id="n-rows"></tbody></table></div></section>
      ${d.discovered.length ? `<section class="panel" style="margin-top:16px"><header><h2><span class="ico">${ICONS.node}</span>${t("Discovered in telemetry · not registered")}</h2><span class="meta">${d.discovered.length}</span></header>
        <div class="table-wrap" style="max-height:300px"><table class="data"><thead><tr><th>${t("Node")}</th><th>${t("Region")}</th><th>${t("Sensors detected")}</th><th>${t("Status")}</th><th>${t("First seen")}</th><th>${t("Last seen")}</th><th></th></tr></thead><tbody>
        ${d.discovered.map((n, i) => `<tr><td class="mono">${n.node_id}</td><td class="mono">${esc(n.region)}</td><td class="wrap">${sensorChips(n.sensors_detected)}</td><td>${status(n)}</td><td class="sm">${n.first_seen ? fmtDateTime(n.first_seen) : "–"}</td><td class="sm">${ago(n.last_seen)}</td>
          <td class="num">${canWrite ? `<button class="btn sm" data-disc="${i}">${t("Register")}</button>` : ""}</td></tr>`).join("")}</tbody></table></div></section>` : ""}
      ${canWrite ? `<section class="panel" style="margin-top:16px"><header><h2><span class="ico">${ICONS.upload}</span>${t("Bulk import (CSV)")}</h2></header><div class="body">
        <p class="note" style="margin-top:0">${t("Columns")}: <span class="mono">region,node_id,name,type,sensors,lat,lon,gateway,install_date,report_interval_s,notes</span> (type = monitoring | control; sensors = hnda|sondas|tuf|supmea) — ${t("existing nodes are updated, new ones created.")}</p>
        <div class="row"><input type="file" id="csv-file" accept=".csv,text/csv" class="input grow"><button class="btn primary" id="csv-go">${t("Import")}</button></div>
        <div id="csv-out"></div></div></section>` : ""}`);
    const paint = () => {
      const q = filter.toLowerCase();
      const rows = d.nodes.filter((n) => (!regionFilter || n.region === regionFilter) && (!typeFilter || n.node_type === typeFilter)
        && (!q || `${n.node_id} ${n.name} ${n.gateway || ""}`.toLowerCase().includes(q)));
      $("#n-rows", body).innerHTML = rows.length ? rows.map((n) => `<tr class="clickable" data-k="${esc(n.region)}|${n.node_id}"><td class="mono">${n.node_id}</td><td><b>${esc(n.name)}</b>${n.lat !== null && n.lat !== undefined ? `<div class="muted mono sm">${(+n.lat).toFixed(4)}, ${(+n.lon).toFixed(4)}</div>` : ""}</td>
        <td>${typeBadge(n.node_type)}</td><td class="wrap">${sensorChips(n.sensors)}</td>
        <td class="mono">${esc(n.region)}</td><td class="mono">${esc(n.gateway || "–")}</td><td>${status(n)}</td><td class="sm">${n.last_seen ? ago(n.last_seen) : "–"}</td></tr>`).join("")
        : `<tr><td colspan="8"><div class="empty">${t(d.nodes.length ? "No nodes match the filter." : "No nodes registered yet — register discovered nodes below or add one.")}</div></td></tr>`;
      $$("tr[data-k]", body).forEach((tr) => tr.addEventListener("click", () => { const [r, id] = tr.dataset.k.split("|"); open(d.nodes.find((n) => n.region === r && n.node_id === +id)); }));
    };
    $("#n-q", body).addEventListener("input", (e) => { filter = e.target.value; paint(); });
    $("#n-r", body).addEventListener("change", (e) => { regionFilter = e.target.value; paint(); });
    $("#n-t", body).addEventListener("change", (e) => { typeFilter = e.target.value; paint(); });
    paint();
    const fields = (isNew) => [
      { k: "region", label: "Region", type: "select", options: regionIds.map((r) => [r, r]), disabled: !isNew, keep: false },
      { k: "node_id", label: "Node ID", type: "number", min: 1, max: 65535, required: true, disabled: !isNew },
      { k: "name", label: "Name", placeholder: "e.g. Pivot 12 probe", maxlength: 80 },
      { k: "node_type", label: "Node type", type: "typecards", full: true },
      { k: "sensors", label: "Sensors fitted", type: "checks", options: Object.entries(SENSORS).map(([k, s]) => [k, s.label]), full: true,
        hint: "Detected automatically from the node's sensor mask when it has reported." },
      { k: "gateway", label: "Gateway", type: "select", options: [["", t("— none —")], ...gw.gateways.map((g) => [g.gw_id, `${g.gw_id} · ${g.name}`])] },
      { k: "report_interval_s", label: "Expected report interval (s)", type: "number", min: 5, max: 604800 },
      { k: "lat", label: "Latitude", type: "number", step: "any", min: -90, max: 90 },
      { k: "lon", label: "Longitude", type: "number", step: "any", min: -180, max: 180 },
      { k: "install_date", label: "Install date", type: "date" },
      ...(isNew ? [] : [{ k: "new_region", label: "Move to region", type: "select", options: regionIds.map((r) => [r, r]) }]),
      { k: "notes", label: "Notes", type: "textarea", full: true, maxlength: 500 },
    ];
    const open = (n, preset) => {
      const isNew = !n;
      const values = n ? { ...n, sensors: n.sensors?.length ? n.sensors : (n.sensors_detected || []), lat: n.lat ?? "", lon: n.lon ?? "", gateway: n.gateway || "",
        report_interval_s: n.report_interval_s ?? "", new_region: n.region }
        : { __new: true, node_type: "monitoring", sensors: preset?.sensors_detected || [], region: preset?.region || state.region || regionIds[0],
            node_id: preset?.node_id ?? "", name: preset ? `Node ${preset.node_id}` : "" };
      editor(n ? `${t("Edit")} · ${t("Node")} ${n.node_id}` : t("Register node"), fields(isNew), values, {
        onSave: async (v) => {
          if (isNew) await send("/org/nodes", "POST", v, "Node registered");
          else await send(`/org/nodes/${encodeURIComponent(n.region)}/${n.node_id}`, "PATCH", v, "Node updated");
          nodes();
        },
        onDelete: n ? async () => { await send(`/org/nodes/${encodeURIComponent(n.region)}/${n.node_id}`, "DELETE", undefined, "Node unregistered"); nodes(); } : null,
        deleteLabel: "Unregister",
        note: t("Unregistering keeps the node's stored data. With strict provisioning on, its new data is rejected."),
      });
    };
    $$("[data-disc]", body).forEach((b) => b.addEventListener("click", () => open(null, d.discovered[+b.dataset.disc])));
    $("#csv-go", body)?.addEventListener("click", async () => {
      const file = $("#csv-file", body).files[0];
      if (!file) { toast(t("Choose a CSV file first"), "error"); return; }
      try {
        const r = await api("/org/nodes/import", { method: "POST", params: Q(), body: { csv: await file.text() } });
        toast(`${t("Imported")}: ${r.created} ${t("new")}, ${r.updated} ${t("updated")}`, r.errors.length ? "" : "ok");
        if (r.errors.length) $("#csv-out", body).innerHTML = `<div class="note">${r.errors.map((e) => `${t("Line")} ${e.line}: ${esc(e.error)}`).join("<br>")}</div>`;
        else nodes();
      } catch (err) { toast(err.message, "error"); }
    });
    open(null);
  }

  // ============================================================= gateways
  async function gateways() {
    const [d, rg] = await Promise.all([api("/org/gateways", { params: Q() }), api("/org/regions", { params: Q() })]);
    const regionIds = [...new Set([...rg.regions.map((r) => r.region), ...state.regions])].sort();
    layout(`<section class="panel"><header><h2><span class="ico">${ICONS.tower}</span>${t("Gateways")} · ${esc(d.company)}</h2><span class="meta">${d.gateways.length}</span></header>
      <div class="table-wrap"><table class="data"><thead><tr><th>${t("Gateway")}</th><th>${t("Region")}</th><th>${t("Backhaul")}</th><th>${t("Primary")}</th><th class="num">${t("Nodes")}</th><th>${t("Location")}</th></tr></thead><tbody>
      ${d.gateways.length ? d.gateways.map((g) => `<tr class="clickable" data-g="${esc(g.gw_id)}"><td><b>${esc(g.name)}</b><div class="muted mono sm">${esc(g.gw_id)}</div></td><td class="mono">${esc(g.region || "–")}</td>
        <td>${g.backhaul.map((b) => `<span class="chip">${esc(t(BACKHAUL[b] || b))}</span>`).join(" ")}</td><td>${badge(["good", BACKHAUL[g.primary] || g.primary])}</td><td class="num">${g.nodes}</td><td>${where(g.lat, g.lon)}</td></tr>`).join("")
        : `<tr><td colspan="6"><div class="empty">${t("No gateways registered yet.")}</div></td></tr>`}</tbody></table></div>
      <p class="note body">${t("A gateway forwards LoRa node traffic to the server over its backhaul. Satellite-ready gateways can switch from cellular to satellite IoT without firmware changes.")}</p></section>`);
    const fields = (isNew) => [
      { k: "gw_id", label: "Gateway ID", required: true, disabled: !isNew, mono: true, placeholder: "e.g. GW-01", maxlength: 32 },
      { k: "name", label: "Name", placeholder: "e.g. Pump station gateway", maxlength: 80 },
      { k: "region", label: "Region", type: "select", options: [["", t("— none —")], ...regionIds.map((r) => [r, r])] },
      { k: "backhaul", label: "Backhaul links", type: "checks", options: Object.entries(BACKHAUL) },
      { k: "primary", label: "Primary backhaul", type: "select", options: Object.entries(BACKHAUL).filter(([k]) => k !== "lora").map(([k, l]) => [k, t(l)]) },
      { k: "lat", label: "Latitude", type: "number", step: "any", min: -90, max: 90 },
      { k: "lon", label: "Longitude", type: "number", step: "any", min: -180, max: 180 },
      { k: "notes", label: "Notes", type: "textarea", full: true, maxlength: 500 },
    ];
    const open = (g) => editor(g ? `${t("Edit")} · ${g.name}` : t("New gateway"), fields(!g),
      g ? { ...g, lat: g.lat ?? "", lon: g.lon ?? "", region: g.region || "" } : { __new: true, backhaul: ["lora", "cellular", "satellite"], primary: "cellular", region: state.region }, {
        onSave: async (v) => {
          if (!g) await send("/org/gateways", "POST", v, "Gateway created");
          else await send(`/org/gateways/${encodeURIComponent(g.gw_id)}`, "PATCH", v, "Gateway updated");
          gateways();
        },
        onDelete: g ? async () => { await send(`/org/gateways/${encodeURIComponent(g.gw_id)}`, "DELETE", undefined, "Gateway removed"); gateways(); } : null,
      });
    $$("tr[data-g]", body).forEach((tr) => tr.addEventListener("click", () => open(d.gateways.find((x) => x.gw_id === tr.dataset.g))));
    open(null);
  }

  // ========================================================= integrations
  async function integrations() {
    const [tk, wh] = await Promise.all([api("/org/tokens", { params: Q() }), api("/org/webhooks", { params: Q() })]);
    const origin = location.origin;
    body.innerHTML = `<div class="grid g-2">
      <section class="panel"><header><h2><span class="ico">${ICONS.key}</span>${t("API tokens")} · ${esc(tk.company)}</h2><span class="meta">${tk.tokens.filter((x) => !x.revoked_at).length} ${t("active")}</span></header>
        <div class="table-wrap"><table class="data"><thead><tr><th>${t("Name")}</th><th>${t("Token")}</th><th>${t("Scope")}</th><th>${t("Last used")}</th><th>${t("Expires")}</th><th></th></tr></thead><tbody>
        ${tk.tokens.length ? tk.tokens.map((x) => `<tr class="${x.revoked_at ? "dim" : ""}"><td><b>${esc(x.name)}</b><div class="muted sm">${esc(x.created_by)} · ${fmtDateTime(x.created_at)}</div></td>
          <td class="mono sm">${esc(x.prefix)}…</td><td>${badge(x.scope === "write" ? ["warning", "Read & write"] : ["info", "Read only"])}</td><td class="sm">${x.last_used_at ? ago(x.last_used_at) : t("never")}</td>
          <td class="sm">${x.expires_at ? fmtDateTime(x.expires_at).slice(0, 10) : t("never")}</td>
          <td class="num">${x.revoked_at ? badge(["neutral", "Revoked"]) : `<button class="btn sm danger" data-revoke="${x.id}">${t("Revoke")}</button>`}</td></tr>`).join("")
          : `<tr><td colspan="6"><div class="empty">${t("No API tokens yet.")}</div></td></tr>`}</tbody></table></div>
        <form class="body" id="tk-form"><div class="section-title">${t("Create token")}</div>${form([
          { k: "name", label: "Name", required: true, placeholder: "e.g. ERP integration", maxlength: 80 },
          { k: "scope", label: "Scope", type: "select", options: [["read", t("Read only")], ["write", t("Read & write (commands, registry)")]] },
          { k: "expires_days", label: "Expires after (days)", type: "number", min: 1, max: 3650, placeholder: t("never") }])}
          <button class="btn primary" type="submit">${t("Create token")}</button><div id="tk-out"></div>
          <p class="note">${t("Use it as")} <span class="mono">Authorization: Bearer wiot_…</span> ${t("on any /api/v2 endpoint. It is scoped to this company and can never manage users, tokens or webhooks.")} <a href="/api/docs" target="_blank" rel="noopener">${t("API reference")}</a></p></form></section>
      <section class="panel"><header><h2><span class="ico">${ICONS.hook}</span>${t("Webhooks")} · ${esc(wh.company)}</h2><span class="meta">${wh.webhooks.length}</span></header>
        <div class="table-wrap"><table class="data"><thead><tr><th>${t("Name")}</th><th>${t("Events")}</th><th>${t("Last delivery")}</th><th class="num">${t("Sent / failed")}</th><th></th></tr></thead><tbody>
        ${wh.webhooks.length ? wh.webhooks.map((x) => `<tr><td><b>${esc(x.name)}</b> ${x.active ? "" : badge(["neutral", "Paused"])}<div class="muted mono sm url">${esc(x.url)}</div></td>
          <td class="sm">${x.events.map((e) => `<span class="chip">${esc(e)}</span>`).join(" ")}</td>
          <td class="sm">${x.last_delivery_at ? `${x.last_error ? badge(["critical", x.last_status ? `HTTP ${x.last_status}` : "Failed"]) : badge(["good", `HTTP ${x.last_status}`])}<div class="muted">${ago(x.last_delivery_at)}</div>` : `<span class="muted">${t("never")}</span>`}</td>
          <td class="num">${x.deliveries} / ${x.failures}</td>
          <td class="num nowrap"><button class="btn sm" data-test="${x.id}">${t("Test")}</button> <button class="btn sm" data-edit="${x.id}">${t("Edit")}</button></td></tr>`).join("")
          : `<tr><td colspan="5"><div class="empty">${t("No webhooks yet.")}</div></td></tr>`}</tbody></table></div>
        <div class="body" id="wh-box"></div></section></div>`;

    $$("[data-revoke]", body).forEach((b) => b.addEventListener("click", async () => {
      if (!confirm(t("Revoke this token? Systems using it will stop working immediately."))) return;
      await send(`/org/tokens/${b.dataset.revoke}`, "DELETE", undefined, "Token revoked").catch(() => {});
      integrations();
    }));
    $("#tk-form", body).addEventListener("submit", async (e) => {
      e.preventDefault();
      const v = read(e.target, [{ k: "name" }, { k: "scope" }, { k: "expires_days", type: "number" }]);
      try {
        const r = await api("/org/tokens", { method: "POST", params: Q(), body: v });
        $("#tk-out", body).innerHTML = `<div class="secret-box"><b>${t("Copy this token now — it will not be shown again.")}</b>
          <div class="row nowrap"><input class="input mono" readonly value="${esc(r.token)}" id="tk-val"><button class="btn sm" type="button" id="tk-copy">${t("Copy")}</button></div>
          <pre class="mono sm">curl -H "Authorization: Bearer ${esc(r.token)}" ${esc(origin)}/api/v2/fleet</pre>
          <button class="btn sm" type="button" id="tk-done">${t("Done")}</button></div>`;
        $("#tk-copy", body).addEventListener("click", () => navigator.clipboard?.writeText(r.token).then(() => toast(t("Copied"), "ok")));
        $("#tk-done", body).addEventListener("click", () => integrations());
      } catch (err) { toast(err.message, "error"); }
    });

    const hookFields = [
      { k: "name", label: "Name", required: true, placeholder: "e.g. Operations alerts", maxlength: 80 },
      { k: "url", label: "Endpoint URL (https://…)", required: true, placeholder: "https://example.com/wiot/webhook", full: true },
      { k: "events", label: "Events", type: "checks", options: Object.entries(EVENTS), full: true },
      { k: "active", label: "Status", type: "check", text: "Active" },
    ];
    const showSecret = (h) => `<div class="secret-box"><b>${t("Signing secret — copy it now, it will not be shown again.")}</b>
      <input class="input mono" readonly value="${esc(h.secret)}"><p class="note">${t("Verify each delivery:")} <span class="mono">X-WIOT-Signature = "sha256=" + HMAC_SHA256(secret, raw body)</span></p></div>`;
    const openHook = (h) => {
      const box = $("#wh-box", body);
      box.innerHTML = `<div class="section-title">${h ? `${t("Edit webhook")} · ${esc(h.name)}` : t("Add webhook")}</div><form id="wh-form">${form(hookFields, h || { active: true, events: ["alert", "automation"] })}
        <div class="row"><button class="btn primary" type="submit">${t(h ? "Save changes" : "Create")}</button>
        ${h ? `<button class="btn" type="button" id="wh-rot">${t("Rotate secret")}</button><button class="btn ghost" type="button" id="wh-new">${t("New")}</button><button class="btn danger" type="button" id="wh-del" style="margin-inline-start:auto">${t("Delete")}</button>` : ""}</div></form>
        <div id="wh-out"></div>${h ? `<div class="section-title" style="margin-top:14px">${t("Recent deliveries")}</div><div id="wh-log" class="sm"></div>` : ""}
        <p class="note">${t("Each delivery is an HTTPS POST with a JSON body {id, event, company, ts, data}, retried up to 3 times. Private network addresses are blocked in production.")}</p>`;
      $("#wh-form", box).addEventListener("submit", async (e) => {
        e.preventDefault();
        const v = read(e.target, hookFields);
        try {
          const r = await api(h ? `/org/webhooks/${h.id}` : "/org/webhooks", { method: h ? "PATCH" : "POST", params: Q(), body: v });
          toast(t(h ? "Webhook updated" : "Webhook created"), "ok");
          if (!h) { await integrations(); $("#wh-out", body).innerHTML = showSecret(r); } else integrations();
        } catch (err) { toast(err.message, "error"); }
      });
      $("#wh-new", box)?.addEventListener("click", () => openHook(null));
      $("#wh-rot", box)?.addEventListener("click", async () => { const r = await send(`/org/webhooks/${h.id}/rotate`, "POST", undefined, "Secret rotated").catch(() => null); if (r) $("#wh-out", box).innerHTML = showSecret(r); });
      $("#wh-del", box)?.addEventListener("click", async () => { if (confirm(t("Delete this webhook?"))) { await send(`/org/webhooks/${h.id}`, "DELETE", undefined, "Webhook deleted").catch(() => {}); integrations(); } });
      if (h) api(`/org/webhooks/${h.id}/deliveries`, { params: Q() }).then((r) => {
        $("#wh-log", box).innerHTML = r.deliveries.length ? r.deliveries.slice(0, 10).map((x) => `<div class="row nowrap"><span class="mono">${fmtDateTime(x.ts).slice(11)}</span>
          ${x.error ? badge(["critical", x.status ? `HTTP ${x.status}` : "Failed"]) : badge(["good", `HTTP ${x.status}`])}<span class="chip">${esc(x.event)}</span><span class="muted">${x.ms ?? "–"} ms ${esc(x.error || "")}</span></div>`).join("")
          : `<span class="muted">${t("No deliveries since the server started.")}</span>`;
      }).catch(() => {});
    };
    $$("[data-edit]", body).forEach((b) => b.addEventListener("click", () => openHook(wh.webhooks.find((x) => x.id === +b.dataset.edit))));
    $$("[data-test]", body).forEach((b) => b.addEventListener("click", async () => {
      b.disabled = true;
      try {
        const r = await api(`/org/webhooks/${b.dataset.test}/test`, { method: "POST", params: Q() });
        toast(r.error ? `${t("Test failed")}: ${r.error}` : `${t("Test delivered")} · HTTP ${r.status} · ${r.ms} ms`, r.error ? "error" : "ok");
      } catch (err) { toast(err.message, "error"); }
      integrations();
    }));
    openHook(null);
  }

  await show();
}
