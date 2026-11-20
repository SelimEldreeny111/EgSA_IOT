'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

class Element {
    constructor() {
        this.children = [];
        this.listeners = new Map();
        this.textContent = '';
        this.classList = {contains: name => name === 'active'};
    }
    append(...children) { this.children.push(...children); }
    replaceChildren(...children) { this.children = children; }
    get firstElementChild() { return this.children[0]; }
    addEventListener(name, listener) { this.listeners.set(name, listener); }
    setAttribute() {}
    dispatch(name, event = {}) {
        event.currentTarget = this;
        const result = this.listeners.get(name)(event);
        event.currentTarget = null;
        return result;
    }
}

const source = fs.readFileSync(path.join(__dirname, '../static/js/water_operations.js'), 'utf8');
const html = '<img src=x onerror=alert(1)>';
const report = {
    observing: true, gateways: [{gateway_id: 3, state: 'online'}],
    nodes: [{node: 7, settings: {name: html, meter: 2, gateway: 3, enabled: true},
        connectivity: 'online', meter_state: 'valid', time_quality: 'fresh',
        last_report: 1795000000, battery_v: 3.8, wdt_reset_count: 1, power_reset_count: 2}],
    incidents: [{id: 4, node: 7, kind: 'high_flow', opened_at: 1795000000,
        evidence: {first_flow_m3h: 15, last_flow_m3h: 16, volume_liters: 30,
            observed_seconds: 20, complete_volume: true}}]
};
const reply = (data, ok = true) => ({ok, json: async () => data});
const tick = () => new Promise(resolve => setImmediate(resolve));

function dashboard(admin) {
    const fields = new Map(), elements = new Map(), requests = [];
    const byId = id => {
        if (!elements.has(id)) elements.set(id, new Element());
        return elements.get(id);
    };
    const form = byId('operations-form');
    form.reset = () => fields.clear();
    form.elements = {namedItem: name => {
        if (!fields.has(name)) fields.set(name, {value: '', focus() {}});
        return fields.get(name);
    }};
    const view = {region: 'Region_1', respond: () => reply(report)};
    vm.runInNewContext(source, {
        URLSearchParams,
        getSelectedCompany: () => 'Company_1',
        getSelectedRegion: () => view.region,
        document: {
            getElementById: id => id === 'operations-form' && !admin ? null : byId(id),
            createElement: () => new Element()
        },
        window: {setInterval() {}},
        fetch: async (url, options) => {
            requests.push({url, options});
            return view.respond(url, options);
        }
    });
    return {view, byId, fields, requests};
}

(async () => {
    const {view, byId, fields, requests} = dashboard(true);
    await byId('operations-tab').dispatch('shown.bs.tab');
    const nodes = byId('operations-nodes'), incidents = byId('operations-incidents');
    assert.equal(nodes.children[0].children[0].textContent, html + ' / 7');
    assert.equal(nodes.children[0].children[1].textContent, 'Online');
    assert.equal(nodes.children[0].children[6].textContent, '3 · Online');
    const edit = nodes.children[0].children[7].firstElementChild;
    edit.dispatch('click');
    assert.equal(fields.get('node').value, 7);
    assert.equal(fields.get('meter').value, 2);
    assert.equal(fields.get('enabled').checked, true);
    assert.match(incidents.children[0].children[4].textContent, /20 s observed.*30 L/);
    const acknowledge = incidents.children[0].children[5].firstElementChild;
    view.respond = () => reply({error: 'Try again'}, false);
    await acknowledge.dispatch('click');
    assert.equal(acknowledge.disabled, false);
    assert.equal(byId('operations-action-result').textContent, 'Try again');
    view.respond = (url, options) => options?.method === 'POST' ? reply({success: true}) : reply(report);
    await acknowledge.dispatch('click');
    assert.ok(requests.some(request => request.options?.method === 'POST' &&
        request.url === '/api/operations/incidents/4/acknowledge?company=Company_1&region=Region_1'));

    let finish;
    view.respond = () => new Promise(resolve => { finish = resolve; });
    const stale = byId('operations-refresh').dispatch('click');
    view.region = 'Region_2';
    view.respond = () => reply({observing: false, gateways: [], nodes: [], incidents: []});
    byId('cfg-region').dispatch('change');
    edit.dispatch('click');
    await tick();
    finish(reply(report));
    await stale;
    assert.equal(fields.size, 0, 'Previous region settings cannot be edited after switching');
    assert.match(nodes.children[0].firstElementChild.textContent, /No monitored lines/);
    assert.match(byId('operations-export').href, /region=Region_2$/);
    assert.match(byId('operations-observation').textContent, /Offline detection is paused/);

    const readOnly = dashboard(false);
    await readOnly.byId('operations-tab').dispatch('shown.bs.tab');
    assert.equal(readOnly.byId('operations-nodes').children[0].children.length, 7);
    assert.equal(readOnly.byId('operations-incidents').children[0].children[5].children.length, 0);
    console.log('PASS water operations UI evidence, role controls, acknowledgements and region switching');
})().catch(error => { console.error(error); process.exitCode = 1; });
