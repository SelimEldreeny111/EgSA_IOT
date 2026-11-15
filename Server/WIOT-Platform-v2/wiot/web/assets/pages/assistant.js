// Optional AI assistant: questions about the user's own fleet, answered from read-only look-ups, plus the daily summary.
import { api, state, ago, toast, ICONS, $, $$ } from "../api.js";
import { esc } from "../charts.js";

const EXAMPLES = ["Which nodes need a visit this week, and why?", "Which fields need water today?",
  "Summarise the open alerts.", "How much water did each field use in the last 7 days?", "ما الحقول التي تحتاج إلى ري اليوم؟"];

export async function render(root) {
  const Q = () => ({ company: state.company });
  const s = await api("/assistant", { params: Q() });
  root.innerHTML = `<div class="ops"><div class="grid g-wide">
    <section class="panel"><header><h2><span class="ico">${ICONS.analytics}</span>Assistant</h2><span class="meta" data-i18n-skip>${esc(s.model)}</span></header>
      <div class="body">${s.ready ? "" : `<div class="inv-link">${s.enabled ? "The assistant is enabled but the <span class=\"mono\">anthropic</span> package is not installed: pip install -e \".[assistant]\"." : "The assistant is turned off on this server. An administrator can enable it with WIOT_ASSISTANT_ENABLED=true and an Anthropic API key, after approving the data-handling rules on the right."}</div>`}
        <div class="chat" id="as-chat" style="margin-top:12px"></div>
        <form id="as-form" class="row" style="gap:8px;margin-top:14px"><input class="input" name="q" maxlength="2000" placeholder="Ask about your nodes, fields, alerts or water use" style="flex:1" ${s.ready ? "" : "disabled"}>
          <button class="btn primary" type="submit" ${s.ready ? "" : "disabled"}>Ask</button></form>
        <div class="row" style="gap:6px;margin-top:10px">${EXAMPLES.map((x) => `<button class="btn sm ghost" type="button" data-ex="${esc(x)}" ${s.ready ? "" : "disabled"}>${esc(x)}</button>`).join("")}</div></div></section>
    <section class="panel"><header><h2><span class="ico">${ICONS.shield}</span>How your data is used</h2></header><div class="body"><ul class="nh-find" style="font-size:13px;line-height:1.7">
      <li>Your question and the data the assistant looks up are sent to Anthropic (Claude) to write the answer, under your organisation's API agreement.</li>
      <li>It can only read your company's data: fleet status, alerts, node health, the farm overview and water use. It cannot send commands or change settings.</li>
      <li>No user names, e-mail addresses, IP addresses or passwords are sent.</li>
      <li>Every question is recorded in the audit trail. Up to ${s.max_per_hour} questions per person per hour.</li>
      <li>Answers can be wrong: check important figures on the dashboard pages.</li></ul></div></section>
  </div></div>`;

  const chat = $("#as-chat", root);
  function paint(history) {
    chat.innerHTML = [...history].reverse().map((h) => `${h.kind === "daily_summary" ? "" : `<div class="q">${esc(h.question)}</div>`}
      <div class="a">${h.kind === "daily_summary" ? "<b>Daily summary</b>\n" : ""}${esc(h.answer || "")}<small>${esc(ago(h.ts))}${h.tools?.length ? ` · looked up ${esc([...new Set(h.tools)].join(", "))}` : ""}</small></div>`).join("")
      || `<div class="empty">${s.ready ? "Ask a question to start." : "No conversations yet."}</div>`;
  }
  paint(s.history);
  async function ask(q) {
    if (!q) return;
    const input = $("#as-form input", root), btn = $("#as-form button", root);
    input.disabled = btn.disabled = true;
    chat.insertAdjacentHTML("beforeend", `<div class="q">${esc(q)}</div><div class="a dim" id="as-wait">Looking it up…</div>`);
    try {
      const r = await api("/assistant/ask", { method: "POST", params: Q(), body: { question: q } });
      $("#as-wait", root)?.remove();
      chat.insertAdjacentHTML("beforeend", `<div class="a">${esc(r.answer)}<small>${r.tools.length ? `looked up ${esc([...new Set(r.tools)].join(", "))}` : ""}</small></div>`);
      input.value = "";
    } catch (err) { $("#as-wait", root)?.remove(); toast(err.message, "error"); }
    input.disabled = btn.disabled = false; input.focus();
  }
  $("#as-form", root).addEventListener("submit", (e) => { e.preventDefault(); ask(e.target.q.value.trim()); });
  $$("[data-ex]", root).forEach((b) => b.addEventListener("click", () => ask(b.dataset.ex)));
  return undefined;
}
