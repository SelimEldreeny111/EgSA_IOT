// WIOT service worker (R2.6, point 24): installable app, offline technician mode, map tiles, push alerts.
// App shell and assets: stale-while-revalidate. API reads: network first, the last good answer when offline
// (marked with X-WIOT-Offline). Map tiles: cache first (saved per farm from Commissioning > Field tools).
const SHELL = "wiot-shell-v2", API = "wiot-api-v1", TILES = "wiot-tiles-v1", TILE_LIMIT = 3000;
const NO_CACHE_API = ["/api/v2/auth/", "/api/v2/ws", "/api/v2/push/", "/api/v2/assistant", "/api/v2/commission/",
  "/api/v2/eo/render.png"];                                  // satellite images: one per map view, cached on the server

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(SHELL).then((c) => c.addAll(["/", "/assets/app.css", "/assets/global.css", "/assets/ops.css",
    "/assets/farm.css", "/assets/app.js", "/assets/api.js", "/assets/charts.js", "/assets/i18n.js", "/assets/theme.js",
    "/assets/favicon.svg", "/assets/icon-192.png"]).catch(() => {})).then(() => self.skipWaiting()));
});
async function carryOver(keys) {                     // page modules of the old shell cache, until revalidated
  const now = await caches.open(SHELL);
  for (const k of keys.filter((n) => n.startsWith("wiot-shell-") && n !== SHELL)) {
    const old = await caches.open(k);
    for (const req of await old.keys()) {
      if (!(await now.match(req))) { const res = await old.match(req); if (res) await now.put(req, res); }
    }
  }
}
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((keys) => carryOver(keys).catch(() => {}).then(() =>
    Promise.all(keys.filter((k) => ![SHELL, API, TILES].includes(k)).map((k) => caches.delete(k)))))
    .then(() => self.clients.claim()));
});

async function networkFirst(req) {
  const cache = await caches.open(API);
  try {
    const res = await fetch(req);
    if (res.ok) cache.put(req, res.clone());
    return res;
  } catch (err) {
    const hit = await cache.match(req);
    if (!hit) throw err;
    const headers = new Headers(hit.headers);
    headers.set("X-WIOT-Offline", hit.headers.get("date") || "earlier");
    return new Response(await hit.blob(), { status: hit.status, headers });
  }
}
async function staleWhileRevalidate(req) {
  const cache = await caches.open(SHELL);
  const hit = await cache.match(req);
  const fresh = fetch(req).then((res) => { if (res.ok) cache.put(req, res.clone()); return res; }).catch(() => hit);
  return hit || fresh;
}
async function tileFirst(req) {
  const cache = await caches.open(TILES);
  const hit = await cache.match(req);
  if (hit) return hit;
  try {
    const res = await fetch(req);
    if (res.ok || res.type === "opaque") cache.put(req, res.clone());
    return res;
  } catch (err) { return new Response("", { status: 504 }); }
}

self.addEventListener("fetch", (e) => {
  const req = e.request, url = new URL(req.url);
  if (req.method !== "GET") return;
  if (url.origin === location.origin) {
    if (req.mode === "navigate") { e.respondWith(fetch(req).catch(() => caches.match("/"))); return; }
    if (url.pathname.startsWith("/assets/")) { e.respondWith(staleWhileRevalidate(req)); return; }
    if (url.pathname.startsWith("/api/v2/") && !NO_CACHE_API.some((p) => url.pathname.startsWith(p))) { e.respondWith(networkFirst(req)); return; }
    return;
  }
  if (req.destination === "image" && /\/tile\/|\{z\}|\/\d+\/\d+\/\d+/.test(url.pathname)) e.respondWith(tileFirst(req));
});

// Field tools: save the map tiles of a farm for offline use; clear cached data at sign-out.
self.addEventListener("message", (e) => {
  const msg = e.data || {};
  if (msg.type === "cache-tiles") {
    e.waitUntil((async () => {
      const cache = await caches.open(TILES);
      let done = 0;
      for (const u of (msg.urls || []).slice(0, TILE_LIMIT)) {
        try { const res = await fetch(u, { mode: "no-cors" }); await cache.put(u, res); } catch { /* skip */ }
        done += 1;
        if (done % 25 === 0 || done === msg.urls.length) e.source?.postMessage({ type: "tiles-progress", done, total: msg.urls.length });
      }
    })());
  }
  if (msg.type === "clear-data") e.waitUntil(caches.delete(API));
});

self.addEventListener("push", (e) => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch { d = { title: "WIOT", body: e.data ? e.data.text() : "" }; }
  e.waitUntil(self.registration.showNotification(d.title || "WIOT alert", {
    body: d.body || "", tag: d.tag, renotify: Boolean(d.tag), icon: "/assets/icon-192.png", badge: "/assets/icon-192.png",
    data: { url: d.url || "/#/alerts" } }));
});
self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  const url = e.notification.data?.url || "/";
  e.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((list) => {
    const open = list.find((c) => new URL(c.url).origin === location.origin);
    if (open) { open.navigate(url); return open.focus(); }
    return self.clients.openWindow(url);
  }));
});
