'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {safeHtml} = require('../static/js/safe_html.js');

class Element {
    constructor() { this.children = []; this.textContent = ''; this.className = ''; }
    replaceChildren() { this.children = []; }
    appendChild(child) { this.children.push(child); }
}
const body = new Element(), note = new Element();
let company = 'Company_1', region = 'Region_1', load, poll, url;
let response = { company, region, observing: true, gateways: [{ gateway_id: 1, state: 'online',
    received_at: 1795000000, uptime_seconds: 3600, transport: 'Wi-Fi', received_node_frames: 0,
    forwarded_node_frames: 0, forward_failures: 0, has_node_uplink: false, wdt_reset_count: 2, power_reset_count: 5 }] };
let pending = null;
const context = { Date, URLSearchParams, getSelectedCompany: () => company, getSelectedRegion: () => region,
    document: { getElementById: id => id === 'gateway-status-rows' ? body : note,
        createElement: () => new Element() },
    window: { addEventListener: (name, fn) => { load = fn; }, setInterval: fn => { poll = fn; } },
    fetch: async value => { url = value; return pending ? pending : { ok: true, json: async () => response }; } };
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname, '../static/js/gateway_status.js'), 'utf8'), context);

(async () => {
    load();
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(body.children[0].children[1].textContent, 'Online');
    assert.equal(body.children[0].children[7].textContent, 'No node reports yet');
    assert.equal(body.children[0].children[3].textContent, '1h 0m 0s');
    assert.ok(url.includes('region=Region_1'));
    for (const [state, expected] of [['overdue', 'Overdue'], ['offline', 'Offline'], ['unobserved', 'Awaiting heartbeat']]) {
        response.gateways[0].state = state;
        await poll();
        assert.equal(body.children[0].children[1].textContent, expected);
    }
    response.gateways[0].transport = '<img src=x onerror=alert(1)>';
    await poll();
    assert.equal(body.children[0].children[4].textContent, '<img src=x onerror=alert(1)>');
    let finish;
    pending = new Promise(resolve => { finish = resolve; });
    const oldRequest = poll();
    region = 'Region_2';
    finish({ ok: true, json: async () => ({ ...response, gateways: [] }) });
    await oldRequest;
    assert.equal(body.children.length, 1, 'Late response cannot replace another region');
    pending = null;
    response = { observing: false, gateways: [] };
    await poll();
    assert.equal(body.children.length, 0);
    assert.ok(note.textContent.includes('Connect the server'));
    console.log('PASS gateway UI states, quiet nodes, safe text and region switching');
    const app = fs.readFileSync(path.join(__dirname, '../static/js/app.js'), 'utf8');
    const historyBody = {children: [], set innerHTML(value) { this.children = []; },
        appendChild(row) { this.children.push(row); }};
    const elements = new Map([['history-type', {value: 'Gateway'}]]);
    const history = {
        safeHtml, URLSearchParams, IS_SUPERVISOR: false,
        getSelectedCompany: () => 'Company_1', getSelectedRegion: () => 'Region_1',
        window: {location: {}},
        document: {
            body: {dataset: {role: 'admin'}},
            querySelector: () => historyBody,
            getElementById(id) {
                if (!elements.has(id)) elements.set(id, {value: ''});
                return elements.get(id);
            },
            createElement: () => ({})
        },
        async fetch(value) {
            url = value;
            return {json: async () => ({total_pages: 1, total: 1, rows: [{
                type: 'Gateway', region: 'Region_1', gateway_id: 2, timestamp: '2026-11-25 15:53:16',
                details: '<img src=x onerror=alert(1)>'
            }]})};
        }
    };
    vm.createContext(history);
    vm.runInContext(app.slice(app.indexOf('let historyPage ='), app.indexOf('async function loadUsers')), history);
    await history.searchTabular();
    assert.ok(url.includes('type=Gateway'));
    assert.match(historyBody.children[0].innerHTML, /Region_1\/Gateway 2/);
    assert.match(historyBody.children[0].innerHTML, /Heartbeat received/);
    assert.match(historyBody.children[0].innerHTML, /&lt;img/);
    history.exportExcel();
    assert.match(history.window.location.href, /^\/export_csv\?.*type=Gateway/);
    console.log('PASS gateway heartbeat history rendering, safe text and export filter');
})().catch(error => { console.error(error); process.exitCode = 1; });
