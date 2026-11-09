// HTTP + WebSocket client, shared state and small UI helpers.
import { esc } from "./charts.js";

const BASE = "/api/v2";
const readCookie = (n) => document.cookie.split("; ").find((c) => c.startsWith(n + "="))?.split("=")[1];

export const state = {
  user: null, company: null, region: "Region_1", companies: [], profiles: {}, regions: ["Region_1"],
  broker: { state: "unknown" }, listeners: new Set(),
};

export class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

export async function api(path, { method = "GET", body, params, raw } = {}) {
  const url = new URL(BASE + path, location.origin);
  Object.entries(params || {}).forEach(([k, v]) => { if (v !== undefined && v !== null && v !== "") url.searchParams.set(k, v); });
  const headers = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET") headers["X-CSRF-Token"] = decodeURIComponent(readCookie("wiot_csrf") || "");
  const res = await fetch(url, { method, headers, body: body !== undefined ? JSON.stringify(body) : undefined, credentials: "same-origin" });
  if (res.status === 401 && !path.startsWith("/auth/login")) { location.href = "/login"; throw new ApiError(401, "Session expired"); }
  if (raw) return res;
  const data = res.status === 204 ? null : await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, data?.detail || `Request failed (${res.status})`);
  return data;
}

export const scoped = (extra = {}) => ({ company: state.company, region: state.region, ...extra });

// ------------------------------------------------------------- websocket
let socket, retry = 0;
export function connectStream() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const qs = state.company && !state.user?.permissions?.global_read ? "" : `?company=${encodeURIComponent(state.company || "")}`;
  socket = new WebSocket(`${proto}://${location.host}${BASE}/ws${qs}`);
  socket.onopen = () => { retry = 0; emit({ type: "socket", data: { open: true } }); };
  socket.onmessage = (e) => { try { const m = JSON.parse(e.data); if (m.type === "broker" || m.type === "hello") { state.broker = m.type === "hello" ? m.data.broker : m.data; } emit(m); } catch { /* ignore */ } };
  socket.onclose = (e) => {
    emit({ type: "socket", data: { open: false } });
    if (e.code === 4401) { location.href = "/login"; return; }
    setTimeout(connectStream, Math.min(15000, 1000 * 2 ** retry++));
  };
}
export function selectStreamCompany(company) {
  if (socket?.readyState === 1) socket.send(JSON.stringify({ action: "select", company }));
}
export function onEvent(fn) { state.listeners.add(fn); return () => state.listeners.delete(fn); }
function emit(m) { state.listeners.forEach((fn) => { try { fn(m); } catch (err) { console.error(err); } }); }

// ------------------------------------------------------------- ui helpers
export function toast(message, kind = "") {
  let host = document.querySelector(".toast-host");
  if (!host) { host = document.createElement("div"); host.className = "toast-host"; document.body.appendChild(host); }
  const t = document.createElement("div"); t.className = `toast ${kind}`; t.textContent = message; host.appendChild(t);
  setTimeout(() => t.remove(), 5000);
}
export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
export function h(html) { const t = document.createElement("template"); t.innerHTML = html.trim(); return t.content.firstElementChild; }
export function ago(epoch) {
  if (!epoch) return "never";
  const s = Math.max(0, Math.floor(Date.now() / 1000 - epoch));
  if (s < 60) return `${s}s ago`; if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`; return `${Math.floor(s / 86400)}d ago`;
}
export const LINK_BADGE = { online: ["good", "Online"], late: ["warning", "Late"], offline: ["critical", "Offline"] };
export const STATE_BADGE = {
  acknowledged: ["good", "Acknowledged"], rejected: ["critical", "Rejected"], outcome_unknown: ["serious", "No reply"],
  superseded: ["neutral", "Superseded"], pending: ["info", "Pending"], dispatched: ["info", "Dispatched"],
  waiting_retry: ["warning", "Retry queued"], expired: ["neutral", "Expired"], broadcast_partial: ["warning", "Partial"],
};
export function badge([cls, text]) { return `<span class="badge ${cls}">${esc(text)}</span>`; }
export function batteryPct(v) { if (!v) return null; return Math.max(0, Math.min(1, (v - 3.3) / (4.15 - 3.3))); }
// ------------------------------------------------------------ night / day
const THEME_KEY = "wiot.theme";
export const currentTheme = () => (document.documentElement.dataset.theme === "light" ? "light" : "dark");
export function savedTheme() { try { return localStorage.getItem(THEME_KEY); } catch { return null; } }
export function setTheme(mode, persist = true) {
  const root = document.documentElement;
  root.classList.add("theme-anim");
  root.dataset.theme = mode;
  if (persist) { try { localStorage.setItem(THEME_KEY, mode); } catch { /* storage blocked: still switches */ } }
  setTimeout(() => root.classList.remove("theme-anim"), 350);
}
export function themeToggleHtml(id = "theme-toggle") {
  const day = currentTheme() === "light";
  return `<button type="button" class="theme-toggle" id="${id}" role="switch" aria-checked="${day}" aria-label="Switch between night and day view" title="Night / Day view">
    <span class="${day ? "" : "on"}">${ICONS.moon}Night</span><span class="${day ? "on" : ""}">${ICONS.sun}Day</span></button>`;
}

export const ICONS = {
  sensor: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="2.5"/><path d="M7.8 7.8a6 6 0 0 0 0 8.4M16.2 7.8a6 6 0 0 1 0 8.4M5 5a10 10 0 0 0 0 14M19 5a10 10 0 0 1 0 14"/></svg>',
  valve: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M3 10v8M21 10v8M3 14h5l4-3 4 3h5"/><path d="M12 11V6M9 4h6"/></svg>',
  chevron: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M15 6l-6 6 6 6"/></svg>',
  world: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.5 2.7 3.8 5.7 3.8 9S14.5 18.3 12 21c-2.5-2.7-3.8-5.7-3.8-9S9.5 5.7 12 3z"/></svg>',
  org: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="4" y="3" width="10" height="18" rx="1"/><path d="M14 9h6v12h-6M7 7h4M7 11h4M7 15h4M17 13h1M17 17h1"/></svg>',
  region: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 21s-7-6.2-7-11.5A7 7 0 0 1 19 9.5C19 14.8 12 21 12 21z"/><circle cx="12" cy="9.5" r="2.5"/></svg>',
  tower: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 9v13M8 22l4-13 4 13M9 17h6"/><path d="M8.5 5.5a5 5 0 0 0 0 7M15.5 5.5a5 5 0 0 1 0 7"/></svg>',
  key: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="8" cy="15" r="4"/><path d="M11 12l9-9M17 6l3 3M15 8l2 2"/></svg>',
  hook: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M9 17a4 4 0 1 1-4-6M15 7a4 4 0 1 1 4 6M9 13l3-6M12 7h7M10 17h9"/></svg>',
  edit: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 20h4L19 9l-4-4L4 16v4zM13 7l4 4"/></svg>',
  download: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 4v11M7 10l5 5 5-5M5 20h14"/></svg>',
  upload: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 20V9M7 14l5-5 5 5M5 4h14"/></svg>',
  clock: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>',
  chip: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="6" y="6" width="12" height="12" rx="2"/><rect x="9.5" y="9.5" width="5" height="5" rx=".8"/><path d="M9 3v3M15 3v3M9 18v3M15 18v3M3 9h3M3 15h3M18 9h3M18 15h3"/></svg>',
  refresh: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M20 11a8 8 0 0 0-14.6-4.5M4 4v4h4M4 13a8 8 0 0 0 14.6 4.5M20 20v-4h-4"/></svg>',
  farm: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="9"/><path d="M12 12l6.4-6.4"/><path d="M3 12h18M12 3v18" opacity=".35"/><circle cx="12" cy="12" r="1.6" fill="currentColor"/></svg>',
  sun: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>',
  moon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>',
  overview: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M3 12h4l3 8 4-16 3 8h4"/></svg>',
  commands: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="m4 17 6-5-6-5M12 19h8"/></svg>',
  analytics: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/></svg>',
  history: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/></svg>',
  admin: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 4-6 8-6s8 2 8 6"/></svg>',
  system: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/></svg>',
  logout: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M15 4h4v16h-4M10 8l-4 4 4 4M6 12h10"/></svg>',
  drop: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 3s6 6.5 6 11a6 6 0 0 1-12 0c0-4.5 6-11 6-11z"/></svg>',
  node: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="3"/><path d="M5 5a10 10 0 0 0 0 14M19 5a10 10 0 0 1 0 14M8 8a5 5 0 0 0 0 8M16 8a5 5 0 0 1 0 8"/></svg>',
};
