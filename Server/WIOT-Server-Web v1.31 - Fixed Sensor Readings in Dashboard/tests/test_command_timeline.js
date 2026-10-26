'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {safeHtml} = require('../static/js/safe_html.js');
const source = fs.readFileSync(path.join(__dirname,'../static/js/app.js'),'utf8');
const code = source.slice(source.indexOf('let commandTimelineBusy'),source.indexOf('function setWakeStatus'));
const body={innerHTML:'',textContent:''}, status={textContent:''};
let company='Company_1', resolveFetch, calls=0, poller;
const context={safeHtml, URLSearchParams, Date,
    getSelectedCompany:()=>company, getSelectedRegion:()=> 'Region_1',
    document:{hidden:false,querySelector:()=>body,getElementById:(id)=>id==='Commands'?{classList:{contains:()=>true}}:status},
    setInterval:(fn,ms)=>{assert.equal(ms,5000);poller=fn;},
    fetch:()=>{calls++;return new Promise(resolve=>{resolveFetch=resolve;});}
};
vm.createContext(context); vm.runInContext(code,context);
const row={request_id:42,created_at:1000,node_id:7,cmd_type:'VALVE',cmd_data:0,
    actor:'<img src=x onerror=attack()>',state:'outcome_unknown',outcome_uncertain:true,
    reason:'<script>attack()</script>',attempts:1,broker_confirmed_at:1001};
(async()=>{
    const pending=context.refreshCommandTimeline();
    await context.refreshCommandTimeline(); assert.equal(calls,1); // overlapping poll suppressed
    resolveFetch({ok:true,json:async()=>({success:true,commands:[row]})}); await pending;
    assert.ok(body.innerHTML.includes('Outcome unknown'));
    assert.ok(body.innerHTML.includes('&lt;img'));
    assert.ok(!body.innerHTML.includes('<script>'));
    assert.ok(!body.innerHTML.includes('Node accepted'));
    const prior=body.innerHTML;
    const changing=context.refreshCommandTimeline(); company='Company_2';
    resolveFetch({ok:true,json:async()=>({success:true,commands:[]})}); await changing;
    assert.equal(body.innerHTML,prior); // wrong company's late response cannot overwrite panel
    const rejected=context.refreshCommandTimeline();
    resolveFetch({ok:false,json:async()=>({success:false,error:'Timeline unavailable'})}); await rejected;
    assert.equal(body.textContent,''); assert.equal(status.textContent,'Timeline unavailable');
    context.document.hidden=true;poller();assert.equal(calls,3);
    console.log('PASS: actual command timeline: escaping, outcome labels, bounded poll, company race and errors');
})().catch(error=>{console.error(error);process.exitCode=1;});
