'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {safeHtml, fragment} = require('../static/js/safe_html.js');
const marker = '<b>audit-markup-marker</b>"\'&';
assert.equal(safeHtml`<td title="${marker}">${marker}</td>`,
    '<td title="&lt;b&gt;audit-markup-marker&lt;/b&gt;&quot;&#39;&amp;">&lt;b&gt;audit-markup-marker&lt;/b&gt;&quot;&#39;&amp;</td>');
assert.equal(safeHtml`<td>${fragment`<b>${marker}</b>`}</td>`,
    '<td><b>&lt;b&gt;audit-markup-marker&lt;/b&gt;&quot;&#39;&amp;</b></td>');
assert.ok(!safeHtml`${{value: '<b>forged</b>'}}`.includes('<b>'));

// Execute actual log handler + helper, with a text-only DOM fixture.
const appSource = fs.readFileSync(path.join(__dirname, '../static/js/app.js'), 'utf8');
const helpers = fs.readFileSync(path.join(__dirname, '../static/js/safe_html.js'), 'utf8');
const callbacks = {};
const children = [];
const term = {children, appendChild(line) { children.push(line); }, scrollHeight: 0};
Object.defineProperty(term, 'firstElementChild', {get: () => ({remove() {children.shift();}})});
const context = {
    document: {createElement: () => ({textContent: ''}), getElementById: () => term},
    socket: {on: (event, callback) => {callbacks[event] = callback;}},
};
vm.createContext(context);
vm.runInContext(helpers, context);
const start = appSource.indexOf("socket.on('system_log'");
const end = appSource.indexOf("socket.on('broker_status'", start);
vm.runInContext(appSource.slice(start, end), context);
callbacks.system_log({message: marker});
assert.equal(children[0].textContent, marker);
for (let index = 0; index < 1100; ++index) callbacks.system_log({message: String(index)});
assert.equal(children.length, 1000);

// Guard every HTML insertion site against a future unescaped template.
assert.ok(!/innerHTML\s*\+=/.test(appSource));
assert.ok(!/innerHTML\s*=\s*`/.test(appSource));
assert.ok(!/onclick="[^"\n]*\$\{/.test(appSource));
// Exercise actual popup generation (Leaflet requires a primitive string).
const popupStart = appSource.indexOf('function buildPopupHtml');
const popupEnd = appSource.indexOf('function initMap', popupStart);
Object.assign(context, {nodeLatestData: {'7': {Time: marker}},
    formatNumberOrDash: () => '-', Number});
vm.runInContext(appSource.slice(popupStart, popupEnd), context);
const popup = context.buildPopupHtml('7');
assert.equal(typeof popup, 'string');
assert.ok(popup.includes('&lt;b&gt;audit-markup-marker'));
assert.ok(!popup.includes('<b>audit-markup-marker'));
console.log('PASS: text/attribute/nested escaping, actual log handler, bounded logs and map popup');

(async () => {
    const rows = [];
    const deleteEvents = [];
    const control = {addEventListener(event, callback) { deleteEvents.push(callback); }};
    const tbody = {innerHTML: '', appendChild(row) {rows.push(row);}};
    context.document.querySelector = () => tbody;
    context.document.createElement = () => ({innerHTML: '', querySelector: () => control});
    Object.assign(context, {console, safeHtml, fragment,
        fetch: async () => ({ok: true, json: async () => ({success: true, users: [
            {id: 7, username: marker, company: marker, role: marker},
            {id: marker, username: marker, company: marker, role: 'user'}
        ]})}), deleteUser() {}, Number});
    vm.runInContext(appSource.slice(appSource.indexOf('async function loadUsers()'),
        appSource.indexOf('async function createUser()')), context);
    await context.loadUsers();
    assert.equal(rows.length, 2);
    assert.ok(rows.every(row => !row.innerHTML.includes('<b>audit-markup-marker')));
    assert.equal(deleteEvents.length, 1); // malformed ID never enters a handler

    const storage = new Map([['wiot_last_broker_config', JSON.stringify({
        broker: 'example.invalid', aes_key: 'test-only-key'})]]);
    Object.assign(context, {localStorage: {getItem: key => storage.get(key) || null,
        setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key)},
        BROKER_STORAGE_KEY: 'wiot_last_broker_config'});
    vm.runInContext(appSource.slice(appSource.indexOf('function saveBrokerConfig'),
        appSource.indexOf('function restoreBrokerConfig')), context);
    const restored = context.loadBrokerConfig();
    assert.equal(restored.broker, 'example.invalid');
    assert.ok(!storage.get('wiot_last_broker_config').includes('test-only-key'));
    assert.ok(!('aes_key' in restored));
    console.log('PASS: actual user-table rendering and legacy browser key purge');
})().catch(error => {console.error(error); process.exitCode = 1;});
