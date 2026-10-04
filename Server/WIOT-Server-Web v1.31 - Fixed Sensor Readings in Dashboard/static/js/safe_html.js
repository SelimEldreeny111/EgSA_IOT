/* Text/quoted-attribute templates only. Never interpolate into JS, CSS or URLs.
 * Only fragment-tagged templates authored in this source can nest as markup;
 * network/storage strings are always escaped, including quotes and ampersands.
 */
class SafeMarkup {
    constructor(value) { this.value = value; }
}
function escapeHTML(value) {
    return String(value ?? '').replace(/[&<>"']/g, char => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[char]));
}
function safeHtml(strings, ...values) {
    return strings.reduce((result, part, index) => result + part + (index < values.length
        ? (values[index] instanceof SafeMarkup ? values[index].value : escapeHTML(values[index]))
        : ''), '');
}
function fragment(strings, ...values) { return new SafeMarkup(safeHtml(strings, ...values)); }

function appendLogText(term, message) {
    const line = document.createElement('div');
    line.textContent = String(message ?? '');
    term.appendChild(line);
    // A bounded log pane prevents an unattended browser consuming unbounded RAM.
    while (term.children.length > 1000) term.firstElementChild.remove();
    term.scrollTop = term.scrollHeight;
}
if (typeof module !== 'undefined') module.exports = {escapeHTML, safeHtml, fragment};
