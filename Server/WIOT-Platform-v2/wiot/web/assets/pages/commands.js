// Command center: compose with pre-send delivery risk, journal timeline, lifecycle drawer.
import { api, state, onEvent, scoped, ago, badge, STATE_BADGE, toast, ICONS, $, $$, h } from "../api.js";
import { esc, gauge, fmtDateTime, riskColor, PALETTE, T } from "../charts.js";

export function contributionsHtml(list, max) {
  if (!list?.length) return `<div class="muted" style="font-size:12px">No explanation available</div>`;
  const m = max || Math.max(...list.map((c) => Math.abs(c.shap)), 1e-6);
  return `<div class="contrib">${list.map((c) => {
    const w = (Math.abs(c.shap) / m) * 50, pos = c.shap >= 0;
    return `<div title="${esc(c.feature)}">${esc(c.label || c.feature)} <span class="muted mono" style="font-size:11px">= ${esc(typeof c.value === "number" ? +c.value.toFixed(3) : c.value)}</span></div>
      <div class="bar"><i style="left:${pos ? 50 : 50 - w}%;width:${Math.max(w, 0.5)}%;background:${pos ? PALETTE[0] : PALETTE[7]}"></i><i style="left:50%;width:1px;background:${T.muted}"></i></div>
      <div class="val">${pos ? "+" : ""}${c.shap.toFixed(2)}</div>`;
  }).join("")}</div><p class="note">SHAP contributions in log-odds: <span style="color:${PALETTE[0]}">blue</span> raises, <span style="color:${PALETTE[7]}">red</span> lowers the delivery probability.</p>`;
}

export async function render(root) {
  const canSend = state.user.permissions.command;
  const [catalog, fleetData] = await Promise.all([api("/commands/catalog"), api("/fleet", { params: scoped() })]);
  const cmds = catalog.commands, nodes = fleetData.nodes;
  let riskTimer = null;

  root.innerHTML = `
    <div class="grid g-cmd">
      <section class="panel">
        <header><h2><span class="ico">${ICONS.commands}</span>Compose command</h2><span class="meta">${esc(state.company)} · ${esc(state.region)}</span></header>
        <form class="body" id="cmd-form">
          ${canSend ? "" : `<p class="badge warning" style="margin-bottom:12px">Read-only role — commands disabled</p>`}
          <div class="form-grid">
            <div class="field"><label for="f-node">Target node</label><select class="input" id="f-node">${nodes.map((n) => `<option value="${n.node_id}">NODE-${String(n.node_id).padStart(3, "0")}${n.name ? ` · ${esc(n.name)}` : ""} · ${n.node_type === "control" ? "Control" : n.node_type === "monitoring" ? "Monitoring" : esc(n.power_mode_name)}</option>`).join("")}<option value="custom">Other node ID…</option></select></div>
            <div class="field hidden" id="f-node-custom-wrap"><label for="f-node-custom">Node ID</label><input class="input" id="f-node-custom" type="number" min="1" max="65535" value="1"></div>
            <div class="field"><label for="f-type">Command</label><select class="input" id="f-type">${["configuration", "diagnostics", "actuation", "power", "flash"].map((g) => `<optgroup label="${g}">${cmds.filter((c) => c.group === g).map((c) => `<option value="${c.type}">${esc(c.label)} (${c.type})</option>`).join("")}</optgroup>`).join("")}</select></div>
          </div>
          <div id="f-data-wrap"></div>
          <div class="field"><label>Delivery</label>
            <div class="seg" id="f-delivery"><button type="button" data-v="auto" class="on" title="Send now if the node is probably listening, otherwise queue it for the node's next wake">Auto</button><button type="button" data-v="now">Send now</button><button type="button" data-v="next_wake">Next wake</button></div></div>
          <label class="check" style="margin-bottom:12px"><input type="checkbox" id="f-bcast"> Broadcast to every node in ${esc(state.region)}</label>
          <p class="note" id="f-help" style="margin:0 0 12px"></p>
          <div class="section-title">Pre-send delivery risk</div>
          <div class="risk-box" id="risk"><div class="empty">Select a node</div></div>
          <div class="row" style="margin-top:14px"><div class="grow"></div><button class="btn primary" id="f-send" type="submit" ${canSend ? "" : "disabled"}>Send command</button></div>
        </form>
      </section>
      <section class="panel">
        <header><h2><span class="ico">${ICONS.history}</span>Command journal</h2><span class="meta" id="j-meta"></span></header>
        <div class="table-wrap" style="max-height:760px"><table class="data"><thead><tr><th>Request</th><th>Command</th><th>Node</th><th>Delivery</th><th>State</th><th class="num">ACK latency</th><th>Created</th><th>Operator</th></tr></thead><tbody id="journal"></tbody></table></div>
      </section>
    </div>`;

  const form = $("#cmd-form", root);
  let delivery = "auto";
  const nodeId = () => $("#f-node", root).value === "custom" ? +$("#f-node-custom", root).value : +$("#f-node", root).value;
  const spec = () => cmds.find((c) => c.type === $("#f-type", root).value);

  function paintData() {
    const c = spec(), wrap = $("#f-data-wrap", root);
    $("#f-help", root).textContent = c.help || (c.single_node ? "Targets a single node." : "");
    $("#f-bcast", root).disabled = !!c.single_node || delivery === "next_wake";
    if (c.data === "seconds" || c.data === "cursor") wrap.innerHTML = `<div class="field"><label for="f-data">${c.data === "cursor" ? "Resume cursor" : "Seconds"} ${c.min !== undefined ? `(${c.min}–${c.max ?? "∞"})` : ""}</label><input class="input" id="f-data" type="number" min="${c.min ?? 0}" ${c.max ? `max="${c.max}"` : ""} value="${c.default ?? 0}"></div>`;
    else if (c.data === "enum") wrap.innerHTML = `<div class="field"><label for="f-data">Value</label><select class="input" id="f-data">${c.options.map(([v, l]) => `<option value="${v}">${esc(l)}</option>`).join("")}</select></div>`;
    else wrap.innerHTML = `<p class="note" style="margin:0 0 12px">${c.data === "auto" ? "Data is filled by the server at dispatch." : "No data required."}</p>`;
    if (c.danger) wrap.insertAdjacentHTML("beforeend", `<p class="badge critical" style="margin-bottom:12px">Destructive: erases the node's flash log</p>`);
    checkType();
  }

  // Valve (actuation) commands need a control node; monitoring nodes only report sensors.
  function checkType() {
    const c = spec(), n = nodes.find((x) => x.node_id === nodeId()), btn = $("#f-send", root);
    const blocked = c.group === "actuation" && !$("#f-bcast", root).checked && n?.node_type === "monitoring";
    let warn = $("#f-type-warn", root);
    if (!warn) { warn = document.createElement("div"); warn.id = "f-type-warn"; $("#f-data-wrap", root).after(warn); }
    warn.innerHTML = blocked ? `<div class="advice dry" style="margin:0 0 12px"><span>${ICONS.sensor}</span><div><b>Monitoring node</b><br>NODE-${String(n.node_id).padStart(3, "0")} has sensors only. Valve commands need a control node — change its type on the Organization page if a valve is fitted.</div></div>` : "";
    btn.disabled = !canSend || blocked;
  }

  async function loadRisk() {
    const box = $("#risk", root);
    if ($("#f-bcast", root).checked) { box.innerHTML = `<div class="empty">Risk is scored per node; broadcasts are not scored</div>`; return; }
    try {
      const r = await api("/commands/risk", { method: "POST", body: { ...scoped(), node_id: nodeId(), cmd_type: spec().type } });
      const color = riskColor(r.tier);
      const advice = delivery === "auto"
        ? (r.tier === "UNLIKELY" ? "Auto: node is probably asleep — the command will wait for its next wake."
          : "Auto: node is probably listening — the command will be sent now.")
        : r.tier === "LIKELY" ? "Node is very likely listening — send now."
        : delivery === "now" ? "Node is probably asleep. Queue for its next wake window to avoid a lost command." : "Queued delivery waits for the node's next Status uplink.";
      box.innerHTML = `<div id="risk-g"></div><div>
          <div class="row" style="margin-bottom:6px">${badge([r.tier === "LIKELY" ? "good" : r.tier === "UNCERTAIN" ? "warning" : "critical", r.tier])}<span class="dim" style="font-size:12.5px">${esc(advice)}</span></div>
          ${contributionsHtml((r.contributions || []).slice(0, 5))}</div>`;
      gauge($("#risk-g", box), { value: r.probability, label: "P(delivered)", color });
      if (r.tier !== "LIKELY" && delivery === "now" && !spec().single_node) box.querySelector(".row").insertAdjacentHTML("beforeend", `<button type="button" class="btn sm" id="use-queue">Use next wake</button>`);
      $("#use-queue", box)?.addEventListener("click", () => setDelivery("next_wake"));
    } catch (err) {
      box.innerHTML = `<div class="empty">${err.status === 404 ? "Delivery-risk model not trained yet — run the analytics pipeline" : esc(err.message)}</div>`;
    }
  }
  const scheduleRisk = () => { clearTimeout(riskTimer); riskTimer = setTimeout(loadRisk, 250); };
  function setDelivery(v) {
    delivery = v; $$("#f-delivery button", root).forEach((b) => b.classList.toggle("on", b.dataset.v === v));
    if (v === "next_wake") $("#f-bcast", root).checked = false; paintData(); scheduleRisk();
  }
  $$("#f-delivery button", root).forEach((b) => b.addEventListener("click", () => setDelivery(b.dataset.v)));
  $("#f-node", root).addEventListener("change", (e) => { $("#f-node-custom-wrap", root).classList.toggle("hidden", e.target.value !== "custom"); checkType(); scheduleRisk(); });
  $("#f-node-custom", root).addEventListener("input", scheduleRisk);
  $("#f-type", root).addEventListener("change", () => { paintData(); scheduleRisk(); });
  $("#f-bcast", root).addEventListener("change", () => { checkType(); scheduleRisk(); });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const c = spec(), dataEl = $("#f-data", root);
    if (c.danger && !confirm(`${c.label}: this cannot be undone. Continue?`)) return;
    const body = { ...scoped(), node_id: nodeId(), cmd_type: c.type, delivery, broadcast: $("#f-bcast", root).checked };
    if (dataEl) body.cmd_data = Number(dataEl.value);
    const btn = $("#f-send", root); btn.disabled = true;
    try {
      const r = await api("/commands", { method: "POST", body });
      toast(`${c.type} #${r.request_id} ${r.queued ? "queued for next wake" : "submitted — awaiting node ACK"}`, "ok");
      loadJournal();
    } catch (err) { toast(err.message, "error"); } finally { btn.disabled = !canSend; checkType(); }
  });

  async function loadJournal() {
    const data = await api("/commands", { params: scoped({ limit: 100 }) });
    $("#j-meta", root).textContent = `${data.commands.length} latest`;
    $("#journal", root).innerHTML = data.commands.map((c) => {
      const lat = c.acknowledged_at && c.submitted_at ? `${c.acknowledged_at - c.submitted_at}s` : "–";
      return `<tr class="clickable" data-id="${c.request_id}" data-node="${c.node_id}"><td class="mono">#${c.request_id}</td><td class="mono">${esc(c.cmd_type)}</td>
        <td class="mono">${c.broadcast ? "ALL" : c.node_id}</td><td>${c.delivery === "now" ? "now" : "next wake"}</td><td>${badge(STATE_BADGE[c.state] || ["neutral", c.state])}</td>
        <td class="num">${lat}</td><td class="dim">${ago(c.created_at)}</td><td class="dim">${esc(c.actor || "–")}</td></tr>`;
    }).join("") || `<tr><td colspan="8"><div class="empty">No commands yet</div></td></tr>`;
    $$("#journal tr[data-id]", root).forEach((tr) => tr.addEventListener("click", () => openDrawer(+tr.dataset.id, +tr.dataset.node)));
  }

  async function openDrawer(id, node) {
    const c = await api(`/commands/${id}`, { params: scoped({ node_id: node }) });
    const ev = new Set(c.events.map((e) => e.event));
    const fail = c.state === "rejected" || c.state === "outcome_unknown" || c.state === "expired";
    const steps = [["accepted", "Accepted"], ["submitted", "Published"], ["broker_confirmed", "Broker PUBACK"], ["node_ack", fail ? "Node reply" : "Node ACK"]];
    const bg = h(`<div class="drawer-bg"></div>`), dr = h(`<aside class="drawer" role="dialog" aria-label="Command detail">
      <div class="row"><h2 style="margin:0;font:600 16px var(--mono)">${esc(c.cmd_type)} #${c.request_id}</h2><div class="grow"></div><button class="btn sm ghost" id="x">Close</button></div>
      <div style="margin:8px 0 14px">${badge(STATE_BADGE[c.state] || ["neutral", c.state])} <span class="dim" style="font-size:12.5px">${esc(c.reason || "")}</span></div>
      <div class="steps">${steps.map(([k, l], i) => `<div class="st ${ev.has(k) ? "done" : i === 3 && fail ? "fail" : ""}"><i></i>${l}</div>`).join("")}</div>
      <dl class="kv" style="margin-top:18px"><dt>Company / region</dt><dd>${esc(c.company)} / ${esc(c.region)}</dd><dt>Target</dt><dd>${c.broadcast ? "broadcast" : "node " + c.node_id}</dd>
        <dt>Data</dt><dd>${c.cmd_data}</dd><dt>Delivery</dt><dd>${esc(c.delivery)}</dd><dt>Operator</dt><dd>${esc(c.actor || "–")}</dd>
        <dt>Created</dt><dd>${fmtDateTime(c.created_at)}</dd><dt>Expires</dt><dd>${fmtDateTime(c.expires_at)}</dd><dt>Attempts</dt><dd>${c.attempts}</dd></dl>
      <div class="section-title" style="margin-top:18px">Event journal</div>
      <table class="data"><tbody>${c.events.map((e) => `<tr><td class="mono dim">${fmtDateTime(e.timestamp)}</td><td class="mono">${esc(e.event)}</td><td class="dim">${esc(e.details)}</td></tr>`).join("")}</tbody></table>
      ${c.receipts.length ? `<div class="section-title" style="margin-top:18px">Receipts</div><table class="data"><tbody>${c.receipts.map((r) => `<tr><td class="mono">node ${r.node_id}</td><td>${r.success ? "success" : "rejected"}</td><td>${r.late ? "late" : "on time"}</td><td class="mono dim">${fmtDateTime(r.received_at)}</td></tr>`).join("")}</tbody></table>` : ""}
    </aside>`);
    const close = () => { bg.remove(); dr.remove(); };
    bg.addEventListener("click", close); $("#x", dr).addEventListener("click", close);
    document.body.append(bg, dr);
  }

  const off = onEvent((m) => { if (m.type === "command" && m.company === state.company) loadJournal(); });
  paintData(); loadJournal(); scheduleRisk();
  return () => { off(); clearTimeout(riskTimer); };
}
