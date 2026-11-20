"""Release A acceptance tests using deterministic MQTT payloads and temporary SQLite."""
import importlib
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import messages_pb2
from mqtt_impl import MqttNodeClient
from water_operations import OperationsStore, validate_settings


START = 1_791_568_800
SCOPE = ('Company_1', 'Region_1', 7)
SETTINGS = dict(name='Test line', meter=2, expected_seconds=10, max_gap_seconds=22,
                hold_seconds=20, recovery_seconds=10, high_flow_m3h=10,
                quiet_start='23:00', quiet_end='05:00', timezone='UTC')


def report(row_id, received, flow=0.0, **changes):
    row = dict(id=row_id, timestamp=received, measured_at=received, time_source='node_rtc',
               operations_digest=str(row_id), operations_fallback=False, flow_meter_type=2,
               flow=flow, flow_live_valid=True, flow_cumulative_totals_valid=True,
               forward_total_liters=1000 + 10 * row_id, reverse_total_liters=10 * row_id,
               legacy_flow_schema=False, secondary_flow_json=None, sensor_mask=8,
               soil_moisture_temp_valid=False, soil_moisture_temp_ec_valid=False,
               battery_voltage=3.8, wdt_reset_count=1, power_reset_count=2)
    row.update(changes)
    return row


class OperationsRuleTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / 'operations.db'
        self.store = OperationsStore(self.path)
        self.configure()

    def configure(self, **settings):
        self.store.configure(*SCOPE, {**SETTINGS, **settings}, 'operator', START, 0)

    def feed(self, *rows, gateway=None, observing=True, now=None, since=START):
        target = self.store.targets()[0]
        now = now if now is not None else rows[-1]['timestamp'] if rows else START
        self.store.process(target, rows, now, observing, since, gateway)

    def incidents(self):
        return self.store.incidents(*SCOPE[:2])

    def test_high_flow_hysteresis_duplicate_restart_and_ack(self):
        first = report(1, START + 10, 12)
        self.feed(first, report(2, START + 11, 12, measured_at=START + 10,
                               operations_digest=first['operations_digest']))
        self.assertEqual(self.incidents(), [])
        self.store = OperationsStore(self.path)
        self.feed(report(3, START + 20, 12), report(4, START + 30, 11))
        incident = self.incidents()[0]
        self.assertEqual(incident['kind'], 'high_flow')
        self.assertEqual(incident['evidence']['first_at'], START + 10)
        self.assertEqual(incident['evidence']['observed_seconds'], 20)
        self.assertEqual(incident['evidence']['volume_liters'], 30)
        incident_id = incident['id']
        self.assertTrue(self.store.acknowledge(*SCOPE[:2], incident_id, 'operator', START + 35))
        self.store.acknowledge(*SCOPE[:2], incident_id, 'other', START + 36)
        self.feed(report(5, START + 40, 9.5), report(6, START + 50, 9.5))
        self.assertIsNone(self.incidents()[0]['closed_at'])
        self.feed(report(7, START + 60, 8.0), report(8, START + 70, 8.0))
        latest = self.incidents()
        self.assertEqual(len(latest), 1)
        self.assertEqual(latest[0]['id'], incident_id)
        self.assertEqual(latest[0]['closed_at'], START + 70)
        self.assertEqual(latest[0]['acknowledged_by'], 'operator')

    def test_validity_and_gaps_do_not_open_or_resolve_water_alerts(self):
        self.feed(report(1, START, 11), report(2, START + 10, 11),
                  report(3, START + 20, 0, flow_live_valid=False),
                  report(4, START + 30, 11), report(5, START + 60, 11),
                  report(6, START + 70, 11))
        self.assertEqual(self.incidents(), [])
        self.feed(report(7, START + 80, 11))
        self.assertEqual(self.incidents()[0]['opened_at'], START + 80)
        self.feed(report(8, START + 90, 0, flow_live_valid=False),
                  report(9, START + 100, 11))
        evidence = self.incidents()[0]['evidence']
        self.assertEqual(evidence['observed_seconds'], 20)
        self.assertFalse(evidence['complete_volume'])
        self.feed(report(10, START + 110, 0, measured_at=START + 75),
                  report(11, START + 120, 0, operations_fallback=True),
                  report(12, START + 130, 0, operations_fallback=True))
        by_kind = {row['kind']: row for row in self.incidents()}
        self.assertIsNone(by_kind['high_flow']['closed_at'])
        self.assertIn('sample_unverified', by_kind)

    def test_quiet_hours_span_midnight_and_exclude_daytime_watering(self):
        self.configure(quiet_flow_m3h=0.5, high_flow_m3h=None)
        midnight = int(datetime(2026, 10, 8, tzinfo=timezone.utc).timestamp())
        self.feed(report(1, midnight + 21600, 1.0), report(2, midnight + 21610, 1.0),
                  report(3, midnight + 21620, 1.0))
        self.assertEqual(self.incidents(), [])
        midnight += 86400
        self.feed(report(4, midnight - 10, 0.8), report(5, midnight, 0.8),
                  report(6, midnight + 10, 0.8))
        self.assertEqual(self.incidents()[0]['kind'], 'quiet_flow')
        self.assertEqual(self.incidents()[0]['evidence']['first_at'], midnight - 10)

    def test_reverse_flow_uses_selected_secondary_and_reverse_total(self):
        self.configure(reverse_flow_m3h=1)
        rows = []
        for index in range(3):
            reading = ('{"flow_meter_type":2,"flow_live_valid":1,"flow_rate":-2,'
                       '"flow_cumulative_totals_valid":1,"forward_total_liters":100,'
                       '"reverse_total_liters":' + str(10 * index) + '}')
            rows.append(report(index + 1, START + 10 * index, 100, flow_meter_type=1,
                               secondary_flow_json=reading))
        self.feed(*rows)
        ops = self.incidents()
        self.assertEqual([row['kind'] for row in ops], ['reverse_flow'])
        self.assertEqual(ops[0]['evidence']['volume_liters'], 20)

    def test_liveness_separates_server_gateway_node_and_reconnect_grace(self):
        self.configure(gateway=5)
        self.feed(report(1, START + 10), gateway='online')
        self.feed(now=START + 41, observing=False, gateway='offline')
        self.assertEqual(self.incidents(), [])
        self.feed(now=START + 41, gateway='offline')
        self.assertEqual(self.store.dashboard(*SCOPE[:2], True)['nodes'][0]['connectivity'],
                         'gateway_unavailable')
        self.feed(now=START + 41, gateway='online', since=START + 40)
        self.assertEqual(self.incidents(), [])
        self.feed(now=START + 70, gateway='online', since=START + 40)
        self.assertEqual(self.incidents()[0]['kind'], 'node_offline')
        self.feed(report(2, START + 75), gateway='online', since=START + 40)
        self.assertEqual(self.incidents()[0]['close_reason'], 'recovered')

    def test_health_battery_sensor_clock_and_reset_rebaseline(self):
        self.configure(battery_min_v=3.3)
        self.feed(report(1, START, battery_voltage=3.1, flow_live_valid=False, sensor_mask=14),
                  report(2, START + 10, battery_voltage=3.2, flow_live_valid=False,
                         sensor_mask=14, wdt_reset_count=3))
        self.assertEqual({inc['kind'] for inc in self.incidents()},
                         {'low_battery', 'meter_unavailable', 'sensor_unavailable', 'watchdog_resets'})
        self.feed(report(3, START + 20, wdt_reset_count=0),
                  report(4, START + 30, wdt_reset_count=0),
                  report(5, START + 40, time_source='server_received', wdt_reset_count=0),
                  report(6, START + 50, time_source='server_received', wdt_reset_count=0))
        kinds = {inc['kind']: inc for inc in self.incidents()}
        self.assertEqual(kinds['watchdog_resets']['evidence']['increase'], 2)
        self.assertEqual(kinds['low_battery']['close_reason'], 'recovered')
        self.assertIsNone(kinds['rtc_untrusted']['closed_at'])

    def test_revision_and_tenant_scope_protect_state(self):
        target = self.store.targets()[0]
        self.configure(hold_seconds=1)
        self.store.process(target, [report(1, START, 99), report(2, START + 10, 99)],
                           START + 10, True, START)
        self.assertEqual(self.incidents(), [])
        self.feed(report(3, START + 20, 99), report(4, START + 30, 99))
        incident = self.incidents()[0]
        self.assertFalse(self.store.acknowledge('Company_2', SCOPE[1], incident['id'], 'other', START))
        self.assertFalse(self.store.acknowledge(SCOPE[0], 'Region_2', incident['id'], 'other', START))
        self.configure(enabled=False, hold_seconds=1)
        self.assertEqual(self.incidents()[0]['close_reason'], 'monitoring_changed')
        self.assertEqual(self.store.targets(), [])
        self.assertIn('high_flow', ''.join(self.store.csv_rows(*SCOPE[:2])))

    def test_config_validation_and_retained_node_status(self):
        for values in ({'high_flow_m3h': 'NaN'}, {'enabled': 1}, {'timezone': '../../file'},
                       {'max_gap_seconds': 5}, {'expected_seconds': 0}, {'meter': 3}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                validate_settings({**SETTINGS, **values})
        mqtt = MqttNodeClient.__new__(MqttNodeClient)
        mqtt.on_status = Mock()
        mqtt.on_plaintext = Mock()
        mqtt._on_message(None, None, Mock(topic='wiot/Company_1/Region_1/7/status',
                                         payload=b'x' * 49, retain=True))
        mqtt.on_plaintext.assert_not_called()


class OperationsServerTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        fixture = patch.dict(os.environ, {key: 'operations-test' for key in
            ('WIOT_ADMIN_PASSWORD', 'WIOT_SUPERVISOR_PASSWORD', 'WIOT_MONITOR_PASSWORD', 'WIOT_FLASK_SECRET_KEY')})
        fixture.start()
        self.addCleanup(fixture.stop)
        # Other test classes configure file logging in their temporary directories.
        # Isolate this test from handlers whose directories were already removed.
        test_logger = patch.object(logging.getLogger(), 'handlers', [logging.NullHandler()])
        test_logger.start()
        self.addCleanup(test_logger.stop)
        cwd = os.getcwd()
        try:
            os.chdir(temp.name)
            self.server = importlib.import_module('server_web')
        finally:
            os.chdir(cwd)
        scope = patch.multiple(self.server, MAIN_DB_FILE=str(Path(temp.name) / 'iot.db'),
                               MESSAGE_DB_DIR=str(Path(temp.name) / 'messages'),
                               _initialized_company_dbs=set(), _gateway_observation_started=START,
                               mqtt_client=Mock(is_connected=Mock(return_value=True)))
        scope.start()
        self.addCleanup(scope.stop)
        self.server.init_db()
        self.client = self.server.app.test_client()
        self.url = '/api/operations'
        self.query = '?company=Company_1&region=Region_1'
        self.login('admin')

    def login(self, role):
        with self.client.session_transaction() as session:
            session.update(role=role, username='operations-test', company='Company_1')

    def test_ingest_after_activation_restart_isolation_and_export(self):
        self.assertEqual(self.client.get('/dashboard').status_code, 200)
        with patch.object(self.server, 'time', Mock(wraps=time, time=Mock(return_value=START))):
            self.assertEqual(self.client.put(self.url + '/profiles/7' + self.query,
                                             json=SETTINGS).status_code, 200)
        server = self.server
        self.assertEqual(self.client.put(self.url + '/profiles/7?company=Company_2',
                                         json=SETTINGS).status_code, 403)
        with patch.object(server, 'dispatch_queued_command') as dispatch:
            for seconds in (10, 20, 30):
                with patch.object(server, 'time', Mock(wraps=time, time=Mock(return_value=START + seconds))):
                    timestamp = START + seconds
                    status = messages_pb2.Status_Message(
                        node_id=7, sensor_id=1, timestamp=timestamp, sample_time_valid=True,
                        flow_meter_type=2, flow_rate=15, flow_live_valid=True,
                        flow_cumulative_totals_valid=True, forward_total_liters=2000 + seconds)
                    server.on_mqtt_plaintext('wiot/Company_1/Region_1/7/status', status.SerializeToString())
            self.assertEqual(dispatch.call_count, 3)
        server.run_operations_pass(now=START + 31)
        server.run_operations_pass(now=START + 32)
        data = self.client.get(self.url + self.query).get_json()
        self.assertEqual(data['nodes'][0]['connectivity'], 'online')
        self.assertEqual(len(data['incidents']), 1)
        self.assertEqual(data['incidents'][0]['evidence']['volume_liters'], 20)
        incident = data['incidents'][0]['id']
        endpoint = self.url + f'/incidents/{incident}/acknowledge'
        self.assertEqual(self.client.post(endpoint + '?region=Region_2', json={}).status_code, 404)
        self.login('user')
        self.assertEqual(self.client.post(endpoint + self.query, json={}).status_code, 403)
        self.assertEqual(self.client.get(self.url + '?company=Company_2').status_code, 403)
        self.login('admin')
        self.assertEqual(self.client.post(endpoint + self.query, json={}).status_code, 200)
        csv_response = self.client.get(self.url + '/export' + self.query)
        self.assertIn(b'high_flow', csv_response.data)
        self.assertIn(b'operations-test', csv_response.data)
        self.assertEqual(self.client.get(self.url + '?region=Region_2').get_json()['incidents'], [])
