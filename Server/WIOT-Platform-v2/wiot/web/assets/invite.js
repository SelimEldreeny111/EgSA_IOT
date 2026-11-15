// Accept an e-mail invitation: the token travels in the URL fragment (never sent to servers or proxies in logs).
import { initLang, t } from "./i18n.js";

initLang();
const token = decodeURIComponent(location.hash.slice(1));
const info = document.getElementById("inv-info"), err = document.getElementById("err"), form = document.getElementById("invite");

async function load() {
  if (!token) { info.textContent = t("This link is incomplete; open the link from your invitation e-mail."); return; }
  const r = await fetch(`/api/v2/auth/invitations/${encodeURIComponent(token)}`);
  const d = await r.json().catch(() => ({}));
  if (!r.ok) { info.textContent = t(d.detail || "This invitation is not valid any more; ask for a new one"); return; }
  info.textContent = `${d.company} · ${d.role} · ${d.email}`;
  info.setAttribute("data-i18n-skip", "");
  document.getElementById("inv-fields").hidden = false;
  form.username.value = d.email.split("@")[0].replace(/[^A-Za-z0-9._-]/g, ".");
}
form.addEventListener("submit", async (e) => {
  e.preventDefault();
  err.textContent = "";
  if (form.password.value !== document.getElementById("p2").value) { err.textContent = t("The passwords do not match"); return; }
  const btn = form.querySelector("button"); btn.disabled = true;
  try {
    const r = await fetch("/api/v2/auth/invitations/accept", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token, username: form.username.value.trim(), password: form.password.value }) });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.detail || "Could not create the account");
    history.replaceState(null, "", "/invite");
    location.href = "/";
  } catch (ex) { err.textContent = t(ex.message); } finally { btn.disabled = false; }
});
load();
