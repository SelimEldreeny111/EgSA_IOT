'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

class Element {
    constructor() {
        this.children = [];
        this.textContent = '';
        this.listeners = {};
        this.classList = {contains: name => name === 'active'};
    }
    append(...children) { this.children.push(...children); }
    replaceChildren(...children) { this.children = children; }
    get firstElementChild() { return this.children[0]; }
    addEventListener(name, callback) { this.listeners[name] = callback; }
    dispatch(name, ...args) { return this.listeners[name](...args); }
}

const source = fs.readFileSync(path.join(__dirname, '../static/js/water_planning.js'), 'utf8');
const fixture = {plans: [{node: 7, meter: 'Supmea', settings: {name: '<script>unsafe()</script>',
    meter: 2, backfill: true}, budgets: [{period: 'day', starts: '2026-11-20', used_m3: 81,
    target_m3: 100, remaining_m3: 19, percent: 81, state: 'near_limit', source: 'Node RTC calculated'}],
    advice: {state: 'dry', sensor: 'sondas', moisture: 18, trend_points_hour: -1.5, budget_limit: true},
    recovery: {state: 'complete', request_id: 3, received: 2, total: 2, gap_records: 1}}]};
const reply = (value, ok = true) => ({ok, json: async () => value});
const tick = () => new Promise(resolve => setImmediate(resolve));

function dashboard(admin) {
    const nodes = new Map(), fields = new Map(), requests = [];
    const get = id => {
        if (id === 'planning-form' && !admin) return null;
        if (!nodes.has(id)) nodes.set(id, new Element());
        return nodes.get(id);
    };
    if (admin) {
        const form = get('planning-form');
        form.reset = () => fields.clear();
        form.elements = {namedItem: name => {
            if (!fields.has(name)) fields.set(name, {value: '', checked: false, focus() {}});
            return fields.get(name);
        }};
        form.querySelector = () => ({disabled: false});
    }
    const view = {region: 'Region_1', respond: () => reply(fixture)};
    vm.runInNewContext(source, {
        URLSearchParams,
        getSelectedCompany: () => 'Company_1',
        getSelectedRegion: () => view.region,
        document: {getElementById: get, createElement: () => new Element()},
        window: {setInterval() {}},
        FormData: class {
            *[Symbol.iterator]() {
                for (const [key, field] of fields) yield [key, field.value];
            }
        },
        fetch: async (url, options) => {
            requests.push({url, options});
            return view.respond(url, options);
        }
    });
    return {get, view, fields, requests};
}

(async () => {
    const {get, view, fields, requests} = dashboard(true);
    await get('planning-tab').dispatch('shown.bs.tab');
    const budget = get('planning-budgets').children[0].children;
    assert.equal(budget[0].textContent, '<script>unsafe()</script> / 7 · Supmea');
    assert.match(budget[5].textContent, /Near limit.*Node RTC calculated/);
    assert.match(get('planning-soil').children[0].children[3].textContent, /budget reached/);
    const recovery = get('planning-recovery').children[0].children;
    assert.match(recovery[3].textContent, /2\/2 records.*1 inside gap/);
    const [edit, download] = recovery[4].children;
    assert.match(download.href, /region=Region_1&node=7&format=csv$/);
    edit.dispatch('click');
    assert.equal(fields.get('node').value, 7);
    assert.equal(fields.get('backfill').checked, true);
    view.respond = (url, options) => options?.method === 'PUT' ? reply({success: true}) : reply(fixture);
    await get('planning-form').dispatch('submit', {preventDefault() {}});
    const update = requests.find(request => request.options?.method === 'PUT');
    assert.match(update.url, /profiles\/7\?company=Company_1&region=Region_1$/);
    assert.equal(JSON.parse(update.options.body).backfill, true);

    let finish;
    view.respond = () => new Promise(resolve => { finish = resolve; });
    const stale = get('planning-refresh').dispatch('click');
    view.region = 'Region_2';
    view.respond = () => reply({plans: []});
    get('cfg-region').dispatch('change');
    edit.dispatch('click');
    await tick();
    finish(reply(fixture));
    await stale;
    assert.equal(fields.size, 0);
    assert.equal(get('planning-recovery').children[0].firstElementChild.textContent, 'No field plans configured.');

    const monitor = dashboard(false);
    await monitor.get('planning-tab').dispatch('shown.bs.tab');
    assert.equal(monitor.get('planning-recovery').children[0].children.length, 4);
    console.log('PASS water planning UI budgets, advice, recovery, safe text, roles and region switching');
})().catch(error => { console.error(error); process.exitCode = 1; });
