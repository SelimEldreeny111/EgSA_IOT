// Public service status: availability of the platform, the MQTT broker link and ingestion.
import { uptimeBars } from "./pages/system.js";
import { applyTheme } from "./charts.js";
import { initLang } from "./i18n.js";

const NAMES = { platform: "Web platform and API", broker: "Field network link (MQTT)", ingestion: "Data ingestion" };
const STATE = { operational: ["ok", "Operational"], degraded: ["warning", "Degraded"], outage: ["critical", "Outage"] };
const HEAD = { operational: "All systems operational", degraded: "Some systems degraded", outage: "Service disruption" };

async function load() {
  const r = await fetch("/api/v2/public/status");
  const d = await r.json();
  const banner = document.getElementById("st-banner");
  banner.className = `sys-banner ${(STATE[d.overall] || STATE.operational)[0]}`;
  banner.innerHTML = `<b>${HEAD[d.overall] || d.overall}</b><span>WIOT ${d.version}</span>`;
  document.getElementById("st-updated").textContent = `Updated ${new Date(d.updated_at * 1000).toLocaleString()}`;
  const avg = (k) => d.days.length ? d.days.reduce((a, x) => a + x[k], 0) / d.days.length : 1;
  document.getElementById("st-components").innerHTML = Object.entries(NAMES).map(([k, label]) => {
    const st = STATE[d.components[k]] || STATE.operational;
    return `<div class="up-row"><div class="up-head"><b>${label}</b><span><span class="badge ${st[0] === "ok" ? "good" : st[0]}">${st[1]}</span> &nbsp;${(avg(k) * 100).toFixed(2)} %</span></div>${uptimeBars(d.days, k)}</div>`;
  }).join("") || "<div class=\"empty\">No measurements yet.</div>";
}
applyTheme();
initLang();
load().catch(() => { document.getElementById("st-banner").textContent = "Status unavailable"; });
setInterval(() => load().catch(() => {}), 60000);
