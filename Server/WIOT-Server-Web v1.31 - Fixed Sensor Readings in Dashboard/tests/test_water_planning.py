"""Water budgets, advisory, and flash recovery using simulated field messages."""
import importlib
import logging
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import command_queue
import flash_archive
import messages_pb2 as pb
from archive_recovery import RETRY_SECONDS, run_recovery_pass
from command_queue import CommandQueue
from flash_archive import FlashArchive
from water_planning import PlanningStore, budget_rows, calendar_day, soil_advice, validate_plan

SCOPE = ('Company_1', 'Region_1', 7)
START = int(datetime(2026, 11, 20, 12, tzinfo=timezone.utc).timestamp())
PLAN = dict(name='Demo line', meter=2, sensor_id=1, timezone='UTC', report_seconds=10,
            day_m3=100, month_m3=1000, year_m3=5000, warning_percent=80, soil='sondas',
            dry_percent=20, wet_percent=70, backfill=True, max_records=4)


def meter(epoch=START, **changes):
    return {**dict(measured_at=epoch, time_source='node_rtc', live_fallback=False,
                   volume_day=81, volume_month=1000, volume_year=3200, period_source=2,
                   period_quality=1, period_totals_valid=True), **changes}


def soil(epoch, moisture, **changes):
    return {**dict(measured_at=epoch, timestamp=epoch, time_source='node_rtc',
                   operations_fallback=False, sensor_mask=6, soil_moisture_temp_valid=1,
                   soil_moisture_temp_ec_valid=1, soil_moisture=91, ec_moisture=moisture), **changes}


def stored(request, index=1, sequence=1, total=2, generation=11, epoch=START + 10, node=7):
    msg = pb.Telemetry(node_id=node, timestamp=epoch, sample_time_valid=True,
                       stored_sample=True, sample_sequence=sequence)
    msg.history.CopyFrom(pb.HistoryInfo(request_id=request, generation=generation, sequence=sequence,
        index=index, total=total, day_key=calendar_day(epoch, 'UTC'), kind=2, phase=2, ack_required=True))
    return msg


def terminal(request, result=0, index=2, total=2):
    msg = pb.Telemetry(node_id=7)
    msg.history.CopyFrom(pb.HistoryInfo(request_id=request, generation=11, index=index,
        total=total, day_key=calendar_day(START, 'UTC'), kind=2, phase=3, result=result, ack_required=True))
    return msg


def flash_status(request, now, count=2):
    msg = pb.Telemetry(node_id=7, command_ack_request_id=request, command_ack_cmd_id=10,
                       command_ack_success=True)
    msg.flash_log.CopyFrom(pb.FlashLogInfo(state=4, capacity_bytes=8388608, usable_bytes=5120,
        used_bytes=count * 512, free_bytes=5120 - count * 512, record_count=count, maximum_records=10,
        generation=11, latest_sequence=count, rtc_trusted=True, next_clear_epoch=now + 7200))
    return msg


class PlanningCalculations(unittest.TestCase):
    def setUp(self):
        self.cfg = validate_plan(PLAN)

    def test_budget_uses_each_reported_period_and_estimates_long_periods(self):
        day, month, year = budget_rows(self.cfg, meter(), START)
        self.assertEqual((day['state'], day['remaining_m3'], day['percent']), ('near_limit', 19, 81))
        self.assertIsNone(day['forecast_m3'])
        self.assertEqual(month['state'], 'at_limit')
        self.assertEqual(month['forecast_m3'], 1538.462)
        self.assertEqual(year['state'], 'within')
        self.assertIsNotNone(year['forecast_m3'])

    def test_budget_keeps_quality_clock_and_period_rollover_visible(self):
        for sample, now, expected in (
            (meter(period_quality=2), START, 'uncertain'),
            (meter(live_fallback=True), START, 'unverified'),
            (meter(live_fallback=None), START, 'unverified'),
            (meter(time_source='server_received'), START, 'untrusted_time'),
            (meter(period_totals_valid=False), START, 'unavailable'),
            (meter(), START + 31, 'stale'),
            (meter(), START + 13 * 3600, 'new_period'),
        ):
            with self.subTest(expected=expected):
                row = budget_rows(self.cfg, sample, now)[0]
                self.assertEqual(row['state'], expected)
                self.assertIsNone(row['forecast_m3'])
        self.assertEqual(budget_rows(self.cfg, None, START)[0]['state'], 'no_data')

    def test_soil_uses_selected_sensor_and_requires_valid_distinct_samples(self):
        readings = [soil(START, 18), soil(START, 18), soil(START - 10, 19)]
        advice = soil_advice(self.cfg, readings, START, budget_rows(self.cfg, meter(), START))
        self.assertEqual((advice['state'], advice['moisture'], advice['trend_points_hour']), ('dry', 18, -360))
        self.assertTrue(advice['budget_limit'])
        for rows, now, expected in (
            (readings[:2], START, 'awaiting_samples'),
            ([soil(START, 18, soil_moisture_temp_ec_valid=0), readings[-1]], START, 'unavailable'),
            ([soil(START, 18, operations_fallback=1), readings[-1]], START, 'unverified'),
            ([soil(START, 18), soil(START - 10, 22)], START, 'confirming'),
            ([soil(START, 72), soil(START - 10, 71)], START, 'wet'),
            ([soil(START, 44), soil(START - 10, 43)], START, 'in_range'),
            (readings, START + 31, 'stale'),
        ):
            with self.subTest(expected=expected):
                self.assertEqual(soil_advice(self.cfg, rows, now, [])['state'], expected)

    def test_settings_validate_limits_defaults_and_future_advice_off(self):
        for changes in (dict(day_m3=0), dict(month_m3='Infinity'), dict(dry_percent=70),
                        dict(wet_percent=101), dict(report_seconds=0), dict(max_records=129),
                        dict(backfill='true'), dict(timezone='unavailable/timezone')):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_plan({**PLAN, **changes})
        self.assertIsNone(soil_advice(validate_plan({**PLAN, 'soil': 'disabled'}), [], START, []))


class PlanningServer(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        folder = Path(temp.name)
        self.use(patch.dict(os.environ, {key: 'planning-fixture' for key in
                 ('WIOT_ADMIN_PASSWORD', 'WIOT_SUPERVISOR_PASSWORD', 'WIOT_MONITOR_PASSWORD', 'WIOT_FLASK_SECRET_KEY')}))
        self.use(patch.object(logging.getLogger(), 'handlers', [logging.NullHandler()]))
        old = os.getcwd()
        try:
            os.chdir(temp.name)
            self.server = importlib.import_module('server_web')
        finally:
            os.chdir(old)
        self.now = START
        for module in (self.server, command_queue, flash_archive):
            self.use(patch.object(module, 'time', Mock(wraps=time, time=Mock(side_effect=lambda: self.now))))
        self.archive = FlashArchive(folder / 'flash.db')
        self.queue = CommandQueue(folder / 'commands.db')
        self.mqtt = Mock(is_connected=Mock(return_value=True), publish_plaintext=Mock(return_value={'mqtt_mid': 1}))
        self.use(patch.multiple(self.server, MAIN_DB_FILE=str(folder / 'main.db'),
                 MESSAGE_DB_DIR=str(folder / 'messages'), _initialized_company_dbs=set(),
                 _flash_archive=self.archive, _command_queue=self.queue, mqtt_client=self.mqtt))
        self.server.init_db()
        self.client = self.server.app.test_client()
        self.login()
        self.query = '?company=Company_1&region=Region_1'

    def use(self, patcher):
        patcher.start()
        self.addCleanup(patcher.stop)

    def login(self, name='admin', role='admin'):
        with self.client.session_transaction() as session:
            session.update(role=role, username=name, company='Company_1')

    def plan(self, **changes):
        response = self.client.put('/api/planning/profiles/7' + self.query, json={**PLAN, **changes})
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))

    def view(self):
        return self.client.get('/api/planning' + self.query).get_json()['plans'][0]

    def ingest(self, family, message):
        self.server.on_mqtt_plaintext('wiot/Company_1/Region_1/7/' + family, message.SerializeToString())

    def status(self, at, *, fallback=False):
        self.now = at
        msg = pb.Status_Message(node_id=7, sensor_id=1, timestamp=self.now, sample_time_valid=True,
            flow_meter_type=2, flow_live_valid=True, flow_period_totals_valid=True, flow_period_source=2,
            flow_period_quality=1, flow_rate_per_day=81, flow_rate_per_month=1000, flow_rate_per_year=3200,
            sensor_mask=12, soil_moisture_temp_ec_valid=1, ec_moisture=18, live_fallback=fallback)
        self.ingest('status', msg)

    def commands(self):
        return [(call.args[0], pb.CMD_Message.FromString(call.args[1]))
                for call in self.mqtt.publish_plaintext.call_args_list]

    def tick(self, now=None):
        if now is not None:
            self.now = now
        self.server.run_site_recovery(now=self.now)

    def probe(self, *, count=2):
        self.plan()
        self.status(START)
        self.tick()
        self.status(START + 30)
        self.tick()
        self.tick()
        self.status(START + 40)
        cmd = self.commands()[-1][1]
        self.assertEqual(cmd.cmd_id, 10)
        self.ingest('data', flash_status(cmd.request_id, self.now, count))
        self.tick()

    def test_scope_dashboard_and_fallback_is_not_a_budget_or_irrigation_signal(self):
        self.plan(backfill=False)
        self.assertEqual(self.client.get('/dashboard').status_code, 200)
        self.status(START)
        self.status(START + 10)
        self.assertEqual(self.view()['advice']['state'], 'dry')
        self.assertEqual(self.view()['budgets'][0]['state'], 'near_limit')
        self.status(START + 20, fallback=True)
        self.assertEqual(self.view()['budgets'][0]['state'], 'unverified')
        self.assertEqual(self.view()['advice']['state'], 'unverified')
        self.assertEqual(self.client.get('/api/planning?region=Region_2').get_json()['plans'], [])
        self.assertEqual(self.client.get('/api/planning?company=Company_2').status_code, 403)
        self.login('Super_User', 'monitor')
        self.assertEqual(self.client.get('/api/planning?company=Company_2').status_code, 200)
        self.assertEqual(self.client.put('/api/planning/profiles/7' + self.query, json=PLAN).status_code, 403)
        self.tick()
        self.assertEqual(self.commands(), [])

    def test_complete_recovery_is_durable_and_archived_only(self):
        self.probe()
        self.tick()
        self.status(START + 50)
        topic, cmd = self.commands()[-1]
        self.assertEqual((topic, cmd.cmd_id, cmd.cmd_data), ('wiot/Company_1/Region_1/7/cmd', 12, (11 << 32) | 1))
        self.ingest('data', stored(cmd.request_id))
        self.ingest('data', stored(cmd.request_id))  # QoS retransmission.
        self.ingest('data', stored(cmd.request_id, index=2, sequence=2, epoch=START + 20))
        self.ingest('data', terminal(cmd.request_id))
        self.assertEqual([item.cmd_id for _, item in self.commands()], [10, 12, 14, 14, 14, 14])
        self.tick()
        result = self.view()['recovery']
        self.assertEqual((result['state'], result['received'], result['gap_records']), ('complete', 2, 2))
        self.assertEqual(len(self.archive.records(*SCOPE)), 2)
        with closing(sqlite3.connect(self.server.get_company_db_path(SCOPE[0]))) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM messages WHERE type='Telemetry'").fetchone()[0], 0)
        restored = PlanningStore(self.server.planning_store().path)
        run_recovery_pass(restored, self.archive, self.queue, self.server.get_company_db_path, self.now + 1, True)
        self.assertEqual(restored.plans()[0][2]['covered_next'], 3)
        self.assertEqual(len(self.commands()), 6)

    def test_incomplete_retry_uses_committed_prefix_for_same_day_and_generation(self):
        self.probe()
        self.tick()
        self.status(START + 50)
        request = self.commands()[-1][1].request_id
        self.ingest('data', stored(request))
        self.ingest('data', terminal(request, result=6, index=1))
        self.tick()
        self.assertEqual(self.view()['recovery']['state'], 'gap_detected')
        retry_at = self.now + RETRY_SECONDS
        self.tick(retry_at)
        self.tick()
        self.status(retry_at + 10)
        probe = self.commands()[-1][1]
        self.assertEqual(probe.cmd_id, 10)
        self.ingest('data', flash_status(probe.request_id, self.now))
        self.tick()
        self.tick()
        self.status(retry_at + 20)
        cmd = self.commands()[-1][1]
        self.assertEqual((cmd.cmd_id, cmd.cmd_data), (12, (11 << 32) | 2))
        self.assertNotEqual(request, cmd.request_id)

    def test_large_archive_defers_and_operator_can_pause_pending(self):
        self.probe(count=6)
        self.assertEqual(self.view()['recovery']['state'], 'manual_required')
        self.status(START + 50)
        self.assertEqual([cmd.cmd_id for _, cmd in self.commands()], [10])
        self.plan(max_records=8)
        self.status(START + 60)
        self.tick()
        self.status(START + 90)
        self.tick()
        self.tick()
        request = self.view()['recovery']['request_id']
        self.plan(backfill=False, max_records=8)
        self.assertEqual(self.queue.get(request, SCOPE[0], SCOPE[2])['state'], 'cancelled')
        self.status(START + 100)
        self.assertEqual(len(self.commands()), 1)

    def test_midnight_and_operator_priority(self):
        self.plan()
        late = START + 12 * 3600 - 30
        self.status(late - 30)
        self.tick()
        self.status(late)
        self.tick()
        self.assertEqual(self.view()['recovery']['state'], 'window_passed')
        self.assertEqual(self.commands(), [])
        self.queue.enqueue(SCOPE[0], 7, 10, 'FLASH_STATUS', 0, request_id=10,
                           now=late, region=SCOPE[1], automatic=True)
        self.queue.enqueue(SCOPE[0], 7, 4, 'GOSTM', 0, request_id=4, now=late, region=SCOPE[1])
        self.assertEqual(self.queue.claim_on_status(SCOPE[0], 7, now=late)['request_id'], 4)
        self.assertIsNone(self.queue.claim_on_status(SCOPE[0], 7, now=late + 1))
        with self.assertRaises(ValueError):
            self.queue.enqueue(SCOPE[0], 8, 9, 'CLEAR_FLASH', 0, now=late, automatic=True)

    def test_completed_transfer_for_different_node_day_is_not_success(self):
        self.probe()
        self.tick()
        self.status(START + 50)
        request = self.commands()[-1][1].request_id
        empty = terminal(request, result=1, index=0, total=0)
        empty.history.day_key = calendar_day(START + 86400, 'UTC')
        self.ingest('data', empty)
        self.tick()
        self.assertEqual(self.view()['recovery']['state'], 'incomplete')
        self.assertIsNone(self.view()['recovery']['gap_records'])

    def test_pending_intent_survives_restart_without_double_enqueue(self):
        self.plan()
        self.status(START)
        self.tick()
        self.status(START + 30)
        self.tick()
        request = self.view()['recovery']['request_id']
        self.assertIsNone(self.queue.get(request, SCOPE[0], SCOPE[2]))
        restored = PlanningStore(self.server.planning_store().path)
        for _ in range(2):
            run_recovery_pass(restored, self.archive, self.queue, self.server.get_company_db_path, self.now, True)
        self.assertEqual([item['request_id'] for item in self.queue.list(SCOPE[0])], [request])
        self.assertEqual(self.commands(), [])


if __name__ == '__main__':
    unittest.main()
