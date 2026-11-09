import { currentTheme, setTheme, themeToggleHtml } from "./api.js";
import { initLang, setLang, langToggleHtml, t } from "./i18n.js";

// English / Arabic on the sign-in page (same saved preference as the dashboard).
initLang();
const langHolder = document.getElementById("login-lang");
function paintLang() {
  langHolder.innerHTML = langToggleHtml("login-lang-toggle");
  langHolder.querySelectorAll("[data-lang]").forEach((b) => b.addEventListener("click", () => {
    if (b.dataset.lang === document.documentElement.lang) return;
    setLang(b.dataset.lang);
    if (b.dataset.lang === "en") location.reload(); else paintLang();
  }));
}
paintLang();

const form = document.getElementById("login"), err = document.getElementById("err");
form.addEventListener("submit", async (e) => {
  e.preventDefault();
  err.textContent = "";
  const btn = form.querySelector("button"); btn.disabled = true;
  try {
    const res = await fetch("/api/v2/auth/login", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: form.username.value.trim(), password: form.password.value }) });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || "Sign-in failed");
    location.href = "/";
  } catch (ex) { err.textContent = t(ex.message); } finally { btn.disabled = false; }
});

// Night / Day view on the sign-in page (same saved preference as the dashboard).
const holder = document.getElementById("login-theme");
function paintToggle() {
  holder.innerHTML = themeToggleHtml();
  holder.firstElementChild.addEventListener("click", () => {
    setTheme(currentTheme() === "light" ? "dark" : "light");
    paintToggle();
  });
}
paintToggle();

// Live satellite backdrop of the demo farm (public basemap only; no tenant data).
fetch("/api/v2/public/map").then((r) => r.json()).then((m) => {
  if (!window.L) return;
  const bg = L.map("login-bg", { zoomControl: false, attributionControl: false, dragging: false, scrollWheelZoom: false,
    doubleClickZoom: false, boxZoom: false, keyboard: false, touchZoom: false }).setView(m.center, m.zoom);
  L.tileLayer(m.tiles, { maxZoom: 19, maxNativeZoom: 18 }).addTo(bg);
  setInterval(() => bg.panBy([0.5, 0.2], { animate: false }), 60);
  document.getElementById("login-attr").textContent = m.attribution;
}).catch(() => {});
