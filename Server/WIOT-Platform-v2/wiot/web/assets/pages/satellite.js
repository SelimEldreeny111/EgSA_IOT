// Satellite: Sentinel-2 crop health per field, pivot detection for new farms, WIOT-SAT passes and products,
// and (R2.7) the Copernicus catalogue and the EUMETSAT Data Store over the farm.
import { api, state, ago, badge, toast, ICONS, $, $$ } from "../api.js";
import { esc, fmtNum, fmtDateTime, lineChart, legend, PALETTE } from "../charts.js";

const toT = (d) => Math.floor(new Date(`${d}T12:00:00`).getTime() / 1000);

export async function render(root) {
  const canWrite = state.user.permissions.command, sup = state.user.permissions.supervisor;
  const Q = () => ({ company: state.company });
  const [st, fl, eo] = await Promise.all([api("/satellite/status"), api("/water/fields", { params: Q() }), api("/eo/status")]);
  const SRC = { sentinelhub: "Copernicus Sentinel Hub", open: "open Sentinel-2 archive (AWS)" };
  const fields = fl.fields;
  root.innerHTML = `<div class="ops">
    <div class="grid g-wide">
      <section class="panel"><header><h2><span class="ico">${ICONS.farm}</span>Crop health · NDVI</h2>
        ${st.sentinel && canWrite ? `<button class="btn sm" id="nd-refresh" style="margin-inline-start:auto">${ICONS.refresh}<span>Update now</span></button>` : ""}</header>
        <div class="body">${st.sentinel ? "" : `<div class="inv-link">Sentinel-2 is not configured on this server. Without an account, set WIOT_SATELLITE_PROVIDER=open (open archive on AWS). With a free Copernicus Data Space account, set WIOT_SENTINEL_CLIENT_ID and WIOT_SENTINEL_CLIENT_SECRET. The server then stores the NDVI of every field after each clear satellite pass.</div>`}
          <div id="nd-job"></div>
          <div id="nd-chart" style="margin-top:10px"></div><div id="nd-lg"></div>
          <div class="table-wrap"><table class="data"><thead><tr><th>Field</th><th class="num">Latest NDVI</th><th>Pass</th><th></th></tr></thead><tbody id="nd-rows"></tbody></table></div>
          <p class="note">NDVI = (NIR − red) / (NIR + red) from Sentinel-2 L2A at 10 m, clouds masked${st.provider ? `; source: ${SRC[st.provider]}` : ""}. Bare desert is below 0.15; a full green canopy is above 0.7. The same view will use MisrSat-2 imagery when it is available.</p></div></section>
      <section class="panel"><header><h2><span class="ico">${ICONS.drop}</span>Field image</h2></header><div class="body" id="nd-img"><div class="empty">Choose a field.</div></div></section>
    </div>
    ${canWrite ? `<section class="panel"><header><h2><span class="ico">${ICONS.region}</span>Find pivots in an image</h2></header>
      <form class="body" id="pv-form"><div class="form-grid" style="grid-template-columns:repeat(4,minmax(0,1fr))">
        <div class="field"><label for="pv-n">North latitude</label><input class="input" id="pv-n" type="number" step="any" required></div>
        <div class="field"><label for="pv-s">South latitude</label><input class="input" id="pv-s" type="number" step="any" required></div>
        <div class="field"><label for="pv-w">West longitude</label><input class="input" id="pv-w" type="number" step="any" required></div>
        <div class="field"><label for="pv-e">East longitude</label><input class="input" id="pv-e" type="number" step="any" required></div></div>
        <div class="row"><input type="file" id="pv-file" accept="image/png,image/jpeg"><button class="btn primary" type="submit">Find pivots</button>
          ${st.provider === "sentinelhub" ? `<button class="btn" type="button" id="pv-sent">Use the Sentinel-2 image</button>` : ""}</div>
        <p class="note">Give the corner coordinates of the image (north-up). Pivots are found as round, filled green discs of 100–800 m radius; review them, then add them to the farm as fields.${st.pivot_detection ? "" : " This server lacks numpy / scipy / Pillow (analytics extra)."}</p>
        <div id="pv-out"></div></form></section>` : ""}
    <div class="grid g-2">
      <section class="panel"><header><h2><span class="ico">${ICONS.region}</span>Copernicus catalogue</h2></header>
        <div class="body"><form class="row" id="cs-form" style="flex-wrap:wrap;gap:8px">
          <label class="sr-only" for="cs-col">Collection</label><select class="input" id="cs-col" style="max-width:280px">${Object.entries(eo.collections).map(([k, v]) => `<option value="${esc(k)}">${esc(v)}</option>`).join("")}</select>
          <label class="sr-only" for="cs-days">Period</label><select class="input" id="cs-days" style="max-width:150px"><option value="30">Last 30 days</option><option value="90" selected>Last 90 days</option><option value="365">Last 12 months</option></select>
          <button class="btn primary" type="submit">Search</button></form></div>
        <div class="table-wrap"><table class="data"><thead><tr><th>Date (UTC)</th><th>Satellite</th><th>Product</th><th class="num">Cloud</th><th></th></tr></thead><tbody id="cs-rows"><tr><td colspan="5"><div class="empty">Search the Copernicus Data Space catalogue over this farm.</div></td></tr></tbody></table></div>
        <div class="body"><p class="note">Public catalogue of the Copernicus Data Space Ecosystem, newest first. "Open in browser" shows the date and place in the Copernicus Browser (sign in there to download full products or draw your own statistics).</p></div></section>
      <section class="panel"><header><h2><span class="ico">${ICONS.drop}</span>EUMETSAT Data Store</h2></header>
        <div class="body"><form class="row" id="eu-form" style="flex-wrap:wrap;gap:8px">
          <label class="sr-only" for="eu-col">Collection</label><select class="input" id="eu-col" style="max-width:300px">${eo.eumetsat_suggested.map((c) => `<option value="${esc(c.id)}">${esc(c.title)}</option>`).join("")}</select>
          <label class="sr-only" for="eu-h">Period</label><select class="input" id="eu-h" style="max-width:140px"><option value="6">Last 6 hours</option><option value="24" selected>Last 24 hours</option><option value="168">Last 7 days</option></select>
          <button class="btn primary" type="submit">Search</button></form></div>
        <div class="table-wrap"><table class="data"><thead><tr><th>Start (UTC)</th><th>Satellite</th><th>Type</th><th class="num">Size</th><th></th></tr></thead><tbody id="eu-rows"><tr><td colspan="5"><div class="empty">Search Meteosat and Metop products over this farm.</div></td></tr></tbody></table></div>
        <div class="body"><p class="note">Search is public. ${eo.eumetsat_download ? "Downloads are saved on the server under data/eo/eumetsat for SNAP, QGIS or ArcGIS." : "Downloads need the EUMETSAT API key on the server (WIOT_EUMETSAT_KEY and WIOT_EUMETSAT_SECRET from api.eumetsat.int/api-key)."}</p>
          <div id="eu-dl"></div></div></section>
    </div>
    <div class="grid g-2">
      <section class="panel"><header><h2><span class="ico">${ICONS.clock}</span>WIOT-SAT passes</h2></header>
        <div class="table-wrap"><table class="data"><thead><tr><th>Satellite</th><th>Station</th><th>Start (AOS)</th><th class="num">Minutes</th><th class="num">Max elevation</th></tr></thead><tbody id="ps-rows"></tbody></table></div>
        <div class="body"><p class="note">The pass schedule comes from the WIOT-SAT ground tool${sup ? " (POST /api/v2/satellite/passes)" : ""}. Readings that nodes send through the satellite arrive after each pass as a product and are marked "satellite" in the message history; this needs the satellite option in the node firmware.</p></div></section>
      <section class="panel"><header><h2><span class="ico">${ICONS.upload}</span>Satellite products</h2></header>
        <div class="table-wrap"><table class="data"><thead><tr><th>Pass</th><th>Imported</th><th class="num">Readings</th><th class="num">Stored</th><th class="num">Rejected</th></tr></thead><tbody id="pr-rows"></tbody></table></div></section>
    </div>
  </div>`;

  let latest = {};
  async function ndvi() {
    const d = await api("/satellite/ndvi", { params: Q() });
    latest = d.latest;
    const byField = {};
    for (const h of d.history) (byField[h.zone_id] ||= []).push([toT(h.date), h.mean]);
    const series = Object.entries(byField).slice(0, 8).map(([z, pts], i) => ({ name: fields.find((f) => f.id === z)?.name || z, color: PALETTE[i], points: pts, markers: true }));
    lineChart($("#nd-chart", root), { series, xType: "time", height: 220, yDomain: [0, 1], xFormat: (t) => new Date(t * 1000).toISOString().slice(5, 10), empty: "No NDVI values yet" });
    $("#nd-lg", root).innerHTML = series.length ? legend(series.map((s) => ({ name: s.name, color: s.color, line: true }))) : "";
    $("#nd-rows", root).innerHTML = fields.map((f) => { const l = latest[f.id]; return `<tr class="clickable" data-z="${esc(f.id)}"><td data-i18n-skip><b>${esc(f.name)}</b></td>
      <td class="num">${l ? fmtNum(l.mean, 2) : "–"}</td><td class="mono sm">${l ? esc(l.date) : "–"}</td><td class="num">${st.sentinel ? `<button class="btn sm">Show</button>` : ""}</td></tr>`; }).join("");
    $$("[data-z]", root).forEach((tr) => tr.addEventListener("click", () => {
      if (!st.sentinel) return;
      const z = tr.dataset.z, q = new URLSearchParams({ ...Q(), kind: "ndvi" });
      $("#nd-img", root).innerHTML = `<img alt="" style="width:100%;border-radius:10px" src="/api/v2/satellite/image/${encodeURIComponent(z)}.png?${q}">
        <p class="note">${esc(fields.find((f) => f.id === z)?.name || z)} · ${st.provider === "open" ? `latest clear pass read by the server (${esc(latest[z]?.date || "")}). Brown = bare soil, yellow = sparse, green = dense healthy crop; grey = cloud.` : "least-cloudy image of the last 30 days. Red = bare or stressed, green = dense healthy crop."}</p>`;
    }));
  }
  $("#nd-refresh", root)?.addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    btn.disabled = true;
    try {
      const r = await api("/satellite/ndvi/refresh", { method: "POST", params: Q() });
      if (r.stored !== undefined) { toast(`${r.stored} NDVI values stored`, "ok"); ndvi(); }
      else await watchJob();
    } catch (err) { toast(err.message, "error"); }
    btn.disabled = false;
  });
  async function watchJob() {
    const box = $("#nd-job", root);
    for (let i = 0; i < 180; i++) {
      const s = await api("/satellite/status");
      if (!s.job.running) {
        box.innerHTML = "";
        if (s.job.error) toast(s.job.error, "error"); else toast(`${s.job.stored ?? 0} NDVI values stored`, "ok");
        ndvi();
        return;
      }
      box.innerHTML = `<div class="inv-link">Reading the farm's pixels of each clear Sentinel-2 pass from the open archive… (${Math.round(Date.now() / 1000 - s.job.since)} s)</div>`;
      await new Promise((ok) => setTimeout(ok, 5000));
    }
  }

  const utc = (iso) => (iso ? String(iso).slice(0, 16).replace("T", " ") : "–");
  $("#cs-form", root).addEventListener("submit", async (e) => {
    e.preventDefault();
    const rows = $("#cs-rows", root);
    rows.innerHTML = `<tr><td colspan="5"><div class="empty">Searching…</div></td></tr>`;
    try {
      const d = await api("/eo/scenes", { params: { ...Q(), collection: $("#cs-col", root).value, days: $("#cs-days", root).value } });
      rows.innerHTML = d.scenes.map((x) => `<tr><td class="mono sm">${esc(utc(x.datetime))}</td><td>${esc(x.platform)}${x.relative_orbit ? ` · R${esc(String(x.relative_orbit))} ${esc(x.orbit_state || "")}` : ""}</td>
        <td class="mono sm" data-i18n-skip title="${esc(x.id)}">${esc(x.id.length > 42 ? `${x.id.slice(0, 40)}…` : x.id)}</td><td class="num">${x.cloud === null || x.cloud === undefined ? "–" : `${fmtNum(x.cloud, 0)} %`}</td>
        <td class="num">${x.browser ? `<a class="btn sm" href="${esc(x.browser)}" target="_blank" rel="noopener noreferrer">Open in browser</a>` : ""}</td></tr>`).join("")
        || `<tr><td colspan="5"><div class="empty">No products in this period.</div></td></tr>`;
    } catch (err) { rows.innerHTML = ""; toast(err.message, "error"); }
  });

  async function downloads() {
    const d = await api("/eo/downloads");
    $("#eu-dl", root).innerHTML = d.downloads.length ? `<div class="table-wrap"><table class="data"><thead><tr><th>Downloaded product</th><th class="num">Size</th><th>When</th></tr></thead><tbody>
      ${d.downloads.slice(0, 10).map((f) => `<tr><td class="mono sm" data-i18n-skip>${esc(f.file)}</td><td class="num">${fmtNum(f.bytes / 1e6, 1)} MB</td><td>${esc(ago(f.time))}</td></tr>`).join("")}</tbody></table></div>` : "";
  }
  $("#eu-form", root).addEventListener("submit", async (e) => {
    e.preventDefault();
    const rows = $("#eu-rows", root), col = $("#eu-col", root).value;
    rows.innerHTML = `<tr><td colspan="5"><div class="empty">Searching…</div></td></tr>`;
    try {
      const d = await api("/eo/eumetsat/products", { params: { ...Q(), collection: col, hours: $("#eu-h", root).value } });
      const dl = d.download && canWrite;
      rows.innerHTML = d.products.map((x, i) => `<tr><td class="mono sm">${esc(utc(x.start))}</td><td>${esc(x.platform)} ${esc(x.instrument)}</td><td>${esc(x.product_type)}</td>
        <td class="num">${x.size_kb ? `${fmtNum(x.size_kb / 1024, 1)} MB` : "–"}</td><td class="num">${dl ? `<button class="btn sm" data-p="${i}">Download</button>` : ""}</td></tr>`).join("")
        || `<tr><td colspan="5"><div class="empty">No products in this period.</div></td></tr>`;
      $$("[data-p]", rows).forEach((b) => b.addEventListener("click", async () => {
        b.disabled = true;
        try { const r = await api("/eo/eumetsat/download", { method: "POST", body: { collection: col, product: d.products[+b.dataset.p].id } }); toast(`Saved ${r.file} (${fmtNum(r.bytes / 1e6, 1)} MB)`, "ok"); downloads(); }
        catch (err) { toast(err.message, "error"); b.disabled = false; }
      }));
    } catch (err) { rows.innerHTML = ""; toast(err.message, "error"); }
  });

  let circles = [];
  async function detect(source) {
    const b = { north: $("#pv-n", root).value, south: $("#pv-s", root).value, west: $("#pv-w", root).value, east: $("#pv-e", root).value, source };
    const file = $("#pv-file", root).files[0];
    if (source === "upload" && !file) { toast("Choose an image file", "error"); return; }
    try {
      const csrf = decodeURIComponent((document.cookie.split("; ").find((c) => c.startsWith("wiot_csrf=")) || "=").split("=")[1]);
      const res = await fetch(`/api/v2/satellite/pivots/detect?${new URLSearchParams(b)}`, { method: "POST", credentials: "same-origin",
        headers: { "Content-Type": file?.type || "application/octet-stream", "X-CSRF-Token": csrf }, body: source === "upload" ? file : undefined });
      const d = await res.json();
      if (!res.ok) throw new Error(d.detail || "Detection failed");
      circles = d.circles;
      $("#pv-out", root).innerHTML = circles.length ? `<div class="table-wrap"><table class="data"><thead><tr><th></th><th>Centre</th><th class="num">Radius</th><th class="num">Area</th><th class="num">Filled</th></tr></thead><tbody>
        ${circles.map((c, i) => `<tr><td><input type="checkbox" data-c="${i}" checked aria-label="Keep pivot ${i + 1}"></td><td class="mono">${c.lat.toFixed(5)}, ${c.lon.toFixed(5)}</td><td class="num">${fmtNum(c.radius_m, 0)} m</td><td class="num">${fmtNum(c.area_ha, 1)} ha</td><td class="num">${fmtNum(c.fill * 100, 0)} %</td></tr>`).join("")}
        </tbody></table></div><div class="row" style="margin-top:10px"><button class="btn primary" type="button" id="pv-add">Add ticked pivots as fields</button></div>`
        : `<div class="empty">No pivots found. Check the coordinates and that the image shows green circles on bare ground.</div>`;
      $("#pv-add", root)?.addEventListener("click", async () => {
        const keep = $$("[data-c]", root).filter((c) => c.checked).map((c) => circles[+c.dataset.c]);
        if (!keep.length) return;
        try { const r = await api("/satellite/pivots/add", { method: "POST", params: Q(), body: { circles: keep } }); toast(`${r.added} fields added to the farm`, "ok"); }
        catch (err) { toast(err.message, "error"); }
      });
    } catch (err) { toast(err.message, "error"); }
  }
  $("#pv-form", root)?.addEventListener("submit", (e) => { e.preventDefault(); detect("upload"); });
  $("#pv-sent", root)?.addEventListener("click", () => detect("sentinel"));

  async function sat() {
    const [p, pr] = await Promise.all([api("/satellite/passes"), api("/satellite/products", { params: Q() })]);
    $("#ps-rows", root).innerHTML = p.passes.map((x) => `<tr><td>${esc(x.satellite)}</td><td>${esc(x.station || "")}</td><td class="mono sm">${esc(fmtDateTime(x.aos))}</td>
      <td class="num">${fmtNum((x.los - x.aos) / 60, 1)}</td><td class="num">${x.max_elevation === null ? "–" : `${fmtNum(x.max_elevation, 0)}°`}</td></tr>`).join("")
      || `<tr><td colspan="5"><div class="empty">No passes scheduled.</div></td></tr>`;
    $("#pr-rows", root).innerHTML = pr.products.map((x) => `<tr><td class="mono">${esc(x.pass_id)}</td><td>${esc(ago(x.imported_at))}</td><td class="num">${x.records}</td>
      <td class="num">${x.stored}</td><td class="num">${x.rejected ? badge(["warning", String(x.rejected)]) : "0"}</td></tr>`).join("")
      || `<tr><td colspan="5"><div class="empty">No satellite products yet.</div></td></tr>`;
  }
  await Promise.all([ndvi(), sat(), downloads()]);
  if (st.job?.running) watchJob();
  return undefined;
}
