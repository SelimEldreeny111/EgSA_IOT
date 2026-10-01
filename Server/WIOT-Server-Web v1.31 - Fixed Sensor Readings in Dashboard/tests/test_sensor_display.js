'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
// Run the real render function with a small DOM fixture, not copied UI logic.
const source = fs.readFileSync(path.join(__dirname, '../static/js/app.js'), 'utf8');
const start = source.indexOf('function renderLiveNode()');
const end = source.indexOf('// ─── Chart', start);
assert.ok(start >= 0 && end > start);
const elements = new Map();
const element = id => {
    if (!elements.has(id)) elements.set(id, {value:'7', textContent:'', className:'', classList:{toggle(){}}});
    return elements.get(id);
};
const context = {
    document:{getElementById:element}, nodeLatestData:{}, Date, Number,
    formatNumberOrDash:(n,digits=3)=>Number(n).toFixed(digits),
    nodeStatusLabel:()=> 'Open', getElapsedLabel:()=> 'now',
    flowMeterName:()=> 'Supmea', updateGauges(){}, updateNodeStatusTexts(){}
};
vm.createContext(context);
vm.runInContext(source.slice(start,end),context);
const good = {'WDT Resets':27, 'Sensor Mask':15, 'Flow Live Valid':1, 'Period Totals Valid':1,
    'Cumulative Totals Valid':1, Flow:12, Velocity:2, 'Flow Day':3,
    'Flow Month':4, 'Flow Year':5, 'Forward Total Liters':10000,
    'Reverse Total Liters':1000, 'Net Total Liters':9000,
    'Soil Valid':1, 'Soil Temp':22, 'Soil Moist':55,
    'EC Valid':1, 'EC Temp':23, 'EC Moist':56, 'EC Cond':1500,
    'Secondary Flow Meter':{flow_meter_name:'Supmea', flow_live_valid:1,
        flow_rate:36, flow_period_totals_valid:1, flow_rate_per_day:6,
        flow_rate_per_month:7, flow_rate_per_year:8}};
context.nodeLatestData['7']=good;
context.renderLiveNode();
assert.equal(element('m-flow').textContent,'12.000');
assert.equal(element('m-soil-temp').textContent,'22.0');
assert.equal(element('m-wdt-resets').textContent,'27');
const failed = {...good, 'Flow Live Valid':0, 'Period Totals Valid':0,
    'Cumulative Totals Valid':0, 'Soil Valid':0, 'EC Valid':0,
    'Secondary Flow Meter':{...good['Secondary Flow Meter'], flow_live_valid:0, flow_period_totals_valid:0}};
context.nodeLatestData['7']=failed;
context.renderLiveNode();
for (const id of ['m-flow','m-velocity','m-fday','m-fmonth','m-fyear',
    'm-forward-total','m-reverse-total','m-net-total','m-secondary-flow',
    'm-secondary-day','m-secondary-month','m-secondary-year']) {
    assert.equal(element(id).textContent,'0.000',id);
}
for (const id of ['m-soil-temp','m-soil-moist','m-ec-temp','m-ec-moist']) {
    assert.equal(element(id).textContent,'0.0',id);
}
assert.equal(element('m-ec-cond').textContent,'0');
assert.equal(element('m-wdt-resets').textContent,'27'); // sensor failure does not clear node diagnostics
assert.equal(element('m-soil-status').textContent,'Sensor Error');
assert.equal(element('m-ec-status').textContent,'Sensor Error');
context.nodeLatestData['7']=good;
context.renderLiveNode();
assert.equal(element('m-flow').textContent,'12.000');
assert.equal(element('m-soil-status').textContent,'Normal');
context.nodeLatestData['7']={...good, 'WDT Resets':4294967295};
context.renderLiveNode();
assert.equal(element('m-wdt-resets').textContent,'4294967295');
context.nodeLatestData['7']={...good};
delete context.nodeLatestData['7']['WDT Resets'];
context.renderLiveNode();
assert.equal(element('m-wdt-resets').textContent,'0'); // old firmware omitted the field
delete context.nodeLatestData['7'];
context.renderLiveNode();
assert.equal(element('m-flow').textContent,'-'); // offline/no message is distinct
assert.equal(element('m-wdt-resets').textContent,'-');
console.log('PASS: real dashboard render valid -> unavailable zeros -> recovery');
