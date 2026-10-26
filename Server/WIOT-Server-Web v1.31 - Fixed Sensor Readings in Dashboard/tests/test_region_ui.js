'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {WakeTracker} = require('../static/js/wake_control.js');
const {safeHtml} = require('../static/js/safe_html.js');
const tracker = new WakeTracker();
tracker.published('Company_1',3,42,false,'Region_2');
const ack = {Type:'Telemetry',Company:'Company_1',Region:'Region_1','Node ID':3,
    'Wake Command ACK':true,'Power Mode':'REMOTE_WAKE','Power State':'ACTIVE','Wake Request ID':42};
assert.equal(tracker.receive(ack),false);
ack.Region='Region_2';assert.equal(tracker.receive(ack),true);
tracker.published('Company_1',3,43,true,'Region_1');
ack['Wake Request ID']=43;assert.equal(tracker.receive(ack),false);
ack.Region='Region_1';assert.equal(tracker.receive(ack),true);

const source=fs.readFileSync(path.join(__dirname,'../static/js/app.js'),'utf8');
const settings={getSelectedCompany:()=> 'Company_1',MAP_STORAGE_KEY:'map',
    localStorage:{getItem:()=>JSON.stringify({'Company_1_3':[30,31]})},
    loadThresholds:()=>({'Company_1':{'3':{flow_max:99}}})};
vm.createContext(settings);
vm.runInContext(source.slice(source.indexOf('function getNodeThreshold('),source.indexOf('function saveThresholds(')),settings);
assert.equal(settings.getNodeThreshold('Company_1/Region_1','3').flow_max,99);
assert.equal(settings.getNodeThreshold('Company_1/Region_2','3').flow_max,'');
vm.runInContext(source.slice(source.indexOf('function loadNodePositions('),source.indexOf('function saveNodePositions(')),settings);
const positions=settings.loadNodePositions();
assert.equal(JSON.stringify(positions[JSON.stringify(['Company_1','Region_1','3'])]),'[30,31]');
assert.equal(positions[JSON.stringify(['Company_1','Region_2','3'])],undefined);
const timeline=source.slice(source.indexOf('let commandTimelineBusy'),source.indexOf('function setWakeStatus'));
let region='Region_1', finish, url;
const body={innerHTML:'original',textContent:''},status={textContent:''};
const context={safeHtml,URLSearchParams,Date,getSelectedCompany:()=> 'Company_1',getSelectedRegion:()=>region,
    document:{hidden:false,querySelector:()=>body,getElementById:()=>status},setInterval(){},
    fetch(value){url=value;return new Promise(resolve=>finish=resolve);}};
vm.createContext(context);vm.runInContext(timeline,context);
(async()=>{
    const pending=context.refreshCommandTimeline();
    assert.ok(url.includes('region=Region_1'));
    region='Region_2';finish({ok:true,json:async()=>({success:true,commands:[]})});await pending;
    assert.equal(body.innerHTML,'original','Late response from another region must not replace current panel');
    console.log('PASS: regional WAKE/broadcast correlation and actual timeline region-switch race');
})().catch(error=>{console.error(error);process.exitCode=1;});
