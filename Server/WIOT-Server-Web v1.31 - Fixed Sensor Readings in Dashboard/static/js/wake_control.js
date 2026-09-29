// Pure WAKE acknowledgement tracking, shared by the dashboard and Node tests.
// MQTT submission is never treated as proof that the remote node is awake.
(function(root) {
    'use strict';
    class WakeTracker {
        constructor() { this.pending = new Map(); this.recent = new Map(); }
        key(company, node) { return `${company}/${node}`; }
        published(company, node, requestId, broadcast = false) {
            const key = this.key(company, broadcast ? '*' : node);
            this.pending.set(key, Number(requestId));
            if (this.pending.size > 256) this.pending.delete(this.pending.keys().next().value);
            if (broadcast) {
                for (const [recentKey, recentId] of this.recent) {
                    if (recentKey.startsWith(`${company}/`) && recentId === Number(requestId)) {
                        this.recent.set(key, recentId);
                        break;
                    }
                }
            }
            return this.recent.get(key) === Number(requestId);
        }
        receive(msg) {
            if (msg.Type !== 'Telemetry' || msg['Wake Command ACK'] !== true ||
                msg['Power Mode'] !== 'REMOTE_WAKE' || msg['Power State'] !== 'ACTIVE' ||
                !Number.isInteger(msg['Wake Request ID']) || msg['Wake Request ID'] <= 0) return false;
            const key = this.key(msg.Company, msg['Node ID']);
            const duplicate = this.recent.get(key) === msg['Wake Request ID'];
            this.recent.set(key, msg['Wake Request ID']);
            // Bound memory even if a supervisor receives many unrelated nodes.
            if (this.recent.size > 256) this.recent.delete(this.recent.keys().next().value);
            const broadcastKey = this.key(msg.Company, '*');
            const broadcastMatch = this.pending.get(broadcastKey) === msg['Wake Request ID'];
            if (broadcastMatch) this.recent.set(broadcastKey, msg['Wake Request ID']);
            return !duplicate && (this.pending.get(key) === msg['Wake Request ID'] || broadcastMatch);
        }
        waiting(company, node, requestId) {
            const key = this.key(company, node);
            return this.pending.get(key) === Number(requestId) &&
                   this.recent.get(key) !== Number(requestId);
        }
    }
    if (typeof module !== 'undefined' && module.exports) module.exports = {WakeTracker};
    else root.WakeTracker = WakeTracker;
})(typeof globalThis !== 'undefined' ? globalThis : this);
