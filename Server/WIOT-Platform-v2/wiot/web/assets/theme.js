// Applies the saved Night/Day view before first paint (no flash of the wrong theme).
// Saved choice wins; otherwise follow the operating-system preference.
(function () {
  var mode = null;
  try { mode = localStorage.getItem("wiot.theme"); } catch (e) { /* storage blocked */ }
  if (mode !== "light" && mode !== "dark") {
    mode = window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
  }
  document.documentElement.setAttribute("data-theme", mode);
  // Language / direction before first paint (English or Arabic, see i18n.js).
  var lang = null;
  try { lang = localStorage.getItem("wiot.lang"); } catch (e) { /* storage blocked */ }
  if (lang === "ar") { document.documentElement.setAttribute("lang", "ar"); document.documentElement.setAttribute("dir", "rtl"); }
})();
