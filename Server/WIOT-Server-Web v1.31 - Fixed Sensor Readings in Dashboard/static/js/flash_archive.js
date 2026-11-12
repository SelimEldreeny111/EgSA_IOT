// Archive replies stay separate from the live sample/charts pipeline.
(function(root) {
    'use strict';
    function memoryText(info) {
        if (!info) return 'No flash status received. Send FLASH_STATUS to the node.';
        const nextClear = info.next_clear_epoch
            ? `Next automatic clear (UTC): ${new Date(info.next_clear_epoch * 1000).toISOString()}.`
            : 'No automatic clear scheduled.';
        return `${info.state_name}: ${info.record_count} / ${info.maximum_records} frames; ` +
            `${info.used_bytes} bytes occupied, ${info.free_bytes} free, ${info.capacity_bytes} total. ` +
            `Generation ${info.generation}; erase sectors remaining: ${info.clear_sectors_remaining}. ` +
            `Dropped samples: ${info.dropped_samples}; corrupt records: ${info.corrupt_records}. ` +
            `RTC trusted: ${info.rtc_trusted ? 'yes' : 'no'}. ${nextClear}`;
    }
    function transferText(t) {
        if (!t) return 'No download transfer received.';
        const results=['OK','Empty','Not ready','Time untrusted','Cancelled','Retention changed','ACK timeout','Read/encode failure','Busy'];
        const state=t.complete ? 'Complete' : t.phase===3 ? `Incomplete: ${results[t.result] || 'Unknown result'}` : t.result ? `Rejected: ${results[t.result] || 'Unknown result'}` : t.phase===1 ? 'Preparing' : 'Receiving';
        return `Request ${t.request}: ${state}; ${t.received} / ${t.total} records persisted.`;
    }
    if (typeof module !== 'undefined' && module.exports) { module.exports={memoryText,transferText}; return; }
    function scope() {
        return {company:getSelectedCompany(),region:getSelectedRegion(),node:document.getElementById('cmd-node')?.value || '1'};
    }
    function query(s) { return new URLSearchParams(s).toString(); }
    function same(a,b) { return a.company===b.company && a.region===b.region && a.node===b.node; }
    root.resetFlashArchiveView=function() {
        clearTimeout(refreshTimer);
        const memory=document.getElementById('flash-memory-summary');
        if (!memory) return;
        memory.textContent='Selection changed. Refresh the server archive or send FLASH_STATUS.';
        document.getElementById('flash-transfer-summary').textContent='No transfer selected.';
        document.getElementById('flash-records-body').replaceChildren();
    };
    root.refreshFlashArchive=async function() {
        const selected=scope();
        try {
            const [statusResponse,rowsResponse]=await Promise.all([
                fetch('/api/flash/status?'+query(selected)),fetch('/api/flash/records?'+query(selected))]);
            if (!statusResponse.ok || !rowsResponse.ok) throw new Error('Archive request failed');
            const [status,rows]=await Promise.all([statusResponse.json(),rowsResponse.json()]);
            if (!same(selected,scope())) return;
            document.getElementById('flash-memory-summary').textContent=
                `${selected.company} / ${selected.region} / Node ${selected.node} — `+memoryText(status.memory);
            document.getElementById('flash-transfer-summary').textContent=transferText(status.transfers?.[0]);
            const body=document.getElementById('flash-records-body');
            body.replaceChildren();
            for (const row of rows.records || []) {
                const tr=document.createElement('tr');
                for (const value of [`${row.generation} / ${row.sequence}`,new Date(row.epoch*1000).toLocaleString(),
                    row.data.flow_rate,row.data.battery_voltage,row.data.soil_moisture]) {
                    const td=document.createElement('td');td.textContent=String(value ?? '');tr.appendChild(td);
                }
                body.appendChild(tr);
            }
        } catch (error) {
            if (same(selected,scope())) document.getElementById('flash-memory-summary').textContent=error.message;
        }
    };
    root.downloadFlashCsv=function() { root.location.assign('/api/flash/records?'+query({...scope(),format:'csv'})); };
    let refreshTimer;
    if (typeof socket !== 'undefined') socket.on('flash_event',function(event) {
        if (!document.getElementById('flash-memory-summary')) return;
        const selected=scope();
        if (event.Company!==selected.company || event.Region!==selected.region || String(event['Node ID'])!==selected.node) return;
        clearTimeout(refreshTimer);refreshTimer=setTimeout(root.refreshFlashArchive,250);
    });
})(typeof globalThis !== 'undefined' ? globalThis : this);
