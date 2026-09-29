'use strict';
const assert = require('node:assert/strict');
const {WakeTracker} = require('../static/js/wake_control.js');
const tracker = new WakeTracker();
const ack = {Type:'Telemetry', Company:'Test', 'Node ID':7, 'Wake Command ACK':true,
    'Power Mode':'REMOTE_WAKE', 'Power State':'ACTIVE', 'Wake Request ID':42};
assert.equal(tracker.published('Test',7,42),false); // publication is not acknowledgement
assert.equal(tracker.waiting('Test',7,42),true);
for (const update of [{'Wake Request ID':43}, {'Node ID':8}, {Company:'Other'},
    {'Wake Command ACK':false}, {'Power Mode':'NORMAL'}, {'Power State':'REACHABLE_IDLE'}, {Type:'Status'}]) {
    assert.equal(tracker.receive({...ack,...update}),false);
}
assert.equal(tracker.receive(ack),true);
assert.equal(tracker.waiting('Test',7,42),false);
assert.equal(tracker.receive(ack),false); // duplicate ACK does not toast repeatedly
const early = new WakeTracker();
assert.equal(early.receive(ack),false);
assert.equal(early.published('Test',7,42),true); // ACK before HTTP response
const broadcast = new WakeTracker();
assert.equal(broadcast.published('Test',7,42,true),false);
assert.equal(broadcast.receive({...ack,'Node ID':8}),true);
assert.equal(broadcast.waiting('Test','*',42),false); // at least one, not all nodes
assert.equal(broadcast.receive({...ack,'Node ID':9}),true);
console.log('PASS: WAKE UI pending/ACK correlation, wrong node/company, duplicate, early response and broadcast');
