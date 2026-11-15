// Commissioning wizard (scan -> register -> first uplink -> clock -> checks -> certificate) and field tools
// for technicians: alerts on this device (Web Push) and the farm map saved for offline use.
import { api, state, toast, ICONS, $, $$ } from "../api.js";
import { esc, fmtNum } from "../charts.js";
import { formHtml, readForm } from "../forms.js";

const STEPS = ["Scan", "Register", "First uplink", "Checks", "Done"];
const SENSORS = [["tuf", "TUF-2000B flow"], ["supmea", "Supmea flow"], ["hnda", "HNDA soil"], ["sondas", "Sondas EC"]];

function tileUrls(template, lat, lon, radiusKm = 3, zooms = [12, 13, 14, 15, 16]) {
  const out = [];
  for (const z of zooms) {
    const n = 2 ** z, dLat = radiusKm / 110.574, dLon = radiusKm / (111.32 * Math.cos(lat * Math.PI / 180));
    const x = (lo) => Math.floor((lo + 180) / 360 * n);
    const y = (la) => { const r = la * Math.PI / 180; return Math.floor((1 - Math.log(Math.tan(r) + 1 / Math.cos(r)) / Math.PI) / 2 * n); };
    for (let tx = x(lon - dLon); tx <= x(lon + dLon); tx++) {
      for (let ty = y(lat + dLat); ty <= y(lat - dLat); ty++) out.push(template.replace("{z}", z).replace("{x}", tx).replace("{y}", ty));
    }
  }
  return out;
}
const b64uToBytes = (s) => Uint8Array.from(atob(s.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - s.length % 4) % 4)), (c) => c.charCodeAt(0));

export async function render(root) {
  const canWrite = state.user.permissions.command;
  const Q = () => ({ company: state.company });
  let step = 0, node = null, timer = null, stream = null;
  root.innerHTML = `<div class="ops">
    <div class="grid g-wide">
      <section class="panel"><header><h2><span class="ico">${ICONS.node}</span>Commission a node</h2></header>
        <div class="body"><div class="wiz-steps" id="cm-steps"></div><div id="cm-body"></div></div></section>
      <section class="panel"><header><h2><span class="ico">${ICONS.tower}</span>Field tools</h2></header>
        <div class="body">
          <div class="section-title">Alerts on this device</div>
          <p class="note" id="push-state">Checking…</p>
          <div class="row" style="gap:8px"><button class="btn sm primary" id="push-on">Turn on alerts</button><button class="btn sm" id="push-test">Send a test</button><button class="btn sm ghost" id="push-off">Turn off</button></div>
          <div class="section-title" style="margin-top:18px">Offline map and data</div>
          <p class="note">Saves the satellite map around the farm (zoom 12–16, about 3 km) and keeps the last data you opened, so the dashboard still works without a connection in the field. Install the dashboard from the browser menu ("Install app" / "Add to Home screen") for a full-screen app.</p>
          <div class="row" style="gap:8px"><button class="btn sm" id="map-save">Save farm map offline</button><span class="dim" id="map-progress"></span></div>
        </div></section>
    </div>
  </div>`;

  function paintSteps() {
    $("#cm-steps", root).innerHTML = STEPS.map((s, i) => `<span class="${i === step ? "on" : i < step ? "done" : ""}">${i + 1}. ${esc(s)}</span>`).join("");
  }
  function stopCamera() { stream?.getTracks().forEach((t) => t.stop()); stream = null; }

  async function show() {
    clearInterval(timer); paintSteps();
    const body = $("#cm-body", root);
    if (step === 0) {
      const camera = "BarcodeDetector" in window && navigator.mediaDevices?.getUserMedia;
      body.innerHTML = `<p>Scan the QR label on the node, or type its number.</p>
        ${camera ? `<video class="qr-video" id="cm-video" playsinline muted hidden></video><div class="row" style="margin:10px 0"><button class="btn" id="cm-cam">${ICONS.region}<span>Scan with the camera</span></button></div>` : `<p class="note">This browser cannot scan QR codes; type the code or node number.</p>`}
        <form class="row" id="cm-code" style="gap:8px"><input class="input mono" name="code" placeholder="WIOT:Company_1/Region_1/12 or 12" style="max-width:320px" required>
        <button class="btn primary" type="submit">Continue</button></form>`;
      const go = async (code) => {
        try { node = { region: state.region, type: "monitoring", sensors: [], ...(await api("/commission/parse", { method: "POST", body: { code } })) }; stopCamera(); step = 1; show(); }
        catch (err) { toast(err.message, "error"); }
      };
      $("#cm-code", body).addEventListener("submit", (e) => { e.preventDefault(); go(e.target.code.value.trim()); });
      $("#cm-cam", body)?.addEventListener("click", async () => {
        try {
          stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } });
          const video = $("#cm-video", body); video.hidden = false; video.srcObject = stream; await video.play();
          const detector = new window.BarcodeDetector({ formats: ["qr_code"] });
          const scan = async () => {
            if (!stream) return;
            const codes = await detector.detect(video).catch(() => []);
            if (codes.length) go(codes[0].rawValue); else requestAnimationFrame(scan);
          };
          scan();
        } catch (err) { toast(`Camera unavailable: ${err.message}`, "error"); }
      });
    } else if (step === 1) {
      if (node.company && node.company !== state.company) toast(`The label is for ${node.company}; switch company first`, "error");
      const f = [
        { k: "node_id", label: "Node number", type: "number", min: 1, max: 65535, required: true },
        { k: "region", label: "Region", type: "select", options: state.regions.map((r) => [r, r]) },
        { k: "name", label: "Name", maxlength: 80, placeholder: "e.g. Pivot P-12 probe" },
        { k: "type", label: "Type", type: "select", options: [["monitoring", "Monitoring (sensors only)"], ["control", "Control (sensors + valve)"]] },
        { k: "sensors", label: "Sensors fitted", type: "checks", options: SENSORS, full: true },
        { k: "lat", label: "Latitude", type: "number", step: "any" }, { k: "lon", label: "Longitude", type: "number", step: "any" },
      ];
      body.innerHTML = `<form id="cm-reg">${formHtml(f, node)}<div class="row" style="gap:8px"><button class="btn" type="button" id="cm-gps">Use my location</button>
        <button class="btn primary" type="submit" ${canWrite ? "" : "disabled"}>Register and continue</button><button class="btn ghost" type="button" id="cm-back">Back</button></div></form>`;
      $("#cm-gps", body).addEventListener("click", () => navigator.geolocation?.getCurrentPosition(
        (p) => { body.querySelector('[name="lat"]').value = p.coords.latitude.toFixed(6); body.querySelector('[name="lon"]').value = p.coords.longitude.toFixed(6); },
        (err) => toast(`Location unavailable: ${err.message}`, "error"), { enableHighAccuracy: true, timeout: 15000 }));
      $("#cm-back", body).addEventListener("click", () => { step = 0; show(); });
      $("#cm-reg", body).addEventListener("submit", async (e) => {
        e.preventDefault();
        const v = readForm(e.target, f);
        try { await api("/commission/register", { method: "POST", params: Q(), body: v }); node = { ...node, ...v }; toast("Node registered", "ok"); step = 2; show(); }
        catch (err) { toast(err.message, "error"); }
      });
    } else if (step === 2 || step === 3) {
      const poll = async () => {
        const c = await api("/commission/check", { params: { ...Q(), region: node.region, node_id: node.node_id } });
        const up = c.items.find((i) => i.key === "uplink");
        if (step === 2 && up?.ok) { step = 3; paintSteps(); }
        const clock = c.items.find((i) => i.key === "clock");
        body.innerHTML = `<p>${step === 2 ? `Power the node on (or press its reset button). Waiting for the first report from <b class="mono" data-i18n-skip>NODE-${String(node.node_id).padStart(3, "0")}</b>…` : "Acceptance checks — they refresh every 10 seconds."}</p>
          <ul class="check-list">${c.items.map((i) => `<li class="${i.ok ? "ok" : i.blocking ? "bad" : "info"}"><div><b>${esc(i.label)}</b><small>${esc(i.detail)}</small></div></li>`).join("")}</ul>
          <div class="row" style="gap:8px;margin-top:12px">${clock && !clock.ok && canWrite ? `<button class="btn" id="cm-clock">Send the clock</button>` : ""}
          <button class="btn primary" id="cm-done" ${c.ready && canWrite ? "" : "disabled"}>Mark commissioned</button><button class="btn ghost" id="cm-restart">Start over</button></div>`;
        $("#cm-clock", body)?.addEventListener("click", async () => { try { await api("/commission/clock", { method: "POST", params: { ...Q(), region: node.region, node_id: node.node_id } }); toast("Clock queued for the node", "ok"); } catch (err) { toast(err.message, "error"); } });
        $("#cm-restart", body).addEventListener("click", () => { step = 0; node = null; show(); });
        $("#cm-done", body).addEventListener("click", async () => {
          try { await api("/commission/complete", { method: "POST", params: Q(), body: { node_id: node.node_id, region: node.region } }); step = 4; show(); }
          catch (err) { toast(err.message, "error"); }
        });
      };
      await poll(); timer = setInterval(() => poll().catch(() => {}), 10000);
    } else {
      const q = new URLSearchParams({ ...Q(), format: "pdf" });
      body.innerHTML = `<div class="inv-link"><b>NODE-${String(node.node_id).padStart(3, "0")} is commissioned.</b> The record is stored with the node's asset on the Maintenance page.</div>
        <div class="row" style="gap:8px;margin-top:12px"><button class="btn" id="cm-pdf">${ICONS.download}<span>Certificate (PDF)</span></button><button class="btn primary" id="cm-next">Commission another node</button></div>`;
      $("#cm-next", body).addEventListener("click", () => { step = 0; node = null; show(); });
      $("#cm-pdf", body).addEventListener("click", async () => {
        const res = await api(`/commission/complete?${q}`, { method: "POST", raw: true, body: { node_id: node.node_id, region: node.region } });
        const url = URL.createObjectURL(await res.blob());
        Object.assign(document.createElement("a"), { href: url, download: `WIOT_commissioning_NODE-${node.node_id}.pdf` }).click();
      });
    }
  }

  // ---------------------------------------------------------------- push
  async function pushState() {
    const el = $("#push-state", root);
    if (!("serviceWorker" in navigator) || !("PushManager" in window)) { el.textContent = "This browser does not support push alerts."; return null; }
    let key;
    try { key = await api("/push/key"); } catch (err) { el.textContent = err.message; return null; }
    let reg, sub;
    try {                                   // headless or locked-down browsers can refuse the push service
      reg = await navigator.serviceWorker.ready;
      sub = await reg.pushManager.getSubscription();
    } catch (err) { el.textContent = `Push alerts are not available in this browser (${err.message}).`; return null; }
    el.textContent = sub ? `Alerts are on for this device (${key.subscriptions} device(s) for your account).` : "Alerts are off for this device. Warning and critical alerts of your company will appear as phone or desktop notifications.";
    return { reg, sub, key };
  }
  $("#push-on", root).addEventListener("click", async () => {
    const s = await pushState(); if (!s) return;
    try {
      if ((await Notification.requestPermission()) !== "granted") { toast("Notifications are blocked for this site", "error"); return; }
      const sub = s.sub || await s.reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64uToBytes(s.key.public_key) });
      await api("/push/subscribe", { method: "POST", body: sub.toJSON() }); toast("Alerts turned on", "ok"); pushState().catch(() => {});
    } catch (err) { toast(err.message, "error"); }
  });
  $("#push-off", root).addEventListener("click", async () => {
    const s = await pushState(); if (!s?.sub) return;
    await api("/push/unsubscribe", { method: "POST", body: s.sub.toJSON() }).catch(() => {});
    try { await s.sub.unsubscribe(); toast("Alerts turned off", "ok"); } catch (err) { toast(err.message, "error"); }
    pushState().catch(() => {});
  });
  $("#push-test", root).addEventListener("click", async () => { try { const r = await api("/push/test", { method: "POST" }); toast(`Test sent to ${r.sent} device(s)`, "ok"); } catch (err) { toast(err.message, "error"); } });

  // ------------------------------------------------------------- offline map
  $("#map-save", root).addEventListener("click", async () => {
    try {
      const farm = await api("/farm/overview", { params: { company: state.company, region: state.region } }), cfg = farm.map || {};
      if (!farm.configured) { toast("This company has no farm layout", "error"); return; }
      const reg = await navigator.serviceWorker?.ready;
      if (!reg?.active) { toast("Offline storage is not available in this browser", "error"); return; }
      const [lat, lon] = farm.site.center;
      const urls = [...tileUrls(cfg.tiles, lat, lon), ...(cfg.labels ? tileUrls(cfg.labels, lat, lon, 3, [12, 13, 14]) : [])];
      navigator.serviceWorker.addEventListener("message", (e) => { if (e.data?.type === "tiles-progress") $("#map-progress", root).textContent = `${e.data.done} / ${e.data.total} tiles saved`; });
      reg.active.postMessage({ type: "cache-tiles", urls });
      toast(`Saving ${fmtNum(urls.length, 0)} map tiles…`, "ok");
    } catch (err) { toast(err.message, "error"); }
  });

  await show(); pushState().catch(() => {});
  return () => { clearInterval(timer); stopCamera(); };
}
