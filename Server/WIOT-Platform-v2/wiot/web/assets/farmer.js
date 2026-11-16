// Simple farmer view (R2.5, point 61): one card per field saying what to do today, Arabic first, phone-sized.
const AR = {
  irrigate: ["اسقِ الآن", "التربة جافة"], stop: ["أوقف الري", "التربة مشبعة والري يعمل"], irrigating: ["الري يعمل", "لا شيء آخر مطلوب"],
  nothing: ["لا شيء اليوم", "رطوبة التربة مناسبة"], check_device: ["افحص الجهاز", "الجهاز لا يرسل بيانات"], check_sensor: ["افحص المجس", "قراءة الرطوبة غير صالحة"],
  no_probe: ["لا يوجد مجس للتربة", "الجهاز يعمل لكن بلا مجس رطوبة"],
};
const EN = {
  irrigate: ["Irrigate now", "Soil is dry"], stop: ["Stop irrigation", "Soil is wet and the valve is open"], irrigating: ["Irrigating", "Nothing else to do"],
  nothing: ["Nothing today", "Soil moisture is right"], check_device: ["Check the device", "No data from the node"], check_sensor: ["Check the probe", "Moisture reading is invalid"],
  no_probe: ["No soil probe", "The device works but has no moisture probe"],
};
const RISK_AR = { "Late blight": "اللفحة المتأخرة", "Yellow (stripe) rust": "الصدأ الأصفر", "Powdery mildew": "البياض الدقيقي",
  "Downy mildew": "البياض الزغبي", "Olive fruit fly": "ذبابة ثمار الزيتون" };
const ICON = { irrigate: "💧", stop: "✋", irrigating: "🚿", nothing: "✅", check_device: "📡", check_sensor: "🔧", no_probe: "📟" };
let lang = (() => { try { return localStorage.getItem("wiot.lang") === "en" ? "en" : "ar"; } catch { return "ar"; } })();
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

async function load() {
  const params = new URLSearchParams(location.search);
  const qs = new URLSearchParams({ ...(params.get("company") ? { company: params.get("company") } : {}), ...(params.get("region") ? { region: params.get("region") } : {}) });
  const r = await fetch(`/api/v2/farmer/today?${qs}`, { credentials: "same-origin" });
  if (r.status === 401) { location.href = "/login"; return; }
  const d = await r.json();
  document.documentElement.lang = lang; document.documentElement.dir = lang === "ar" ? "rtl" : "ltr";
  document.getElementById("fm-lang").textContent = lang === "ar" ? "English" : "العربية";
  const T = lang === "ar" ? AR : EN;
  if (!d.configured) { document.getElementById("fm-cards").innerHTML = `<div class="empty">${lang === "ar" ? "لم تُرسم حقول هذه المزرعة بعد." : "This farm has no fields yet."}</div>`; return; }
  document.getElementById("fm-site").textContent = d.site;
  document.getElementById("fm-date").textContent = new Date(`${d.date}T12:00:00`).toLocaleDateString(lang === "ar" ? "ar-EG" : "en-GB", { weekday: "long", day: "numeric", month: "long" });
  const w = d.weather || {}, rain = d.fields[0]?.rain_next_24h_mm;
  document.getElementById("fm-weather").innerHTML = `${w.temp_c !== null && w.temp_c !== undefined ? `<b>${Math.round(w.temp_c)}°</b>` : ""}
    ${rain ? `<span>${lang === "ar" ? `أمطار متوقعة ${rain} مم` : `${rain} mm rain expected`}</span>` : ""}
    ${(d.warnings || []).map((x) => `<span class="farmer-warn">${esc(lang === "ar" ? (x.kind === "frost_risk" ? "خطر صقيع" : "إجهاد حراري") : x.message)}</span>`).join("")}`;
  document.getElementById("fm-cards").innerHTML = d.fields.map((f) => {
    const [title, why] = T[f.action];
    const amount = f.action === "irrigate" && f.runtime_min ? (lang === "ar" ? `حوالي ${f.runtime_min} دقيقة (${f.deficit_mm} مم)` : `about ${f.runtime_min} min (${f.deficit_mm} mm)`) : "";
    const risks = (f.risks || []).map((r) => `<span class="farmer-risk">⚠ ${esc(lang === "ar" ? RISK_AR[r.risk] || r.risk : r.risk)}</span>`).join("");
    return `<article class="farmer-card ${f.level}"><div class="fc-icon" aria-hidden="true">${ICON[f.action]}</div>
      <div class="fc-body"><h2>${esc(f.name)}</h2><b>${esc(title)}</b><span>${esc(why)}${f.moisture !== null && f.moisture !== undefined ? ` · ${Math.round(f.moisture)}%` : ""}</span>
      ${amount ? `<span class="fc-amount">${esc(amount)}</span>` : ""}${risks}</div></article>`;
  }).join("");
}
document.getElementById("fm-lang").addEventListener("click", () => { lang = lang === "ar" ? "en" : "ar"; try { localStorage.setItem("wiot.lang", lang); } catch { /* blocked */ } load(); });
load().catch(() => { document.getElementById("fm-cards").innerHTML = `<div class="empty">⚠</div>`; });
setInterval(() => load().catch(() => {}), 120000);
