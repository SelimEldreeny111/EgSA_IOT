// Small form kit shared by the R2.3+ pages: fields → HTML, form element → values.
// field: {k, label, type: text|number|select|check|checks|textarea|password|date, options: [[v, label]],
//         required, placeholder, hint, min, max, step, maxlength, mono, full, text}
import { esc } from "./charts.js";

let seq = 0;
export function formHtml(fields, values = {}) {
  return `<div class="form-grid">${fields.map((f) => {
    const v = values[f.k] ?? f.value ?? "";
    const id = `ff-${f.k}-${++seq}`;
    const attrs = `id="${id}" name="${f.k}" ${f.required ? "required" : ""} ${f.placeholder ? `placeholder="${esc(f.placeholder)}"` : ""} ${f.maxlength ? `maxlength="${f.maxlength}"` : ""}`;
    let input;
    if (f.type === "select") input = `<select class="input" ${attrs}>${f.options.map(([ov, ol]) => `<option value="${esc(ov)}" ${String(ov) === String(v) ? "selected" : ""}>${esc(ol)}</option>`).join("")}</select>`;
    else if (f.type === "check") input = `<label class="check"><input type="checkbox" id="${id}" name="${f.k}" ${v ? "checked" : ""}> ${esc(f.text || f.label)}</label>`;
    else if (f.type === "checks") input = `<div class="check-grid" role="group" aria-labelledby="${id}-l">${f.options.map(([ov, ol]) => `<label class="check"><input type="checkbox" name="${f.k}" value="${esc(ov)}" ${(v || []).includes(ov) ? "checked" : ""}> ${esc(ol)}</label>`).join("")}</div>`;
    else if (f.type === "textarea") input = `<textarea class="input ${f.mono ? "mono" : ""}" rows="${f.rows || 3}" ${attrs}>${esc(v)}</textarea>`;
    else input = `<input class="input ${f.mono ? "mono" : ""}" type="${f.type || "text"}" ${attrs} value="${esc(v)}" ${f.step ? `step="${f.step}"` : ""} ${f.min !== undefined ? `min="${f.min}"` : ""} ${f.max !== undefined ? `max="${f.max}"` : ""} autocomplete="off">`;
    const label = f.type === "check" ? "<label>&nbsp;</label>"
      : f.type === "checks" ? `<label id="${id}-l">${esc(f.label)}</label>` : `<label for="${id}">${esc(f.label)}</label>`;
    return `<div class="field ${f.full ? "full" : ""}" data-field="${f.k}">${label}${input}${f.hint ? `<div class="hint">${esc(f.hint)}</div>` : ""}</div>`;
  }).join("")}</div>`;
}

export function readForm(el, fields) {
  const out = {};
  for (const f of fields) {
    const node = el.querySelector(`[name="${f.k}"]`);
    if (!node) continue;
    if (f.type === "check") out[f.k] = node.checked;
    else if (f.type === "checks") out[f.k] = [...el.querySelectorAll(`[name="${f.k}"]:checked`)].map((i) => i.value);
    else {
      const raw = node.value.trim();
      out[f.k] = f.type === "number" ? (raw === "" ? null : +raw) : raw;
    }
  }
  return out;
}

export function download(name, text, mime = "text/plain") {
  const url = URL.createObjectURL(new Blob([text], { type: mime }));
  const a = Object.assign(document.createElement("a"), { href: url, download: name });
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export async function copy(text) {
  try { await navigator.clipboard.writeText(text); return true; } catch { return false; }
}

export function uaLabel(ua) {
  if (!ua) return "Unknown device";
  const browser = /Edg\//.test(ua) ? "Edge" : /Chrome\//.test(ua) ? "Chrome" : /Firefox\//.test(ua) ? "Firefox"
    : /Safari\//.test(ua) ? "Safari" : /python|curl|httpx/i.test(ua) ? "API client" : "Browser";
  const os = /Windows/.test(ua) ? "Windows" : /Android/.test(ua) ? "Android" : /iPhone|iPad/.test(ua) ? "iOS"
    : /Mac OS/.test(ua) ? "macOS" : /Linux/.test(ua) ? "Linux" : "";
  return os ? `${browser} · ${os}` : browser;
}
