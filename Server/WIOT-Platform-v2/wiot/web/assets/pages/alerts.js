// Alerts: silent nodes, low batteries and unstable flow readings, opened and cleared by the
// server's fleet monitor once a minute. Operators acknowledge what they have seen; an alert
// stays open until its condition clears.
import { api, state, onEvent, ago, badge, toast, ICONS, $, $$ } from "../api.js";
import { esc, fmtDateTime, fmtNum } from "../charts.js";
import { conv, unit } from "../units.js";

const nodeTag = (id) => (+id === 0 ? "SITE" : `NODE-${String(id).padStart(3, "0")}`);
const KIND = {
  node_offline: { title: "Node silent", icon: "tower" },
  low_battery: { title: "Low battery", icon: "battery" },
  flow_unstable: { title: "Flow reading unstable", icon: "drop" },
  leak_suspected: { title: "Leak suspected", icon: "drop" },
  no_flow: { title: "No flow", icon: "drop" },
  night_flow: { title: "Night flow", icon: "drop" },
  frost_risk: { title: "Frost risk", icon: "thermo" },
  heat_stress: { title: "Heat stress", icon: "thermo" },
  foreign_command: { title: "Command not sent by this server", icon: "shield" },
  possible_replay: { title: "Possible replay", icon: "shield" },
};
const SEV = { critical: "Critical", warning: "Warning", info: "Info" };

function dur(s) {
  if (s === null || s === undefined || !Number.isFinite(+s)) return "–";
  s = Math.max(0, Math.round(+s));
  if (s < 60) return `${s} s`;
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
  return d ? `${d} d ${h} h` : h ? `${h} h ${m} min` : `${m} min`;
}
const flow = (v) => `${fmtNum(conv(v, "flow"), 1)} ${unit("flow")}`;
const temp = (v) => `${fmtNum(conv(v, "temp"), 1)} ${unit("temp")}`;
const events = (n) => `${n} ${+n === 1 ? "event" : "events"}`;

/** [headline, detail] for one alert, as plain text (the Arabic layer translates each). */
function describe(a, now) {
  const d = a.details || {};
  if (a.kind === "node_offline") {
    const silent = d.last_seen ? (a.state === "open" ? now : a.resolved_at) - d.last_seen : null;
    return [d.last_seen ? `No uplink since ${fmtDateTime(d.last_seen)}` : "No uplink received yet",
      [a.state === "open" ? `Silent for ${dur(silent)}` : `Was silent for ${dur(silent)}`,
        d.interval_s ? `Usually reports every ${dur(d.interval_s)}` : null].filter(Boolean).join(" · ")];
  }
  if (a.kind === "low_battery") {
    return [`Battery ${fmtNum(d.battery_v, 2)} V — below ${fmtNum(d.threshold_v, 1)} V`,
      d.last_seen ? `Last uplink ${ago(d.last_seen)}` : ""];
  }
  if (a.kind === "flow_unstable") {
    const ex = d.example || {};
    return [`${d.jumps} jumps of ×${fmtNum(d.ratio, 0)} or more in one hour (${d.readings} readings)`,
      [ex.from !== undefined ? `e.g. ${flow(ex.from)} → ${flow(ex.to)}` : null,
        "Real pipe flow does not oscillate like this: check the meter, its wiring and Modbus settings"].filter(Boolean).join(" · ")];
  }
  if (a.kind === "leak_suspected") {
    return [`Flow ${flow(d.flow_m3h)} with the valve closed for 15+ minutes`,
      "Check for a leak, a valve that did not close, or a meter fault"];
  }
  if (a.kind === "no_flow") {
    return ["No flow with the valve open for 15+ minutes", "Check the pump, upstream valves and the line for blockage or air"];
  }
  if (a.kind === "night_flow") {
    return [`Flow ${flow(d.flow_m3h)} during night hours ${d.night_hours}`, "Possible leak or unauthorised use"];
  }
  if (a.kind === "frost_risk") {
    return [`Minimum ${temp(d.tmin_c)} forecast on ${d.date}`, "Protect sensitive crops and exposed pipes"];
  }
  if (a.kind === "heat_stress") {
    return [`Maximum ${temp(d.tmax_c)} forecast on ${d.date}`, "Irrigate early in the day; watch soil moisture and crop stress"];
  }
  if (a.kind === "foreign_command") {
    return [`${d.cmd} (data ${d.data}) on this node's command topic, not sent by this server`,
      `${events(d.events || 1)} · request ${d.request_id} · Check who else publishes to the broker`];
  }
  if (a.kind === "possible_replay") {
    return ["An older Status was received again after newer data", `${events(d.events || 1)} · Not processed`];
  }
  return [a.kind, ""];
}

export async function render(root) {
  const canAck = state.user.permissions.command;
  let view = "open", data = null, timer = null;

  root.innerHTML = `
    <div class="tiles al-kpis" id="al-kpis"></div>
    <section class="panel">
      <header><h2><span class="ico">${ICONS.bell}</span>Fleet alerts</h2>
        <div class="seg al-view" id="al-view"><button data-v="open" class="on">Open</button><button data-v="all">Last 7 days</button></div></header>
      <div class="table-wrap"><table class="data al-table"><thead><tr><th>Severity</th><th>Alert</th><th>Node</th><th>Region</th><th>Opened</th><th>Status</th><th></th></tr></thead>
        <tbody id="al-rows"></tbody></table></div>
      <div class="body"><p class="note">The server checks every node once a minute. A node is silent after six times its usual report interval without an uplink; low battery means below 3.3 V; an unstable flow reading jumps by ×5 or more, repeatedly and in both directions, within an hour. Each alert is sent to webhooks once when it opens and once when it clears. Acknowledging only records that it has been seen.</p>
        <p class="note">On valve nodes, a leak is flow with the valve closed and "no flow" is an open valve without flow, each for 15 minutes or more. Frost and heat warnings come from the farm's forecast for today and tomorrow. A command on a node's topic that this server did not send, or an old Status received again after newer data, opens a security alert that clears after a quiet day.</p></div>
    </section>`;

  $$("#al-view button", root).forEach((b) => b.addEventListener("click", () => {
    view = b.dataset.v;
    $$("#al-view button", root).forEach((x) => x.classList.toggle("on", x === b));
    load();
  }));

  function paint() {
    const s = data.summary, now = Math.floor(Date.now() / 1000);
    const tiles = [
      ["Open alerts", fmtNum(s.open, 0), s.unacknowledged ? `${s.unacknowledged} not acknowledged` : s.open ? "all acknowledged" : "all nodes reporting normally", s.critical ? "crit" : s.open ? "warn" : ""],
      ["Critical", fmtNum(s.critical, 0), "silent nodes, leaks, frost, security", ""],
      ["Warnings", fmtNum(s.warning, 0), "battery, flow, heat, replay", ""],
      ["Resolved in 24 h", fmtNum(s.resolved_24h, 0), "conditions that cleared", ""],
    ];
    $("#al-kpis", root).innerHTML = tiles.map(([k, v, sub, cls]) => `<div class="tile ${cls}"><div class="label">${k}</div><div class="v">${v}</div><div class="s">${esc(sub)}</div></div>`).join("");

    $("#al-rows", root).innerHTML = data.alerts.map((a) => {
      const meta = KIND[a.kind] || { title: a.kind, icon: "bell" };
      const [head, detail] = describe(a, now);
      const status = a.state === "resolved"
        ? `${badge(["good", "Resolved"])}<div class="al-sub">${esc(ago(a.resolved_at))}</div>`
        : a.acknowledged_at ? `${badge(["neutral", "Acknowledged"])}<div class="al-sub" data-i18n-skip>${esc(a.acknowledged_by || "")}</div>`
          : badge([a.severity === "critical" ? "critical" : "warning", "Open"]);
      const action = a.state === "open" && !a.acknowledged_at && canAck
        ? `<button class="btn sm" data-ack="${a.id}">Acknowledge</button>` : "";
      return `<tr class="${a.state === "resolved" ? "al-done" : ""}">
        <td><span class="al-sev ${esc(a.severity)}"><i></i>${esc(SEV[a.severity] || a.severity)}</span></td>
        <td><div class="al-what"><span class="ico">${ICONS[meta.icon] || ICONS.bell}</span><div><b>${esc(meta.title)}</b><span>${esc(head)}</span>${detail ? `<small>${esc(detail)}</small>` : ""}</div></div></td>
        <td class="mono" data-i18n-skip>${nodeTag(a.node_id)}${a.details?.name ? `<div class="al-sub">${esc(a.details.name)}</div>` : ""}</td>
        <td class="mono" data-i18n-skip>${esc(a.region)}</td>
        <td title="${esc(fmtDateTime(a.opened_at))}">${esc(ago(a.opened_at))}</td>
        <td>${status}</td><td class="num">${action}</td></tr>`;
    }).join("") || `<tr><td colspan="7"><div class="empty">${view === "open" ? "No open alerts — every node is reporting normally." : "No alerts in the last 7 days."}</div></td></tr>`;

    $$("[data-ack]", root).forEach((b) => b.addEventListener("click", async () => {
      b.disabled = true;
      try { await api(`/alerts/${b.dataset.ack}/acknowledge`, { method: "POST", params: { company: state.company } }); toast("Alert acknowledged", "ok"); }
      catch (err) { toast(err.message, "error"); b.disabled = false; }
      load();
    }));
  }

  async function load() {
    data = await api("/alerts", { params: { company: state.company, status: view } });
    paint();
  }

  const off = onEvent((m) => {
    if (m.type !== "alert" || m.company !== state.company) return;
    clearTimeout(timer); timer = setTimeout(load, 500);
  });
  const tick = setInterval(() => data && paint(), 30000);   // keep "silent for" and ages current
  await load();
  return () => { off(); clearTimeout(timer); clearInterval(tick); };
}
