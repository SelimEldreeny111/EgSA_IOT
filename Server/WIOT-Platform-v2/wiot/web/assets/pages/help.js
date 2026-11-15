// Help center: searchable guides, the guided tour and release notes.
import { $, $$ } from "../api.js";
import { esc } from "../charts.js";
import { t } from "../i18n.js";
import { ARTICLES, TOUR, WHATS_NEW } from "../help-content.js";

function block([kind, content], q) {
  const hl = (s) => { const e = esc(t(s)); return q ? e.replace(new RegExp(`(${q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")})`, "gi"), "<mark>$1</mark>") : e; };
  return kind === "ul" ? `<ul>${content.map((x) => `<li>${hl(x)}</li>`).join("")}</ul>` : `<p>${hl(content)}</p>`;
}

export async function render(root) {
  root.innerHTML = `<div class="ops"><div class="help-grid">
    <section class="panel"><div class="body">
      <input class="input" id="hl-q" type="search" placeholder="Search help" aria-label="Search help">
      <nav class="help-toc" id="hl-toc" style="margin-top:10px"></nav>
      <div class="row" style="margin-top:14px;gap:8px"><button class="btn sm primary" id="hl-tour">Start the tour</button><button class="btn sm" id="hl-new">What's new</button></div>
    </div></section>
    <section class="panel"><div class="body help-article" id="hl-body"></div></section>
  </div></div>`;
  let current = ARTICLES[0].id;
  function paint() {
    const q = $("#hl-q", root).value.trim();
    const match = (a) => !q || [a.title, ...a.body.flatMap(([, c]) => (Array.isArray(c) ? c : [c]))].some((s) => t(s).toLowerCase().includes(q.toLowerCase()) || s.toLowerCase().includes(q.toLowerCase()));
    const list = ARTICLES.filter(match);
    $("#hl-toc", root).innerHTML = list.map((a) => `<a href="#/help" data-a="${a.id}" class="${a.id === current ? "on" : ""}">${esc(t(a.title))}</a>`).join("") || `<div class="dim">${esc(t("No guide matches."))}</div>`;
    $$("[data-a]", root).forEach((l) => l.addEventListener("click", (e) => { e.preventDefault(); current = l.dataset.a; paint(); }));
    const shown = q ? list : ARTICLES.filter((a) => a.id === current);
    $("#hl-body", root).innerHTML = shown.map((a) => `<h3>${esc(t(a.title))}</h3>${a.body.map((b) => block(b, q)).join("")}`).join("")
      || `<div class="empty">${esc(t("No guide matches."))}</div>`;
  }
  $("#hl-q", root).addEventListener("input", paint);
  $("#hl-tour", root).addEventListener("click", () => startTour());
  $("#hl-new", root).addEventListener("click", () => whatsNew(true));
  paint();
  return undefined;
}

// ------------------------------------------------------------------ tour
export function startTour() {
  const steps = TOUR.filter((s) => document.querySelector(s.sel));
  if (!steps.length) return;
  let i = 0;
  const ring = Object.assign(document.createElement("div"), { className: "tour-ring" });
  const card = Object.assign(document.createElement("div"), { className: "tour-card", role: "dialog" });
  document.body.append(ring, card);
  const end = () => { ring.remove(); card.remove(); removeEventListener("keydown", key); try { localStorage.setItem("wiot.tourDone", "1"); } catch { /* blocked */ } };
  const key = (e) => { if (e.key === "Escape") end(); };
  addEventListener("keydown", key);
  function show() {
    const s = steps[i], el = document.querySelector(s.sel);
    el.scrollIntoView({ block: "nearest" });
    const r = el.getBoundingClientRect();
    Object.assign(ring.style, { left: `${r.left - 4}px`, top: `${r.top - 4}px`, width: `${r.width + 8}px`, height: `${r.height + 8}px` });
    card.innerHTML = `<h3>${esc(t(s.title))}</h3><p>${esc(t(s.text))}</p><div class="row"><span class="dim">${i + 1} / ${steps.length}</span>
      <span class="row" style="gap:6px"><button class="btn sm ghost" data-x="end">${esc(t("Skip"))}</button>${i ? `<button class="btn sm" data-x="prev">${esc(t("Back"))}</button>` : ""}
      <button class="btn sm primary" data-x="next">${esc(t(i === steps.length - 1 ? "Finish" : "Next"))}</button></span></div>`;
    const cw = Math.min(380, innerWidth - 32), rtl = document.documentElement.dir === "rtl";
    let left = rtl ? r.left - cw - 16 : r.right + 16, top = r.top - 8;
    if (left + cw > innerWidth - 8 || left < 8) { left = Math.max(8, Math.min(innerWidth - cw - 8, r.left)); top = r.bottom + 12; }
    top = Math.min(innerHeight - 190, Math.max(8, top));
    Object.assign(card.style, { left: `${left}px`, top: `${top}px` });
    card.querySelector('[data-x="next"]').focus();
    card.querySelectorAll("[data-x]").forEach((b) => b.addEventListener("click", () => {
      if (b.dataset.x === "end" || (b.dataset.x === "next" && i === steps.length - 1)) { end(); return; }
      i += b.dataset.x === "next" ? 1 : -1; show();
    }));
  }
  show();
}

// ------------------------------------------------------------ what's new
export function whatsNew(force = false) {
  const latest = WHATS_NEW[0].version;
  let seen = null;
  try { seen = localStorage.getItem("wiot.seenVersion"); } catch { /* blocked */ }
  if (!force && seen === latest) return;
  try { localStorage.setItem("wiot.seenVersion", latest); } catch { /* blocked */ }
  if (!force && !seen) return;          // first visit: the tour is offered instead
  const veil = Object.assign(document.createElement("div"), { className: "tour-veil" });
  const card = Object.assign(document.createElement("div"), { className: "modal-card", role: "dialog" });
  card.innerHTML = `<h3>${esc(t("What's new"))}</h3>${WHATS_NEW.map((r) => `<div class="wn-item"><b>${esc(`${r.version} · ${t(r.title)}`)}</b><ul>${r.items.map((x) => `<li>${esc(t(x))}</li>`).join("")}</ul></div>`).join("")}
    <div class="row" style="justify-content:flex-end;margin-top:12px"><button class="btn primary sm" id="wn-close">${esc(t("Close"))}</button></div>`;
  document.body.append(veil, card);
  const close = () => { veil.remove(); card.remove(); };
  veil.addEventListener("click", close);
  card.querySelector("#wn-close").addEventListener("click", close);
  card.querySelector("#wn-close").focus();
}

export function firstRun() {
  let done = null;
  try { done = localStorage.getItem("wiot.tourDone"); } catch { /* blocked */ }
  if (!done) {
    try { localStorage.setItem("wiot.tourDone", "offered"); localStorage.setItem("wiot.seenVersion", WHATS_NEW[0].version); } catch { /* blocked */ }
    setTimeout(startTour, 900);
  } else whatsNew();
}
