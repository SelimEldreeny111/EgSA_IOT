"""Server-side water incidents and equipment health from committed Status reports."""
import csv
import json
import math
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta
from io import StringIO
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from input_validation import company_id, integer
from region_topics import region_id


BATCH_SIZE = 100
CLOCK_SKEW = 5
FLOW_RULES = (
    ('quiet_flow', 'quiet_min', 'quiet_flow_m3h'),
    ('high_flow', 'high_min', 'high_flow_m3h'),
    ('reverse_flow', 'reverse_min', 'reverse_flow_m3h'),
)
SELECT_REPORTS = """SELECT id, timestamp, measured_at, time_source, operations_digest, operations_fallback,
    flow_meter_type, flow, flow_live_valid, flow_cumulative_totals_valid,
    forward_total_liters, reverse_total_liters, legacy_flow_schema,
    secondary_flow_json, sensor_mask, soil_moisture_temp_valid, soil_moisture_temp_ec_valid,
    battery_voltage, wdt_reset_count, power_reset_count
    FROM messages WHERE region=? AND node_id=? AND id>? AND type='Status'
    AND operations_digest IS NOT NULL ORDER BY id LIMIT ?"""


def _threshold(value, label, maximum):
    if value is None or value == '':
        return None
    if type(value) not in (float, int, str):
        raise ValueError(f'{label} must be a positive number')
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f'{label} must be a positive number') from None
    if not math.isfinite(number) or not 0 < number <= maximum:
        raise ValueError(f'{label} must be greater than zero and at most {maximum}')
    return number


def validate_settings(data):
    """A blank threshold disables only that rule. Report interval is site-specific."""
    enabled = data.get('enabled', True)
    if type(enabled) is not bool:
        raise ValueError('Enabled must be true or false')
    name = data.get('name', '')
    if not isinstance(name, str) or not name.strip() or len(name) > 80 or not name.isprintable():
        raise ValueError('Site name must be 1–80 printable characters')
    timezone = data.get('timezone', 'Africa/Cairo')
    if not isinstance(timezone, str) or len(timezone) > 64:
        raise ValueError('Invalid IANA time zone')
    try:
        ZoneInfo(timezone)
    except (ValueError, ZoneInfoNotFoundError):
        raise ValueError('Invalid or unavailable IANA time zone') from None
    start, end = data.get('quiet_start', '00:00'), data.get('quiet_end', '05:00')
    if any(not isinstance(value, str) or not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]', value)
           for value in (start, end)):
        raise ValueError('Quiet hours use HH:MM')
    quiet = _threshold(data.get('quiet_flow_m3h'), 'Quiet-hours flow', 1_000_000)
    if quiet is not None and start == end:
        raise ValueError('Quiet hours need different start and end times')
    expected = integer(data.get('expected_seconds'), 5, 604800, 'Report interval')
    max_gap = integer(data.get('max_gap_seconds', 2 * expected), expected, 1209600, 'Maximum sample gap')
    return {
        'name': name.strip(), 'enabled': enabled, 'timezone': timezone,
        'meter': integer(data.get('meter'), 1, 2, 'Flow meter'),
        'gateway': integer(data.get('gateway') or 0, 0, 65535, 'Gateway ID'),
        'expected_seconds': expected, 'max_gap_seconds': max_gap,
        'hold_seconds': integer(data.get('hold_seconds', 60), 1, 604800, 'Alert hold'),
        'recovery_seconds': integer(data.get('recovery_seconds', 30), 1, 604800, 'Recovery hold'),
        'quiet_start': start, 'quiet_end': end, 'quiet_flow_m3h': quiet,
        'high_flow_m3h': _threshold(data.get('high_flow_m3h'), 'High flow', 1_000_000),
        'reverse_flow_m3h': _threshold(data.get('reverse_flow_m3h'), 'Reverse flow', 1_000_000),
        'battery_min_v': _threshold(data.get('battery_min_v'), 'Battery voltage', 100),
    }


def _quiet_window(epoch, settings):
    local = datetime.fromtimestamp(epoch, ZoneInfo(settings['timezone']))
    clock = local.strftime('%H:%M')
    start, end = settings['quiet_start'], settings['quiet_end']
    if start < end:
        return local.date().isoformat() if start <= clock < end else None
    if start == end or (clock < start and clock >= end):
        return None
    return (local.date() - timedelta(days=int(clock < end))).isoformat()


def _reading(report, meter):
    if report['flow_meter_type'] == meter and not report['legacy_flow_schema']:
        return (report['flow_live_valid'], report['flow'], report['flow_cumulative_totals_valid'],
                report['forward_total_liters'], report['reverse_total_liters'])
    secondary = json.loads(report['secondary_flow_json'] or '{}')
    if secondary.get('flow_meter_type') == meter and not secondary.get('legacy_flow_schema'):
        return (secondary['flow_live_valid'], secondary['flow_rate'],
                secondary['flow_cumulative_totals_valid'], secondary['forward_total_liters'],
                secondary['reverse_total_liters'])
    return False, None, False, None, None


def _seed(epoch, flow, total, window):
    return {'first_at': epoch, 'last_at': epoch, 'first_flow_m3h': flow,
            'last_flow_m3h': flow, 'last_total': total, 'window': window,
            'observed_seconds': 0, 'volume_liters': None, 'complete_volume': True}


def _extend(span, epoch, flow, total, max_gap, window, interrupted):
    elapsed = epoch - span['last_at']
    continuous = not interrupted and 0 < elapsed <= max_gap and span['window'] == window
    if continuous:
        span['observed_seconds'] += elapsed
    before = span['last_total']
    if continuous and before is not None and total is not None and total >= before:
        span['volume_liters'] = (span['volume_liters'] or 0) + total - before
    else:
        span['complete_volume'] = False
    span.update(last_at=epoch, last_flow_m3h=flow, last_total=total, window=window)


class OperationsStore:
    """Persist profiles, a per-node cursor, and incident transitions in one transaction."""

    def __init__(self, path):
        self.path = path
        with closing(self._db()) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS operations_profiles (
                    company TEXT NOT NULL, region TEXT NOT NULL, node INTEGER NOT NULL,
                    settings TEXT NOT NULL, activated_at INTEGER NOT NULL,
                    updated_by TEXT NOT NULL, revision INTEGER NOT NULL,
                    cursor INTEGER NOT NULL, snapshot TEXT NOT NULL,
                    PRIMARY KEY(company,region,node));
                CREATE TABLE IF NOT EXISTS operations_incidents (
                    id INTEGER PRIMARY KEY, company TEXT NOT NULL, region TEXT NOT NULL,
                    node INTEGER NOT NULL, kind TEXT NOT NULL, opened_at INTEGER NOT NULL,
                    last_at INTEGER NOT NULL, closed_at INTEGER, close_reason TEXT,
                    acknowledged_at INTEGER, acknowledged_by TEXT, evidence TEXT NOT NULL);
                CREATE UNIQUE INDEX IF NOT EXISTS operations_single_open
                    ON operations_incidents(company,region,node,kind) WHERE closed_at IS NULL;
                CREATE INDEX IF NOT EXISTS operations_by_region
                    ON operations_incidents(company,region,id DESC);
            """)

    def _db(self):
        db = sqlite3.connect(self.path, timeout=3)
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def _scope(company, region, node):
        return company_id(company), region_id(region), integer(node, 1, 65535, 'Node ID')

    def configure(self, company, region, node, data, actor, at, cursor):
        scope = self._scope(company, region, node)
        settings = json.dumps(validate_settings(data), sort_keys=True)
        with closing(self._db()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            previous = db.execute('SELECT settings FROM operations_profiles '
                                  'WHERE company=? AND region=? AND node=?', scope).fetchone()
            if previous and previous['settings'] == settings:
                return
            db.execute("""INSERT INTO operations_profiles VALUES(?,?,?,?,?,?,1,?,'{}')
                       ON CONFLICT(company,region,node) DO UPDATE SET settings=excluded.settings,
                       activated_at=excluded.activated_at,updated_by=excluded.updated_by,
                       revision=operations_profiles.revision+1,cursor=excluded.cursor,snapshot='{}'""",
                       (*scope, settings, at, actor, cursor))
            db.execute("""UPDATE operations_incidents SET closed_at=?,close_reason='monitoring_changed'
                       WHERE company=? AND region=? AND node=? AND closed_at IS NULL""", (at, *scope))

    def targets(self):
        with closing(self._db()) as db:
            rows = db.execute("SELECT company,region,node,cursor,revision,settings FROM operations_profiles").fetchall()
        return [row for row in rows if json.loads(row['settings'])['enabled']]

    def process(self, target, reports, now, observing, observed_since, gateway_state=None):
        scope = (target['company'], target['region'], target['node'])
        with closing(self._db()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM operations_profiles WHERE company=? AND region=? AND node=?',
                             scope).fetchone()
            if row is None or row['revision'] != target['revision']:
                return
            state = json.loads(row['snapshot'])
            settings = json.loads(row['settings'])
            cursor = row['cursor']
            for report in reports:
                if report['id'] <= cursor:
                    continue
                cursor = report['id']
                self._report(db, scope, settings, state, report)
            self._connectivity(db, scope, settings, state, now,
                               observing, observed_since, row['activated_at'], gateway_state)
            snapshot = json.dumps(state)
            if cursor != row['cursor'] or snapshot != row['snapshot']:
                db.execute('UPDATE operations_profiles SET cursor=?,snapshot=? '
                           'WHERE company=? AND region=? AND node=?', (cursor, snapshot, *scope))

    @staticmethod
    def _incident(db, scope, kind):
        return db.execute('SELECT id,evidence FROM operations_incidents '
                          'WHERE company=? AND region=? AND node=? AND kind=? AND closed_at IS NULL',
                          (*scope, kind)).fetchone()

    @staticmethod
    def _update(db, scope, kind, condition, epoch, evidence):
        if condition:
            db.execute("""INSERT INTO operations_incidents
                       (company,region,node,kind,opened_at,last_at,evidence) VALUES(?,?,?,?,?,?,?)
                       ON CONFLICT(company,region,node,kind) WHERE closed_at IS NULL DO UPDATE SET
                       last_at=excluded.last_at,evidence=excluded.evidence""",
                       (*scope, kind, epoch, epoch, json.dumps(evidence)))
        else:
            db.execute("""UPDATE operations_incidents SET closed_at=MAX(?,opened_at), close_reason='recovered'
                       WHERE company=? AND region=? AND node=? AND kind=? AND closed_at IS NULL""",
                       (epoch, *scope, kind))

    def _flow(self, db, scope, cfg, state, epoch, reading):
        _, rate, cumulative, forward, reverse = reading
        candidates = state.setdefault('flow_candidates', {})
        recovering = state.setdefault('flow_recovery', {})
        interruptions = state.setdefault('flow_interruptions', {})
        for kind, direction, threshold_field in FLOW_RULES:
            threshold = cfg[threshold_field]
            window = _quiet_window(epoch, cfg) if direction == 'quiet_min' else 'all'
            if threshold is None or window is None:
                candidates.pop(kind, None)
                recovering.pop(kind, None)
                interruptions[kind] = True
                continue
            magnitude = -rate if direction == 'reverse_min' else rate
            total = (reverse if direction == 'reverse_min' else forward) if cumulative else None
            incident = self._incident(db, scope, kind)
            if magnitude >= threshold:
                recovering.pop(kind, None)
                if incident:
                    span = json.loads(incident['evidence'])
                else:
                    span = candidates.get(kind)
                    if (span is None or span['window'] != window or
                            epoch - span['last_at'] > cfg['max_gap_seconds']):
                        candidates[kind] = _seed(epoch, rate, total, window)
                        interruptions.pop(kind, None)
                        continue
                _extend(span, epoch, rate, total, cfg['max_gap_seconds'], window,
                        interruptions.pop(kind, False))
                if incident or span['observed_seconds'] >= cfg['hold_seconds']:
                    self._update(db, scope, kind, True, epoch, span)
                    candidates.pop(kind, None)
            else:
                candidates.pop(kind, None)
                interruptions[kind] = True
                # Separate thresholds give 15% hysteresis around the trigger.
                if incident and magnitude <= threshold * 0.85:
                    first, last, prior_window = recovering.get(kind, (epoch, epoch, window))
                    if prior_window != window or epoch - last > cfg['max_gap_seconds']:
                        first = epoch
                    recovering[kind] = (first, epoch, window)
                    if epoch - first >= cfg['recovery_seconds']:
                        self._update(db, scope, kind, False, epoch, {})
                        recovering.pop(kind, None)
                else:
                    recovering.pop(kind, None)

    def _debounce(self, db, scope, kind, state, condition, epoch, evidence, max_gap):
        counters = state.setdefault('health_candidates', {})
        if condition is None:
            counters.pop(kind, None)
            return
        prior, count, previous_at = counters.get(kind, (None, 0, 0))
        count = min(count + 1, 2) if prior == condition and epoch - previous_at <= max_gap else 1
        counters[kind] = (condition, count, epoch)
        if count >= 2:
            self._update(db, scope, kind, condition, epoch, evidence)

    def _report(self, db, scope, cfg, state, report):
        receipt, epoch = report['timestamp'], report['measured_at']
        last_receipt = state.get('last_report', -1)
        if receipt < last_receipt or (receipt - last_receipt <= 2 and
                                      report['operations_digest'] == state.get('last_digest')):
            return
        state.update(last_report=receipt, last_digest=report['operations_digest'])
        trusted_clock = (report['time_source'] == 'node_rtc' and epoch is not None and
                         epoch <= receipt + CLOCK_SKEW)
        current_time = trusted_clock and receipt - epoch <= cfg['max_gap_seconds']
        fresh = current_time and not report['operations_fallback']
        reading = _reading(report, cfg['meter'])
        valid = bool(reading[0]) and reading[1] is not None
        battery = report['battery_voltage']
        battery = battery if battery is not None and battery > 0 else None
        time_quality = ('unverified' if current_time and not fresh else 'fresh' if fresh
                        else 'delayed' if trusted_clock else 'untrusted')
        state.update(time_quality=time_quality,
                     meter_state='valid' if fresh and valid else
                                 ('unavailable' if fresh else 'unknown'),
                     battery_v=battery)
        if fresh:
            state['last_measurement'] = max(epoch, state.get('last_measurement', epoch))
        if fresh and epoch > state.get('last_water_sample', -1):
            state['last_water_sample'] = epoch
            if valid:
                self._flow(db, scope, cfg, state, epoch, reading)
            else:
                # Break continuity without declaring an open alert recovered.
                state.pop('flow_candidates', None)
                state.pop('flow_recovery', None)
                state['flow_interruptions'] = {kind: True for kind, _, _ in FLOW_RULES}
            failed = [name for mask, flag, name in
                      ((2, 'soil_moisture_temp_valid', 'HNDA'),
                       (4, 'soil_moisture_temp_ec_valid', 'Sondas'))
                      if (report['sensor_mask'] or 0) & mask and not report[flag]]
            self._debounce(db, scope, 'meter_unavailable', state, not valid, receipt,
                           {'meter': cfg['meter']}, cfg['max_gap_seconds'])
            self._debounce(db, scope, 'sensor_unavailable', state, bool(failed), receipt,
                           {'sensors': failed}, cfg['max_gap_seconds'])
        elif not fresh:
            state.pop('flow_candidates', None)
            state.pop('flow_recovery', None)
            state['flow_interruptions'] = {kind: True for kind, _, _ in FLOW_RULES}
        self._debounce(db, scope, 'stale_sample', state, not current_time if trusted_clock else None,
                       receipt, {'measured_at': epoch}, cfg['max_gap_seconds'])
        self._debounce(db, scope, 'sample_unverified', state, bool(report['operations_fallback']),
                       receipt, {}, cfg['max_gap_seconds'])
        self._debounce(db, scope, 'rtc_untrusted', state, not trusted_clock,
                       receipt, {}, cfg['max_gap_seconds'])
        low = cfg['battery_min_v']
        self._debounce(db, scope, 'low_battery', state,
                       (True if battery < low else False if battery >= low + 0.1 else None)
                       if low is not None and battery is not None and fresh else None,
                       receipt, {'voltage': battery, 'threshold': low}, cfg['max_gap_seconds'])
        for kind, field in (('watchdog_resets', 'wdt_reset_count'), ('power_resets', 'power_reset_count')):
            count, prior = report[field], state.get(field)
            if count is None:
                continue
            delta = count - prior if prior is not None else 0
            if delta > 0 and fresh:
                self._update(db, scope, kind, True, receipt, {'counter': count, 'increase': delta})
                state[field + '_changed'] = receipt
            elif prior is not None and count < prior and fresh:
                state[field + '_changed'] = receipt
            elif fresh and receipt - state.get(field + '_changed', receipt) >= 3 * cfg['expected_seconds']:
                self._update(db, scope, kind, False, receipt, {})
            if fresh or prior is None:
                state[field] = count

    def _connectivity(self, db, scope, cfg, state, now, observing, since, activated, gateway):
        last_report = state.get('last_report')
        interval = cfg['expected_seconds']
        if not observing:
            status = 'unobserved'
        elif cfg['gateway'] and gateway in ('offline', 'overdue', 'unobserved'):
            status = 'gateway_unavailable'
        else:
            baseline = max(last_report or 0, since, activated)
            elapsed = max(0, now - baseline)
            if elapsed >= 3 * interval:
                status = 'offline'
                if self._incident(db, scope, 'node_offline') is None:
                    self._update(db, scope, 'node_offline', True, now,
                                 {'last_report': last_report, 'expected_seconds': interval})
            elif elapsed >= 2 * interval:
                status = 'overdue'
            elif last_report is None or last_report < max(since, activated):
                status = 'awaiting_report'
            else:
                status = 'online'
                self._update(db, scope, 'node_offline', False, last_report, {})
        state['connectivity'] = status

    def dashboard(self, company, region, observing, before=None):
        scope = company_id(company), region_id(region)
        with closing(self._db()) as db:
            profiles = []
            for row in db.execute("SELECT node,settings,snapshot FROM operations_profiles "
                                  "WHERE company=? AND region=? ORDER BY node", scope):
                snapshot = json.loads(row['snapshot'])
                settings = json.loads(row['settings'])
                connectivity = ('disabled' if not settings['enabled'] else
                                snapshot.get('connectivity', 'awaiting_report') if observing else 'unobserved')
                health = {key: snapshot.get(key) for key in
                          ('last_report', 'last_measurement', 'battery_v', 'meter_state',
                           'time_quality', 'wdt_reset_count', 'power_reset_count')}
                profiles.append(dict(node=row['node'], settings=settings, **health, connectivity=connectivity))
        incidents = self.incidents(*scope, before=before, limit=50)
        return dict(observing=observing, nodes=profiles, incidents=incidents)

    def incidents(self, company, region, before=None, limit=100):
        scope = company_id(company), region_id(region)
        with closing(self._db()) as db:
            rows = db.execute("""SELECT * FROM operations_incidents WHERE company=? AND region=?
                              AND (? IS NULL OR id<?) ORDER BY id DESC LIMIT ?""",
                              (*scope, before, before, limit)).fetchall()
        return [dict(row, evidence=json.loads(row['evidence'])) for row in rows]

    def acknowledge(self, company, region, incident, actor, now):
        scope = company_id(company), region_id(region)
        with closing(self._db()) as db, db:
            result = db.execute("""UPDATE operations_incidents SET
                                acknowledged_at=COALESCE(acknowledged_at,?),
                                acknowledged_by=COALESCE(acknowledged_by,?)
                                WHERE id=? AND company=? AND region=?""",
                                (now, actor, incident, *scope))
            return result.rowcount == 1

    def csv_rows(self, company, region):
        buffer = StringIO()
        writer = csv.writer(buffer)
        writer.writerow(('ID', 'Node', 'Rule', 'Opened UTC epoch', 'Last evidence UTC epoch',
                         'Closed UTC epoch', 'Close reason', 'Acknowledged UTC epoch',
                         'Acknowledged by', 'Evidence JSON'))
        yield buffer.getvalue()
        before = None
        while rows := self.incidents(company, region, before):
            buffer.seek(0)
            buffer.truncate(0)
            for row in rows:
                actor = row['acknowledged_by'] or ''
                if actor.lstrip().startswith(('=', '+', '-', '@')):
                    actor = "'" + actor
                writer.writerow((row['id'], row['node'], row['kind'], row['opened_at'], row['last_at'],
                                 row['closed_at'], row['close_reason'], row['acknowledged_at'],
                                 actor, json.dumps(row['evidence'])))
            yield buffer.getvalue()
            before = rows[-1]['id']
