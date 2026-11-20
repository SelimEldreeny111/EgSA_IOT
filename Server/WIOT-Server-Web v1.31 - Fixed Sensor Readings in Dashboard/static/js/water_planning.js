(function () {
    'use strict';
    const panel = document.getElementById('WaterPlanning');
    if (!panel) return;
    const byId = name => document.getElementById('planning-' + name);
    const form = byId('form');
    const selected = () => new URLSearchParams({company: getSelectedCompany(), region: getSelectedRegion()}).toString();
    const when = epoch => epoch == null ? '—' : new Date(epoch * 1000).toLocaleString();
    const format = new Intl.NumberFormat(undefined, {maximumFractionDigits: 3});
    const quantity = (value, unit) => value == null ? '—' : format.format(value) + ' ' + unit;
    const budgetStates = {within: 'Within budget', near_limit: 'Near limit', at_limit: 'At or over budget',
        no_data: 'Awaiting a meter sample', untrusted_time: 'Untrusted clock', unverified: 'Unverified sample',
        new_period: 'Awaiting this period’s total', unavailable: 'Period total unavailable',
        uncertain: 'Uncertain total', stale: 'Stale total'};
    const soilStates = {dry: 'Dry confirmed. Review irrigation need.',
        wet: 'Wet confirmed. Review before adding water.', in_range: 'Within configured range',
        confirming: 'Waiting for confirmation', awaiting_samples: 'Awaiting two valid soil readings',
        unverified: 'Unverified measurement', stale: 'Reading is stale', unavailable: 'Sensor data unavailable'};
    const recoveryStates = {watching: 'Watching for report gaps', gap_detected: 'Gap detected',
        probing: 'Checking flash on next Status', downloading: 'Recovering retained records', complete: 'Completed',
        deferred: 'Deferred', empty: 'No new retained records', incomplete: 'Incomplete',
        manual_required: 'Manual download required', window_passed: 'Recovery window passed'};
    let activeScope = '';
    let revision = 0;

    function row(values) {
        const tr = document.createElement('tr');
        for (const value of values) {
            const td = document.createElement('td');
            td.textContent = String(value);
            tr.append(td);
        }
        return tr;
    }

    function table(name, rows, columns, emptyMessage) {
        if (!rows.length) {
            const empty = row([emptyMessage]);
            empty.firstElementChild.colSpan = columns;
            empty.firstElementChild.className = 'status-note text-center py-3';
            rows = [empty];
        }
        byId(name).replaceChildren(...rows);
    }

    function label(plan) {
        return plan.settings.name + ' / ' + plan.node;
    }

    function budgetRows(plans) {
        return plans.flatMap(plan => plan.budgets.map(budget => {
            const use = quantity(budget.used_m3, 'm³') + ' / ' + quantity(budget.target_m3, 'm³') +
                (budget.percent == null ? '' : ' (' + quantity(budget.percent, '%') + ')');
            const evidence = [budgetStates[budget.state], budget.quality, budget.source,
                budget.measured_at == null ? null : when(budget.measured_at)].filter(Boolean).join(' · ');
            return row([label(plan) + ' · ' + plan.meter, budget.period + ' · ' + budget.starts,
                use, quantity(budget.remaining_m3, 'm³'), quantity(budget.forecast_m3, 'm³'), evidence]);
        }));
    }

    function soilRows(plans) {
        return plans.filter(plan => plan.advice).map(plan => {
            const advice = plan.advice;
            const action = advice.state === 'dry' && advice.budget_limit
                ? 'Dry confirmed. Water budget reached. Review with the operator.' : soilStates[advice.state];
            return row([label(plan) + ' · ' + (advice.sensor === 'hnda' ? 'HNDA' : 'Sondas'),
                quantity(advice.moisture, '%'), quantity(advice.trend_points_hour, 'percentage points/h'),
                action, when(advice.measured_at)]);
        });
    }

    function edit(plan, scope) {
        if (selected() !== scope) return;
        byId('settings').open = true;
        form.elements.namedItem('node').value = plan.node;
        for (const [key, value] of Object.entries(plan.settings)) {
            const field = form.elements.namedItem(key);
            if (!field) continue;
            if (key === 'backfill') field.checked = value;
            else field.value = value ?? '';
        }
        byId('result').textContent = '';
        form.elements.namedItem('name').focus();
    }

    function recoveryRows(plans, scope) {
        return plans.map(plan => {
            const progress = plan.recovery;
            const state = plan.settings.backfill ? recoveryStates[progress.state] || 'Watching' : 'Disabled';
            const request = progress.request_id == null ? '—' : '#' + progress.request_id;
            const records = progress.received == null ? '' :
                ' · ' + progress.received + (progress.total == null ? '' : '/' + progress.total) + ' records';
            const gapRecords = progress.gap_records == null ? '' : ' · ' + progress.gap_records + ' inside gap';
            const tr = row([label(plan), state + (progress.reason ? ' · ' + progress.reason : ''),
                progress.gap_from == null ? '—' : when(progress.gap_from) + ' → ' + when(progress.gap_to),
                request + records + gapRecords]);
            if (form) {
                const actions = document.createElement('td');
                const button = document.createElement('button');
                button.type = 'button';
                button.className = 'btn btn-sm btn-outline-secondary me-2';
                button.textContent = 'Edit';
                button.addEventListener('click', () => edit(plan, scope));
                const link = document.createElement('a');
                link.textContent = 'CSV';
                link.className = 'btn btn-sm btn-outline-secondary';
                link.href = '/api/flash/records?' + scope + '&node=' + encodeURIComponent(plan.node) + '&format=csv';
                actions.append(button, link);
                tr.append(actions);
            }
            return tr;
        });
    }

    async function send(url, options) {
        const reply = await fetch(url, options);
        const data = await reply.json().catch(() => ({}));
        if (!reply.ok || !data || !Object.keys(data).length) {
            throw new Error(data.error || 'Unable to load the water plan.');
        }
        return data;
    }

    async function refresh() {
        const scope = selected();
        if (activeScope !== scope) {
            activeScope = scope;
            for (const name of ['budgets', 'soil', 'recovery']) byId(name).replaceChildren();
            byId('status').textContent = 'Loading field plans';
            if (form) {
                form.reset();
                byId('result').textContent = '';
            }
        }
        const attempt = ++revision;
        try {
            const data = await send('/api/planning?' + scope);
            if (revision !== attempt || selected() !== scope) return;
            table('budgets', budgetRows(data.plans), 6, 'No water budgets configured.');
            table('soil', soilRows(data.plans), 5, 'No soil advisory configured.');
            table('recovery', recoveryRows(data.plans, scope), form ? 5 : 4, 'No field plans configured.');
            byId('status').textContent = '';
        } catch (error) {
            if (revision === attempt && selected() === scope) byId('status').textContent = error.message;
        }
    }

    byId('refresh').addEventListener('click', refresh);
    byId('tab').addEventListener('shown.bs.tab', refresh);
    for (const name of ['cfg-company', 'cfg-region']) {
        document.getElementById(name)?.addEventListener('change', () => {
            if (panel.classList.contains('active')) refresh();
        });
    }
    if (form) form.addEventListener('submit', async event => {
        event.preventDefault();
        const scope = selected();
        if (scope !== activeScope) { refresh(); return; }
        const submit = form.querySelector('[type="submit"]');
        submit.disabled = true;
        const data = Object.fromEntries(new FormData(form));
        const node = data.node;
        delete data.node;
        data.backfill = form.elements.namedItem('backfill').checked;
        try {
            await send('/api/planning/profiles/' + encodeURIComponent(node) + '?' + scope,
                {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data)});
            if (selected() !== scope) return;
            byId('result').textContent = 'Field plan saved.';
            refresh();
        } catch (error) {
            if (selected() === scope) byId('result').textContent = error.message;
        } finally {
            submit.disabled = false;
        }
    });
    window.setInterval(() => { if (panel.classList.contains('active')) refresh(); }, 15000);
}());
