'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const view=require('../static/js/flash_archive.js');
assert.match(view.memoryText(null),/No flash status/);
assert.match(view.memoryText({state_name:'Ready',record_count:24,maximum_records:14322,
    used_bytes:12288,free_bytes:7320576,capacity_bytes:8388608,generation:2,
    clear_sectors_remaining:0,dropped_samples:0,corrupt_records:0,rtc_trusted:true}),/24 \/ 14322/);
assert.match(view.transferText({request:1,phase:3,result:4,complete:0,received:1,total:2}),/Incomplete: Cancelled/);
assert.match(view.transferText({request:1,phase:3,result:0,complete:0,received:1,total:2}),/Incomplete/);
assert.match(view.transferText({request:1,phase:3,result:0,complete:1,received:2,total:2}),/Complete/);
assert.match(view.transferText({request:1,phase:1,result:8,complete:0,received:0,total:0}),/Rejected: Busy/);
const source=fs.readFileSync(path.join(__dirname,'../static/js/flash_archive.js'),'utf8');
assert(!source.includes('innerHTML'));
assert(source.includes('event.Region!==selected.region'));
console.log('PASS flash archive progress and safe scoped rendering');
