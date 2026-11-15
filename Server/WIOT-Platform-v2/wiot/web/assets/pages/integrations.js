// Integrations: forward every reading to ThingsBoard, Azure IoT Hub or any HTTPS endpoint, and the
// pull feed for Power BI / Excel. API tokens and webhooks stay on Organization → API & webhooks.
import { api, state, ago, badge, toast, ICONS, $, $$ } from "../api.js";
import { esc, fmtNum } from "../charts.js";
import { formHtml, readForm, copy } from "../forms.js";

const KIND = { thingsboard: "ThingsBoard", azure_iot: "Azure IoT Hub", http_json: "HTTPS (JSON)" };
const SECRETS = ["access_token", "device_key", "headers", "node_tokens"];

function fields(kind) {
  const base = [{ k: "name", label: "Name", required: true, maxlength: 80 }, { k: "kind", label: "Platform", type: "select", options: Object.entries(KIND) }];
  const extra = {
    thingsboard: [{ k: "host", label: "ThingsBoard URL", placeholder: "https://thingsboard.cloud", full: true, mono: true },
      { k: "access_token", label: "Device access token", type: "password", mono: true },
      { k: "device_per_node", label: "Devices", type: "check", text: "One ThingsBoard device per node (token map below)" },
      { k: "node_tokens", label: "Node tokens (JSON: {\"2\": \"token\"})", type: "password", full: true, mono: true }],
    azure_iot: [{ k: "hub", label: "IoT Hub name", placeholder: "egsa-hub (without .azure-devices.net)", mono: true },
      { k: "device_id", label: "Device id", mono: true }, { k: "device_key", label: "Device primary key (base64)", type: "password", full: true, mono: true }],
    http_json: [{ k: "url", label: "Endpoint URL (https)", full: true, mono: true },
      { k: "headers", label: "Headers (JSON, e.g. an API key)", type: "password", full: true, mono: true, placeholder: '{"x-api-key": "…"}' }],
  }[kind];
  return [...base, ...extra, { k: "enabled", label: "Status", type: "check", text: "Forward readings" }];
}

export async function render(root) {
  const Q = () => ({ company: state.company });
  const feed = `${location.origin}/api/v2/feeds/daily.csv?company=${encodeURIComponent(state.company)}&days=365`;
  root.innerHTML = `<div class="ops">
    <div class="ed-split">
      <section class="panel"><header><h2><span class="ico">${ICONS.hook}</span>Forwarding</h2><span class="meta" id="in-meta"></span></header>
        <div class="table-wrap"><table class="data"><thead><tr><th>Integration</th><th class="num">Sent</th><th class="num">Failed</th><th>Last result</th><th>Status</th></tr></thead><tbody id="in-rows"></tbody></table></div>
        <div class="body"><p class="note">Every stored node reading (Status and Telemetry) is forwarded within seconds, with three attempts. Forwarding never slows down ingestion: when a platform is unreachable for long, readings for it are counted as dropped.</p></div></section>
      <section class="panel" id="in-editor"></section>
    </div>
    <section class="panel"><header><h2><span class="ico">${ICONS.analytics}</span>Power BI and Excel</h2></header>
      <div class="body"><p>One row per node and day (mean, minimum and maximum of flow, battery, soil moisture, soil temperature and salinity), from the daily summaries:</p>
        <div class="feed-url"><input class="input mono" readonly value="${esc(feed)}" data-i18n-skip><button class="btn sm" id="feed-copy">Copy</button></div>
        <ol class="note" style="padding-inline-start:18px;line-height:1.7">
          <li>Create an API token with read access on Organization → API &amp; webhooks.</li>
          <li>Power BI Desktop: Get data → Web → Advanced; paste the URL and add the header <span class="mono">Authorization</span> = <span class="mono">Bearer wiot_…</span>.</li>
          <li>Excel: Data → From Web → Advanced, same URL and header. Refresh to update.</li>
        </ol>
        <p class="note">Code examples for Python, PowerShell, curl and Power Query are in <span class="mono">docs/integrations/</span>; the full API is at <a href="/api/docs" target="_blank" rel="noopener">/api/docs</a>.</p></div></section>
  </div>`;
  $("#feed-copy", root).addEventListener("click", async () => toast(await copy(feed) ? "URL copied" : "Copy failed", "ok"));

  let items = [];
  function editor(item, kindOverride) {
    const box = $("#in-editor", root);
    const kind = kindOverride || item?.kind || "thingsboard";
    const f = fields(kind);
    const values = { name: item?.name || KIND[kind], kind, enabled: item ? item.enabled : true, ...(item?.config || {}) };
    box.innerHTML = `<header><h2><span class="ico">${ICONS.edit}</span>${item ? `Edit · ${esc(item.name)}` : "New integration"}</h2></header>
      <form class="body" id="in-form">${formHtml(f, values)}
        ${item?.secrets_set?.length ? `<p class="note">Stored secrets: ${item.secrets_set.join(", ")}. Leave secret fields empty to keep them.</p>` : ""}
        ${item?.last_error ? `<p class="note">Last error ${esc(ago(item.last_error_at))}: <span class="mono" data-i18n-skip>${esc(item.last_error)}</span></p>` : ""}
        <div class="row"><button class="btn primary" type="submit">${item ? "Save changes" : "Create"}</button>
          ${item ? `<button class="btn" type="button" id="in-test">Send test reading</button><button class="btn ghost" type="button" id="in-new">New</button><button class="btn danger" type="button" id="in-del" style="margin-inline-start:auto">Delete</button>` : ""}</div></form>`;
    const form = $("#in-form", box);
    form.kind.addEventListener("change", () => editor(item, form.kind.value));
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const v = readForm(form, f), config = {}, secrets = {};
      for (const x of f) {
        if (["name", "kind", "enabled"].includes(x.k)) continue;
        if (SECRETS.includes(x.k)) { if (v[x.k]) secrets[x.k] = v[x.k]; } else config[x.k] = v[x.k];
      }
      try {
        await api(item ? `/integrations/${item.id}` : "/integrations", { method: item ? "PATCH" : "POST", params: Q(),
          body: { name: v.name, kind: v.kind, enabled: v.enabled, config, secrets } });
        toast(item ? "Integration saved" : "Integration created", "ok"); load();
      } catch (err) { toast(err.message, "error"); }
    });
    $("#in-test", box)?.addEventListener("click", async (e) => {
      e.currentTarget.disabled = true;
      try { const r = await api(`/integrations/${item.id}/test`, { method: "POST", params: Q() }); toast(r.ok ? `Test delivered (${r.detail})` : `Test failed: ${r.detail}`, r.ok ? "ok" : "error"); }
      catch (err) { toast(err.message, "error"); }
      e.currentTarget.disabled = false;
    });
    $("#in-new", box)?.addEventListener("click", () => editor(null));
    $("#in-del", box)?.addEventListener("click", async () => {
      if (!confirm("Delete this integration?")) return;
      try { await api(`/integrations/${item.id}`, { method: "DELETE", params: Q() }); load(); editor(null); } catch (err) { toast(err.message, "error"); }
    });
  }
  async function load() {
    items = (await api("/integrations", { params: Q() })).integrations;
    $("#in-meta", root).textContent = `${items.length}`;
    $("#in-rows", root).innerHTML = items.map((i) => `<tr class="clickable" data-in="${i.id}"><td><b data-i18n-skip>${esc(i.name)}</b><div class="nh-sub">${esc(KIND[i.kind])}</div></td>
      <td class="num">${fmtNum(i.sent, 0)}</td><td class="num">${fmtNum(i.failed + i.dropped, 0)}</td>
      <td>${i.last_error_at && (!i.last_ok_at || i.last_error_at > i.last_ok_at) ? `${badge(["critical", "Failed"])}<div class="nh-sub">${esc(ago(i.last_error_at))}</div>`
        : i.last_ok_at ? `${badge(["good", "Delivered"])}<div class="nh-sub">${esc(ago(i.last_ok_at))}</div>` : `<span class="dim">not yet</span>`}</td>
      <td>${i.enabled ? badge(["good", "Active"]) : badge(["neutral", "Paused"])}</td></tr>`).join("")
      || `<tr><td colspan="5"><div class="empty">No integrations yet.</div></td></tr>`;
    $$("[data-in]", root).forEach((tr) => tr.addEventListener("click", () => editor(items.find((x) => x.id === +tr.dataset.in))));
  }
  await load();
  editor(null);
  return undefined;
}
