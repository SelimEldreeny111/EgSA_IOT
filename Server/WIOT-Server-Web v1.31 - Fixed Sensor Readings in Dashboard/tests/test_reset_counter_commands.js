'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../static/js/app.js'), 'utf8');
const start = source.indexOf('async function sendCommand(');
const end = source.indexOf('function updateStimeStatus(', start);
assert.ok(start > 0 && end > start);
let selected = 'CLEAR_POWER_RESETS', confirmed = true, calls = [];
const context = {
    document: {getElementById(id) { return {value: ({
        'cmd-node':'7', 'cmd-type':selected, 'cmd-data':'corrupted-input',
        'cmd-delivery':'now', 'cmd-ttl':'86400'})[id]}; }},
    window: {confirm() { return confirmed; }},
    getSelectedCompany() { return 'Company_1'; },
    showToast() {}, setWakeStatus() {}, refreshCommandTimeline() {},
    async fetch(url, options) {
        calls.push(JSON.parse(options.body));
        return {async json() { return {success:true, request_id:42}; }};
    }
};
vm.createContext(context);
vm.runInContext(source.slice(start, end), context);
(async () => {
    for (selected of ['CLEAR_POWER_RESETS', 'CLEAR_WDT_RESETS']) {
        confirmed = false; calls = [];
        await context.sendCommand(false);
        assert.equal(calls.length, 0, 'Cancel must not publish');
        confirmed = true;
        await context.sendCommand(true);
        assert.equal(calls.length, 0, 'Broadcast must not publish');
        await context.sendCommand(false);
        assert.equal(calls.length, 1);
        assert.equal(calls[0].cmd_type, selected);
        assert.equal(calls[0].cmd_data, 0);
        assert.equal(calls[0].broadcast, false);
    }
    console.log('PASS: actual clear-command UI: confirmation, cancel, single node and fixed zero data');
})().catch(error => { console.error(error); process.exitCode=1; });
