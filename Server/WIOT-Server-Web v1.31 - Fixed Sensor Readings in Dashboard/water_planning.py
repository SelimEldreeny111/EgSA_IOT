"""Calendar budgets and soil advice calculated from committed field samples."""
import json
import math
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flow_schema import DEFAULT_CALENDAR_TIMEZONE, flow_meter_name, period_quality_name, period_source_name
from input_validation import company_id, integer
from region_topics import region_id

PERIODS = ('day', 'month', 'year')


def _number(value, minimum, maximum, label):
    if value is None or value == '':
        return None
    if not isinstance(value, (int, float, str)) or isinstance(value, bool):
        raise ValueError(f'{label} must be numeric')
    try:
        result = float(value)
    except (ValueError, OverflowError):
        raise ValueError(f'{label} must be numeric') from None
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise ValueError(f'{label} must be {minimum}–{maximum}')
    return result


def validate_plan(data):
    zone = data.get('timezone', DEFAULT_CALENDAR_TIMEZONE)
    if not isinstance(zone, str) or len(zone) > 64:
        raise ValueError('Invalid site time zone')
    try:
        ZoneInfo(zone)
    except (ValueError, ZoneInfoNotFoundError):
        raise ValueError('Use an available IANA time zone') from None
    name = data.get('name', '')
    if not isinstance(name, str) or not name.strip() or len(name) > 80 or not name.isprintable():
        raise ValueError('Line name must be 1–80 printable characters')
    soil = data.get('soil', 'disabled')
    if soil not in ('disabled', 'hnda', 'sondas'):
        raise ValueError('Unknown soil sensor')
    dry = _number(data.get('dry_percent'), 0, 100, 'Dry moisture')
    wet = _number(data.get('wet_percent'), 0, 100, 'Wet moisture')
    if soil != 'disabled' and (dry is None or wet is None or dry >= wet):
        raise ValueError('Select distinct moisture thresholds with dry below wet')
    backfill = data.get('backfill', False)
    if type(backfill) is not bool:
        raise ValueError('Automatic backfill must be true or false')
    return {
        'name': name.strip(), 'timezone': zone, 'soil': soil, 'dry_percent': dry, 'wet_percent': wet,
        'sensor_id': integer(data.get('sensor_id', 1), 0, 65535, 'Flow sensor ID'),
        'meter': integer(data.get('meter', 1), 1, 2, 'Flow meter'),
        'report_seconds': integer(data.get('report_seconds'), 5, 86400, 'Report interval'),
        'warning_percent': integer(data.get('warning_percent', 80), 1, 99, 'Budget warning percent'),
        **{f'{period}_m3': _number(data.get(f'{period}_m3'), 0.001, 1e9, f'{period.title()} budget')
           for period in PERIODS},
        'backfill': backfill,
        'max_records': integer(data.get('max_records', 24), 1, 128, 'Automatic download record limit'),
    }


def calendar_day(epoch, zone):
    return int(datetime.fromtimestamp(epoch, tz=ZoneInfo(zone)).strftime('%Y%m%d'))


def _period_bounds(now, zone):
    local = datetime.fromtimestamp(now, tz=ZoneInfo(zone))
    day = local.replace(hour=0, minute=0, second=0, microsecond=0)
    month = day.replace(day=1)
    year = month.replace(month=1)
    next_month = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
    return {'day': (day, day + timedelta(days=1)), 'month': (month, next_month),
            'year': (year, year.replace(year=year.year + 1))}


def budget_rows(cfg, sample, now):
    """Use one reported snapshot per real period; never sum repeated totals."""
    rows = []
    bounds = _period_bounds(now, cfg['timezone'])
    for period in PERIODS:
        target = cfg[period + '_m3']
        if target is None:
            continue
        first, end = bounds[period]
        start_at, end_at = first.timestamp(), end.timestamp()
        used = epoch = forecast = quality = source = None
        state = 'no_data'
        if sample:
            epoch = sample['measured_at']
            if sample['time_source'] != 'node_rtc' or not epoch or epoch > now + 5:
                state = 'untrusted_time'
            elif sample['live_fallback'] != 0:
                state = 'unverified'
            elif not start_at <= epoch < end_at:
                state = 'new_period'
            else:
                source = period_source_name(sample['period_source'])
                quality = period_quality_name(sample['period_quality'])
                value = sample['volume_' + period]
                if sample['period_totals_valid'] and sample['period_source'] in (1, 2) and (
                        value is not None and math.isfinite(value) and value >= 0):
                    used = value
                    if sample['period_quality'] != 1:
                        state = 'uncertain'
                    elif now - epoch > 3 * cfg['report_seconds']:
                        state = 'stale'
                    else:
                        state = ('at_limit' if used >= target else 'near_limit'
                                 if 100 * used >= cfg['warning_percent'] * target else 'within')
                        elapsed = epoch - start_at
                        if period != 'day' and elapsed >= 2 * 86400:
                            forecast = round(used * (end_at - start_at) / elapsed, 3)
                else:
                    state = 'unavailable'
        rows.append(dict(period=period, starts=first.date().isoformat(), target_m3=target,
                         used_m3=used, remaining_m3=round(target - used, 3) if used is not None else None,
                         percent=round(100 * used / target, 1) if used is not None else None,
                         forecast_m3=forecast, measured_at=epoch, quality=quality, source=source, state=state))
    return rows


def soil_advice(cfg, samples, now, budgets):
    """Require two distinct, timely, valid readings for a threshold advisory."""
    soil = cfg['soil']
    if soil == 'disabled':
        return None
    result = dict(sensor=soil, state='awaiting_samples', moisture=None, trend_points_hour=None,
                  measured_at=None, budget_limit=any(row['state'] == 'at_limit' for row in budgets))
    if not samples:
        return result
    status = samples[0]
    epoch = status['measured_at']
    result['measured_at'] = epoch
    freshness = 3 * cfg['report_seconds']
    if status['time_source'] != 'node_rtc' or not epoch or epoch > now + 5 or status['operations_fallback']:
        return {**result, 'state': 'unverified'}
    if status['timestamp'] - epoch < -5:
        return {**result, 'state': 'unverified'}
    if now - epoch > freshness or status['timestamp'] - epoch > freshness:
        return {**result, 'state': 'stale'}
    mask, valid, moisture = ((2, 'soil_moisture_temp_valid', 'soil_moisture') if soil == 'hnda' else
                             (4, 'soil_moisture_temp_ec_valid', 'ec_moisture'))

    def reading(row):
        value = row[moisture]
        if (row['sensor_mask'] or 0) & mask and row[valid] and value is not None and 0 <= value <= 100:
            return value
        return None

    current = reading(status)
    if current is None:
        return {**result, 'state': 'unavailable'}
    result['moisture'] = current
    earlier = next((row for row in samples[1:] if row['measured_at'] != epoch or
                    row['time_source'] != 'node_rtc' or row['operations_fallback']), None)
    if (earlier is None or earlier['time_source'] != 'node_rtc' or earlier['operations_fallback'] or
            not earlier['measured_at'] or not 0 < epoch - earlier['measured_at'] <= freshness or
            now - earlier['measured_at'] > freshness or
            not -5 <= earlier['timestamp'] - earlier['measured_at'] <= freshness):
        return result
    previous = reading(earlier)
    if previous is None:
        return result
    result['trend_points_hour'] = round((current - previous) * 3600 / (epoch - earlier['measured_at']), 1)
    if max(current, previous) <= cfg['dry_percent']:
        result['state'] = 'dry'
    elif min(current, previous) >= cfg['wet_percent']:
        result['state'] = 'wet'
    elif all(cfg['dry_percent'] < value < cfg['wet_percent'] for value in (current, previous)):
        result['state'] = 'in_range'
    else:
        result['state'] = 'confirming'
    return result


class PlanningStore:
    """Keep site plans and durable automatic-recovery progress alongside operations."""

    def __init__(self, path):
        self.path = path
        with closing(self._db()) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS field_plans (
                company TEXT NOT NULL, region TEXT NOT NULL, node INTEGER NOT NULL,
                settings TEXT NOT NULL, recovery TEXT NOT NULL, updated_by TEXT NOT NULL,
                updated_at INTEGER NOT NULL, PRIMARY KEY(company,region,node))""")

    def _db(self):
        db = sqlite3.connect(self.path, timeout=3)
        db.row_factory = sqlite3.Row
        return db

    def configure(self, scope, data, actor, now, cursor):
        company, region, node = scope
        scope = company_id(company), region_id(region), integer(node, 1, 65535, 'Node ID')
        settings = validate_plan(data)
        with closing(self._db()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            prior = db.execute('SELECT settings,recovery FROM field_plans WHERE company=? AND region=? AND node=?',
                               scope).fetchone()
            old = json.loads(prior['settings']) if prior else {}
            if old == settings:
                return
            state = json.loads(prior['recovery']) if prior else {}
            recovery_changed = any(old.get(key) != settings[key] for key in
                                   ('backfill', 'report_seconds', 'timezone', 'max_records'))
            if recovery_changed:
                if state.get('state') in ('probing', 'downloading'):
                    state.update(cursor=cursor, stopped=True)
                    state.pop('last_report', None)
                else:
                    state = dict(cursor=cursor, state='watching')
            db.execute("""INSERT INTO field_plans VALUES(?,?,?,?,?,?,?)
                          ON CONFLICT(company,region,node) DO UPDATE SET settings=excluded.settings,
                          recovery=excluded.recovery,updated_by=excluded.updated_by,updated_at=excluded.updated_at""",
                       (*scope, json.dumps(settings), json.dumps(state), actor, now))
            return recovery_changed and old.get('backfill', False)

    def plans(self, company=None, region=None):
        with closing(self._db()) as db:
            rows = db.execute('SELECT * FROM field_plans WHERE (? IS NULL OR (company=? AND region=?)) '
                              'ORDER BY company,region,node', (company, company, region)).fetchall()
        return [((row['company'], row['region'], row['node']), json.loads(row['settings']),
                 json.loads(row['recovery'])) for row in rows]

    def save_recovery(self, scope, state):
        with closing(self._db()) as db, db:
            db.execute('UPDATE field_plans SET recovery=? WHERE company=? AND region=? AND node=?',
                       (json.dumps(state), *scope))


def planning_metrics(db, region, node, cfg, now):
    sample = None
    if any(cfg[period + '_m3'] is not None for period in PERIODS):
        sample = db.execute("""SELECT measured_at,time_source,volume_day,volume_month,volume_year,
                    period_source,period_quality,period_totals_valid,live_fallback FROM meter_samples
                    WHERE region=? AND node_id=? AND sensor_id=? AND flow_meter_type=?
                    ORDER BY received_at DESC,id DESC LIMIT 1""",
                    (region, node, str(cfg['sensor_id']), cfg['meter'])).fetchone()
    budgets = budget_rows(cfg, sample, now)
    readings = []
    if cfg['soil'] != 'disabled':
        readings = db.execute("""SELECT measured_at,timestamp,time_source,operations_fallback,sensor_mask,
                    soil_moisture,soil_moisture_temp_valid,ec_moisture,soil_moisture_temp_ec_valid
                    FROM messages WHERE region=? AND node_id=? AND type='Status'
                    AND operations_digest IS NOT NULL ORDER BY id DESC LIMIT 32""", (region, node)).fetchall()
    return dict(meter=flow_meter_name(cfg['meter']), budgets=budgets,
                advice=soil_advice(cfg, readings, now, budgets))
