/* Gateway life uses server receive time and remains independent of sensor reports. */
(function () {
    'use strict';
    let loading = false;
    let displayedScope = '';

    function duration(seconds) {
        const value = Math.max(0, Number(seconds) || 0);
        const days = Math.floor(value / 86400);
        const hours = Math.floor(value % 86400 / 3600);
        const minutes = Math.floor(value % 3600 / 60);
        return (days ? days + 'd ' : '') + hours + 'h ' + minutes + 'm ' + Math.floor(value % 60) + 's';
    }

    async function refresh() {
        const body = document.getElementById('gateway-status-rows');
        const note = document.getElementById('gateway-monitor-note');
        if (!body || !note || loading) return;
        const company = getSelectedCompany();
        const region = getSelectedRegion();
        const scope = JSON.stringify([company, region]);
        if (scope !== displayedScope) {
            body.replaceChildren();
            note.textContent = 'Loading gateways.';
            displayedScope = scope;
        }
        loading = true;
        try {
            const response = await fetch('/api/gateways?' + new URLSearchParams({ company, region }));
            if (!response.ok) throw new Error('Gateway status query failed');
            const data = await response.json();
            if (company !== getSelectedCompany() || region !== getSelectedRegion()) return;
            body.replaceChildren();
            note.textContent = !data.observing ? 'Connect the server to MQTT to observe gateway life.' :
                data.gateways.length ? 'Overdue after two missed heartbeat intervals. Offline after three.' :
                'No gateway heartbeat received for this company and region.';
            for (const gateway of data.gateways) {
                const row = document.createElement('tr');
                const labels = { online: 'Online', overdue: 'Overdue', offline: 'Offline', unobserved: 'Awaiting heartbeat' };
                const values = [gateway.gateway_id, labels[gateway.state] || 'Unknown',
                    new Date(gateway.received_at * 1000).toLocaleString(), duration(gateway.uptime_seconds),
                    gateway.transport, gateway.received_node_frames + ' / ' + gateway.forwarded_node_frames,
                    gateway.forward_failures,
                    gateway.has_node_uplink ? duration(gateway.last_node_age_seconds) + ' before heartbeat' : 'No node reports yet',
                    gateway.wdt_reset_count + ' / ' + gateway.power_reset_count];
                for (const value of values) {
                    const cell = document.createElement('td');
                    cell.textContent = String(value);
                    row.appendChild(cell);
                }
                row.children[1].className = { online: 'text-success', overdue: 'text-warning', offline: 'text-danger' }[gateway.state] || 'text-muted';
                body.appendChild(row);
            }
        } catch (error) {
            if (company === getSelectedCompany() && region === getSelectedRegion()) {
                body.replaceChildren();
                note.textContent = 'Gateway status is unavailable. The next check will retry.';
            }
        } finally {
            loading = false;
        }
    }

    window.addEventListener('load', () => {
        refresh();
        window.setInterval(refresh, 5000);
    });
}());
