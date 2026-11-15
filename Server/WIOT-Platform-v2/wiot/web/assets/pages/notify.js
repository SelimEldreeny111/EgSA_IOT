// Rules & notifications: custom threshold alerts and where alerts are sent (e-mail, Telegram, SMS, WhatsApp, Teams).
import { api, state, ago, badge, toast, ICONS, $, $$ } from "../api.js";
import { esc, fmtNum, fmtDateTime } from "../charts.js";
import { formHtml, readForm } from "../forms.js";

const METRIC_LABEL = {
  flow: "Flow (m³/h)", velocity: "Velocity (m/s)", battery_voltage: "Battery (V)", soil_temperature: "Soil temperature (°C)",
  soil_moisture: "Soil moisture (%)", ec_temperature: "EC probe temperature (°C)", ec_moisture: "EC probe moisture (%)",
  electrical_conductivity: "Salinity, EC (µS/cm)", flow_day: "Water today (m³)", silent_minutes: "Minutes since last uplink",
};
const KIND_LABEL = { email: "E-mail", telegram: "Telegram", sms: "SMS", whatsapp: "WhatsApp", teams: "Microsoft Teams" };
const EVENTS = [["alert", "Alert opened"], ["resolved", "Alert resolved"], ["report", "Monthly report"]];

export async function render(root) {
  const canWrite = state.user.permissions.command;
  const Q = () => ({ company: state.company });
  const cat = await api("/alert-rules/catalog");
  root.innerHTML = `<div class="ops">
    <div class="ed-split">
      <section class="panel"><header><h2><span class="ico">${ICONS.bell}</span>Alert rules</h2><span class="meta" id="r-meta"></span></header>
        <div class="table-wrap"><table class="data"><thead><tr><th>Rule</th><th>Condition</th><th>Nodes</th><th>Severity</th><th>Status</th></tr></thead><tbody id="r-rows"></tbody></table></div>
        <div class="body"><p class="note">Rules run with the built-in checks once a minute on each node's latest valid reading. An alert opens when the condition holds for the set duration and clears when the reading is back within the limit. Alerts from rules appear on the Alerts page, go to webhooks and to the channels below.</p></div></section>
      ${canWrite ? `<section class="panel" id="r-editor"></section>` : ""}
    </div>
    ${canWrite ? `<div class="ed-split">
      <section class="panel"><header><h2><span class="ico">${ICONS.hook}</span>Notification channels</h2><span class="meta" id="c-meta"></span></header>
        <div class="table-wrap"><table class="data"><thead><tr><th>Channel</th><th>Sends</th><th>Last delivery</th><th>Status</th></tr></thead><tbody id="c-rows"></tbody></table></div>
        <div class="body"><p class="note">At most 20 messages per channel in 10 minutes; further alerts are summarised in the next message, so a site-wide outage cannot flood a phone. Secrets (bot tokens, API keys) are stored encrypted and never shown again.</p></div></section>
      <section class="panel" id="c-editor"></section></div>` : ""}
  </div>`;

  // ------------------------------------------------------------------ rules
  let rules = [];
  const ruleFields = [
    { k: "name", label: "Rule name", required: true, maxlength: 80, placeholder: "e.g. Soil too dry in P-12", full: true },
    { k: "metric", label: "Reading", type: "select", options: Object.keys(cat.metrics).map((m) => [m, METRIC_LABEL[m] || m]) },
    { k: "op", label: "Condition", type: "select", options: cat.ops.map((o) => [o, { "<": "below", "<=": "at or below", ">": "above", ">=": "at or above" }[o]]) },
    { k: "value", label: "Threshold", type: "number", step: "any", required: true },
    { k: "duration_min", label: "For at least (minutes)", type: "number", min: 0, max: 10080, value: 0 },
    { k: "nodes", label: "Nodes (empty = every node)", placeholder: "e.g. 2, 5, 12", maxlength: 200 },
    { k: "severity", label: "Severity", type: "select", options: [["warning", "Warning"], ["critical", "Critical"]] },
    { k: "enabled", label: "Status", type: "check", text: "Rule is active" },
  ];
  function ruleEditor(r) {
    const box = $("#r-editor", root); if (!box) return;
    const v = r ? { ...r, duration_min: Math.round(r.duration_s / 60), nodes: (r.nodes || []).join(", ") }
      : { metric: "soil_moisture", op: "<", severity: "warning", enabled: true, duration_min: 30 };
    box.innerHTML = `<header><h2><span class="ico">${ICONS.edit}</span>${r ? "Edit rule" : "New rule"}</h2></header>
      <form class="body" id="r-form">${formHtml(ruleFields, v)}
        <div class="row"><button class="btn primary" type="submit">${r ? "Save changes" : "Create rule"}</button>
          <button class="btn" type="button" id="r-preview">Check now</button>
          ${r ? `<button class="btn ghost" type="button" id="r-new">New</button><button class="btn danger" type="button" id="r-del" style="margin-inline-start:auto">Delete</button>` : ""}</div>
        <div id="r-prev"></div></form>`;
    const read = () => {
      const x = readForm($("#r-form", box), ruleFields);
      const nodes = x.nodes ? x.nodes.split(/[\s,;]+/).filter(Boolean).map(Number) : null;
      return { name: x.name, metric: x.metric, op: x.op, value: x.value, duration_s: Math.round((x.duration_min || 0) * 60),
        nodes: nodes && nodes.length ? nodes : null, severity: x.severity, enabled: x.enabled };
    };
    $("#r-form", box).addEventListener("submit", async (e) => {
      e.preventDefault();
      try {
        await api(r ? `/alert-rules/${r.id}` : "/alert-rules", { method: r ? "PATCH" : "POST", params: Q(), body: read() });
        toast(r ? "Rule saved" : "Rule created", "ok"); loadRules();
      } catch (err) { toast(err.message, "error"); }
    });
    $("#r-preview", box).addEventListener("click", async () => {
      try {
        const p = await api("/alert-rules/preview", { method: "POST", params: { ...Q(), region: state.region }, body: read() });
        const hit = p.nodes.filter((n) => n.breached);
        $("#r-prev", box).innerHTML = `<p class="note">${hit.length ? `Now breached by ${hit.length} node(s): ${hit.map((n) => `NODE-${String(n.node_id).padStart(3, "0")} (${fmtNum(n.value, 2)})`).join(", ")}` : `No node breaches this rule with its latest reading (${p.nodes.length} checked).`}</p>`;
      } catch (err) { toast(err.message, "error"); }
    });
    $("#r-new", box)?.addEventListener("click", () => ruleEditor(null));
    $("#r-del", box)?.addEventListener("click", async () => {
      if (!confirm("Delete this rule? Its open alert stays until resolved.")) return;
      try { await api(`/alert-rules/${r.id}`, { method: "DELETE", params: Q() }); toast("Rule deleted", "ok"); loadRules(); ruleEditor(null); }
      catch (err) { toast(err.message, "error"); }
    });
  }
  const opWord = { "<": "<", "<=": "≤", ">": ">", ">=": "≥" };
  async function loadRules() {
    rules = (await api("/alert-rules", { params: Q() })).rules;
    $("#r-meta", root).textContent = `${rules.length}`;
    $("#r-rows", root).innerHTML = rules.map((r) => `<tr class="clickable" data-rule="${r.id}"><td><b>${esc(r.name)}</b></td>
      <td class="rule-expr">${esc(METRIC_LABEL[r.metric] || r.metric)} <b>${opWord[r.op]} ${fmtNum(r.value, 2)}</b>${r.duration_s ? ` · ${Math.round(r.duration_s / 60)} min` : ""}</td>
      <td class="mono">${r.nodes ? `<span data-i18n-skip>${r.nodes.map((n) => `NODE-${String(n).padStart(3, "0")}`).join(", ")}</span>` : "all"}</td>
      <td>${badge([r.severity === "critical" ? "critical" : "warning", r.severity === "critical" ? "Critical" : "Warning"])}</td>
      <td>${r.enabled ? badge(["good", "Active"]) : badge(["neutral", "Paused"])}</td></tr>`).join("")
      || `<tr><td colspan="5"><div class="empty">No custom rules yet. The built-in checks (silent node, low battery, flow, leak, weather, security) always run.</div></td></tr>`;
    $$("[data-rule]", root).forEach((tr) => tr.addEventListener("click", () => ruleEditor(rules.find((x) => x.id === +tr.dataset.rule))));
  }

  // --------------------------------------------------------------- channels
  let channels = [];
  function channelFields(kind, provider) {
    const base = [
      { k: "name", label: "Name", required: true, maxlength: 80, placeholder: "e.g. Farm manager" },
      { k: "kind", label: "Type", type: "select", options: Object.entries(KIND_LABEL) },
    ];
    let extra = [];
    if (kind === "email") extra = [{ k: "to", label: "Recipients", placeholder: "a@example.org, b@example.org", full: true, hint: "Up to 20 addresses; uses the server's SMTP account" }];
    else if (kind === "telegram") extra = [{ k: "chat_id", label: "Chat id", placeholder: "-1001234567890", mono: true }, { k: "bot_token", label: "Bot token", type: "password", placeholder: "from @BotFather", mono: true }];
    else if (kind === "teams") extra = [{ k: "webhook_url", label: "Incoming webhook URL", type: "password", full: true, mono: true }];
    else {
      extra = [{ k: "provider", label: "Provider", type: "select", options: cat.providers[kind].map((p) => [p, { twilio: "Twilio", meta: "Meta WhatsApp Cloud API", generic: "Other HTTPS gateway" }[p]]) },
        { k: "to", label: "Phone numbers", placeholder: "+201001234567, +201112223334", full: true }];
      if (provider === "twilio") extra.push({ k: "account_sid", label: "Account SID", mono: true }, { k: "from", label: "Sender number", placeholder: "+14155550100" }, { k: "auth_token", label: "Auth token", type: "password", mono: true });
      else if (provider === "meta") extra.push({ k: "phone_number_id", label: "Phone number id", mono: true }, { k: "token", label: "Access token", type: "password", mono: true });
      else extra.push({ k: "url", label: "Gateway URL (https)", full: true, mono: true }, { k: "body_template", label: "Body template ({to}, {text})", type: "textarea", full: true, mono: true, value: '{"to": "{to}", "text": "{text}"}' },
        { k: "headers", label: "Headers (JSON, e.g. API key)", type: "password", full: true, mono: true, placeholder: '{"Authorization": "Bearer …"}' });
    }
    return [...base, ...extra,
      { k: "min_severity", label: "Send alerts from", type: "select", options: [["warning", "Warning and critical"], ["critical", "Critical only"], ["info", "All, including info"]] },
      { k: "events", label: "Events", type: "checks", options: EVENTS, full: true },
      { k: "enabled", label: "Status", type: "check", text: "Channel is active" }];
  }
  const SECRET = ["bot_token", "auth_token", "token", "headers", "webhook_url"];
  function channelEditor(c, kindOverride, providerOverride) {
    const box = $("#c-editor", root); if (!box) return;
    const kind = kindOverride || c?.kind || "email";
    const provider = providerOverride || c?.config?.provider || (cat.providers[kind] || [])[0];
    const fields = channelFields(kind, provider);
    const cfg = c?.config || {};
    const values = { name: c?.name, kind, provider, ...cfg, to: (cfg.to || []).join(", "), min_severity: c?.min_severity || "warning",
      events: c?.events || ["alert", "resolved"], enabled: c ? c.enabled : true };
    box.innerHTML = `<header><h2><span class="ico">${ICONS.edit}</span>${c ? `Edit · ${esc(c.name)}` : "New channel"}</h2></header>
      <form class="body" id="c-form">${formHtml(fields, values)}
        ${c?.secrets_set?.length ? `<p class="note">Stored secrets: ${c.secrets_set.join(", ")}. Leave secret fields empty to keep them.</p>` : ""}
        <div class="row"><button class="btn primary" type="submit">${c ? "Save changes" : "Create channel"}</button>
          ${c ? `<button class="btn" type="button" id="c-test">Send test</button><button class="btn ghost" type="button" id="c-new">New</button><button class="btn danger" type="button" id="c-del" style="margin-inline-start:auto">Delete</button>` : ""}</div>
        ${c ? `<div class="section-title" style="margin-top:14px">Delivery log</div><ul class="log-list" id="c-log"></ul>` : ""}</form>`;
    const form = $("#c-form", box);
    form.kind.addEventListener("change", () => channelEditor(c, form.kind.value));
    form.provider?.addEventListener("change", () => channelEditor(c, kind, form.provider.value));
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const v = readForm(form, fields), config = {}, secrets = {};
      for (const f of fields) {
        if (["name", "kind", "min_severity", "events", "enabled"].includes(f.k)) continue;
        if (SECRET.includes(f.k)) { if (v[f.k]) secrets[f.k] = v[f.k]; } else config[f.k] = v[f.k];
      }
      if (config.to !== undefined) config.to = config.to.split(/[\s,;]+/).filter(Boolean);
      try {
        await api(c ? `/notify/channels/${c.id}` : "/notify/channels", { method: c ? "PATCH" : "POST", params: Q(),
          body: { name: v.name, kind: v.kind, config, secrets, min_severity: v.min_severity, events: v.events, enabled: v.enabled } });
        toast(c ? "Channel saved" : "Channel created", "ok"); loadChannels();
      } catch (err) { toast(err.message, "error"); }
    });
    $("#c-test", box)?.addEventListener("click", async (e) => {
      e.currentTarget.disabled = true;
      try { const r = await api(`/notify/channels/${c.id}/test`, { method: "POST", params: Q() }); toast(r.ok ? "Test message sent" : `Test failed: ${r.detail}`, r.ok ? "ok" : "error"); loadLog(c); loadChannels(false); }
      catch (err) { toast(err.message, "error"); }
      e.currentTarget.disabled = false;
    });
    $("#c-new", box)?.addEventListener("click", () => channelEditor(null));
    $("#c-del", box)?.addEventListener("click", async () => {
      if (!confirm("Delete this channel?")) return;
      try { await api(`/notify/channels/${c.id}`, { method: "DELETE", params: Q() }); loadChannels(); channelEditor(null); } catch (err) { toast(err.message, "error"); }
    });
    if (c) loadLog(c);
  }
  async function loadLog(c) {
    const log = (await api(`/notify/channels/${c.id}/log`, { params: Q() })).log;
    const el = $("#c-log", root); if (!el) return;
    el.innerHTML = log.map((l) => `<li><span>${esc(fmtDateTime(l.ts))}</span>${l.ok ? badge(["good", l.event]) : badge(["critical", l.event])}<span class="dim" data-i18n-skip>${esc(l.detail || "")}</span></li>`).join("")
      || `<li><span class="dim">Nothing sent yet.</span></li>`;
  }
  async function loadChannels(resetEditor = true) {
    const d = await api("/notify/channels", { params: Q() });
    channels = d.channels;
    $("#c-meta", root).textContent = d.email_enabled ? `${channels.length} · e-mail ready` : `${channels.length} · e-mail not configured on the server`;
    $("#c-rows", root).innerHTML = channels.map((c) => `<tr class="clickable" data-ch="${c.id}"><td><span class="ch-kind">${esc(KIND_LABEL[c.kind])}</span> · <b data-i18n-skip>${esc(c.name)}</b></td>
      <td>${esc(c.events.map((e) => EVENTS.find((x) => x[0] === e)?.[1] || e).join(", "))}<div class="nh-sub">from ${esc(c.min_severity)}</div></td>
      <td>${c.last_at ? `${c.last_ok ? badge(["good", "Delivered"]) : badge(["critical", "Failed"])}<div class="nh-sub">${esc(ago(c.last_at))}</div>` : `<span class="dim">never</span>`}</td>
      <td>${c.enabled ? badge(["good", "Active"]) : badge(["neutral", "Paused"])}</td></tr>`).join("")
      || `<tr><td colspan="4"><div class="empty">No channels yet. Add one to receive alerts outside the dashboard.</div></td></tr>`;
    $$("[data-ch]", root).forEach((tr) => tr.addEventListener("click", () => channelEditor(channels.find((x) => x.id === +tr.dataset.ch))));
    if (resetEditor && !$("#c-form", root)) channelEditor(null);
  }

  await loadRules();
  ruleEditor(null);
  if (canWrite) await loadChannels();
  return undefined;
}
