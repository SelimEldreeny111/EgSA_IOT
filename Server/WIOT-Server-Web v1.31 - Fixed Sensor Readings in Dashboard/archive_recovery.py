"""Bounded, opt-in recovery through the existing Status and flash command paths."""
import logging
import secrets
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from flash_archive import FLASH_COMMANDS, MAX_RECORDS, RESULT_NAMES
from water_planning import calendar_day

ACTIVE = ('probing', 'downloading')
TERMINAL_COMMANDS = ('expired', 'cancelled', 'rejected', 'outcome_unknown', 'superseded')
SCAN_SIZE = 100
COOLDOWN_SECONDS = 4 * 3600
RETRY_SECONDS = 300
STREAM_SILENCE = 180


def _today_end(now, zone):
    local = datetime.fromtimestamp(now, tz=ZoneInfo(zone))
    return int((local.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)).timestamp())


def _observe(db, scope, cfg, state, now):
    interval = cfg['report_seconds']
    reports = db.execute("""SELECT id,timestamp,measured_at,time_source,operations_digest
        FROM messages WHERE region=? AND node_id=? AND id>? AND type='Status'
        AND operations_digest IS NOT NULL ORDER BY id LIMIT ?""",
        (*scope[1:], state.get('cursor', 0), SCAN_SIZE)).fetchall()
    for report in reports:
        state['cursor'] = report['id']
        receipt, measured = report['timestamp'], report['measured_at']
        prior = state.get('last_report')
        if prior is not None and (receipt <= prior or (receipt - prior <= 2 and
                state.get('last_digest') == report['operations_digest'])):
            continue
        state.update(last_report=receipt, last_digest=report['operations_digest'])
        if (prior is not None and receipt - prior >= 3 * interval and
                receipt >= now - 3 * interval and report['time_source'] == 'node_rtc' and
                measured is not None and -5 <= receipt - measured <= 3 * interval and
                state.get('state') not in ACTIVE):
            state.update(gap_from=prior, gap_to=receipt, gap_day=calendar_day(receipt, cfg['timezone']),
                         state='gap_detected', attempts=0, reason='Status reporting resumed after a gap')
    return len(reports) < SCAN_SIZE


def _finish(state, now, status, reason, retry=False):
    can_retry = retry and state['attempts'] < 2 and now + RETRY_SECONDS + 60 < state['day_end']
    state.update(state='gap_detected' if can_retry else status, reason=reason,
                 next_attempt=now + (RETRY_SECONDS if can_retry else COOLDOWN_SECONDS), updated_at=now)


def _prepare_request(store, scope, state, stage, now, command_data=0):
    state.update(state=stage, request_id=secrets.randbelow(0xFFFFFFFF) + 1, staged_at=now,
                 command_data=command_data, updated_at=now)
    # Persist the ID before enqueueing. A restart can reconcile the same intent.
    store.save_recovery(scope, state)


def _queued_intent(journal, scope, state, now):
    company, region, node = scope
    request = state['request_id']
    item = journal.get(request, company, node, now=now, region=region)
    if item:
        if not item['automatic']:
            raise RuntimeError('Automatic archive request ID collides with an operator command')
        return item
    ttl = state['queue_until'] - now
    if ttl < 60:
        return {'state': 'expired'}
    cmd = 'FLASH_STATUS' if state['state'] == 'probing' else 'FLASH_TODAY'
    # A concurrent operator request or full queue defers control until a later pass.
    try:
        journal.enqueue(company, node, FLASH_COMMANDS[cmd], cmd, state['command_data'],
                        request_id=request, ttl_seconds=ttl, now=now, actor='Automatic archive',
                        region=region, automatic=True)
    except ValueError:
        return None
    return journal.get(request, company, node, now=now, region=region)


def _start_download(store, archive, scope, cfg, state, item, now):
    summary = archive.summary(*scope)
    memory = summary['memory']
    if not memory or summary['status_request'] != item['request_id'] or summary['received_at'] < item['submitted_at']:
        if now - item['submitted_at'] > STREAM_SILENCE:
            _finish(state, now, 'incomplete', 'Flash probe did not return current memory status', retry=True)
        return
    if (not memory['rtc_trusted'] or memory['state'] not in (4, 5) or memory['busy'] or
            memory['next_clear_epoch'] and int(memory['next_clear_epoch']) <= now + 60):
        _finish(state, now, 'deferred', 'Flash unavailable, busy, near erase or RTC untrusted', retry=True)
        return
    if any(transfer['phase'] < 3 and transfer['result'] == 0 and transfer['received'] and
           now - transfer['updated'] < STREAM_SILENCE for transfer in summary['transfers']):
        _finish(state, now, 'deferred', 'Another history transfer is active', retry=True)
        return
    generation, latest = int(memory['generation']), int(memory['latest_sequence'])
    if not 0 < generation < 2**31 or not 0 <= latest <= MAX_RECORDS:
        _finish(state, now, 'deferred', 'Flash generation or sequence is outside the resume range')
        return
    day = state['gap_day']
    first = state.get('covered_next', 1) if (
        state.get('covered_generation') == generation and state.get('covered_day') == day) else 1
    if latest < first or not memory['record_count']:
        _finish(state, now, 'empty', 'No new retained records were reported')
        return
    cap = cfg['max_records']
    if min(int(memory['record_count']), latest - first + 1) > cap:
        _finish(state, now, 'manual_required', 'Retained record count exceeds the automatic limit')
        return
    deadline = min(state['day_end'], now + min(21600, max(300, 4 * cfg['report_seconds'])))
    if memory['next_clear_epoch']:
        deadline = min(deadline, int(memory['next_clear_epoch']) - 30)
    state.update(generation=generation, first=first, cap=cap, received=0, total=None,
                 gap_records=None, queue_until=deadline)
    # Send the generation even for sequence 1 so erase/reformat cannot change the target.
    _prepare_request(store, scope, state, 'downloading', now, (generation << 32) | first)


def _advance(store, archive, journal, scope, cfg, state, now, observing):
    stage = state['state']
    if stage == 'downloading':
        # A flash transfer can make progress even after a transient disconnect,
        # or after the operator has paused future automated requests.
        transfer, cursor, prefix = archive.recovery_progress(scope, state['request_id'], state['gap_day'],
                                                             state['generation'], state['first'], state['cap'])
        if transfer:
            state.update(received=transfer['received'], total=transfer['total'], updated_at=transfer['updated'])
            if cursor > state['first']:
                state.update(covered_generation=state['generation'], covered_day=state['gap_day'],
                             covered_next=cursor)
            if transfer['phase'] == 3 or transfer['result']:
                result = transfer['result']
                if (transfer['complete'] and transfer['generation'] == state['generation'] and
                        transfer['day'] == state['gap_day'] and transfer['received'] == prefix):
                    state['gap_records'] = archive.gap_records(
                        scope, state['generation'], state['gap_day'], state['gap_from'], state['gap_to'])
                    _finish(state, now, 'complete', f"{transfer['received']} retained records committed")
                else:
                    _finish(state, now, 'incomplete', RESULT_NAMES[result] if result else 'History coverage incomplete',
                            retry=result in (5, 6, 8))
                return
            if now - transfer['updated'] <= STREAM_SILENCE and transfer['phase'] == 2:
                return
    if stage not in ACTIVE:
        if (stage != 'gap_detected' or not cfg['backfill'] or not observing or
                now < state.get('next_attempt', 0)):
            return
        if calendar_day(now, cfg['timezone']) != state['gap_day']:
            state.update(state='window_passed', reason='Recovered gap belongs to an earlier node day', updated_at=now)
            return
        end = _today_end(now, cfg['timezone'])
        queue_until = min(end, now + min(21600, max(300, 4 * cfg['report_seconds'])))
        if queue_until - now < 60:
            state.update(state='window_passed', reason='Too close to the node day boundary', updated_at=now)
            return
        state.update(attempts=state['attempts'] + 1, day_end=end, queue_until=queue_until, stopped=False)
        _prepare_request(store, scope, state, 'probing', now)
        return
    if state.get('stopped') or not cfg['backfill'] or now >= state['day_end']:
        journal.withdraw_automatic(*scope, now)
        _finish(state, now, 'deferred', 'Automatic request paused or node day changed')
        return
    if not observing:
        return
    item = _queued_intent(journal, scope, state, now)
    if not item:
        return
    if item['state'] in TERMINAL_COMMANDS:
        _finish(state, now, 'incomplete', f"Automatic {stage} request {item['state']}",
                retry=item['state'] in ('outcome_unknown', 'rejected'))
    elif item['state'] == 'acknowledged':
        if stage == 'probing':
            _start_download(store, archive, scope, cfg, state, item, now)
        elif now - (state.get('updated_at') or item['submitted_at']) > STREAM_SILENCE:
            _finish(state, now, 'incomplete', 'No recent history progress', retry=True)


def run_recovery_pass(store, archive, journal, database_path, now, observing):
    """Scan committed Status in bounded batches; leave publication to the existing mailbox."""
    targets = [target for target in store.plans() if target[1]['backfill'] or target[2].get('state') in ACTIVE]
    occupied = any(state.get('state') in ACTIVE for _, _, state in targets)
    for scope, cfg, state in targets:
        previous = state.copy()
        active = state.get('state') in ACTIVE
        try:
            caught_up = True
            if cfg['backfill']:
                path = Path(database_path(scope[0]))
                with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=2)) as db:
                    db.row_factory = sqlite3.Row
                    caught_up = _observe(db, scope, cfg, state, now)
            if active or (not occupied and caught_up):
                _advance(store, archive, journal, scope, cfg, state, now, observing)
                occupied |= state.get('state') in ACTIVE
            if state != previous:
                store.save_recovery(scope, state)
        except (sqlite3.Error, OSError, RuntimeError, ValueError):
            logging.exception('Automatic archive pass failed for %s/%s/%s', *scope)
