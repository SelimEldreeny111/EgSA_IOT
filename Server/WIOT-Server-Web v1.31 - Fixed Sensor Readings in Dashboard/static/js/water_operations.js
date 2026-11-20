/* Render tenant-scoped incidents without interpreting data as HTML. */
(function () {
    'use strict';
    const rules = {
        quiet_flow: 'Unexpected flow during quiet hours', high_flow: 'High flow',
        reverse_flow: 'Reverse flow', meter_unavailable: 'Reporting meter unavailable',
        sensor_unavailable: 'Soil sensor unavailable', stale_sample: 'Stale measurement',
        sample_unverified: 'Measurement freshness unverified', rtc_untrusted: 'Untrusted node clock',
        low_battery: 'Low battery', watchdog_resets: 'Watchdog reset detected',
        power_resets: 'Power reset detected', node_offline: 'Node offline'
    };
    const states = {
        online: 'Online', overdue: 'Overdue', offline: 'Offline', unobserved: 'MQTT unobserved',
        awaiting_report: 'Awaiting report', gateway_unavailable: 'Gateway unavailable',
        disabled: 'Monitoring paused', valid: 'Valid', unavailable: 'Unavailable',
        unknown: 'Unknown', fresh: 'Fresh', delayed: 'Delayed', untrusted: 'Untrusted',
        unverified: 'Unverified'
    };
    const form = document.getElementById('operations-form');
    const panel = document.getElementById('WaterOperations');
    if (!panel) return;
    const byId = id => document.getElementById('operations-' + id);
    const query = () => new URLSearchParams({company: getSelectedCompany(), region: getSelectedRegion()});
    const date = epoch => epoch == null ? '—' : new Date(epoch * 1000).toLocaleString();
    let scope = '';
    let version = 0;
    let before = null;
    let next = null;

    function row(values) {
        const tr = document.createElement('tr');
        for (const value of values) {
            const td = document.createElement('td');
            td.textContent = String(value);
            tr.append(td);
        }
        return tr;
    }

    function empty(body, columns, message) {
        const tr = row([message]);
        tr.firstElementChild.colSpan = columns;
        tr.firstElementChild.className = 'status-note text-center py-3';
        body.replaceChildren(tr);
    }

    function action(label, labelForReader, handler) {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'btn btn-sm btn-outline-secondary';
        button.textContent = label;
        button.setAttribute('aria-label', labelForReader);
        button.addEventListener('click', handler);
        return button;
    }

    async function jsonResponse(url, options) {
        const response = await fetch(url, options);
        const data = await response.json().catch(() => ({}));
        if (!response.ok || !data || Object.keys(data).length === 0) {
            throw new Error(data.error || 'The server could not complete the request.');
        }
        return data;
    }

    function populateForm(node) {
        byId('settings').open = true;
        form.elements.namedItem('node').value = node.node;
        for (const [key, value] of Object.entries(node.settings)) {
            const field = form.elements.namedItem(key);
            if (key === 'enabled') field.checked = value;
            else if (field) field.value = value == null || (key === 'gateway' && !value) ? '' : value;
        }
        byId('save-result').textContent = '';
        form.elements.namedItem('name').focus();
    }

    function showNodes(data, selectedScope) {
        const body = byId('nodes');
        if (!data.nodes.length) {
            empty(body, form ? 8 : 7, 'No monitored lines for this company and region.');
            return;
        }
        const gateways = new Map(data.gateways.map(gateway => [gateway.gateway_id, gateway.state]));
        const rows = data.nodes.map(node => {
            const gateway = node.settings.gateway;
            const tr = row([
                node.settings.name + ' / ' + node.node, states[node.connectivity], date(node.last_report),
                (node.settings.meter === 1 ? 'TUF' : 'Supmea') + ' · ' + (states[node.meter_state] || 'Unknown') +
                    ' · ' + (states[node.time_quality] || 'Unknown'),
                node.battery_v == null ? '—' : node.battery_v.toFixed(2) + ' V',
                (node.wdt_reset_count ?? '—') + ' / ' + (node.power_reset_count ?? '—'),
                gateway ? gateway + ' · ' + (states[gateways.get(gateway)] || 'Awaiting heartbeat') : '—'
            ]);
            tr.children[1].className = {
                online: 'text-success', overdue: 'text-warning', offline: 'text-danger',
                gateway_unavailable: 'text-warning'
            }[node.connectivity] || 'status-note';
            if (form) {
                const edit = document.createElement('td');
                edit.append(action('Edit', 'Edit settings for node ' + node.node, () => {
                    if (query().toString() === selectedScope) populateForm(node);
                }));
                tr.append(edit);
            }
            return tr;
        });
        body.replaceChildren(...rows);
    }

    function evidence(incident) {
        const data = incident.evidence;
        if (data.last_flow_m3h != null) {
            const duration = data.observed_seconds + ' s observed';
            const volume = data.volume_liters == null ? 'volume unavailable' :
                data.volume_liters + ' L ' + (data.complete_volume ? 'during observed flow' : 'partial');
            return data.first_flow_m3h.toFixed(3) + ' → ' + data.last_flow_m3h.toFixed(3) +
                ' m³/h · ' + duration + ' · ' + volume;
        }
        if (data.voltage != null) return data.voltage.toFixed(2) + ' V (limit ' + data.threshold + ' V)';
        if (data.counter != null) return 'Count ' + data.counter + ' (+' + data.increase + ')';
        if (data.sensors) return data.sensors.join(', ');
        if (data.measured_at != null) return 'Measured ' + date(data.measured_at);
        if (incident.kind === 'node_offline') return 'Last report ' + date(data.last_report);
        return date(incident.last_at);
    }

    function showIncidents(incidents, selectedScope) {
        const body = byId('incidents');
        if (!incidents.length) {
            empty(body, 6, 'No incidents recorded.');
            return;
        }
        body.replaceChildren(...incidents.map(incident => {
            const state = incident.closed_at == null ? 'Open' :
                incident.close_reason === 'monitoring_changed' ? 'Monitoring changed' : 'Resolved';
            const tr = row([rules[incident.kind] || incident.kind, incident.node, state,
                date(incident.opened_at), evidence(incident),
                incident.acknowledged_by ? incident.acknowledged_by + ' · ' + date(incident.acknowledged_at) : 'Unacknowledged']);
            tr.children[2].className = state === 'Open' ? 'text-danger' : 'status-note';
            if (form && !incident.acknowledged_at) {
                tr.children[5].replaceChildren(action('Acknowledge', 'Acknowledge incident ' + incident.id, async event => {
                    if (query().toString() !== selectedScope) return;
                    const button = event.currentTarget;
                    button.disabled = true;
                    try {
                        await jsonResponse('/api/operations/incidents/' + incident.id + '/acknowledge?' + selectedScope,
                            {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'});
                        if (query().toString() === selectedScope) refresh();
                    } catch (error) {
                        if (query().toString() === selectedScope) {
                            button.disabled = false;
                            byId('action-result').textContent = error.message;
                        }
                    }
                }));
            }
            return tr;
        }));
    }

    async function refresh() {
        const params = query();
        const selectedScope = params.toString();
        if (scope !== selectedScope) {
            scope = selectedScope;
            before = null;
            next = null;
            byId('nodes').replaceChildren();
            byId('incidents').replaceChildren();
            byId('action-result').textContent = '';
            if (form) {
                form.reset();
                byId('save-result').textContent = '';
            }
        }
        const current = ++version;
        if (before) params.set('before', before);
        const exportLink = byId('export');
        exportLink.href = '/api/operations/export?' + selectedScope;
        try {
            const data = await jsonResponse('/api/operations?' + params);
            if (current !== version || selectedScope !== query().toString()) return;
            byId('observation').textContent = data.observing ?
                'Monitoring incoming Status reports.' : 'The server is not observing MQTT. Offline detection is paused.';
            showNodes(data, selectedScope);
            showIncidents(data.incidents, selectedScope);
            next = data.incidents.length === 50 ? data.incidents[49].id : null;
            byId('older').disabled = !next;
            byId('newest').disabled = !before;
        } catch (error) {
            if (current === version && selectedScope === query().toString())
                byId('observation').textContent = error.message;
        }
    }

    byId('refresh').addEventListener('click', refresh);
    byId('older').addEventListener('click', () => { if (next) { before = next; refresh(); } });
    byId('newest').addEventListener('click', () => { before = null; refresh(); });
    byId('tab').addEventListener('shown.bs.tab', refresh);
    for (const filter of ['cfg-company', 'cfg-region']) {
        document.getElementById(filter)?.addEventListener('change', () => {
            if (panel.classList.contains('active')) refresh();
        });
    }
    if (form) form.addEventListener('submit', async event => {
        event.preventDefault();
        const selectedScope = query().toString();
        if (scope !== selectedScope) { refresh(); return; }
        const submit = form.querySelector('[type="submit"]');
        submit.disabled = true;
        const data = Object.fromEntries(new FormData(form));
        const node = data.node;
        delete data.node;
        if (!data.max_gap_seconds) delete data.max_gap_seconds;
        data.enabled = form.elements.namedItem('enabled').checked;
        try {
            await jsonResponse('/api/operations/profiles/' + encodeURIComponent(node) + '?' + selectedScope,
                {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data)});
            if (query().toString() !== selectedScope) return;
            byId('save-result').textContent = 'Settings saved.';
            refresh();
        } catch (error) {
            if (query().toString() === selectedScope) byId('save-result').textContent = error.message;
        } finally {
            submit.disabled = false;
        }
    });
    window.setInterval(() => { if (panel.classList.contains('active')) refresh(); }, 10000);
}());
