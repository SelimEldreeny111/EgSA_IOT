const socket = io();
const THEME_KEY = 'wiot_theme';

function getPreferredTheme() {
    return localStorage.getItem(THEME_KEY) || 'dark';
}

function getThemeColors() {
    const styles = getComputedStyle(document.documentElement);
    return {
        text: styles.getPropertyValue('--wiot-text').trim(),
        muted: styles.getPropertyValue('--wiot-muted').trim(),
        grid: styles.getPropertyValue('--wiot-border').trim()
    };
}

function updateThemeButton(theme) {
    const btn = document.getElementById('theme-toggle');
    if (!btn) return;
    const isLight = theme === 'light';
    btn.innerHTML = `<i class="bi ${isLight ? 'bi-moon-stars' : 'bi-sun'}"></i>`;
    btn.setAttribute('aria-label', isLight ? 'Switch to dark mode' : 'Switch to light mode');
    btn.setAttribute('title', isLight ? 'Switch to dark mode' : 'Switch to light mode');
}

function updateChartTheme() {
    if (!myChart) return;
    const colors = getThemeColors();
    myChart.options.scales.y.ticks.color = colors.muted;
    myChart.options.scales.y.grid.color = colors.grid;
    myChart.options.scales.y1.ticks.color = colors.muted;
    myChart.options.scales.x.ticks.color = colors.muted;
    myChart.options.scales.x.grid.color = colors.grid;
    myChart.options.plugins.legend.labels.color = colors.text;
    myChart.update('none');
}

function getMapTileUrl() {
    const theme = document.documentElement.getAttribute('data-bs-theme') || 'dark';
    return theme === 'light'
        ? 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png'
        : 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png';
}

function updateMapTheme() {
    if (!mapTileLayer) return;
    mapTileLayer.setUrl(getMapTileUrl());
}

function applyTheme(theme) {
    const nextTheme = theme === 'light' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-bs-theme', nextTheme);
    localStorage.setItem(THEME_KEY, nextTheme);
    updateThemeButton(nextTheme);
    updateChartTheme();
    updateMapTheme();
}


// ─── State ────────────────────────────────────────────────────────────────────
let nodeLatestData = {};
let nodeHistoryData = {};
let stimePeriodicHandle = null;
const COMPANY_NODE_MAP = { Company_1: ['1','2','3'], Company_2: ['1','2'] };
const MAX_POINTS = 50;
let myChart = null;
let chartWindow = MAX_POINTS;
let wiotMap = null;
let mapTileLayer = null;
let nodeMarkers = {};
let nodePositions = {};
let alertCooldowns = {};
let alertCount = 0;
let isBrokerConnected = false;
const IS_SUPERVISOR = document.body.dataset.supervisor === '1' || document.body.dataset.role === 'monitor';
let latestMessageTime = null;
let latestMessageEpoch = null;
let freshnessInterval = null;
const STALE_WARNING_SECONDS = 30;
const STALE_CRITICAL_SECONDS = 60;
const BROKER_STORAGE_KEY = 'wiot_last_broker_config';
let prevGaugeVals = { flow: null, vel: null };
const GAUGE_ARC_LEN  = 340; // π × 108 ≈ 340
const GAUGE_DEFAULTS = { flow: 100, vel: 5 };

applyTheme(getPreferredTheme());

function formatNumberOrDash(value, decimals = 2) {
    if (value === '-' || value === null || value === undefined || value === '') return '-';
    const n = Number(value);
    return Number.isFinite(n) ? n.toFixed(decimals) : '-';
}

function flowMeterName(value) {
    return ({ 0: 'None/Unknown', 1: 'TUF', 2: 'Supmea' })[Number(value)] || `Unknown (${value})`;
}

function flowPeriodSourceName(value) {
    return ({ 0: 'Unknown', 1: 'Meter native', 2: 'Node RTC calculated' })[Number(value)] || `Unknown (${value})`;
}

function flowPeriodQualityName(value) {
    return ({ 0: 'Invalid', 1: 'Valid', 2: 'Partial', 3: 'Estimated', 4: 'Counter reset', 5: 'Anomaly', 6: 'Time uncertain' })[Number(value)] || `Unknown (${value})`;
}

function getSelectedCompany() {
    return document.getElementById('cfg-company')?.value || 'Company_1';
}

function getAllowedNodeIds() {
    const company = getSelectedCompany();
    return COMPANY_NODE_MAP[company] || ['1','2','3','4','5'];
}
function getAllowedNodeText() { return getAllowedNodeIds().join(', '); }

function updateFleetSummary() {
    const allowedIds = getAllowedNodeIds();
    const activeCount = allowedIds.filter(nid => isNodeActive(nid)).length;
    const setText = (id, text) => {
        const el = document.getElementById(id);
        if (el) el.textContent = text;
    };
    setText('fleet-total', allowedIds.length);
    setText('fleet-active', activeCount);
    setText('fleet-alerts', alertCount);
    setText('fleet-last', latestMessageTime || 'No data');
}

function updateCommandAvailability() {
    const queued = document.getElementById('cmd-delivery')?.value === 'next_wake';
    const sendBtn = document.getElementById('send-command-btn');
    const broadcastBtn = document.getElementById('broadcast-command-btn');
    if (sendBtn) sendBtn.disabled = !queued && !isBrokerConnected;
    if (broadcastBtn) broadcastBtn.disabled = queued || !isBrokerConnected;
    const ttl = document.getElementById('cmd-ttl');
    if (ttl) ttl.disabled = !queued;
    const startBtn = document.getElementById('start-stime-btn');
    if (startBtn) startBtn.disabled = queued || !isBrokerConnected ||
        document.getElementById('cmd-type')?.value !== 'STIME' || !!stimePeriodicHandle;
}

function saveBrokerConfig(settings) {
    try {
        localStorage.setItem(BROKER_STORAGE_KEY, JSON.stringify(settings));
    } catch (err) {
        console.warn('Unable to persist broker config', err);
    }
}

function loadBrokerConfig() {
    try {
        return JSON.parse(localStorage.getItem(BROKER_STORAGE_KEY)) || null;
    } catch {
        return null;
    }
}

function restoreBrokerConfig() {
    const saved = loadBrokerConfig();
    if (!saved) return;
    const brokerInput = document.getElementById('cfg-broker');
    const portInput = document.getElementById('cfg-port');
    const aesInput = document.getElementById('cfg-aes');
    const clientInput = document.getElementById('cfg-client');
    if (brokerInput) brokerInput.value = saved.broker || brokerInput.value;
    if (portInput) portInput.value = saved.port || portInput.value;
    if (aesInput) aesInput.value = saved.aes_key || aesInput.value;
    if (clientInput) clientInput.value = saved.client_id || clientInput.value;
}

function setLiveEmptyState(message, visible) {
    const el = document.getElementById('live-empty-state');
    if (!el) return;
    el.textContent = message;
    el.classList.toggle('d-none', !visible);
}

function getElapsedLabel(seconds) {
    if (seconds === null || seconds === undefined) return 'No update yet';
    if (seconds < 60) return `${seconds}s ago`;
    const mins = Math.floor(seconds / 60);
    return mins === 1 ? '1 minute ago' : `${mins} minutes ago`;
}

function syncNodeSelection(nodeId) {
    const selectors = ['live-node-select', 'graph-node-select', 'cmd-node'];
    selectors.forEach(id => {
        const el = document.getElementById(id);
        if (el) el.value = nodeId;
    });
    renderLiveNode();
    // Load the node's real chart history from the DB if we don't already have
    // points buffered, then render — prevents "no data available" + graph reset
    // when selecting a node whose history was never pre-seeded.
    loadNodeHistory(nodeId).then(renderGraphNode);
    updateNodeStatusTexts();
}

/**
 * Lazily fetch a node's recent chart history from the server and populate
 * nodeHistoryData[nid]. No-op if the node already has buffered points (so we
 * don't clobber the live-updating buffer). Used when a node is selected.
 */
async function loadNodeHistory(nid) {
    if (!nid) return;
    const existing = nodeHistoryData[nid];
    if (existing && existing.flows.length > 0) return; // already have live/seeded points
    try {
        const params = new URLSearchParams({ history_node: nid });
        if (document.body.dataset.role === 'admin' || IS_SUPERVISOR) params.append('company', getSelectedCompany());
        const res = await fetch(`/api/node_latest?${params}`);
        if (!res.ok) return;
        const data = await res.json();
        const bucket = { flows: [], vels: [], lbls: [] };
        (data.history || []).forEach(row => {
            bucket.flows.push(Number(row.flow));
            bucket.vels.push(Number(row.velocity));
            const ts = row.timestamp_epoch != null ? new Date(row.timestamp_epoch * 1000) : new Date(row.timestamp);
            bucket.lbls.push(ts);
        });
        nodeHistoryData[nid] = bucket;
    } catch (err) {
        console.warn('Failed to load node history:', err);
    }
}

function updateFreshnessIndicator() {
    const el = document.getElementById('data-freshness');
    const banner = document.getElementById('live-warning-banner');
    if (!el || !banner) return;
    const dot = el.querySelector('.dot');
    const textEl = el.querySelector('.text');
    if (!latestMessageEpoch) {
        el.className = 'freshness-indicator';
        if (dot) dot.style.background = 'var(--wiot-muted)';
        if (textEl) textEl.textContent = 'No live data';
        banner.classList.add('d-none');
        return;
    }
    const elapsedSeconds = Math.round((Date.now() - latestMessageEpoch) / 1000);
    if (textEl) textEl.textContent = `Last update: ${elapsedSeconds}s ago`;
    if (elapsedSeconds >= STALE_CRITICAL_SECONDS) {
        el.className = 'freshness-indicator danger';
        banner.textContent = 'No data received for 60s — check connection.';
        banner.classList.remove('d-none');
    } else if (elapsedSeconds >= STALE_WARNING_SECONDS) {
        el.className = 'freshness-indicator warn';
        banner.classList.add('d-none');
    } else {
        el.className = 'freshness-indicator ok';
        banner.classList.add('d-none');
    }
}

function startFreshnessTimer() {
    if (freshnessInterval) return;
    freshnessInterval = setInterval(updateFreshnessIndicator, 1000);
    updateFreshnessIndicator();
}

function stopFreshnessTimer() {
    if (freshnessInterval) {
        clearInterval(freshnessInterval);
        freshnessInterval = null;
    }
}

function resetLiveTelemetryState() {
    nodeLatestData = {};
    nodeHistoryData = {};
    latestMessageTime = null;
    latestMessageEpoch = null;
    prevGaugeVals = { flow: null, vel: null };
    setLiveEmptyState('Connect to an MQTT broker to start receiving live data. Use the Connect button above.', true);
    updateFreshnessIndicator();
}

// ─── Toast notifications ──────────────────────────────────────────────────────
function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) { console.warn(message); return; }
    const colors = { success: '#22c55e', danger: '#ef4444', warning: '#f59e0b', info: '#4cc9f0' };
    const icons  = { success: 'bi-check-circle-fill', danger: 'bi-x-circle-fill', warning: 'bi-exclamation-triangle-fill', info: 'bi-info-circle-fill' };
    const id = 'toast-' + Date.now();
    const html = `
    <div id="${id}" class="toast align-items-center border-0 mb-2 show" role="alert" style="background:var(--wiot-surface-2); color:var(--wiot-text); border-left: 4px solid ${colors[type]} !important;">
      <div class="d-flex">
        <div class="toast-body d-flex align-items-center gap-2">
          <i class="bi ${icons[type]}" style="color:${colors[type]};font-size:1.1rem;"></i>
          <span>${message}</span>
        </div>
        <button type="button" class="btn-close me-2 m-auto" data-bs-dismiss="toast"></button>
      </div>
    </div>`;
    container.insertAdjacentHTML('beforeend', html);
    const el = document.getElementById(id);
    const bsToast = new bootstrap.Toast(el, { delay: 4000 });
    bsToast.show();
    el.addEventListener('hidden.bs.toast', () => el.remove());
}

// ─── Confirm dialog (replaces browser confirm()) ──────────────────────────────
function confirmAction(message) {
    return new Promise(resolve => {
        const modal = document.getElementById('confirm-modal');
        document.getElementById('confirm-message').textContent = message;
        const bsModal = new bootstrap.Modal(modal);
        const btnOk = document.getElementById('confirm-ok');
        const handler = () => { bsModal.hide(); btnOk.removeEventListener('click', handler); resolve(true); };
        btnOk.addEventListener('click', handler);
        modal.addEventListener('hidden.bs.modal', () => { btnOk.removeEventListener('click', handler); resolve(false); }, { once: true });
        bsModal.show();
    });
}

// ─── Bootstrap tab side-effects ───────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('#sideTabs button[data-bs-toggle="pill"]').forEach(btn => {
        btn.addEventListener('shown.bs.tab', (e) => {
            const target = e.target.getAttribute('data-bs-target');
            if (target === '#UserMgmt') {
                loadUsers();
                if (document.getElementById('companies-table')) loadCompanies();
            }
            if (target === '#NodeLocation') {
                initMap();
            }
            if (target === '#Commands') {
                loadCommandHistory(1);
            }
            if (target === '#Configuration') {
                renderThresholdTable();
                renderLocationTable();
            }
        });
        btn.addEventListener('hidden.bs.tab', (e) => {
            const from = e.target.getAttribute('data-bs-target');
            if (from === '#Commands') {
                const gostmBody = document.querySelector('#gostm-table tbody');
                if (gostmBody) gostmBody.innerHTML = '';
            }
        });
    });

    // Mobile sidebar toggle
    const toggler = document.getElementById('sidebar-toggler');
    const sidebar = document.querySelector('.sidebar');
    const backdrop = document.getElementById('sidebar-backdrop');
    if (toggler && sidebar) {
        const closeSidebar = () => {
            sidebar.classList.remove('sidebar-open');
            backdrop?.classList.remove('show');
        };
        toggler.addEventListener('click', () => {
            const willOpen = !sidebar.classList.contains('sidebar-open');
            sidebar.classList.toggle('sidebar-open', willOpen);
            backdrop?.classList.toggle('show', willOpen);
        });
        backdrop?.addEventListener('click', closeSidebar);
        document.querySelectorAll('#sideTabs button[data-bs-toggle="pill"]').forEach(btn => {
            btn.addEventListener('shown.bs.tab', closeSidebar);
        });
    }

    const themeToggle = document.getElementById('theme-toggle');
    if (themeToggle) {
        updateThemeButton(getPreferredTheme());
        themeToggle.addEventListener('click', () => {
            const current = document.documentElement.getAttribute('data-bs-theme') || 'dark';
            applyTheme(current === 'dark' ? 'light' : 'dark');
        });
    }

    // Historical table keyword search
    const searchBox = document.getElementById('table-search');
    if (searchBox) {
        searchBox.addEventListener('input', () => {
            const q = searchBox.value.toLowerCase();
            document.querySelectorAll('#message-table tbody tr').forEach(row => {
                row.style.display = row.textContent.toLowerCase().includes(q) ? '' : 'none';
            });
        });
    }
    restoreBrokerConfig();
    setLiveEmptyState('Connect to an MQTT broker to start receiving live data. Use the Connect button above.', true);
    startFreshnessTimer();
    const savedBroker = loadBrokerConfig();
    if (savedBroker && document.getElementById('btn-connect')) {
        setConnIndicator('connecting');
        connect().catch(() => {
            setConnIndicator(false);
        });
    }
    updateFleetSummary();
    updateCommandAvailability();
});

// ─── Connection indicator ─────────────────────────────────────────────────────
function setConnIndicator(connected) {
    const ind = document.getElementById('conn-indicator');
    const isConnected = connected === true || connected === 'connected';
    const isConnecting = connected === 'connecting';
    isBrokerConnected = isConnected;
    if (ind) {
        ind.classList.toggle('connected', isConnected);
        ind.classList.toggle('connecting', isConnecting);
        ind.classList.toggle('disconnected', !isConnected && !isConnecting);
        const text = isConnected ? 'Connected' : isConnecting ? 'Reconnecting…' : 'Disconnected';
        ind.querySelector('.text').textContent = text;
    }
    updateCommandAvailability();
}

// ─── Node selectors ───────────────────────────────────────────────────────────
function initNodeSelectors() {
    const selectors = ['live-node-select', 'graph-node-select', 'cmd-node'];
    const allowedIds = getAllowedNodeIds();
    selectors.forEach(id => {
        const el = document.getElementById(id);
        if (!el) return;
        el.innerHTML = '';
        allowedIds.forEach(nid => {
            const opt = document.createElement('option');
            opt.value = nid;
            opt.textContent = `Node ${nid} (inactive)`;
            el.appendChild(opt);
        });
        el.value = allowedIds[0] || '1';
    });
    updateNodeStatusTexts();
    updateFleetSummary();
}

function refreshNodeSelectors() {
    const selectors = ['live-node-select', 'graph-node-select', 'cmd-node'];
    const activeNodes = Object.keys(nodeLatestData);
    const allowedIds = getAllowedNodeIds();
    selectors.forEach(id => {
        const el = document.getElementById(id);
        if (!el) return;
        const currentVal = el.value || allowedIds[0] || '1';
        el.innerHTML = '';
        allowedIds.forEach(nid => {
            const opt = document.createElement('option');
            opt.value = nid;
            const isActive = activeNodes.includes(nid);
            opt.textContent = `Node ${nid}${isActive ? ' ✔ active' : ' (inactive)'}`;
            if (isActive) opt.style.color = '#4ade80';
            el.appendChild(opt);
        });
        el.value = allowedIds.includes(currentVal) ? currentVal : allowedIds[0] || '1';
    });
    updateNodeStatusTexts();
    updateFleetSummary();
}

function isNodeActive(nodeId) { return Object.prototype.hasOwnProperty.call(nodeLatestData, nodeId); }

function getNodeStatusText(nodeId) {
    if (!nodeId) return `Select a node from: ${getAllowedNodeText()}.`;
    return isNodeActive(nodeId)
        ? `Node ${nodeId} is active and streaming data.`
        : `Node ${nodeId} is inactive — no recent data received.`;
}

function updateNodeStatusTexts() {
    [['live-node-note','live-node-select'],['graph-node-note','graph-node-select'],['cmd-node-note','cmd-node']].forEach(([noteId, selId]) => {
        const note = document.getElementById(noteId);
        const sel  = document.getElementById(selId);
        if (note && sel) note.innerText = getNodeStatusText(sel.value);
    });
}

function setGraphWindow(size) {
    chartWindow = Math.min(Math.max(1, Number(size)), MAX_POINTS);
    document.querySelectorAll('.graph-range-group .btn').forEach(btn => {
        btn.classList.toggle('active', Number(btn.dataset.range) === chartWindow);
    });
    renderGraphNode();
}

async function handleCompanyChange() {
    const company = getSelectedCompany();

    // Update server-side session company (admin or supervisor/monitor)
    if (document.body.dataset.role === 'admin' || IS_SUPERVISOR) {
        try {
            await fetch('/api/set_company', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ company })
            });
        } catch (err) {
            console.warn('Company session update failed', err);
        }
    }

    if (IS_SUPERVISOR) {
        // Supervisor keeps the wildcard MQTT connection alive.
        // Pre-load last-known data from the DB so gauges, metrics and charts
        // are populated immediately — no waiting for the next MQTT message.
        await preloadCompanyData(company);
    } else {
        // Regular users: full reset (they reconnect to a single company).
        resetLiveTelemetryState();
    }

    initNodeSelectors();
    refreshNodeSelectors();
    renderLiveNode();
    // Load chart history for whatever node the graph selector landed on AFTER
    // the selectors were reset (preload used the previous company's selection,
    // which may not exist in the new company).
    await loadNodeHistory(document.getElementById('graph-node-select')?.value);
    renderGraphNode();
    refreshMap();
    renderThresholdTable();
    renderLocationTable();
    searchTabular();
    updateFleetSummary();
}

/**
 * Fetch the latest node data (and chart history for the currently selected
 * node) from the server and seed the in-memory state dictionaries.
 * Only called for the supervisor on company switch.
 */
async function preloadCompanyData(company) {
    // Clear state for the new company without triggering the empty-state UI
    nodeLatestData  = {};
    nodeHistoryData = {};
    prevGaugeVals   = { flow: null, vel: null };

    const selectedNode = document.getElementById('live-node-select')?.value
                      || getAllowedNodeIds()[0]
                      || '1';
    try {
        const params = new URLSearchParams({ company, history_node: selectedNode });
        const res  = await fetch(`/api/node_latest?${params}`);
        if (!res.ok) return;
        const data = await res.json();

        // Seed nodeLatestData with the latest record per node.
        // Also ensure every node has an empty history bucket so renderGraphNode()
        // never hits undefined even before live data arrives for that node.
        (data.latest || []).forEach(row => {
            const nid = String(row.node_id);
            nodeLatestData[nid] = {
                Time:         row.timestamp,
                Type:         row.type,
                'Node ID':    row.node_id,
                'Sensor ID':  row.sensor_id,
                Flow:         row.flow,
                Velocity:     row.velocity,
                'Flow Day':   row.flow_day,
                'Flow Month': row.flow_month,
                'Flow Year':  row.flow_year,
                'Node Status':row.node_status,
                'Battery Voltage': row.battery_voltage,
                'WDT Resets': row.wdt_reset_count ?? 0,
                Details:      row.details || '',
                Company:      company,
                'Soil Temp':  row.soil_temperature,
                'Soil Moist': row.soil_moisture,
                'Soil Valid': row.soil_moisture_temp_valid,
                'EC Temp':    row.ec_temperature,
                'EC Moist':   row.ec_moisture,
                'EC Cond':    row.electrical_conductivity,
                'EC Valid':   row.soil_moisture_temp_ec_valid,
                'Active Sensors': row.active_sensor_count,
                'Sensor Mask': row.sensor_mask,
                'Flow Meter': flowMeterName(row.flow_meter_type),
                'Period Source': flowPeriodSourceName(row.flow_period_source),
                'Flow Live Valid': row.flow_live_valid,
                'Period Totals Valid': row.flow_period_totals_valid,
                'Cumulative Totals Valid': row.flow_cumulative_totals_valid,
                'RTC Valid': row.rtc_valid,
                'Forward Total Liters': row.forward_total_liters,
                'Reverse Total Liters': row.reverse_total_liters,
                'Net Total Liters': row.net_total_liters,
                'Period Quality': flowPeriodQualityName(row.flow_period_quality),
                'Flow Alarm Flags': row.flow_meter_alarm_flags,
                'Secondary Flow Meter': row.secondary_flow_meter,
                'Time Source': row.time_source,
            };
            // Guarantee a history bucket exists so switching graph-node-select
            // never shows "no data available" for a node that has latest values.
            if (!nodeHistoryData[nid]) nodeHistoryData[nid] = { flows:[], vels:[], lbls:[] };
        });

        // Seed chart history for the selected node
        if (data.history && data.history.length) {
            const nid = String(selectedNode);
            nodeHistoryData[nid] = { flows: [], vels: [], lbls: [] };
            data.history.forEach(row => {
                nodeHistoryData[nid].flows.push(Number(row.flow));
                nodeHistoryData[nid].vels.push(Number(row.velocity));
                const ts = row.timestamp_epoch != null ? new Date(row.timestamp_epoch * 1000) : new Date(row.timestamp);
                nodeHistoryData[nid].lbls.push(ts);
            });
            // Use the most recent record's timestamp for freshness
            const latest = data.history[data.history.length - 1];
            if (latest) {
                latestMessageTime  = latest.timestamp;
                latestMessageEpoch = latest.timestamp_epoch != null ? latest.timestamp_epoch * 1000 : new Date(latest.timestamp).getTime();
            }
        }
    } catch (err) {
        console.warn('Failed to preload company data:', err);
    }
    updateFreshnessIndicator();
}

// ─── MQTT connect / disconnect ────────────────────────────────────────────────
async function connect() {
    // For non-admin users, restore broker config from localStorage
    const brokerField = document.getElementById('cfg-broker');
    if (brokerField && !brokerField.value) {
        const stored = localStorage.getItem('broker_config');
        if (stored) {
            const config = JSON.parse(stored);
            brokerField.value = config.broker || 'broker.hivemq.com';
            document.getElementById('cfg-port').value = config.port || '1883';
            document.getElementById('cfg-aes').value = config.aes_key || '';
            document.getElementById('cfg-client').value = config.client_id || 'iot_server';
        } else {
            brokerField.value = 'broker.hivemq.com';
        }
    }

    const data = {
        broker: document.getElementById('cfg-broker').value,
        port: parseInt(document.getElementById('cfg-port').value),
        company: getSelectedCompany(),
        aes_key: document.getElementById('cfg-aes').value,
        client_id: document.getElementById('cfg-client').value
    };
    setConnIndicator('connecting');
    try {
        const res = await fetch('/api/connect', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data) });
        let result = null;
        try {
            result = await res.json();
        } catch (err) {
            const text = await res.text().catch(() => 'Non-JSON response');
            setConnIndicator(false);
            showToast('Connect failed: ' + (text || err.message), 'danger');
            return { success: false, error: text || err.message };
        }

        if (result && result.success) {
            document.getElementById('btn-connect').disabled = true;
            document.getElementById('btn-disconnect').disabled = false;
            setConnIndicator('connected');
            saveBrokerConfig(data);
            setLiveEmptyState('Waiting for live data from the broker...', true);
            showToast('Connected to broker successfully.', 'success');
        } else {
            setConnIndicator(false);
            showToast('Connect failed: ' + (result && result.error ? result.error : 'Unknown error'), 'danger');
        }
        return result;
    } catch (err) {
        setConnIndicator(false);
        showToast('Connect failed: ' + (err && err.message ? err.message : String(err)), 'danger');
        return { success: false, error: err && err.message ? err.message : String(err) };
    }
}

async function disconnect() {
    await fetch('/api/disconnect', { method:'POST' });
    document.getElementById('btn-connect').disabled = false;
    document.getElementById('btn-disconnect').disabled = true;
    setConnIndicator(false);
    latestMessageEpoch = null;
    updateFreshnessIndicator();
    setLiveEmptyState('Connect to an MQTT broker to start receiving live data. Use the Connect button above.', true);
    stopPeriodicStime();
    showToast('Disconnected from broker.', 'info');
}

// ─── Commands ─────────────────────────────────────────────────────────────────
const wakeTracker = new WakeTracker();

function setWakeStatus(text) {
    const status = document.getElementById('wake-status');
    if (status) status.textContent = text;
}

function handleCmdChange() {
    // Guard: command elements only exist for admin role
    if (!document.getElementById('cmd-type')) {
        return;
    }

    const type = document.getElementById('cmd-type').value;
    const inp  = document.getElementById('cmd-data');
    const intervalInput = document.getElementById('cmd-interval');
    const startBtn = document.getElementById('start-stime-btn');
    const help = document.getElementById('cmd-data-help');
    if (help) help.textContent = type === 'WAKE'
        ? 'Active seconds: 1–86400. Use 0 for the node default. Requires REMOTE_WAKE mode.'
        : 'Command-specific data.';

    if (type === 'STIME') {
        inp.disabled = true; inp.value = 'Epoch Time';
        intervalInput.disabled = false;
        if (startBtn) startBtn.disabled = !isBrokerConnected;
    } else if (type === 'GOSTM') {
        inp.disabled = true; inp.value = 'No Data Required';
        intervalInput.disabled = true;
        if (startBtn && !stimePeriodicHandle) startBtn.disabled = true;
    } else if (type === 'WAKE') {
        inp.disabled = false; inp.value = '60';
        intervalInput.disabled = true;
        if (startBtn && !stimePeriodicHandle) startBtn.disabled = true;
    } else if (type === 'VALVE') {
        inp.disabled = false; inp.value = '0';
        intervalInput.disabled = true;
        if (startBtn && !stimePeriodicHandle) startBtn.disabled = true;
    } else {
        inp.disabled = false;
        if (inp.value === 'Epoch Time' || inp.value === 'No Data Required') inp.value = '5';
        intervalInput.disabled = true;
        if (startBtn && !stimePeriodicHandle) startBtn.disabled = true;
    }
    if (type !== 'STIME' && stimePeriodicHandle) stopPeriodicStime();
    updateCommandAvailability();
}

async function sendCommand(broadcast, suppressToast = false) {
    const nodeValue = document.getElementById('cmd-node').value || '1';
    const data = {
        node_id: nodeValue,
        cmd_type: document.getElementById('cmd-type').value,
        cmd_data: document.getElementById('cmd-data').value,
        broadcast: broadcast,
        company: getSelectedCompany(),
        delivery: document.getElementById('cmd-delivery')?.value || 'now',
        ttl_seconds: Number(document.getElementById('cmd-ttl')?.value || 86400)
    };
    const res = await fetch('/api/command', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data) });
    const result = await res.json();
    if (result.success && result.queued) {
        setWakeStatus(`Command ${data.cmd_type} queued as request ${result.request_id}. It will be sent after Node ${nodeValue} next reports Status; expiry ${new Date(result.expires_at * 1000).toLocaleString()}.`);
    } else if (result.success && data.cmd_type === 'WAKE') {
        const alreadyAcknowledged = wakeTracker.published(data.company, nodeValue, result.request_id, broadcast);
        setWakeStatus(alreadyAcknowledged
            ? `${broadcast ? 'At least one broadcast node' : `Node ${nodeValue}`} acknowledged WAKE request ${result.request_id}.`
            : `WAKE request ${result.request_id} published. Waiting for ${broadcast ? 'individual broadcast node acknowledgements' : `Node ${nodeValue} acknowledgement`}.`);
        if (!alreadyAcknowledged) setTimeout(() => {
            if (wakeTracker.waiting(data.company, broadcast ? '*' : nodeValue, result.request_id)) {
                setWakeStatus(`No acknowledgement yet for WAKE ${result.request_id}. The node may be offline, in RTC deep sleep, or using an unsupported profile. Publication alone does not confirm wake.`);
            }
        }, 20000);
    } else if (result.success && data.cmd_type === 'VALVE') {
        setWakeStatus(`VALVE request ${result.request_id} published to ${broadcast ? 'broadcast nodes' : `Node ${nodeValue}`}. Waiting for pulse completion acknowledgement; this is not position feedback.`);
    }
    if (!suppressToast) {
        if (result.success && result.queued) showToast(`Command ${data.cmd_type} queued until Node ${nodeValue} wakes.`, 'info');
        else if (result.success && data.cmd_type === 'WAKE') showToast('WAKE published; waiting for node acknowledgement.', 'info');
        else if (result.success && data.cmd_type === 'VALVE') showToast('VALVE published; waiting for pulse completion acknowledgement.', 'info');
        else if (result.success) showToast(`Command ${data.cmd_type} sent to Node ${nodeValue}.`, 'success');
        else showToast('Command failed: ' + result.error, 'danger');
    }
    return result;
}

function updateStimeStatus(message) {
    const status = document.getElementById('stime-status');
    if (status) status.textContent = message;
}

function updateStimeIndicator(active) {
    const indicator = document.getElementById('stime-blinker');
    if (!indicator) return;
    indicator.classList.toggle('active', active);
}

function startPeriodicStime() {
    const type = document.getElementById('cmd-type').value;
    if (type !== 'STIME') { showToast('Select STIME command first.', 'warning'); return; }
    const intervalSec = parseFloat(document.getElementById('cmd-interval').value);
    if (Number.isNaN(intervalSec) || intervalSec <= 0) { showToast('Enter a valid interval in seconds.', 'warning'); return; }
    if (stimePeriodicHandle) stopPeriodicStime();
    sendCommand(true).then(result => {
        if (result.success) {
            stimePeriodicHandle = setInterval(() => sendCommand(true, true), intervalSec * 1000);
            document.getElementById('start-stime-btn').disabled = true;
            document.getElementById('stop-stime-btn').disabled = false;
            updateStimeIndicator(true);
            updateStimeStatus(`Periodic STIME broadcasting every ${intervalSec}s.`);
            showToast(`Periodic STIME started — every ${intervalSec}s.`, 'success');
            updateCommandAvailability();
        }
    });
}

function stopPeriodicStime() {
    if (stimePeriodicHandle) { clearInterval(stimePeriodicHandle); stimePeriodicHandle = null; }
    const startBtn = document.getElementById('start-stime-btn');
    const stopBtn  = document.getElementById('stop-stime-btn');
    if (startBtn) startBtn.disabled = false;
    if (stopBtn)  stopBtn.disabled  = true;
    updateStimeIndicator(false);
    updateStimeStatus('Periodic STIME is stopped.');
    updateCommandAvailability();
}

// ─── Socket events ────────────────────────────────────────────────────────────
socket.on('system_log', function(data) {
    const term = document.getElementById('sys-logs');
    if (term) { term.innerHTML += data.message + '<br>'; term.scrollTop = term.scrollHeight; }
});

socket.on('broker_status', function(data) {
    const isConnected = data && data.connected === true;
    setConnIndicator(isConnected ? 'connected' : false);
    const connectBtn = document.getElementById('btn-connect');
    const disconnectBtn = document.getElementById('btn-disconnect');
    if (connectBtn) connectBtn.disabled = isConnected;
    if (disconnectBtn) disconnectBtn.disabled = !isConnected;
});

socket.on('iot_message', function(msg) {
    // The supervisor receives every company's stream; show only the one
    // currently selected. Other users are room-scoped server-side already.
    if (IS_SUPERVISOR && msg.Company && msg.Company !== getSelectedCompany()) return;
    if (msg['Command ACK Success'] && msg['Command ACK Request ID']) {
        setWakeStatus(`Node ${msg['Node ID']} acknowledged command request ${msg['Command ACK Request ID']}.`);
        showToast(`Node ${msg['Node ID']} acknowledged command execution.`, 'success');
    } else if (msg['Command ACK Request ID']) {
        setWakeStatus(`Node ${msg['Node ID']} rejected command request ${msg['Command ACK Request ID']}. Check node logs.`);
        showToast(`Node ${msg['Node ID']} rejected the command.`, 'danger');
    }
    if (wakeTracker.receive(msg)) {
        setWakeStatus(`Node ${msg['Node ID']} confirmed ACTIVE: WAKE ${msg['Wake Request ID']}, ${msg['Wake Remaining Seconds']} seconds remaining at acknowledgement.`);
        showToast(`Node ${msg['Node ID']} acknowledged WAKE.`, 'success');
    }

    // Prepend to historical table
    const tbody = document.querySelector('#message-table tbody');
    if (tbody) {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td class="text-nowrap">${msg.Time}</td>
            <td><span class="badge badge-type-${msg.Type.toLowerCase()}">${msg.Type}</span></td>
            <td>${msg['Node ID']}</td><td>${msg['Sensor ID']}</td><td>${msg.Type === 'Command' ? '-' : nodeStatusLabel(msg['Node Status'])}</td>
            <td>${formatNumberOrDash(msg['Battery Voltage'], 2)}</td>
            <td>${formatNumberOrDash(msg.Flow)}</td>
            <td>${formatNumberOrDash(msg.Velocity)}</td>
            <td>${formatNumberOrDash(msg['Flow Day'])}</td>
            <td>${formatNumberOrDash(msg['Flow Month'])}</td>
            <td>${formatNumberOrDash(msg['Flow Year'])}</td>
            <td>${msg['Flow Meter'] || '-'}</td>
            <td>${msg['Period Source'] || '-'}</td>
            <td>${msg['Period Quality'] || '-'}</td>
            <td>${formatNumberOrDash(msg['Soil Temp'])}</td>
            <td>${formatNumberOrDash(msg['Soil Moist'])}</td>
            <td>${formatNumberOrDash(msg['EC Temp'])}</td>
            <td>${formatNumberOrDash(msg['EC Moist'])}</td>
            <td>${formatNumberOrDash(msg['EC Cond'])}</td>
            <td class="text-truncate" style="max-width:200px;" title="${msg.Details}">${msg.Details}</td>`;
        tbody.prepend(tr);
    }

    // Update GOSTM table for Telemetry
    if (msg.Type === 'Telemetry') {
        const gostmBody = document.querySelector('#gostm-table tbody');
        if (gostmBody) {
            gostmBody.innerHTML = `<tr>
                <td>${msg.Time}</td><td>${msg['Node ID']}</td><td>${msg['Sensor ID']}</td>
                <td>${formatNumberOrDash(msg['Battery Voltage'], 2)}</td>
                <td>${formatNumberOrDash(msg.Flow)}</td>
                <td>${formatNumberOrDash(msg.Velocity)}</td>
                <td>${formatNumberOrDash(msg['Flow Day'])} / ${formatNumberOrDash(msg['Flow Month'])} / ${formatNumberOrDash(msg['Flow Year'])}</td>
                <td>${msg['Flow Meter'] || '-'} / ${msg['Period Source'] || '-'} / ${msg['Period Quality'] || '-'}</td>
                <td>${msg.Details}</td></tr>`;
        }
    }

    if (msg.Type !== 'Status' && msg.Type !== 'Telemetry') return;
    const nid = String(msg['Node ID']);

    // Zero is a legitimate no-flow reading. Use the explicit node validity bit
    // instead of guessing validity from the numeric value.
    const shouldHoldFlowVel = Number(msg['Flow Live Valid']) !== 1;

    // Always ensure a history bucket exists — do NOT gate on nodeLatestData because
    // preloadCompanyData may have already seeded nodeLatestData without seeding history
    // for every node, which caused the init to be skipped and .push() to crash.
    if (!nodeHistoryData[nid]) nodeHistoryData[nid] = { flows:[], vels:[], lbls:[] };
    nodeLatestData[nid] = msg;
    latestMessageTime = msg.Time || latestMessageTime;
    latestMessageEpoch = msg.Epoch != null ? msg.Epoch * 1000 : Date.now();
    setLiveEmptyState('', false);
    updateFreshnessIndicator();
    refreshNodeSelectors();
    if (document.getElementById('live-node-select').value === nid) {
        renderLiveNode();
        if (!shouldHoldFlowVel) pulseLiveGauges();
    }
    if (!shouldHoldFlowVel) {
        nodeHistoryData[nid].flows.push(Number(msg.Flow));
        nodeHistoryData[nid].vels.push(Number(msg.Velocity));
        const pointTime = msg.Epoch != null ? new Date(msg.Epoch * 1000) : new Date(msg.Time);
        nodeHistoryData[nid].lbls.push(pointTime);
        if (nodeHistoryData[nid].flows.length > MAX_POINTS) {
            nodeHistoryData[nid].flows.shift();
            nodeHistoryData[nid].vels.shift();
            nodeHistoryData[nid].lbls.shift();
        }
        if (document.getElementById('graph-node-select').value === nid) renderGraphNode();
    }
    updateMapMarkers();
    checkThresholds(msg);
    updateFleetSummary();
});

// ─── SVG Gauges ───────────────────────────────────────────────────────────────
function _gaugeThreshold(field) {
    const company = getSelectedCompany();
    const nid     = document.getElementById('live-node-select')?.value || '1';
    const t = getNodeThreshold(company, nid);
    if (field === 'flow') return { min: t.flow_min, max: t.flow_max };
    if (field === 'vel')  return { min: t.vel_min,  max: t.vel_max  };
    return { min: '', max: '' };
}

function _gaugeMax(field) {
    const t = _gaugeThreshold(field);
    return (t.max !== '' && !isNaN(t.max)) ? Number(t.max) : GAUGE_DEFAULTS[field];
}
function _gaugeMin(field) {
    const t = _gaugeThreshold(field);
    return (t.min !== '' && !isNaN(t.min)) ? Number(t.min) : 0;
}

// _gaugeColor retained for any external callers; colour logic lives in updateWaterGauge
function _gaugeColor(value, minVal, maxVal, field) {
    const t = _gaugeThreshold(field || 'flow');
    if (t.max !== '' && !isNaN(t.max) && value > Number(t.max)) return '#ef4444';
    if (t.min !== '' && !isNaN(t.min) && value < Number(t.min)) return '#f59e0b';
    if (maxVal && value >= maxVal * 0.85) return '#f59e0b';
    return '#4cc9f0';
}

function pulseWaterGauge(circleId) {
    const circle = document.getElementById(circleId);
    if (!circle) return;
    circle.classList.remove('wg-pulse');
    void circle.offsetWidth;
    circle.classList.add('wg-pulse');
}

function pulseLiveGauges() {
    pulseWaterGauge('wg-flow-circle');
    pulseWaterGauge('wg-vel-circle');
}

// stateId = id of the .wg-state-badge span; trendId = id of .gauge-trend div
function updateWaterGauge(fillId, pctId, circleId, minLabelId, maxLabelId, value, field, stateId, trendId) {
    const fill   = document.getElementById(fillId);
    const pctEl  = document.getElementById(pctId);
    const circle = document.getElementById(circleId);
    const stateEl = stateId ? document.getElementById(stateId) : null;
    const trendEl = trendId ? document.getElementById(trendId) : null;
    if (!fill) return;

    if (isNaN(value)) {
        fill.style.height = '0%';
        if (pctEl)   pctEl.textContent = '—';
        if (stateEl) { stateEl.textContent = ''; stateEl.className = 'wg-state-badge'; }
        if (circle)  circle.classList.remove('wg-danger', 'wg-warn');
        return;
    }

    const maxVal = _gaugeMax(field);
    const minVal = _gaugeMin(field);
    const minEl  = document.getElementById(minLabelId);
    const maxEl  = document.getElementById(maxLabelId);
    if (minEl) minEl.textContent = minVal;
    if (maxEl) maxEl.textContent = maxVal;

    const pct = Math.min(Math.max((value - minVal) / (maxVal - minVal), 0), 1);
    fill.style.height = `${(pct * 100).toFixed(1)}%`;
    if (pctEl) pctEl.textContent = `${(pct * 100).toFixed(0)}% of max`;

    // Threshold colour state
    const t = _gaugeThreshold(field);
    let state = 'ok';
    let overMin = false;
    if      (t.max !== '' && !isNaN(t.max) && value > Number(t.max))    state = 'danger';
    else if (t.min !== '' && !isNaN(t.min) && value < Number(t.min)) { state = 'warn'; overMin = true; }
    else if (maxVal && value >= maxVal * 0.85)                           state = 'warn';

    if (circle) {
        circle.classList.toggle('wg-danger', state === 'danger');
        circle.classList.toggle('wg-warn',   state === 'warn');
    }

    // State badge: shows threshold violation clearly, separate from trend direction
    if (stateEl) {
        stateEl.className = 'wg-state-badge';
        if (state === 'danger') {
            stateEl.textContent = '▲ OVER MAX';
            stateEl.classList.add('state-danger');
        } else if (state === 'warn' && overMin) {
            stateEl.textContent = '▼ BELOW MIN';
            stateEl.classList.add('state-warn');
        } else if (state === 'warn') {
            stateEl.textContent = '▲ NEAR MAX';
            stateEl.classList.add('state-warn');
        } else {
            stateEl.textContent = '';
        }
    }

    // Colour the trend text to match threshold state
    if (trendEl) {
        trendEl.classList.toggle('trend-state-danger', state === 'danger');
        trendEl.classList.toggle('trend-state-warn',   state === 'warn');
    }
}

function updateTrend(trendId, current, previous) {
    const el = document.getElementById(trendId);
    if (!el) return;
    if (previous === null || isNaN(current)) { el.innerHTML = ''; return; }
    const diff = current - previous;
    if (Math.abs(diff) < 0.005) {
        el.innerHTML = '<span class="trend-same">— stable</span>';
    } else if (diff > 0) {
        el.innerHTML = `<span class="trend-up">&#8593; +${diff.toFixed(2)}</span>`;
    } else {
        el.innerHTML = `<span class="trend-down">&#8595; ${diff.toFixed(2)}</span>`;
    }
}

// node_status is a uint32 valve-state code reported by the device.
// These are completed commands, never measured position/flow feedback.
const VALVE_LABELS = {
    0: 'Closed / OFF (commanded)',
    1: 'Open / ON (commanded)',
    2: 'Unknown — not confirmed',
    3: 'Fault — position unknown',
};

function nodeStatusLabel(status) {
    if (status === null || status === undefined || status === '-') return '-';
    const code = Number(status);
    if (Number.isNaN(code)) return String(status);
    return VALVE_LABELS[code] !== undefined ? VALVE_LABELS[code] : `Unknown (${code})`;
}

function updateStatusCard(status) {
    const card = document.getElementById('status-card');
    const icon = document.getElementById('status-icon');
    if (!card || !icon) return;
    // No data → neutral; 1 = Open (cyan); 0 = Closed (amber); other = unknown (gray)
    const hasData = status !== null && status !== undefined && status !== '-';
    const code    = hasData ? Number(status) : null;
    const isOpen  = code === 1;
    const isClosed = code === 0;
    card.classList.toggle('status-card-ok',   isOpen);
    card.classList.toggle('status-card-warn', hasData && !isOpen);
    icon.className  = isOpen ? 'bi bi-droplet icon' : isClosed ? 'bi bi-droplet-slash icon' : 'bi bi-toggles icon';
    icon.style.color = isOpen ? 'var(--wiot-accent)' : isClosed ? 'var(--wiot-warning, #f59e0b)' : 'var(--wiot-muted)';
}

function updateGauges(d) {
    if (!d) {
        updateWaterGauge('wg-fill-flow', 'wg-pct-flow', 'wg-flow-circle', 'g-flow-min', 'g-flow-max', NaN, 'flow', 'wg-state-flow', 'trend-flow');
        updateWaterGauge('wg-fill-vel',  'wg-pct-vel',  'wg-vel-circle',  'g-vel-min',  'g-vel-max',  NaN, 'vel',  'wg-state-vel',  'trend-vel');
        updateTrend('trend-flow', NaN, null);
        updateTrend('trend-vel',  NaN, null);
        updateStatusCard(null);
        return;
    }
    const liveValid = Number(d['Flow Live Valid']) === 1;
    const flow = liveValid ? Number(d.Flow) : NaN;
    const vel  = liveValid ? Number(d.Velocity) : NaN;
    updateWaterGauge('wg-fill-flow', 'wg-pct-flow', 'wg-flow-circle', 'g-flow-min', 'g-flow-max', flow, 'flow', 'wg-state-flow', 'trend-flow');
    updateWaterGauge('wg-fill-vel',  'wg-pct-vel',  'wg-vel-circle',  'g-vel-min',  'g-vel-max',  vel,  'vel',  'wg-state-vel',  'trend-vel');
    updateTrend('trend-flow', flow, prevGaugeVals.flow);
    updateTrend('trend-vel',  vel,  prevGaugeVals.vel);
    prevGaugeVals.flow = flow;
    prevGaugeVals.vel  = vel;
    updateStatusCard(d['Node Status']);
}

// ─── Live Status ──────────────────────────────────────────────────────────────
function renderLiveNode() {
    const nid = document.getElementById('live-node-select').value;
    const d = nodeLatestData[nid];
    document.getElementById('m-time').textContent     = d ? d.Time || '-' : '-';
    document.getElementById('m-sensor').textContent   = d ? d['Sensor ID'] || '-' : '-';
    document.getElementById('m-battery').textContent  = d ? formatNumberOrDash(d['Battery Voltage'], 2) : '-';
    document.getElementById('m-wdt-resets').textContent = d ? String(d['WDT Resets'] ?? 0) : '-';
    document.getElementById('m-status').textContent   = d ? nodeStatusLabel(d['Node Status']) : '-';
    const flowValid = d && Number(d['Flow Live Valid']) === 1;
    const periodsValid = d && Number(d['Period Totals Valid']) === 1;
    const cumulativeValid = d && Number(d['Cumulative Totals Valid']) === 1;
    // A received failed poll displays zero, never a previous sensor value.
    // Validity/quality remain separate; invalid zeros are not chart samples.
    document.getElementById('m-flow').textContent     = d ? formatNumberOrDash(flowValid ? d.Flow : 0) : '-';
    document.getElementById('m-velocity').textContent = d ? formatNumberOrDash(flowValid ? d.Velocity : 0) : '-';
    document.getElementById('m-fday').textContent     = d ? formatNumberOrDash(periodsValid ? d['Flow Day'] : 0, 3) : '-';
    document.getElementById('m-fmonth').textContent   = d ? formatNumberOrDash(periodsValid ? d['Flow Month'] : 0, 3) : '-';
    document.getElementById('m-fyear').textContent    = d ? formatNumberOrDash(periodsValid ? d['Flow Year'] : 0, 3) : '-';
    const setFlowText = (id, value) => {
        const el = document.getElementById(id);
        if (el) el.textContent = value;
    };
    setFlowText('m-flow-meter', d ? d['Flow Meter'] || '-' : '-');
    setFlowText('m-period-source', d ? d['Period Source'] || '-' : '-');
    setFlowText('m-period-quality', d ? d['Period Quality'] || '-' : '-');
    setFlowText('m-rtc-valid', d ? (Number(d['RTC Valid']) === 1 ? 'Trusted' : 'Not trusted') : '-');
    setFlowText('m-forward-total', d ? formatNumberOrDash(cumulativeValid ? Number(d['Forward Total Liters']) / 1000 : 0, 3) : '-');
    setFlowText('m-reverse-total', d ? formatNumberOrDash(cumulativeValid ? Number(d['Reverse Total Liters']) / 1000 : 0, 3) : '-');
    setFlowText('m-net-total', d ? formatNumberOrDash(cumulativeValid ? Number(d['Net Total Liters']) / 1000 : 0, 3) : '-');
    const secondary = d && d['Secondary Flow Meter'];
    const secondaryCard = document.getElementById('m-secondary-flow-card');
    if (secondaryCard) secondaryCard.classList.toggle('d-none', !secondary);
    if (secondary) {
        setFlowText('m-secondary-name', secondary.flow_meter_name || flowMeterName(secondary.flow_meter_type));
        setFlowText('m-secondary-flow', formatNumberOrDash(Number(secondary.flow_live_valid) === 1 ? secondary.flow_rate : 0, 3));
        const secondaryPeriodsValid = Number(secondary.flow_period_totals_valid) === 1;
        setFlowText('m-secondary-day', formatNumberOrDash(secondaryPeriodsValid ? secondary.flow_rate_per_day : 0, 3));
        setFlowText('m-secondary-month', formatNumberOrDash(secondaryPeriodsValid ? secondary.flow_rate_per_month : 0, 3));
        setFlowText('m-secondary-year', formatNumberOrDash(secondaryPeriodsValid ? secondary.flow_rate_per_year : 0, 3));
        setFlowText('m-secondary-quality', `${secondary.flow_period_source_name || '-'} · ${secondary.flow_period_quality_name || '-'}`);
    }
    document.getElementById('m-details').textContent  = d ? d.Details || '-' : 'No active data for selected node.';
    const updatedText = d && d.Time ? `Updated ${getElapsedLabel(Math.round((Date.now() - new Date(d.Time).getTime()) / 1000))}` : 'No recent update';
    const updatedEl = document.getElementById('m-updated');
    if (updatedEl) updatedEl.textContent = updatedText;

    // Update Soil Moisture & Temp Sensor
    const soilStatusEl = document.getElementById('m-soil-status');
    const soilTempEl = document.getElementById('m-soil-temp');
    const soilMoistEl = document.getElementById('m-soil-moist');

    const soilHasRawValues = d && (d['Soil Temp'] !== undefined || d['Soil Moist'] !== undefined);
    const soilMask = d && d['Sensor Mask'] !== undefined ? Number(d['Sensor Mask']) : 0;
    const soilEnabled = soilMask === 0 || (soilMask & 0x0002) !== 0;
    const soilValid = d && d['Soil Valid'] !== undefined ? Number(d['Soil Valid']) === 1 : true;

    if (!soilHasRawValues) {
        if (soilStatusEl) { soilStatusEl.textContent = 'No Data'; soilStatusEl.className = 'badge bg-secondary'; }
        if (soilTempEl) soilTempEl.textContent = '-';
        if (soilMoistEl) soilMoistEl.textContent = '-';
    } else if (!soilEnabled) {
        if (soilStatusEl) { soilStatusEl.textContent = 'Disabled'; soilStatusEl.className = 'badge bg-secondary'; }
        if (soilTempEl) soilTempEl.textContent = '-';
        if (soilMoistEl) soilMoistEl.textContent = '-';
    } else if (!soilValid) {
        if (soilStatusEl) { soilStatusEl.textContent = 'Sensor Error'; soilStatusEl.className = 'badge bg-danger'; }
        if (soilTempEl) soilTempEl.textContent = formatNumberOrDash(0, 1);
        if (soilMoistEl) soilMoistEl.textContent = formatNumberOrDash(0, 1);
    } else {
        if (soilStatusEl) { soilStatusEl.textContent = 'Normal'; soilStatusEl.className = 'badge bg-success'; }
        if (soilTempEl) soilTempEl.textContent = formatNumberOrDash(d['Soil Temp'], 1);
        if (soilMoistEl) soilMoistEl.textContent = formatNumberOrDash(d['Soil Moist'], 1);
    }

    // Update Soil Temp, Moisture & EC Sensor
    const ecStatusEl = document.getElementById('m-ec-status');
    const ecTempEl = document.getElementById('m-ec-temp');
    const ecMoistEl = document.getElementById('m-ec-moist');
    const ecCondEl = document.getElementById('m-ec-cond');

    const ecHasRawValues = d && (d['EC Temp'] !== undefined || d['EC Moist'] !== undefined || d['EC Cond'] !== undefined);
    const ecMask = d && d['Sensor Mask'] !== undefined ? Number(d['Sensor Mask']) : 0;
    const ecEnabled = ecMask === 0 || (ecMask & 0x0004) !== 0;
    const ecValid = d && d['EC Valid'] !== undefined ? Number(d['EC Valid']) === 1 : true;

    if (!ecHasRawValues) {
        if (ecStatusEl) { ecStatusEl.textContent = 'No Data'; ecStatusEl.className = 'badge bg-secondary'; }
        if (ecTempEl) ecTempEl.textContent = '-';
        if (ecMoistEl) ecMoistEl.textContent = '-';
        if (ecCondEl) ecCondEl.textContent = '-';
    } else if (!ecEnabled) {
        if (ecStatusEl) { ecStatusEl.textContent = 'Disabled'; ecStatusEl.className = 'badge bg-secondary'; }
        if (ecTempEl) ecTempEl.textContent = '-';
        if (ecMoistEl) ecMoistEl.textContent = '-';
        if (ecCondEl) ecCondEl.textContent = '-';
    } else if (!ecValid) {
        if (ecStatusEl) { ecStatusEl.textContent = 'Sensor Error'; ecStatusEl.className = 'badge bg-danger'; }
        if (ecTempEl) ecTempEl.textContent = formatNumberOrDash(0, 1);
        if (ecMoistEl) ecMoistEl.textContent = formatNumberOrDash(0, 1);
        if (ecCondEl) ecCondEl.textContent = formatNumberOrDash(0, 0);
    } else {
        if (ecStatusEl) { ecStatusEl.textContent = 'Normal'; ecStatusEl.className = 'badge bg-success'; }
        if (ecTempEl) ecTempEl.textContent = formatNumberOrDash(d['EC Temp'], 1);
        if (ecMoistEl) ecMoistEl.textContent = formatNumberOrDash(d['EC Moist'], 1);
        if (ecCondEl) ecCondEl.textContent = formatNumberOrDash(d['EC Cond'], 0);
    }

    updateGauges(d);
    updateNodeStatusTexts();
}

// ─── Chart ────────────────────────────────────────────────────────────────────
const ctx = document.getElementById('liveChart').getContext('2d');
myChart = new Chart(ctx, {
    type: 'line',
    data: {
        labels: [],
        datasets: [
            { label: 'Flow (m³/h)',    borderColor: '#4cc9f0', backgroundColor: 'rgba(76,201,240,0.08)', data: [], tension: 0.35, yAxisID: 'y',  pointRadius: 2 },
            { label: 'Velocity (m/s)', borderColor: '#f472b6', backgroundColor: 'transparent',             data: [], tension: 0.35, yAxisID: 'y1', pointRadius: 2 }
        ]
    },
    options: {
        responsive: true, maintainAspectRatio: false,
        animation: { duration: 0 },
        interaction: { mode:'index', intersect:false },
        scales: {
            y:  {
                type:'linear', position:'left', ticks:{ color:'#98a2c3' }, grid:{ color:'#1e2a4a' },
                title:{ display:true, text:'Flow (m³/h)', color:'#98a2c3', font:{ size:12 } }
            },
            y1: {
                type:'linear', position:'right', ticks:{ color:'#98a2c3' }, grid:{ display:false },
                title:{ display:true, text:'Velocity (m/s)', color:'#98a2c3', font:{ size:12 } }
            },
            x:  {
                type:'time', ticks:{ color:'#98a2c3' }, grid:{ color:'#1e2a4a' },
                title:{ display:true, text:'Time', color:'#98a2c3', font:{ size:12 } },
                time:{ displayFormats:{ second:'HH:mm:ss', minute:'HH:mm', hour:'HH:mm' } }
            }
        },
        plugins: {
            legend:{ labels:{ color:'#e6edf7' } },
            tooltip:{ mode:'index', intersect:false }
        }
    }
});
updateChartTheme();

function switchGraphNode() { renderGraphNode(); }
function downloadChartImage() {
    if (!myChart) return;
    const link = document.createElement('a');
    link.href = myChart.toBase64Image();
    link.download = `wiot_live_graph_${new Date().toISOString().replace(/[:.]/g,'-')}.png`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}
function renderGraphNode() {
    const nid = document.getElementById('graph-node-select').value;
    const h = nodeHistoryData[nid];
    const emptyState = document.getElementById('graph-empty-state');
    if (!h || h.flows.length === 0) {
        myChart.data.labels = [];
        myChart.data.datasets[0].data = [];
        myChart.data.datasets[1].data = [];
        if (emptyState) emptyState.classList.add('visible');
    } else {
        const offset = Math.max(0, h.flows.length - chartWindow);
        myChart.data.labels = h.lbls.slice(offset);
        myChart.data.datasets[0].data = h.flows.slice(offset);
        myChart.data.datasets[1].data = h.vels.slice(offset);
        if (emptyState) emptyState.classList.remove('visible');
    }
    myChart.update();
    updateNodeStatusTexts();
}

// ─── Historical DB ────────────────────────────────────────────────────────────
let historyPage = 1;
let historyPageSize = 50;
let historyTotalPages = 1;
let commandHistoryPage = 1;
let commandHistorySize = 20;
let commandHistoryTotalPages = 1;

async function searchTabular(page = 1) {
    historyPage = Math.max(1, page);
    const s = document.getElementById('filter-start').value;
    const e = document.getElementById('filter-end').value;
    const params = new URLSearchParams();
    if (s) params.append('start', `${s} 00:00:00`);
    if (e) params.append('end',   `${e} 23:59:59`);
    if (document.body.dataset.role === 'admin' || IS_SUPERVISOR) params.append('company', getSelectedCompany());
    params.append('page', historyPage);
    params.append('page_size', historyPageSize);
    const url = '/api/messages' + (params.toString() ? '?' + params : '');
    const res  = await fetch(url);
    const result = await res.json();
    const rows = result.rows || [];
    historyTotalPages = result.total_pages || 1;
    const tbody = document.querySelector('#message-table tbody');
    tbody.innerHTML = '';
    rows.forEach(msg => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td class="text-nowrap">${msg.timestamp}</td>
            <td><span class="badge badge-type-${(msg.type||'').toLowerCase()}">${msg.type}</span></td>
            <td>${msg.node_id}</td><td>${msg.sensor_id}</td><td>${msg.node_status === undefined || msg.node_status === null ? '-' : nodeStatusLabel(msg.node_status)}</td>
            <td>${formatNumberOrDash(msg.battery_voltage, 2)}</td>
            <td>${formatNumberOrDash(msg.flow)}</td>
            <td>${formatNumberOrDash(msg.velocity)}</td>
            <td>${formatNumberOrDash(msg.flow_day)}</td>
            <td>${formatNumberOrDash(msg.flow_month)}</td>
            <td>${formatNumberOrDash(msg.flow_year)}</td>
            <td>${flowMeterName(msg.flow_meter_type)}</td>
            <td>${flowPeriodSourceName(msg.flow_period_source)}</td>
            <td>${flowPeriodQualityName(msg.flow_period_quality)}</td>
            <td>${formatNumberOrDash(msg.soil_temperature)}</td>
            <td>${formatNumberOrDash(msg.soil_moisture)}</td>
            <td>${formatNumberOrDash(msg.ec_temperature)}</td>
            <td>${formatNumberOrDash(msg.ec_moisture)}</td>
            <td>${formatNumberOrDash(msg.electrical_conductivity)}</td>
            <td class="text-truncate" style="max-width:200px;" title="${msg.details}">${msg.details}</td>`;
        tbody.appendChild(tr);
    });
    document.getElementById('table-count').textContent = `${rows.length} of ${result.total || rows.length} record${result.total === 1 ? '' : 's'}`;
    document.getElementById('history-page-info').textContent = `Page ${historyPage} of ${historyTotalPages}`;
    document.getElementById('history-prev-btn').disabled = historyPage <= 1;
    document.getElementById('history-next-btn').disabled = historyPage >= historyTotalPages;
}

function changeHistoryPage(delta) {
    const nextPage = Math.min(Math.max(1, historyPage + delta), historyTotalPages);
    if (nextPage !== historyPage) searchTabular(nextPage);
}

function setHistoryPageSize(size) {
    historyPageSize = Number(size) || 50;
    searchTabular(1);
}

async function loadCommandHistory(page = 1) {
    commandHistoryPage = Math.max(1, page);
    const params = new URLSearchParams();
    params.append('type', 'Command');
    params.append('page', commandHistoryPage);
    params.append('page_size', commandHistorySize);
    if (document.body.dataset.role === 'admin' || IS_SUPERVISOR) params.append('company', getSelectedCompany());
    const url = '/api/messages?' + params;
    const res = await fetch(url);
    const result = await res.json();
    const rows = result.rows || [];
    commandHistoryTotalPages = result.total_pages || 1;
    const tbody = document.querySelector('#command-history-table tbody');
    tbody.innerHTML = '';
    rows.forEach(msg => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td class="text-nowrap">${msg.timestamp}</td>
            <td>${msg.node_id}</td>
            <td>${msg.type}</td>
            <td class="text-truncate" style="max-width:240px;" title="${msg.details}">${msg.details}</td>
            <td>${msg.company || '-'}</td>`;
        tbody.appendChild(tr);
    });
    document.getElementById('command-history-count').textContent = `Showing ${rows.length} of ${result.total || rows.length} command${result.total === 1 ? '' : 's'}`;
    document.getElementById('command-history-page-info').textContent = `Page ${commandHistoryPage} of ${commandHistoryTotalPages}`;
    document.getElementById('cmd-history-prev').disabled = commandHistoryPage <= 1;
    document.getElementById('cmd-history-next').disabled = commandHistoryPage >= commandHistoryTotalPages;
}

function changeCommandHistoryPage(delta) {
    const nextPage = Math.min(Math.max(1, commandHistoryPage + delta), commandHistoryTotalPages);
    if (nextPage !== commandHistoryPage) loadCommandHistory(nextPage);
}

function exportExcel() {
    const s = document.getElementById('filter-start').value;
    const e = document.getElementById('filter-end').value;
    const params = new URLSearchParams();
    if (s) params.append('start', `${s} 00:00:00`);
    if (e) params.append('end',   `${e} 23:59:59`);
    if (document.body.dataset.role === 'admin' || IS_SUPERVISOR) params.append('company', getSelectedCompany());
    window.location.href = '/export_csv' + (params.toString() ? '?' + params : '');
}

// ─── User Management ──────────────────────────────────────────────────────────
async function loadUsers() {
    try {
        const res = await fetch('/api/users');
        if (!res.ok) return;
        const result = await res.json();
        if (result.success) {
            const tbody = document.querySelector('#users-table tbody');
            tbody.innerHTML = '';
            result.users.forEach(u => {
                const PROTECTED = ['EgSA_Supervisor','Company1_Admin','Company2_Admin','Company1_User','Company2_User'];
                const deleteBtn = PROTECTED.includes(u.username) ? '' : `<button class="btn btn-sm btn-danger" onclick="deleteUser(${u.id})"><i class="bi bi-trash"></i></button>`;
                const roleBadge = `<span class="badge ${u.role==='admin'?'bg-danger':'bg-info'}">${u.role.toUpperCase()}</span>`;
                const tr = document.createElement('tr');
                tr.innerHTML = `<td>${u.id}</td><td>${u.username}</td><td>${roleBadge}</td><td>${u.company}</td><td>${deleteBtn}</td>`;
                tbody.appendChild(tr);
            });
        }
    } catch(err) { console.error('loadUsers failed', err); }
}

async function createUser() {
    const data = {
        username: document.getElementById('new-user-name').value.trim(),
        password: document.getElementById('new-user-pass').value,
        role: document.getElementById('new-user-role').value
    };
    const companySelect = document.getElementById('new-user-company');
    if (companySelect) data.company = companySelect.value;
    if (!data.username || !data.password) { showToast('Username and password are required.', 'warning'); return; }
    const res = await fetch('/api/users', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data) });
    const result = await res.json();
    if (result.success) {
        document.getElementById('new-user-name').value = '';
        document.getElementById('new-user-pass').value = '';
        showToast(`User "${data.username}" created.`, 'success');
        loadUsers();
    } else {
        showToast('Error: ' + result.error, 'danger');
    }
}

async function deleteUser(id) {
    const ok = await confirmAction('Delete this user? This cannot be undone.');
    if (!ok) return;
    const res = await fetch('/api/users/' + id, { method:'DELETE' });
    const result = await res.json();
    if (result.success) { showToast('User deleted.', 'success'); loadUsers(); }
    else showToast('Delete failed: ' + result.error, 'danger');
}

// ─── Company Management ───────────────────────────────────────────────────────
async function loadCompanies() {
    try {
        const res = await fetch('/api/companies');
        if (!res.ok) return;
        const result = await res.json();
        if (result.success) {
            const tbody = document.querySelector('#companies-table tbody');
            tbody.innerHTML = '';
            result.companies.forEach(c => {
                const tr = document.createElement('tr');
                tr.innerHTML = `<td>${c.name}</td><td>${c.created_at}</td>`;
                tbody.appendChild(tr);
            });
            updateCompanySelectors(result.companies);
        }
    } catch(err) { console.error('loadCompanies failed', err); }
}

async function addCompany() {
    const companyName = document.getElementById('new-company-name').value.trim();
    if (!companyName) { showToast('Enter a company name.', 'warning'); return; }
    const res = await fetch('/api/companies', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ company_name: companyName }) });
    const result = await res.json();
    if (result.success) {
        document.getElementById('new-company-name').value = '';
        showToast(`Company "${companyName}" added.`, 'success');
        loadCompanies();
    } else {
        showToast('Error: ' + result.error, 'danger');
    }
}

function updateCompanySelectors(companies) {
    ['cfg-company','new-user-company'].forEach(id => {
        const el = document.getElementById(id);
        if (!el) return;
        const currentVal = el.value;
        el.innerHTML = '';
        companies.forEach(c => {
            const opt = document.createElement('option');
            opt.value = c.name; opt.textContent = c.name;
            el.appendChild(opt);
        });
        el.value = currentVal || (companies.length > 0 ? companies[0].name : 'Company_1');
    });
}

// ─── Thresholds & Alerts ──────────────────────────────────────────────────────
const THRESHOLD_KEY = 'wiot_thresholds';
const ALERT_COOLDOWN_MS = 60000;

function loadThresholds() {
    try { return JSON.parse(localStorage.getItem(THRESHOLD_KEY)) || {}; } catch { return {}; }
}

function getNodeThreshold(company, nid) {
    const all = loadThresholds();
    return all[company]?.[nid] || { flow_min: '', flow_max: '', vel_min: '', vel_max: '' };
}

function saveThresholds() {
    const company = getSelectedCompany();
    const all = loadThresholds();
    if (!all[company]) all[company] = {};
    let saved = 0;
    document.querySelectorAll('#threshold-tbody tr[data-node]').forEach(row => {
        const nid = row.dataset.node;
        all[company][nid] = {
            flow_min: row.querySelector('[data-field="flow_min"]').value.trim(),
            flow_max: row.querySelector('[data-field="flow_max"]').value.trim(),
            vel_min:  row.querySelector('[data-field="vel_min"]').value.trim(),
            vel_max:  row.querySelector('[data-field="vel_max"]').value.trim(),
        };
        const badge = row.querySelector('.thresh-saved');
        if (badge) {
            badge.style.display = '';
            setTimeout(() => { badge.style.display = 'none'; }, 2000);
        }
        row.classList.remove('threshold-dirty');
        saved++;
    });
    localStorage.setItem(THRESHOLD_KEY, JSON.stringify(all));
    setThresholdDirty(false);
    showToast(`Thresholds saved for ${saved} node(s).`, 'success');
    const nid = document.getElementById('live-node-select')?.value;
    if (nid && nodeLatestData[nid]) updateGauges(nodeLatestData[nid]);
}

function resetThresholds() {
    document.querySelectorAll('#threshold-tbody tr[data-node] input').forEach(inp => { inp.value = ''; });
    setThresholdDirty(true);
    showToast('Thresholds cleared — click Save All to apply.', 'info');
}

function setThresholdDirty(isDirty) {
    const badge = document.getElementById('threshold-dirty-badge');
    if (!badge) return;
    badge.classList.toggle('d-none', !isDirty);
}

function markThresholdRowDirty(row) {
    if (!row) return;
    row.classList.add('threshold-dirty');
    setThresholdDirty(true);
}

function renderThresholdTable() {
    const company = getSelectedCompany();
    const nodeIds = getAllowedNodeIds();
    const tbody = document.getElementById('threshold-tbody');
    if (!tbody) return;
    tbody.innerHTML = '';
    nodeIds.forEach(nid => {
        const t = getNodeThreshold(company, nid);
        const active = isNodeActive(nid);
        const statusDot = active
            ? '<span style="color:var(--wiot-success)"><i class="bi bi-circle-fill" style="font-size:.6rem"></i> Active</span>'
            : '<span style="color:var(--wiot-muted)"><i class="bi bi-circle" style="font-size:.6rem"></i> Inactive</span>';
        const tr = document.createElement('tr');
        tr.dataset.node = nid;
        tr.innerHTML = `
            <td class="fw-semibold">Node ${nid}</td>
            <td><input class="form-control form-control-sm" type="number" step="any" placeholder="—" data-field="flow_min" value="${t.flow_min}" style="max-width:90px"></td>
            <td><input class="form-control form-control-sm" type="number" step="any" placeholder="—" data-field="flow_max" value="${t.flow_max}" style="max-width:90px"></td>
            <td><input class="form-control form-control-sm" type="number" step="any" placeholder="—" data-field="vel_min"  value="${t.vel_min}"  style="max-width:90px"></td>
            <td><input class="form-control form-control-sm" type="number" step="any" placeholder="—" data-field="vel_max"  value="${t.vel_max}"  style="max-width:90px"></td>
            <td>${statusDot} <span class="badge bg-success thresh-saved ms-1" style="display:none;font-size:0.65rem">Saved</span></td>`;
        tbody.appendChild(tr);
        tr.querySelectorAll('input[data-field]').forEach(input => {
            input.addEventListener('input', () => markThresholdRowDirty(tr));
        });
    });
    setThresholdDirty(false);
}

function checkThresholds(msg) {
    if (msg.Type !== 'Status' && msg.Type !== 'Telemetry') return;
    if (Number(msg['Flow Live Valid']) !== 1) return;
    const company = getSelectedCompany();
    const nid = String(msg['Node ID']);
    const t = getNodeThreshold(company, nid);

    const checks = [
        { field: 'Flow',     value: Number(msg.Flow),     min: t.flow_min, max: t.flow_max, unit: 'm³/h' },
        { field: 'Velocity', value: Number(msg.Velocity), min: t.vel_min,  max: t.vel_max,  unit: 'm/s' },
    ];

    checks.forEach(({ field, value, min, max, unit }) => {
        if (min !== '' && !isNaN(min) && value < Number(min)) {
            triggerAlert(nid, field, value, Number(min), 'LOW', unit);
        } else if (max !== '' && !isNaN(max) && value > Number(max)) {
            triggerAlert(nid, field, value, Number(max), 'HIGH', unit);
        }
    });
}

function triggerAlert(nid, field, value, limit, type, unit) {
    const key = `${nid}_${field}_${type}`;
    if (alertCooldowns[key] && Date.now() - alertCooldowns[key] < ALERT_COOLDOWN_MS) return;
    alertCooldowns[key] = Date.now();

    const dir = type === 'HIGH' ? 'exceeded max' : 'below min';
    showToast(
        `<b>Node ${nid}</b> — ${field} ${dir}: <b>${value.toFixed(2)} ${unit}</b> (limit: ${limit} ${unit})`,
        'danger'
    );
    logAlert(nid, field, value, limit, type, unit);
}

function logAlert(nid, field, value, limit, type, unit) {
    alertCount++;
    const badge  = document.getElementById('alert-count-badge');
    const navBadge = document.getElementById('alert-nav-badge');
    if (badge)    { badge.textContent = alertCount;    badge.style.display = ''; }
    if (navBadge) { navBadge.textContent = alertCount; navBadge.style.display = ''; }
    updateFleetSummary();

    const tbody = document.getElementById('alert-log-tbody');
    if (!tbody) return;
    const placeholder = tbody.querySelector('td[colspan]');
    if (placeholder) placeholder.closest('tr').remove();

    const typeBadge = type === 'HIGH'
        ? '<span class="badge" style="background:rgba(239,68,68,0.2);color:#f87171">HIGH</span>'
        : '<span class="badge" style="background:rgba(245,158,11,0.2);color:#fbbf24">LOW</span>';
    const now = new Date().toLocaleTimeString();
    const tr = document.createElement('tr');
    tr.innerHTML = `<td class="text-nowrap">${now}</td><td>Node ${nid}</td><td>${field}</td>
        <td><b>${value.toFixed(2)} ${unit}</b></td><td>${limit} ${unit}</td><td>${typeBadge}</td>`;
    tbody.prepend(tr);
}

function clearAlertLog() {
    alertCount = 0;
    const badge    = document.getElementById('alert-count-badge');
    const navBadge = document.getElementById('alert-nav-badge');
    if (badge)    { badge.textContent = '0'; badge.style.display = 'none'; }
    if (navBadge) { navBadge.textContent = '0'; navBadge.style.display = 'none'; }
    const tbody = document.getElementById('alert-log-tbody');
    if (tbody) tbody.innerHTML = '<tr><td colspan="6" class="text-center status-note py-3">No alerts triggered yet.</td></tr>';
    alertCooldowns = {};
    updateFleetSummary();
}

// ─── Node Location Map ────────────────────────────────────────────────────────
const MAP_STORAGE_KEY = 'wiot_node_positions';
const MAP_DEFAULT_CENTER = [26.8, 30.8]; // Egypt centre
const MAP_DEFAULT_ZOOM   = 6;

function loadNodePositions() {
    try { return JSON.parse(localStorage.getItem(MAP_STORAGE_KEY)) || {}; } catch { return {}; }
}
function saveNodePositions() {
    localStorage.setItem(MAP_STORAGE_KEY, JSON.stringify(nodePositions));
}

function makePinIcon(nodeId, active) {
    return L.divIcon({
        html: `<div class="wiot-pin${active ? ' active' : ''}">N${nodeId}</div>`,
        className: '',
        iconSize:   [42, 42],
        iconAnchor: [21, 21],
        popupAnchor:[0, -26]
    });
}

function buildPopupHtml(nid) {
    const d = nodeLatestData[nid];
    const active = !!d;
    const liveValid = active && Number(d['Flow Live Valid']) === 1;
    const periodsValid = active && Number(d['Period Totals Valid']) === 1;
    const statusDot = active
        ? '<span style="color:#4ade80">&#9679; Active</span>'
        : '<span style="color:#98a2c3">&#9679; Inactive</span>';
    const rows = active ? `
        <tr><td style="color:#98a2c3;padding-right:12px">Flow</td><td><b>${liveValid ? formatNumberOrDash(d.Flow) + ' m³/h' : '-'}</b></td></tr>
        <tr><td style="color:#98a2c3">Velocity</td><td><b>${liveValid ? formatNumberOrDash(d.Velocity) + ' m/s' : '-'}</b></td></tr>
        <tr><td style="color:#98a2c3">Battery</td><td><b>${formatNumberOrDash(d['Battery Voltage'], 2)} V</b></td></tr>
        <tr><td style="color:#98a2c3">WDT Resets</td><td><b>${Number(d['WDT Resets'] ?? 0)}</b></td></tr>
        <tr><td style="color:#98a2c3">Today</td><td>${periodsValid ? formatNumberOrDash(d['Flow Day']) + ' m³' : '-'}</td></tr>
        <tr><td style="color:#98a2c3">Last seen</td><td style="font-size:0.78rem">${d.Time}</td></tr>` : '';
    return `<div style="min-width:170px">
        <div style="font-weight:700;font-size:1rem;margin-bottom:6px">Node ${nid}</div>
        <div style="margin-bottom:8px;font-size:0.82rem">${statusDot}</div>
        <table style="width:100%;font-size:0.83rem">${rows}</table>
        <div style="margin-top:8px;font-size:0.72rem;color:#98a2c3">Drag marker to reposition</div>
    </div>`;
}

function initMap() {
    if (wiotMap) { setTimeout(() => wiotMap.invalidateSize(), 100); return; }
    nodePositions = loadNodePositions();
    const company = getSelectedCompany();

    wiotMap = L.map('node-map', { zoomControl: true }).setView(MAP_DEFAULT_CENTER, MAP_DEFAULT_ZOOM);

    mapTileLayer = L.tileLayer(getMapTileUrl(), {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>',
        maxZoom: 19,
        subdomains: 'abcd'
    }).addTo(wiotMap);

    const nodeIds = getAllowedNodeIds();
    nodeIds.forEach((nid, i) => {
        const posKey = `${company}_${nid}`;
        const pos = nodePositions[posKey] || [
            MAP_DEFAULT_CENTER[0] + (i - Math.floor(nodeIds.length / 2)) * 1.2,
            MAP_DEFAULT_CENTER[1]
        ];
        const active = isNodeActive(nid);
        const marker = L.marker(pos, {
            icon: makePinIcon(nid, active),
            draggable: true,
            title: `Node ${nid}`
        })
        .bindPopup(buildPopupHtml(nid), { maxWidth: 240 })
        .addTo(wiotMap);

        marker.on('dragend', () => {
            const ll = marker.getLatLng();
            nodePositions[posKey] = [ll.lat, ll.lng];
            saveNodePositions();
        });

        nodeMarkers[nid] = { marker, posKey };
    });

    renderMapNodeList();
    setTimeout(() => wiotMap.invalidateSize(), 150);
}

function updateMapMarkers() {
    renderMapNodeList();
    if (!wiotMap) return;
    const company = getSelectedCompany();
    getAllowedNodeIds().forEach(nid => {
        const entry = nodeMarkers[nid];
        if (!entry) return;
        const active = isNodeActive(nid);
        entry.marker.setIcon(makePinIcon(nid, active));
        if (entry.marker.isPopupOpen()) entry.marker.setPopupContent(buildPopupHtml(nid));
    });
}

function renderMapNodeList() {
    const panel = document.getElementById('map-node-list');
    if (!panel) return;
    const nodeIds = getAllowedNodeIds();
    if (nodeIds.length === 0) { panel.innerHTML = '<div class="status-note small p-2">No nodes configured.</div>'; return; }
    panel.innerHTML = nodeIds.map(nid => {
        const active = isNodeActive(nid);
        const d = nodeLatestData[nid];
        const liveValid = active && Number(d['Flow Live Valid']) === 1;
        const sub = liveValid ? `${formatNumberOrDash(d.Flow)} m³/h / ${formatNumberOrDash(d.Velocity)} m/s` : (active ? 'Flow reading invalid' : 'No data received');
        return `<div class="map-node-item" onclick="focusMapNode('${nid}')">
            <div class="map-node-dot${active ? ' active' : ''}"></div>
            <div style="flex:1;min-width:0">
                <div style="font-weight:600;font-size:0.85rem">Node ${nid}</div>
                <div class="status-note" style="font-size:0.72rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${sub}</div>
            </div>
            ${active ? '<i class="bi bi-broadcast" style="color:var(--wiot-success);font-size:0.9rem"></i>' : ''}
        </div>`;
    }).join('');
}

function focusMapNode(nid) {
    if (!wiotMap || !nodeMarkers[nid]) return;
    const { marker } = nodeMarkers[nid];
    wiotMap.setView(marker.getLatLng(), Math.max(wiotMap.getZoom(), 10), { animate: true });
    marker.openPopup();
}

function resetMapView() {
    if (!wiotMap) return;
    wiotMap.setView(MAP_DEFAULT_CENTER, MAP_DEFAULT_ZOOM, { animate: true });
}

function refreshMap() {
    if (!wiotMap) return;
    Object.values(nodeMarkers).forEach(({ marker }) => wiotMap.removeLayer(marker));
    nodeMarkers = {};

    const company = getSelectedCompany();
    const nodeIds = getAllowedNodeIds();
    nodeIds.forEach((nid, i) => {
        const posKey = `${company}_${nid}`;
        const pos = nodePositions[posKey] || [
            MAP_DEFAULT_CENTER[0] + (i - Math.floor(nodeIds.length / 2)) * 1.2,
            MAP_DEFAULT_CENTER[1]
        ];
        const active = isNodeActive(nid);
        const marker = L.marker(pos, {
            icon: makePinIcon(nid, active),
            draggable: true,
            title: `Node ${nid}`
        })
        .bindPopup(buildPopupHtml(nid), { maxWidth: 240 })
        .addTo(wiotMap);

        marker.on('dragend', () => {
            const ll = marker.getLatLng();
            nodePositions[posKey] = [ll.lat, ll.lng];
            saveNodePositions();
        });

        nodeMarkers[nid] = { marker, posKey };
    });

    renderMapNodeList();
}

// ─── Node Location Picker (Configuration Tab) ────────────────────────────────
let locationPickerMap  = null;
let locationPickerMark = null;
let locationPickerNid  = null;

/** Render the Node Locations table in the Configuration tab. */
function renderLocationTable() {
    const tbody = document.getElementById('location-tbody');
    if (!tbody) return;
    const company  = getSelectedCompany();
    const nodeIds  = getAllowedNodeIds();
    tbody.innerHTML = '';
    nodeIds.forEach(nid => {
        const posKey = `${company}_${nid}`;
        const pos    = nodePositions[posKey] || null;
        const active = isNodeActive(nid);
        const statusDot = active
            ? '<span style="color:var(--wiot-success)"><i class="bi bi-circle-fill" style="font-size:.6rem"></i> Active</span>'
            : '<span style="color:var(--wiot-muted)"><i class="bi bi-circle" style="font-size:.6rem"></i> Inactive</span>';
        const latCell = pos
            ? `<span class="loc-coord">${pos[0].toFixed(5)}</span>`
            : `<span class="loc-coord not-set">—</span>`;
        const lngCell = pos
            ? `<span class="loc-coord">${pos[1].toFixed(5)}</span>`
            : `<span class="loc-coord not-set">—</span>`;
        const tr = document.createElement('tr');
        tr.dataset.node = nid;
        tr.innerHTML = `
            <td class="fw-semibold">Node ${nid}</td>
            <td>${latCell}</td>
            <td>${lngCell}</td>
            <td>${statusDot}</td>
            <td>
                <button class="btn btn-sm btn-outline-info" onclick="openLocationPicker('${nid}')">
                    <i class="bi bi-pin-map me-1"></i>Set Location
                </button>
                ${pos ? `<button class="btn btn-sm btn-outline-danger ms-1" onclick="clearNodeLocation('${nid}')" title="Clear location"><i class="bi bi-x-lg"></i></button>` : ''}
            </td>`;
        tbody.appendChild(tr);
    });
}

/** Open the location picker modal for a given node. */
function openLocationPicker(nid) {
    locationPickerNid = nid;
    document.getElementById('loc-modal-title').textContent = `Node ${nid}`;

    const company  = getSelectedCompany();
    const posKey   = `${company}_${nid}`;
    const pos      = nodePositions[posKey] || MAP_DEFAULT_CENTER;

    // Update coord inputs
    document.getElementById('loc-lat-input').value = pos[0].toFixed(6);
    document.getElementById('loc-lng-input').value = pos[1].toFixed(6);

    const modal = new bootstrap.Modal(document.getElementById('location-picker-modal'));
    modal.show();

    // Init map after modal is fully visible so Leaflet gets correct dimensions
    document.getElementById('location-picker-modal').addEventListener('shown.bs.modal', function onShown() {
        this.removeEventListener('shown.bs.modal', onShown);
        _initPickerMap(pos);
    }, { once: true });
}

function _initPickerMap(pos) {
    if (!locationPickerMap) {
        locationPickerMap = L.map('location-picker-map', { zoomControl: true })
            .setView(pos, 13);
        L.tileLayer(getMapTileUrl(), {
            attribution: '&copy; OpenStreetMap &copy; CARTO',
            maxZoom: 19, subdomains: 'abcd'
        }).addTo(locationPickerMap);

        locationPickerMark = L.marker(pos, { draggable: true })
            .addTo(locationPickerMap);

        locationPickerMark.on('dragend', () => _syncPickerCoords(locationPickerMark.getLatLng()));
        locationPickerMap.on('click', e => {
            locationPickerMark.setLatLng(e.latlng);
            _syncPickerCoords(e.latlng);
        });
    } else {
        locationPickerMap.setView(pos, 13);
        locationPickerMark.setLatLng(pos);
        locationPickerMap.invalidateSize();
        _syncPickerCoords(L.latLng(pos[0], pos[1]));
    }
}

function _syncPickerCoords(latlng) {
    document.getElementById('loc-lat-input').value = latlng.lat.toFixed(6);
    document.getElementById('loc-lng-input').value = latlng.lng.toFixed(6);
}

/** Move the picker marker to manually typed lat/lng. */
function applyManualCoords() {
    const lat = parseFloat(document.getElementById('loc-lat-input').value);
    const lng = parseFloat(document.getElementById('loc-lng-input').value);
    if (isNaN(lat) || isNaN(lng)) { showToast('Enter valid latitude and longitude.', 'warning'); return; }
    if (!locationPickerMap || !locationPickerMark) return;
    const ll = L.latLng(lat, lng);
    locationPickerMark.setLatLng(ll);
    locationPickerMap.setView(ll, Math.max(locationPickerMap.getZoom(), 12));
}

/** Save the pinned position and close the modal. */
function savePickedLocation() {
    if (!locationPickerMark || !locationPickerNid) return;
    const ll      = locationPickerMark.getLatLng();
    const company = getSelectedCompany();
    const posKey  = `${company}_${locationPickerNid}`;
    nodePositions[posKey] = [ll.lat, ll.lng];
    saveNodePositions();
    if (wiotMap) refreshMap();                 // sync main map
    renderLocationTable();                     // refresh table
    bootstrap.Modal.getInstance(document.getElementById('location-picker-modal'))?.hide();
    showToast(`Location saved for Node ${locationPickerNid} (${ll.lat.toFixed(4)}, ${ll.lng.toFixed(4)}).`, 'success');
}

/** Remove a node's saved position. */
function clearNodeLocation(nid) {
    const company = getSelectedCompany();
    const posKey  = `${company}_${nid}`;
    delete nodePositions[posKey];
    saveNodePositions();
    if (wiotMap) refreshMap();
    renderLocationTable();
    showToast(`Location cleared for Node ${nid}.`, 'info');
}

// ─── Page init ────────────────────────────────────────────────────────────────
window.onload = function() {
    searchTabular();
    if (document.getElementById('users-table')) {
        loadUsers();
        if (document.getElementById('companies-table')) loadCompanies();
    }
    initNodeSelectors();
    // Seed the chart with the default node's stored history so it isn't blank
    // (and doesn't "reset" on the first live reading) before any MQTT data.
    loadNodeHistory(document.getElementById('graph-node-select')?.value).then(renderGraphNode);
    handleCmdChange();
    updateFleetSummary();
    updateCommandAvailability();
};
