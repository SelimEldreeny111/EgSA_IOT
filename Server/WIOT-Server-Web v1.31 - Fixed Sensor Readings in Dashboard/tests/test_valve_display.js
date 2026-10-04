'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../static/js/app.js'), 'utf8');
const start = source.indexOf('const VALVE_LABELS =');
const end = source.indexOf('function updateGauges', start);
assert.ok(start > 0 && end > start);
const events = [];
const elements = {
    'status-card': {classList: {toggle: (key, on) => events.push([key, on])}},
    'status-icon': {className: '', style: {}}
};
const context = {document: {getElementById: id => elements[id]}};
vm.createContext(context); vm.runInContext(source.slice(start, end), context);
for (const [code, label] of [[0, 'Closed / OFF (commanded)'], [1, 'Open / ON (commanded)'],
    [2, 'Unknown — not confirmed'], [3, 'Fault — position unknown']]) {
    assert.equal(context.nodeStatusLabel(code), label);
    assert.equal(context.nodeStatusLabel(String(code)), label);
    events.length = 0; context.updateStatusCard(code);
    assert.equal(events.find(row => row[0] === 'status-card-ok')[1], code === 1);
    if (code >= 2) assert.equal(elements['status-icon'].className, 'bi bi-toggles icon');
}
assert.equal(context.nodeStatusLabel(undefined), '-');
assert.equal(context.nodeStatusLabel(99), 'Unknown (99)');
assert.ok(source.includes('VALVE published; waiting for pulse completion acknowledgement.'));
console.log('PASS: real valve labels, Unknown/Fault UI, publication is not completion');
