// Administration: broker, users, tenants, audit trail, system health.
import { api, state, toast, ICONS, ago, $, $$ } from "../api.js";
import { esc, fmtDateTime } from "../charts.js";

export async function render(root) {
  const sup = state.user.permissions.supervisor;
  root.innerHTML = `
    <div class="grid g-2">
      <section class="panel"><header><h2><span class="ico">${ICONS.node}</span>MQTT ingestion</h2><span class="meta" id="b-state"></span></header><div class="body" id="broker"></div></section>
      <section class="panel"><header><h2><span class="ico">${ICONS.system}</span>System</h2><span class="meta" id="sys-v"></span></header><div class="body" id="system"></div></section>
      <section class="panel"><header><h2><span class="ico">${ICONS.admin}</span>Users</h2><span class="meta" id="u-meta"></span></header>
        <div class="table-wrap"><table class="data"><thead><tr><th>User</th><th>Role</th><th>Company</th><th>Last login</th><th></th></tr></thead><tbody id="users"></tbody></table></div>
        <form class="body" id="u-form"><div class="section-title">Add user</div><div class="form-grid">
          <div class="field"><label>Username</label><input class="input" name="username" required minlength="3" maxlength="80" autocomplete="off"></div>
          <div class="field"><label>Password (≥10, 3 classes)</label><input class="input" name="password" type="password" required minlength="10" autocomplete="new-password"></div>
          <div class="field"><label>Role</label><select class="input" name="role"><option value="user">user (read-only)</option><option value="monitor">monitor (read-only)</option><option value="admin">admin (commands, users)</option></select></div>
          <div class="field"><label>Company</label><select class="input" name="company" ${sup ? "" : "disabled"}>${state.companies.map((c) => `<option ${c === state.company ? "selected" : ""}>${esc(c)}</option>`).join("")}</select></div>
        </div><button class="btn primary" type="submit">Create user</button></form></section>
      <section class="panel"><header><h2><span class="ico">${ICONS.history}</span>Audit trail</h2></header><div class="table-wrap" style="max-height:420px"><table class="data"><thead><tr><th>When</th><th>Actor</th><th>Action</th><th>Target</th><th>IP</th></tr></thead><tbody id="audit"></tbody></table></div></section>
      ${sup ? `<section class="panel"><header><h2>Tenants</h2></header><div class="body"><div id="companies" class="row" style="margin-bottom:12px"></div>
        <form class="row" id="c-form"><input class="input grow" name="name" placeholder="New company ID (letters, digits, _ -)" required maxlength="80"><button class="btn" type="submit">Add company</button></form></div></section>
      <section class="panel"><header><h2>Server log</h2><a class="meta" href="/api/v2/system/logs/download">DOWNLOAD</a></header><div class="console" id="logs" style="max-height:340px"></div></section>` : ""}
      <section class="panel"><header><h2>Change my password</h2></header><form class="body" id="pw-form"><div class="form-grid">
        <div class="field"><label>Current password</label><input class="input" type="password" name="current_password" required autocomplete="current-password"></div>
        <div class="field"><label>New password</label><input class="input" type="password" name="new_password" required minlength="10" autocomplete="new-password"></div></div>
        <button class="btn" type="submit">Update password</button><p class="note">Changing your password signs out every other session.</p></form></section>
    </div>`;

  async function loadBroker() {
    const b = await api("/broker");
    $("#b-state", root).textContent = (b.state || "").replace(/^./, (c) => c.toUpperCase());
    $("#broker", root).innerHTML = `
      <dl class="kv"><dt>State</dt><dd>${esc(b.state)}</dd>${b.host ? `<dt>Endpoint</dt><dd>${esc(b.host)}:${b.port}</dd><dt>Client ID</dt><dd>${esc(b.client_id || "–")}</dd>` : ""}
      ${b.rx !== undefined ? `<dt>Frames RX / TX</dt><dd>${b.rx} / ${b.tx}</dd><dt>Subscriptions</dt><dd>${(b.subscriptions || []).map(esc).join("<br>")}</dd>` : ""}
      <dt>Ready since</dt><dd>${b.connected_since ? fmtDateTime(b.connected_since) : "–"}</dd><dt>Last uplink</dt><dd>${b.last_rx_at ? ago(b.last_rx_at) : "–"}</dd>
      ${b.last_error ? `<dt>Last error</dt><dd style="color:#ff8b8b">${esc(b.last_error)}</dd>` : ""}</dl>
      ${sup ? `<form id="b-form" style="margin-top:14px"><div class="section-title">Connection (supervisor)</div><div class="form-grid">
        <div class="field"><label>Host</label><input class="input" name="host" placeholder="from server config" value="${esc(b.host || "")}"></div>
        <div class="field"><label>Port</label><input class="input" name="port" type="number" value="${b.port || 1883}"></div>
        <div class="field"><label>Client ID</label><input class="input" name="client_id" placeholder="wiot_platform"></div>
        <div class="field"><label>AES-128 key (hex)</label><input class="input" name="aes_key" type="password" placeholder="blank = WIOT_MQTT_AES_KEY_HEX" autocomplete="off"></div>
        <div class="field"><label>MQTT username</label><input class="input" name="username" autocomplete="off"></div>
        <div class="field"><label>MQTT password</label><input class="input" name="password" type="password" autocomplete="off"></div></div>
        <div class="row"><button class="btn primary" type="submit">Connect</button><button class="btn danger" type="button" id="b-off">Disconnect</button></div></form>` : `<p class="note">Only the supervisor controls shared ingestion.</p>`}`;
    $("#b-form", root)?.addEventListener("submit", async (e) => {
      e.preventDefault();
      const body = Object.fromEntries([...new FormData(e.target)].filter(([, v]) => v !== ""));
      if (body.port) body.port = +body.port;
      try { await api("/broker/connect", { method: "POST", body }); toast("Connecting to broker…", "ok"); setTimeout(loadBroker, 1500); } catch (err) { toast(err.message, "error"); }
    });
    $("#b-off", root)?.addEventListener("click", async () => { await api("/broker/disconnect", { method: "POST" }); loadBroker(); });
  }
  async function loadSystem() {
    const s = await api("/system/info");
    $("#sys-v", root).textContent = `v${s.version}`;
    $("#system", root).innerHTML = `<dl class="kv"><dt>Uptime</dt><dd>${Math.floor(s.uptime_s / 3600)} h ${Math.floor((s.uptime_s % 3600) / 60)} m</dd><dt>Python</dt><dd>${esc(s.python)}</dd>
      <dt>Live sockets</dt><dd>${s.websockets}</dd>${s.config ? `<dt>Environment</dt><dd>${esc(s.config.env)}</dd><dt>Data directory</dt><dd>${esc(s.config.data_dir)}</dd><dt>Session TTL</dt><dd>${s.config.token_ttl_minutes} min</dd><dt>Secure cookies</dt><dd>${s.config.cookie_secure}</dd>` : ""}</dl>
      <div class="row" style="margin-top:14px"><a class="btn sm" href="/api/docs" target="_blank" rel="noopener">OpenAPI docs</a><a class="btn sm" href="/readyz" target="_blank">Readiness</a><a class="btn sm" href="/metrics" target="_blank">Prometheus metrics</a></div>`;
  }
  async function loadUsers() {
    const { users } = await api("/users");
    $("#u-meta", root).textContent = `${users.length} accounts`;
    $("#users", root).innerHTML = users.map((u) => `<tr><td class="mono">${esc(u.username)}</td><td>${esc(u.role)}</td><td>${esc(u.company || "all")}</td><td class="dim">${u.last_login_at ? ago(u.last_login_at) : "–"}</td>
      <td>${u.protected || u.username === state.user.username ? `<span class="muted" style="font-size:11px">protected</span>` : `<button class="btn sm danger" data-del="${u.id}" data-name="${esc(u.username)}">Delete</button>`}</td></tr>`).join("");
    $$("[data-del]", root).forEach((b) => b.addEventListener("click", async () => {
      if (!confirm(`Delete user ${b.dataset.name}? This cannot be undone.`)) return;
      try { await api(`/users/${b.dataset.del}`, { method: "DELETE" }); toast("User deleted", "ok"); loadUsers(); loadAudit(); } catch (err) { toast(err.message, "error"); }
    }));
  }
  async function loadAudit() {
    const { entries } = await api("/audit", { params: { limit: 100 } });
    $("#audit", root).innerHTML = entries.map((a) => `<tr><td class="mono dim">${fmtDateTime(a.ts)}</td><td>${esc(a.actor)}</td><td class="mono">${esc(a.action)}</td><td class="dim">${esc(a.target || a.company || "")}</td><td class="mono dim">${esc(a.ip || "")}</td></tr>`).join("");
  }
  async function loadCompanies() {
    if (!sup) return;
    const { companies } = await api("/companies");
    $("#companies", root).innerHTML = companies.map((c) => `<span class="badge info">${esc(c.name)}</span>`).join("");
    const logs = await api("/system/logs", { params: { limit: 400 } });
    $("#logs", root).innerHTML = logs.lines.slice().reverse().map((l) => `<div class="${esc(l.level)}"><span class="t">${esc(l.time)}</span> ${l.company ? `[${esc(l.company)}] ` : ""}${esc(l.message)}</div>`).join("");
  }
  $("#u-form", root).addEventListener("submit", async (e) => {
    e.preventDefault();
    const body = Object.fromEntries(new FormData(e.target)); if (!sup) delete body.company;
    try { await api("/users", { method: "POST", body }); toast(`User ${body.username} created`, "ok"); e.target.reset(); loadUsers(); loadAudit(); } catch (err) { toast(err.message, "error"); }
  });
  $("#c-form", root)?.addEventListener("submit", async (e) => {
    e.preventDefault();
    try { await api("/companies", { method: "POST", body: { name: e.target.name.value.trim() } }); toast("Company added", "ok"); e.target.reset(); loadCompanies(); } catch (err) { toast(err.message, "error"); }
  });
  $("#pw-form", root).addEventListener("submit", async (e) => {
    e.preventDefault();
    try { await api("/auth/password", { method: "POST", body: Object.fromEntries(new FormData(e.target)) }); toast("Password updated", "ok"); e.target.reset(); } catch (err) { toast(err.message, "error"); }
  });
  await Promise.all([loadBroker(), loadSystem(), loadUsers(), loadAudit(), loadCompanies()]);
  const t = setInterval(loadBroker, 10000);
  return () => clearInterval(t);
}
