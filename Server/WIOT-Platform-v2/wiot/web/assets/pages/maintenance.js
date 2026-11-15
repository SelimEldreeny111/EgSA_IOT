// Maintenance: work orders (from alerts or by hand) with notes and photos, assets and their calibration history.
import { api, state, ago, badge, toast, ICONS, $, $$ } from "../api.js";
import { esc, fmtNum, fmtDateTime } from "../charts.js";
import { formHtml, readForm } from "../forms.js";

const PRIO = { urgent: ["critical", "Urgent"], high: ["serious", "High"], normal: ["info", "Normal"], low: ["neutral", "Low"] };
const STATUS = { open: ["warning", "Open"], assigned: ["info", "Assigned"], in_progress: ["info", "In progress"], done: ["good", "Done"], cancelled: ["neutral", "Cancelled"] };
const KINDS = [["node", "WIOT node"], ["pump", "Pump"], ["valve", "Valve"], ["flow_meter", "Flow meter"], ["soil_probe", "Soil probe"],
  ["ec_probe", "EC probe"], ["gateway", "Gateway"], ["solar", "Solar panel / battery"], ["other", "Other"]];

export async function render(root) {
  const canWrite = state.user.permissions.command;
  const Q = () => ({ company: state.company });
  const prefill = JSON.parse(sessionStorage.getItem("wiot.newOrder") || "null");
  sessionStorage.removeItem("wiot.newOrder");
  let view = "active", orders = [], assets = [];
  root.innerHTML = `<div class="ops">
    <div class="ed-split">
      <section class="panel"><header><h2><span class="ico">${ICONS.edit}</span>Work orders</h2>
        <div class="seg" id="wo-view" style="margin-inline-start:auto"><button data-v="active" class="on">Active</button><button data-v="done">Done</button><button data-v="">All</button></div></header>
        <div class="table-wrap" style="max-height:480px"><table class="data"><thead><tr><th>#</th><th>Work order</th><th>Asset</th><th>Priority</th><th>Status</th><th>Assignee</th><th>Due</th></tr></thead><tbody id="wo-rows"></tbody></table></div></section>
      <section class="panel" id="wo-ed"></section>
    </div>
    <div class="ed-split">
      <section class="panel"><header><h2><span class="ico">${ICONS.chip}</span>Assets</h2></header>
        <div class="table-wrap" style="max-height:420px"><table class="data"><thead><tr><th>Asset</th><th>Kind</th><th>Serial</th><th>Installed</th><th class="num">Open orders</th><th>Next calibration</th></tr></thead><tbody id="as-rows"></tbody></table></div>
        <div class="body"><p class="note">Nodes appear here when they are commissioned or named in a work order. A calibration past its next due date opens an alert.</p></div></section>
      <section class="panel" id="as-ed"></section>
    </div>
  </div>`;

  const assetName = (id) => assets.find((a) => a.id === id)?.name || "";
  async function loadOrders() {
    orders = (await api("/maintenance/orders", { params: { ...Q(), status: view } })).orders;
    const today = new Date().toISOString().slice(0, 10);
    $("#wo-rows", root).innerHTML = orders.map((o) => `<tr class="clickable" data-o="${o.id}"><td class="mono">${o.id}</td><td><b>${esc(o.title)}</b><div class="nh-sub">${esc(ago(o.created_at))} by <span data-i18n-skip>${esc(o.created_by)}</span></div></td>
      <td data-i18n-skip>${esc(o.asset || "–")}</td><td>${badge(PRIO[o.priority])}</td><td>${badge(STATUS[o.status])}</td><td data-i18n-skip>${esc(o.assignee || "–")}</td>
      <td class="mono ${o.due && o.due < today && !["done", "cancelled"].includes(o.status) ? "nh-drift" : ""}">${esc(o.due || "–")}</td></tr>`).join("")
      || `<tr><td colspan="7"><div class="empty">No work orders here.</div></td></tr>`;
    $$("[data-o]", root).forEach((tr) => tr.addEventListener("click", () => openOrder(+tr.dataset.o)));
  }
  $$("#wo-view button", root).forEach((b) => b.addEventListener("click", () => { view = b.dataset.v; $$("#wo-view button", root).forEach((x) => x.classList.toggle("on", x === b)); loadOrders(); }));

  const newFields = () => [
    { k: "title", label: "Title", required: true, maxlength: 120, full: true },
    { k: "asset_id", label: "Asset", type: "select", options: [["", "— none —"], ...assets.map((a) => [String(a.id), a.name])] },
    { k: "node_id", label: "or node number", type: "number", min: 1, max: 65535 },
    { k: "priority", label: "Priority", type: "select", options: Object.entries(PRIO).map(([k, v]) => [k, v[1]]) },
    { k: "due", label: "Due date", type: "date" }, { k: "assignee", label: "Assignee", maxlength: 80 },
    { k: "description", label: "Description", type: "textarea", full: true, maxlength: 2000 },
  ];
  function newOrder(values = {}) {
    const box = $("#wo-ed", root);
    if (!canWrite) { box.innerHTML = `<div class="empty">Select a work order.</div>`; return; }
    const f = newFields();
    box.innerHTML = `<header><h2><span class="ico">${ICONS.edit}</span>New work order</h2></header><form class="body" id="wo-new">${formHtml(f, { priority: "normal", ...values })}
      <button class="btn primary" type="submit">Create work order</button></form>`;
    $("#wo-new", box).addEventListener("submit", async (e) => {
      e.preventDefault();
      const v = readForm(e.target, f);
      const body = { ...v, asset_id: v.asset_id ? +v.asset_id : null, node_id: v.node_id || null, region: state.region, alert_id: values.alert_id || null };
      Object.keys(body).forEach((k) => (body[k] === "" || body[k] === null) && delete body[k]);
      try { const o = await api("/maintenance/orders", { method: "POST", params: Q(), body }); toast("Work order created", "ok"); await Promise.all([loadOrders(), loadAssets()]); openOrder(o.id); }
      catch (err) { toast(err.message, "error"); }
    });
  }
  async function openOrder(id) {
    const o = await api(`/maintenance/orders/${id}`, { params: Q() });
    const box = $("#wo-ed", root);
    const photos = o.events.filter((e) => e.photo);
    box.innerHTML = `<header><h2><span class="ico">${ICONS.edit}</span>#${o.id} · ${esc(o.title)}</h2></header><div class="body">
      <div class="row" style="gap:8px;margin-bottom:10px">${badge(PRIO[o.priority])} ${badge(STATUS[o.status])} ${o.asset ? `<span class="dim" data-i18n-skip>${esc(o.asset)}</span>` : ""}</div>
      ${o.description ? `<p style="white-space:pre-wrap">${esc(o.description)}</p>` : ""}
      ${photos.length ? `<div class="wo-photos">${photos.map((p) => `<a href="/api/v2/maintenance/photos/${encodeURIComponent(p.photo)}?company=${encodeURIComponent(state.company)}" target="_blank" rel="noopener"><img alt="${esc(p.text || "photo")}" src="/api/v2/maintenance/photos/${encodeURIComponent(p.photo)}?company=${encodeURIComponent(state.company)}"></a>`).join("")}</div>` : ""}
      <div class="section-title" style="margin-top:12px">Timeline</div>
      <ul class="timeline">${o.events.map((e) => `<li>${esc(e.kind === "photo" ? `Photo${e.text ? `: ${e.text}` : ""}` : e.text || e.kind)}<small>${esc(fmtDateTime(e.ts))} · <span data-i18n-skip>${esc(e.actor)}</span></small></li>`).join("")}</ul>
      ${canWrite && !["done", "cancelled"].includes(o.status) ? `<form id="wo-upd" style="margin-top:14px"><div class="form-grid">
        <div class="field"><label for="wo-st">Status</label><select class="input" id="wo-st" name="status">${Object.entries(STATUS).map(([k, v]) => `<option value="${k}" ${k === o.status ? "selected" : ""}>${v[1]}</option>`).join("")}</select></div>
        <div class="field"><label for="wo-as">Assignee</label><input class="input" id="wo-as" name="assignee" value="${esc(o.assignee || "")}" maxlength="80"></div>
        <div class="field full"><label for="wo-note">Note (or what was done, to close)</label><textarea class="input" id="wo-note" name="note" rows="2" maxlength="2000"></textarea></div></div>
        <div class="row" style="gap:8px"><button class="btn primary" type="submit">Update</button>
        <label class="btn">${ICONS.upload}<span>Add photo</span><input type="file" id="wo-photo" accept="image/jpeg,image/png" capture="environment" hidden></label>
        <button class="btn ghost" type="button" id="wo-new-btn" style="margin-inline-start:auto">New</button></div></form>`
        : `${o.closure ? `<p class="note">Closure: ${esc(o.closure)}</p>` : ""}${canWrite ? `<button class="btn ghost" type="button" id="wo-new-btn">New work order</button>` : ""}`}
    </div>`;
    $("#wo-new-btn", box)?.addEventListener("click", () => newOrder());
    $("#wo-upd", box)?.addEventListener("submit", async (e) => {
      e.preventDefault();
      const st = e.target.status.value, note = e.target.note.value.trim();
      const body = { status: st, assignee: e.target.assignee.value.trim() || null, ...(["done", "cancelled"].includes(st) ? { closure: note } : note ? { note } : {}) };
      try { await api(`/maintenance/orders/${id}`, { method: "PATCH", params: Q(), body }); toast("Work order updated", "ok"); loadOrders(); openOrder(id); }
      catch (err) { toast(err.message, "error"); }
    });
    $("#wo-photo", box)?.addEventListener("change", async (e) => {
      const file = e.target.files[0]; if (!file) return;
      if (file.size > 2 * 1024 * 1024) { toast("Photos must be 2 MB or smaller", "error"); return; }
      try {
        const res = await api(`/maintenance/orders/${id}/photos`, { method: "POST", params: Q(), raw: true, body: undefined, rawBody: file });
        if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "Upload failed");
        toast("Photo added", "ok"); openOrder(id);
      } catch (err) { toast(err.message, "error"); }
    });
  }

  // ------------------------------------------------------------------ assets
  const assetFields = [
    { k: "name", label: "Name", required: true, maxlength: 80 }, { k: "kind", label: "Kind", type: "select", options: KINDS },
    { k: "serial", label: "Serial number", maxlength: 60 }, { k: "model", label: "Model", maxlength: 80 },
    { k: "installed", label: "Installed", type: "date" }, { k: "node_id", label: "Node number (WIOT nodes)", type: "number", min: 1, max: 65535 },
    { k: "notes", label: "Notes", type: "textarea", full: true, maxlength: 500 },
  ];
  const calFields = [
    { k: "date", label: "Date", type: "date", required: true }, { k: "method", label: "Method", maxlength: 120, placeholder: "e.g. bucket test, reference meter" },
    { k: "reference", label: "Reference value", type: "number", step: "any", required: true }, { k: "measured", label: "Measured value", type: "number", step: "any", required: true },
    { k: "unit", label: "Unit", maxlength: 20 }, { k: "tolerance_pct", label: "Tolerance (%)", type: "number", step: "0.1", min: 0, max: 100 },
    { k: "next_due", label: "Next calibration due", type: "date" }, { k: "notes", label: "Notes", maxlength: 500 },
  ];
  async function loadAssets() {
    assets = (await api("/maintenance/assets", { params: Q() })).assets;
    const today = new Date().toISOString().slice(0, 10);
    $("#as-rows", root).innerHTML = assets.map((a) => `<tr class="clickable" data-a="${a.id}"><td data-i18n-skip><b>${esc(a.name)}</b></td><td>${esc(KINDS.find((k) => k[0] === a.kind)?.[1] || a.kind)}</td>
      <td class="mono sm" data-i18n-skip>${esc(a.serial || "–")}</td><td class="mono sm">${esc(a.installed || "–")}</td><td class="num">${a.open_orders}</td>
      <td class="mono sm ${a.next_calibration && a.next_calibration < today ? "nh-drift" : ""}">${esc(a.next_calibration || "–")}</td></tr>`).join("")
      || `<tr><td colspan="6"><div class="empty">No assets yet.</div></td></tr>`;
    $$("[data-a]", root).forEach((tr) => tr.addEventListener("click", () => openAsset(assets.find((x) => x.id === +tr.dataset.a))));
  }
  async function openAsset(a) {
    const box = $("#as-ed", root);
    const recs = a ? (await api("/maintenance/records", { params: { ...Q(), asset_id: a.id } })).records : [];
    box.innerHTML = `<header><h2><span class="ico">${ICONS.edit}</span>${a ? esc(a.name) : "New asset"}</h2></header><div class="body">
      <form id="as-form">${formHtml(assetFields, a || { kind: "pump" })}${canWrite ? `<div class="row" style="gap:8px"><button class="btn primary" type="submit">${a ? "Save" : "Create asset"}</button>${a ? `<button class="btn ghost" type="button" id="as-new">New</button>` : ""}</div>` : ""}</form>
      ${a ? `<div class="section-title" style="margin-top:16px">History</div><ul class="timeline">${recs.map((r) => `<li>${esc(r.kind)}${r.kind === "calibration" ? ` · ${fmtNum(r.data.deviation_pct, 2)} % ${r.data.pass ? "(within tolerance)" : "(OUT of tolerance)"}` : ""}<small>${esc(r.date)} · <span data-i18n-skip>${esc(r.created_by)}</span>${r.next_due ? ` · next due ${esc(r.next_due)}` : ""}</small></li>`).join("") || `<li class="dim">No records yet.</li>`}</ul>
        ${canWrite ? `<div class="section-title" style="margin-top:16px">Record a calibration</div><form id="cal-form">${formHtml(calFields, { date: new Date().toISOString().slice(0, 10), tolerance_pct: 5 })}<button class="btn" type="submit">Save calibration</button></form>` : ""}` : ""}</div>`;
    $("#as-new", box)?.addEventListener("click", () => openAsset(null));
    $("#as-form", box).addEventListener("submit", async (e) => {
      e.preventDefault();
      const v = readForm(e.target, assetFields);
      try { const r = await api(a ? `/maintenance/assets/${a.id}` : "/maintenance/assets", { method: a ? "PATCH" : "POST", params: Q(), body: v }); toast("Asset saved", "ok"); await loadAssets(); openAsset(r); }
      catch (err) { toast(err.message, "error"); }
    });
    $("#cal-form", box)?.addEventListener("submit", async (e) => {
      e.preventDefault();
      try { const r = await api(`/maintenance/assets/${a.id}/calibrations`, { method: "POST", params: Q(), body: readForm(e.target, calFields) });
        toast(`Deviation ${fmtNum(r.deviation_pct, 2)} % — ${r.pass ? "within tolerance" : "out of tolerance"}`, r.pass ? "ok" : "error"); await loadAssets(); openAsset(a); }
      catch (err) { toast(err.message, "error"); }
    });
  }

  await loadAssets();
  await loadOrders();
  if (prefill) newOrder(prefill); else newOrder();
  openAsset(null);
  return undefined;
}
