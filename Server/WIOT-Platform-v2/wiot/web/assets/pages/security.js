// Security: your two-factor sign-in and sessions; for administrators also every session, invitations,
// page access per user and the audit trail (filters + CSV).
import { api, state, ago, badge, toast, ICONS, $, $$ } from "../api.js";
import { esc, fmtDateTime } from "../charts.js";
import { formHtml, readForm, download, copy, uaLabel } from "../forms.js";

const PAGES = [["farm", "Smart farm"], ["planning", "Irrigation planning"], ["crop", "Crop care"], ["satellite", "Satellite"], ["maintenance", "Maintenance"], ["commission", "Commissioning"], ["assistant", "Assistant"], ["world", "World operations"], ["overview", "Fleet overview"], ["alerts", "Alerts"],
  ["health", "Node health"], ["notify", "Rules & notifications"], ["commands", "Command center"], ["analytics", "Data science"],
  ["history", "Message history"], ["flash", "Flash data"], ["reports", "Reports"], ["water", "Water accounts"], ["org", "Organization"],
  // pages that also need a role (admin or national account): the role still decides; listed so a page list keeps them
  ["regional", "Regional dashboard"], ["admin", "Administration"], ["integrations", "Integrations"], ["usage", "Usage"]];
const METHOD = { password: "Password", totp: "Password + code", recovery: "Recovery code", sso: "Single sign-on" };

export async function render(root) {
  const P = state.user.permissions, isAdmin = P.manage_users || P.supervisor;
  root.innerHTML = `<div class="ops">
    <div class="grid g-2">
      <section class="panel"><header><h2><span class="ico">${ICONS.shield}</span>Two-factor sign-in</h2><span class="meta" id="tf-state"></span></header>
        <div class="body" id="tf-body"></div></section>
      <section class="panel"><header><h2><span class="ico">${ICONS.key}</span>Your sessions</h2>
        <button class="btn sm" id="ss-others" style="margin-inline-start:auto">Sign out other sessions</button></header>
        <div class="table-wrap"><table class="data"><thead><tr><th>Device</th><th>Signed in</th><th>Last active</th><th></th></tr></thead><tbody id="ss-rows"></tbody></table></div></section>
    </div>
    ${isAdmin ? `
    <section class="panel"><header><h2><span class="ico">${ICONS.upload}</span>Invitations</h2><span class="meta" id="inv-mail"></span></header>
      <div class="body"><form id="inv-form"></form><div id="inv-result"></div></div>
      <div class="table-wrap"><table class="data"><thead><tr><th>E-mail</th><th>Role</th><th>Company</th><th>Invited by</th><th>Status</th><th></th></tr></thead><tbody id="inv-rows"></tbody></table></div></section>
    <section class="panel"><header><h2><span class="ico">${ICONS.admin}</span>Users and page access</h2></header>
      <div class="table-wrap"><table class="data"><thead><tr><th>User</th><th>Role</th><th>Company</th><th>Two-factor</th><th>Pages</th><th></th></tr></thead><tbody id="ua-rows"></tbody></table></div>
      <div class="body" id="ua-edit" hidden></div></section>
    <section class="panel"><header><h2><span class="ico">${ICONS.key}</span>All sessions</h2><span class="meta" id="as-meta"></span></header>
      <div class="table-wrap" style="max-height:360px"><table class="data"><thead><tr><th>User</th><th>Company</th><th>Device</th><th>IP</th><th>Method</th><th>Last active</th><th></th></tr></thead><tbody id="as-rows"></tbody></table></div></section>
    <section class="panel"><header><h2><span class="ico">${ICONS.history}</span>Audit trail</h2>
      <a class="btn sm" id="au-csv" style="margin-inline-start:auto" href="#">${ICONS.download}<span>Download CSV</span></a></header>
      <div class="body"><form id="au-form" class="au-filters"></form></div>
      <div class="table-wrap" style="max-height:520px"><table class="data"><thead><tr><th>When</th><th>Actor</th><th>Action</th><th>Company</th><th>Target</th><th>IP</th><th>Details</th></tr></thead><tbody id="au-rows"></tbody></table></div>
      <div class="body"><button class="btn sm" id="au-more" hidden>Load more</button></div></section>` : ""}
  </div>`;

  // ------------------------------------------------------------ two-factor
  async function twoFactor() {
    const s = await api("/auth/totp");
    $("#tf-state", root).innerHTML = s.enabled ? badge(["good", "On"]) : badge(["neutral", "Off"]);
    const body = $("#tf-body", root);
    if (s.enabled) {
      body.innerHTML = `<p>Signing in asks for a 6-digit code from your authenticator app after the password.</p>
        <p class="note">${s.recovery_codes_left} of 10 recovery codes left. Each code works once if your phone is not at hand.</p>
        <form id="tf-off" class="row" style="margin-top:12px;gap:8px"><input class="input" type="password" name="password" placeholder="Your password" autocomplete="current-password" required style="max-width:240px">
        <button class="btn danger" type="submit">Turn off</button></form>`;
      $("#tf-off", body).addEventListener("submit", async (e) => {
        e.preventDefault();
        try { await api("/auth/totp/disable", { method: "POST", body: { password: e.target.password.value } }); toast("Two-factor sign-in turned off", "ok"); twoFactor(); }
        catch (err) { toast(err.message, "error"); }
      });
      return;
    }
    body.innerHTML = `<p>Protect your account with a second step: a code from an authenticator app (Microsoft or Google Authenticator, Authy, 1Password) on your phone.</p>
      <button class="btn primary" id="tf-start" style="margin-top:8px">Set up two-factor sign-in</button>`;
    $("#tf-start", body).addEventListener("click", async () => {
      let setup;
      try { setup = await api("/auth/totp/setup", { method: "POST" }); } catch (err) { toast(err.message, "error"); return; }
      const grouped = setup.secret.match(/.{1,4}/g).join(" ");
      body.innerHTML = `<ol class="tf-steps">
          <li>In your authenticator app choose <b>Add account</b> and enter this key (time-based):<div class="tf-key mono" data-i18n-skip>${esc(grouped)}</div>
            <div class="row" style="gap:8px"><button class="btn sm" id="tf-copy" type="button">Copy key</button><a class="btn sm" href="${esc(setup.uri)}">Open in authenticator app</a></div></li>
          <li>Enter the 6-digit code the app shows:<form id="tf-on" class="row" style="gap:8px;margin-top:8px">
            <input class="input mono" name="code" inputmode="numeric" maxlength="6" required placeholder="123456" style="max-width:140px">
            <button class="btn primary" type="submit">Turn on</button></form></li></ol>`;
      $("#tf-copy", body).addEventListener("click", async () => toast(await copy(setup.secret) ? "Key copied" : "Copy failed", "ok"));
      $("#tf-on", body).addEventListener("submit", async (e) => {
        e.preventDefault();
        try {
          const r = await api("/auth/totp/enable", { method: "POST", body: { code: e.target.code.value.trim() } });
          body.innerHTML = `<p><b>Two-factor sign-in is on.</b> Save these recovery codes somewhere safe; each works once if you lose your phone. They are not shown again.</p>
            <div class="tf-codes mono" data-i18n-skip>${r.recovery_codes.map(esc).join("<br>")}</div>
            <div class="row" style="gap:8px;margin-top:10px"><button class="btn sm" id="tf-dl">Download codes</button><button class="btn sm primary" id="tf-done">Done</button></div>`;
          $("#tf-dl", body).addEventListener("click", () => download("wiot-recovery-codes.txt", `WIOT recovery codes for ${state.user.username}\n\n${r.recovery_codes.join("\n")}\n`));
          $("#tf-done", body).addEventListener("click", () => { twoFactor(); sessions(); });
        } catch (err) { toast(err.message, "error"); }
      });
    });
  }

  // -------------------------------------------------------------- sessions
  async function sessions() {
    const rows = (await api("/auth/sessions")).sessions;
    $("#ss-rows", root).innerHTML = rows.map((s) => `<tr><td><b>${esc(uaLabel(s.user_agent))}</b><div class="nh-sub" data-i18n-skip>${esc(s.ip || "")}</div></td>
      <td>${esc(ago(s.created_at))}<div class="nh-sub">${esc(METHOD[s.method] || s.method)}</div></td><td>${esc(ago(s.last_seen_at))}</td>
      <td class="num">${s.current ? badge(["good", "This browser"]) : `<button class="btn sm" data-revoke="${esc(s.jti)}">Sign out</button>`}</td></tr>`).join("")
      || `<tr><td colspan="4"><div class="empty">No active sessions.</div></td></tr>`;
    $$("[data-revoke]", root).forEach((b) => b.addEventListener("click", async () => {
      try { await api(`/auth/sessions/${b.dataset.revoke}`, { method: "DELETE" }); toast("Session signed out", "ok"); sessions(); }
      catch (err) { toast(err.message, "error"); }
    }));
  }
  $("#ss-others", root).addEventListener("click", async () => {
    try { const r = await api("/auth/sessions/revoke-others", { method: "POST" }); toast(`${r.revoked} session(s) signed out`, "ok"); sessions(); }
    catch (err) { toast(err.message, "error"); }
  });

  await Promise.all([twoFactor(), sessions()]);
  if (!isAdmin) return undefined;

  // ----------------------------------------------------------- invitations
  const invFields = [
    { k: "email", label: "E-mail address", type: "email", required: true, maxlength: 200, placeholder: "name@example.org" },
    { k: "role", label: "Role", type: "select", options: [["user", "User (read only)"], ["monitor", "Monitor (read only)"], ["admin", "Administrator"]] },
    ...(P.supervisor ? [{ k: "company", label: "Company", type: "select", options: state.companies.map((c) => [c, state.profiles[c]?.display_name || c]) }] : []),
    { k: "pages", label: "Pages (none ticked = all pages of the role)", type: "checks", options: PAGES, full: true },
  ];
  $("#inv-form", root).innerHTML = formHtml(invFields, { role: "user", company: state.company }) + `<button class="btn primary" type="submit">Create invitation</button>`;
  $("#inv-form", root).addEventListener("submit", async (e) => {
    e.preventDefault();
    const v = readForm(e.target, invFields);
    if (!v.pages.length) v.pages = null;
    try {
      const r = await api("/invitations", { method: "POST", body: v });
      $("#inv-result", root).innerHTML = `<div class="inv-link"><b>${r.emailed ? "Invitation e-mailed." : "Send this link to the person (valid 7 days, works once):"}</b>
        <div class="row" style="gap:8px;margin-top:6px"><input class="input mono" readonly value="${esc(r.link)}" data-i18n-skip><button class="btn sm" id="inv-copy" type="button">Copy</button></div>
        ${r.email_error ? `<p class="note">E-mail failed: ${esc(r.email_error)}</p>` : ""}</div>`;
      $("#inv-copy", root).addEventListener("click", async () => toast(await copy(r.link) ? "Link copied" : "Copy failed", "ok"));
      e.target.reset(); invitations();
    } catch (err) { toast(err.message, "error"); }
  });
  async function invitations() {
    const d = await api("/invitations");
    $("#inv-mail", root).textContent = d.email_enabled ? "sent by e-mail" : "e-mail not configured: copy the link";
    const now = Date.now() / 1000;
    $("#inv-rows", root).innerHTML = d.invitations.map((i) => {
      const st = i.accepted_at ? ["good", `Accepted · ${i.accepted_username}`] : i.revoked_at ? ["neutral", "Revoked"] : i.expires_at < now ? ["neutral", "Expired"] : ["info", "Pending"];
      return `<tr><td data-i18n-skip>${esc(i.email)}</td><td>${esc(i.role)}</td><td data-i18n-skip>${esc(i.company)}</td><td data-i18n-skip>${esc(i.invited_by)}</td>
        <td>${badge(st)}<div class="nh-sub">${esc(ago(i.created_at))}</div></td>
        <td class="num">${st[1] === "Pending" ? `<button class="btn sm" data-inv="${i.id}">Revoke</button>` : ""}</td></tr>`;
    }).join("") || `<tr><td colspan="6"><div class="empty">No invitations yet.</div></td></tr>`;
    $$("[data-inv]", root).forEach((b) => b.addEventListener("click", async () => {
      try { await api(`/invitations/${b.dataset.inv}`, { method: "DELETE" }); invitations(); } catch (err) { toast(err.message, "error"); }
    }));
  }

  // ----------------------------------------------------------- page access
  async function users() {
    const list = (await api("/users")).users;
    $("#ua-rows", root).innerHTML = list.map((u) => `<tr><td><b data-i18n-skip>${esc(u.username)}</b>${u.email ? `<div class="nh-sub" data-i18n-skip>${esc(u.email)}</div>` : ""}${u.sso ? ` ${badge(["info", "SSO"])}` : ""}</td>
      <td>${esc(u.role)}</td><td data-i18n-skip>${esc(u.company)}</td><td>${u.totp_enabled ? badge(["good", "On"]) : badge(["neutral", "Off"])}</td>
      <td>${u.pages ? esc(u.pages.map((p) => PAGES.find((x) => x[0] === p)?.[1] || p).join(", ")) : `<span class="dim">All pages of the role</span>`}</td>
      <td class="num">${u.protected || u.role === "supervisor" ? "" : `<button class="btn sm" data-pages="${u.id}">Pages</button>`}${u.totp_enabled && !u.protected ? ` <button class="btn sm" data-reset="${u.id}">Reset two-factor</button>` : ""}</td></tr>`).join("");
    $$("[data-pages]", root).forEach((b) => b.addEventListener("click", () => {
      const u = list.find((x) => x.id === +b.dataset.pages), box = $("#ua-edit", root);
      const f = [{ k: "pages", label: `Pages for ${u.username}`, type: "checks", options: PAGES, full: true }];
      box.hidden = false;
      box.innerHTML = `<form id="ua-form">${formHtml(f, { pages: u.pages || PAGES.map((p) => p[0]) })}<div class="row" style="gap:8px">
        <button class="btn primary" type="submit">Save</button><button class="btn" type="button" id="ua-all">All pages of the role</button><button class="btn ghost" type="button" id="ua-cancel">Cancel</button></div></form>`;
      const save = async (pages) => {
        try { await api(`/users/${u.id}/pages`, { method: "PUT", body: { pages } }); toast("Page access saved", "ok"); box.hidden = true; users(); }
        catch (err) { toast(err.message, "error"); }
      };
      $("#ua-form", box).addEventListener("submit", (e) => { e.preventDefault(); save(readForm(e.target, f).pages); });
      $("#ua-all", box).addEventListener("click", () => save(null));
      $("#ua-cancel", box).addEventListener("click", () => { box.hidden = true; });
      box.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }));
    $$("[data-reset]", root).forEach((b) => b.addEventListener("click", async () => {
      if (!confirm("Turn off two-factor sign-in for this user and sign out their sessions?")) return;
      try { await api(`/users/${b.dataset.reset}/totp/reset`, { method: "POST" }); toast("Two-factor sign-in reset", "ok"); users(); }
      catch (err) { toast(err.message, "error"); }
    }));
  }

  async function allSessions() {
    const rows = (await api("/sessions")).sessions;
    $("#as-meta", root).textContent = `${rows.length} active`;
    $("#as-rows", root).innerHTML = rows.map((s) => `<tr><td data-i18n-skip><b>${esc(s.username)}</b></td><td data-i18n-skip>${esc(s.company || "")}</td>
      <td>${esc(uaLabel(s.user_agent))}</td><td class="mono" data-i18n-skip>${esc(s.ip || "")}</td><td>${esc(METHOD[s.method] || s.method)}</td>
      <td>${esc(ago(s.last_seen_at))}</td><td class="num">${s.current ? badge(["good", "You"]) : `<button class="btn sm" data-kill="${esc(s.jti)}">Sign out</button>`}</td></tr>`).join("")
      || `<tr><td colspan="7"><div class="empty">No active sessions.</div></td></tr>`;
    $$("[data-kill]", root).forEach((b) => b.addEventListener("click", async () => {
      try { await api(`/sessions/${b.dataset.kill}`, { method: "DELETE" }); allSessions(); } catch (err) { toast(err.message, "error"); }
    }));
  }

  // ------------------------------------------------------------ audit trail
  let offset = 0, actions = [];
  const auFields = () => [
    { k: "actor", label: "Actor", maxlength: 80, placeholder: "user name" },
    { k: "action", label: "Action", type: "select", options: [["", "All actions"], ...actions.map((a) => [a, a.replace(/_/g, " ")])] },
    { k: "q", label: "Contains", maxlength: 80, placeholder: "target, IP or detail" },
    { k: "since", label: "From", type: "date" }, { k: "until", label: "To", type: "date" },
  ];
  function filters() {
    const v = readForm($("#au-form", root), auFields());
    const day = (d, end) => (d ? Math.floor(new Date(`${d}T00:00:00`).getTime() / 1000) + (end ? 86400 : 0) : undefined);
    return { actor: v.actor, action: v.action, q: v.q, since: day(v.since), until: day(v.until, true), ...(P.supervisor ? {} : {}) };
  }
  async function audit(more = false) {
    offset = more ? offset + 100 : 0;
    const d = await api("/audit", { params: { ...filters(), limit: 100, offset } });
    if (!actions.length) { actions = d.actions; $("#au-form", root).innerHTML = formHtml(auFields()) + `<button class="btn primary sm" type="submit">Apply</button>`; }
    const html = d.entries.map((a) => `<tr><td class="mono dim">${esc(fmtDateTime(a.ts))}</td><td data-i18n-skip>${esc(a.actor)}</td><td class="mono">${esc(a.action)}</td>
      <td data-i18n-skip>${esc(a.company || "")}</td><td class="dim" data-i18n-skip>${esc(a.target || "")}</td><td class="mono dim" data-i18n-skip>${esc(a.ip || "")}</td>
      <td class="mono sm dim au-det" data-i18n-skip title="${esc(JSON.stringify(a.details))}">${esc(JSON.stringify(a.details)).slice(0, 90)}</td></tr>`).join("");
    if (more) $("#au-rows", root).insertAdjacentHTML("beforeend", html);
    else $("#au-rows", root).innerHTML = html || `<tr><td colspan="7"><div class="empty">No entries match.</div></td></tr>`;
    $("#au-more", root).hidden = d.entries.length < 100;
    const qs = new URLSearchParams(Object.entries({ ...filters(), format: "csv", limit: 5000 }).filter(([, x]) => x !== undefined && x !== ""));
    $("#au-csv", root).href = `/api/v2/audit?${qs}`;
  }
  $("#au-form", root).addEventListener("submit", (e) => { e.preventDefault(); audit(); });
  $("#au-more", root).addEventListener("click", () => audit(true));

  await Promise.all([invitations(), users(), allSessions(), audit()]);
  return undefined;
}
