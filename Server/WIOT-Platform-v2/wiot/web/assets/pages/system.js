// System health (supervisor): broker, ingestion per company, disk, backups, databases,
// background threads, maintenance and 30 days of availability.
import { api, ago, badge, toast, ICONS, $ } from "../api.js";
import { esc, fmtNum, fmtDateTime } from "../charts.js";

const LEVEL = { ok: ["good", "OK"], info: ["info", "Info"], warning: ["warning", "Warning"], critical: ["critical", "Critical"] };
const OVERALL = { ok: "All systems normal", info: "All systems normal", warning: "Needs attention", critical: "Action required" };
export function bytes(n) {
  if (!n) return "0 B";
  const u = ["B", "KB", "MB", "GB", "TB"], i = Math.min(u.length - 1, Math.floor(Math.log(n) / Math.log(1024)));
  return `${fmtNum(n / 1024 ** i, i ? 1 : 0)} ${u[i]}`;
}
function dur(s) {
  if (s === null || s === undefined) return "–";
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
  return d ? `${d} d ${h} h` : h ? `${h} h ${m} min` : `${m} min`;
}
export function uptimeBars(days, key, slots = 30) {
  const pad = Math.max(0, slots - days.length);
  return `<div class="up-bars">${"<i class=\"none\" title=\"not monitored\"></i>".repeat(pad)}${days.map((d) => {
    const v = d[key], cls = v >= 0.999 ? "good" : v >= 0.95 ? "warn" : "bad";
    return `<i class="${cls}" title="${esc(new Date(d.day * 1000).toISOString().slice(0, 10))} · ${fmtNum(v * 100, 2)} %"></i>`;
  }).join("")}</div><div class="up-axis"><span>${slots} days ago</span><span>today</span></div>`;
}

export async function render(root) {
  root.innerHTML = `<div class="ops">
    <div class="sys-banner" id="sys-banner"></div>
    <div class="grid g-2">
      <section class="panel"><header><h2><span class="ico">${ICONS.system}</span>Checks</h2><span class="meta" id="sys-ver"></span></header>
        <div class="body flush"><table class="data"><tbody id="sys-checks"></tbody></table></div></section>
      <section class="panel"><header><h2><span class="ico">${ICONS.clock}</span>Availability · 30 days</h2><span class="meta" id="sys-avail"></span></header>
        <div class="body" id="sys-uptime"></div></section>
    </div>
    <section class="panel"><header><h2><span class="ico">${ICONS.history}</span>Ingestion and storage</h2></header>
      <div class="table-wrap"><table class="data"><thead><tr><th>Company</th><th>Last message</th><th class="num">Database</th><th>Status</th></tr></thead><tbody id="sys-companies"></tbody></table></div>
      <div class="body"><div class="tiles" id="sys-dbs"></div></div></section>
    <section class="panel"><header><h2><span class="ico">${ICONS.refresh}</span>Maintenance</h2>
      <button class="btn sm" id="sys-run" style="margin-left:auto">${ICONS.refresh}<span>Update summaries now</span></button></header>
      <div class="body" id="sys-maint"></div></section></div>`;

  async function load() {
    const [h, st] = await Promise.all([api("/system/health"), api("/system/status-history", { params: { days: 30 } })]);
    const lv = LEVEL[h.overall] || LEVEL.ok;
    $("#sys-banner", root).className = `sys-banner ${lv[0]}`;
    $("#sys-banner", root).innerHTML = `<b>${esc(OVERALL[h.overall] || h.overall)}</b><span>Version ${esc(h.version)} · ${esc(h.env)} · up ${esc(dur(h.uptime_s))} · ${h.websockets} dashboard connection${h.websockets === 1 ? "" : "s"}</span>`;
    $("#sys-ver", root).textContent = `v${h.version}`;
    $("#sys-checks", root).innerHTML = h.checks.map((c) => `<tr><td><b>${esc(c.name)}</b></td><td>${badge(LEVEL[c.level] || LEVEL.ok)}</td><td class="dim sys-detail">${esc(c.detail)}</td></tr>`).join("");
    $("#sys-companies", root).innerHTML = h.companies.map((c) => `<tr><td data-i18n-skip><b>${esc(c.company)}</b></td>
      <td>${c.last_message_at ? `${esc(ago(c.last_message_at))}<div class="nh-sub">${esc(fmtDateTime(c.last_message_at))}</div>` : "no data yet"}</td>
      <td class="num">${bytes(c.db_bytes)}</td><td>${badge(LEVEL[c.level] || LEVEL.ok)}</td></tr>`).join("");
    const b = h.backup;
    $("#sys-dbs", root).innerHTML = [
      ...Object.entries(h.databases).map(([k, v]) => [k.charAt(0).toUpperCase() + k.slice(1), bytes(v), "database file"]),
      ["Last backup", b ? ago(b.at) : "none", b ? `${b.encrypted ? "encrypted" : "NOT encrypted"} · ${bytes(b.bytes)} · ${b.count} kept` : "run python -m wiot backup"],
    ].map(([k, v, s]) => `<div class="tile"><div class="label">${esc(k)}</div><div class="v">${esc(v)}</div><div class="s">${esc(s)}</div></div>`).join("");
    const days = st.days || [];
    const avg = (k) => days.length ? days.reduce((a, d) => a + d[k], 0) / days.length : null;
    $("#sys-avail", root).textContent = avg("platform") === null ? "" : `${fmtNum(avg("platform") * 100, 2)} %`;
    $("#sys-uptime", root).innerHTML = days.length ? [["Platform", "platform"], ["MQTT broker", "broker"], ["Ingestion", "ingestion"]].map(([l, k]) =>
      `<div class="up-row"><div class="up-head"><b>${l}</b><span>${fmtNum((avg(k) ?? 0) * 100, 2)} %</span></div>${uptimeBars(days, k)}</div>`).join("")
      + `<p class="note">A status sample is recorded every 5 minutes; a day without samples means the server was not running. The same view without company details is public at <a href="/status" target="_blank" rel="noopener">/status</a>.</p>`
      : `<div class="empty">No samples yet — the first is recorded within 10 minutes of start-up.</div>`;
    const m = h.maintenance;
    $("#sys-maint", root).innerHTML = m ? `<div class="tiles">
        <div class="tile"><div class="label">Last cycle</div><div class="v">${esc(ago(m.at))}</div><div class="s">${fmtNum(m.seconds, 2)} s${m.daily ? " · with retention" : ""}</div></div>
        <div class="tile"><div class="label">Readings summarised</div><div class="v">${fmtNum(m.rollups.reduce((a, r) => a + r.messages, 0), 0)}</div><div class="s">into hourly and daily summaries</div></div>
        <div class="tile"><div class="label">Raw rows removed</div><div class="v">${fmtNum(m.retention.reduce((a, r) => a + r.messages_deleted, 0), 0)}</div><div class="s">by retention (minimum 365 days)</div></div>
        <div class="tile ${m.errors.length ? "crit" : ""}"><div class="label">Errors</div><div class="v">${m.errors.length}</div><div class="s">${esc(m.errors[0]?.error || "none")}</div></div></div>
        <p class="note">Every 10 minutes the server folds new readings into hourly and daily summaries; charts longer than 7 days read them. Once a day it applies each company's data retention (Organization → company; 0 keeps everything) and optimises the databases.</p>`
      : `<div class="empty">The first maintenance cycle runs shortly after start-up.</div>`;
  }
  $("#sys-run", root).addEventListener("click", async (e) => {
    const btn = e.currentTarget; btn.disabled = true;
    try { const r = await api("/system/maintenance/run", { method: "POST" }); toast(`Summaries updated: ${r.rollups.reduce((a, x) => a + x.messages, 0)} readings in ${r.seconds} s`, "ok"); await load(); }
    catch (err) { toast(err.message, "error"); }
    btn.disabled = false;
  });
  await load();
  const timer = setInterval(load, 30000);
  return () => clearInterval(timer);
}
