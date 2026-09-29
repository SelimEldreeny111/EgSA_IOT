"""Remote-wake wire/API/SQLite regression tests, isolated from real broker/data."""
from __future__ import annotations
import importlib
import logging
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

SERVER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_DIR))
import messages_pb2
import power_commands
from mqtt_impl import MqttNodeClient


class PowerWireTests(unittest.TestCase):
    def test_duration_validation(self):
        for value, expected in [(0, 0), ('0', 0), (' 60 ', 60), (86400, 86400)]:
            self.assertEqual(power_commands.validate_wake_seconds(value), expected)
        for value in [-1, 86401, 2**64, True, False, None, 1.0, '1.5', '1e2', '', '１２', '-1']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                power_commands.validate_wake_seconds(value)

    def test_wire_fields_append_without_renumbering(self):
        self.assertEqual(messages_pb2.CMD_Message.DESCRIPTOR.fields_by_name['cmd_data'].number, 3)
        self.assertEqual(messages_pb2.CMD_Message.DESCRIPTOR.fields_by_name['request_id'].number, 4)
        self.assertEqual(messages_pb2.Status_Message.DESCRIPTOR.fields_by_name['power_mode'].number, 32)
        self.assertEqual(messages_pb2.Telemetry.DESCRIPTOR.fields_by_name['wake_request_id'].number, 40)
        msg = messages_pb2.CMD_Message(node_id=7, cmd_id=6, cmd_data=60, request_id=42)
        parsed = messages_pb2.CMD_Message.FromString(msg.SerializeToString())
        self.assertEqual((parsed.cmd_id, parsed.cmd_data, parsed.request_id), (6, 60, 42))

    def test_legacy_telemetry_is_not_a_wake_ack(self):
        metadata = power_commands.power_metadata(messages_pb2.Telemetry(node_id=7))
        self.assertFalse(power_commands.is_confirmed_wake(metadata))
        self.assertEqual(power_commands.power_dashboard_fields(metadata)['Power Mode'], 'Unknown / legacy')

    def test_ack_requires_explicit_remote_active_state_and_request(self):
        msg = messages_pb2.Telemetry(power_mode=3, power_state=1, wake_command_ack=True, wake_request_id=42)
        self.assertTrue(power_commands.is_confirmed_wake(power_commands.power_metadata(msg)))
        for field, value in [('power_mode', 1), ('power_state', 2), ('wake_command_ack', False), ('wake_request_id', 0)]:
            modified = messages_pb2.Telemetry(); modified.CopyFrom(msg); setattr(modified, field, value)
            self.assertFalse(power_commands.is_confirmed_wake(power_commands.power_metadata(modified)))

    def test_mqtt_publish_is_not_retained_and_offline_submission_fails(self):
        client = MqttNodeClient.__new__(MqttNodeClient)
        client.on_status = None
        client.encrypt_frame = lambda _plain: {'payload': b'test-encrypted-frame'}
        calls = []
        def publish(*args, **kwargs):
            calls.append((args, kwargs)); return SimpleNamespace(rc=0)
        client.client = SimpleNamespace(publish=publish)
        client.publish_plaintext('EgSA/Test/7/CMD', b'test')
        self.assertEqual(calls[0][1], {'qos': 1, 'retain': False})
        client.client.publish = lambda *args, **kwargs: SimpleNamespace(rc=4)
        with self.assertRaises(RuntimeError): client.publish_plaintext('EgSA/Test/7/CMD', b'test')


class RemoteWakeServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.env_patch = patch.dict(os.environ, {name: 'test-only-wake' for name in (
            'WIOT_FLASK_SECRET_KEY', 'WIOT_ADMIN_PASSWORD', 'WIOT_SUPERVISOR_PASSWORD', 'WIOT_MONITOR_PASSWORD')})
        cls.env_patch.start()
        original_cwd = os.getcwd()
        try:
            os.chdir(cls.temp.name)
            cls.server = importlib.import_module('server_web')
        finally:
            os.chdir(original_cwd)
        # Earlier test classes may have closed a now-deleted temporary logfile.
        for handler in logging.getLogger().handlers[:]:
            handler.close(); logging.getLogger().removeHandler(handler)
        logging.basicConfig(filename=str(Path(cls.temp.name) / 'system.log'), level=logging.INFO)
        cls.server.MAIN_DB_FILE = str(Path(cls.temp.name) / 'iot_data.db')
        cls.server.MESSAGE_DB_DIR = str(Path(cls.temp.name) / 'messages_dbs')
        cls.server._initialized_company_dbs.clear()
        cls.server.init_db()

    @classmethod
    def tearDownClass(cls):
        logging.shutdown(); cls.env_patch.stop(); cls.temp.cleanup()

    def setUp(self):
        self.company = 'Wake_' + uuid.uuid4().hex[:10]
        self.sent = []
        self.client = self.server.app.test_client()
        with self.client.session_transaction() as session:
            session.update(role='admin', username='wake_tester', company=self.company)
        self.fake_mqtt = SimpleNamespace(is_connected=lambda: True,
            publish_plaintext=lambda topic, plain: self.sent.append((topic, plain)))
        self.mqtt_patch = patch.object(self.server, 'mqtt_client', self.fake_mqtt)
        self.mqtt_patch.start(); self.addCleanup(self.mqtt_patch.stop)

    def post(self, **updates):
        data = dict(node_id='7', cmd_type='WAKE', cmd_data='60', broadcast=False, company=self.company)
        data.update(updates)
        return self.client.post('/api/command', json=data)

    def test_wake_api_publishes_correlated_command_not_awake_claim(self):
        result = self.post().get_json()
        self.assertTrue(result['success']); self.assertFalse(result['node_awake'])
        self.assertTrue(result['awaiting_node_ack']); self.assertGreater(result['request_id'], 0)
        topic, plain = self.sent[0]
        self.assertEqual(topic, f'EgSA/{self.company}/7/CMD')
        msg = messages_pb2.CMD_Message.FromString(plain)
        self.assertEqual((msg.node_id, msg.cmd_id, msg.cmd_data), (7, 6, 60))
        self.assertEqual(msg.request_id, result['request_id'])
        conn = sqlite3.connect(self.server.get_company_db_path(self.company))
        try:
            row = conn.execute('SELECT details,wake_request_id,wake_command_ack FROM messages WHERE type="Command"').fetchone()
            self.assertIn(f"request={result['request_id']}", row[0])
            self.assertEqual(row[1:], (result['request_id'], 0))
        finally: conn.close()

    def test_default_and_broadcast(self):
        result = self.post(cmd_data='0', broadcast=True).get_json()
        self.assertTrue(result['success'])
        self.assertEqual(self.sent[0][0], f'EgSA/{self.company}/BroadCast/CMD')
        self.assertEqual(messages_pb2.CMD_Message.FromString(self.sent[0][1]).cmd_data, 0)

    def test_invalid_durations_do_not_publish(self):
        for value in [-1, 86401, True, 1.5, None, '1.5', '1e2']:
            with self.subTest(value=value):
                response = self.post(cmd_data=value)
                self.assertEqual(response.status_code, 400)
                self.assertFalse(response.get_json()['success'])
        self.assertEqual(self.sent, [])

    def test_invalid_node_and_broadcast_do_not_publish(self):
        for values in [dict(node_id=0), dict(node_id=65536), dict(node_id=True), dict(node_id=1.5),
                       dict(node_id=None), dict(node_id='invalid'), dict(node_id=[]), dict(broadcast='false')]:
            with self.subTest(values=values):
                self.assertEqual(self.post(**values).status_code, 400)
        self.assertEqual(self.sent, [])

    def test_malformed_command_objects_do_not_publish(self):
        for body in [[], ['WAKE'], None, 'WAKE']:
            with self.subTest(body=body):
                self.assertEqual(self.client.post('/api/command', json=body).status_code, 400)
        for values in [dict(company=[]), dict(cmd_type=[]), dict(company=None)]:
            with self.subTest(values=values):
                self.assertEqual(self.post(**values).status_code, 400)
        self.assertEqual(self.sent, [])

    def test_omitted_wake_duration_uses_node_default(self):
        response = self.client.post('/api/command', json=dict(
            company=self.company, node_id=7, cmd_type='WAKE'))
        self.assertTrue(response.get_json()['success'])
        self.assertEqual(messages_pb2.CMD_Message.FromString(self.sent[0][1]).cmd_data, 0)

    def test_tenant_permissions_and_user_role(self):
        self.assertEqual(self.post(company='OtherCompany').status_code, 403)
        with self.client.session_transaction() as session: session['role'] = 'user'
        self.assertEqual(self.post().status_code, 403)
        self.assertEqual(self.sent, [])

    def test_disconnected_broker(self):
        self.fake_mqtt.is_connected = lambda: False
        self.assertEqual(self.post().status_code, 503)
        self.assertEqual(self.sent, [])

    def test_existing_gostm_command_unchanged(self):
        self.assertTrue(self.post(cmd_type='GOSTM').get_json()['success'])
        msg = messages_pb2.CMD_Message.FromString(self.sent[0][1])
        self.assertEqual((msg.cmd_id, msg.cmd_data, msg.request_id), (4, 0, 0))

    def test_ack_is_persisted_without_manufacturing_flow_samples(self):
        msg = messages_pb2.Telemetry(node_id=7, sensor_id=1, timestamp=1800000000,
            power_mode=3, power_state=1, wake_remaining_seconds=59,
            wake_command_ack=True, wake_request_id=42, flow_meter_type=2,
            flow_live_valid=True, flow_period_totals_valid=True, flow_rate=5.0,
            flow_rate_per_day=3.0, flow_period_source=2)
        with patch.object(self.server, 'emit_iot_message') as emit:
            self.server.on_mqtt_plaintext(f'EgSA/{self.company}/7/Telemetry', msg.SerializeToString())
        conn = sqlite3.connect(self.server.get_company_db_path(self.company))
        try:
            row = conn.execute('SELECT power_mode,power_state,wake_remaining_seconds,wake_command_ack,wake_request_id,time_source FROM messages').fetchone()
            self.assertEqual(row, (3, 1, 59, 1, 42, 'wake_ack_cached'))
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM meter_samples').fetchone()[0], 0)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM consumption_periods').fetchone()[0], 0)
        finally: conn.close()
        payload = emit.call_args.args[0]
        self.assertTrue(payload['Wake Command ACK']); self.assertEqual(payload['Wake Request ID'], 42)
        self.assertEqual(payload['Power State'], 'ACTIVE')

    def test_topic_mismatch_never_confirms_wake(self):
        msg = messages_pb2.Telemetry(node_id=8, power_mode=3, power_state=1, wake_command_ack=True, wake_request_id=42)
        with patch.object(self.server, 'emit_iot_message') as emit:
            self.server.on_mqtt_plaintext(f'EgSA/{self.company}/7/Telemetry', msg.SerializeToString())
        emit.assert_not_called()

    def test_legacy_database_migration_preserves_row(self):
        db = self.server.get_company_db_path(self.company)
        Path(db).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db)
        conn.execute('CREATE TABLE messages (id INTEGER PRIMARY KEY, timestamp INTEGER, type TEXT, node_id INTEGER, sensor_id TEXT, flow REAL, velocity REAL, flow_day REAL, flow_month REAL, flow_year REAL, details TEXT, company TEXT, node_status INTEGER)')
        conn.execute('INSERT INTO messages VALUES (1,1800000000,"Status",7,"1",5,0,0,0,0,"keep",?,0)', (self.company,))
        conn.commit(); conn.close()
        self.server.ensure_message_db(self.company)
        self.server._initialized_company_dbs.discard(self.company)
        self.server.ensure_message_db(self.company) # migration is idempotent
        conn = sqlite3.connect(db)
        try:
            self.assertEqual(conn.execute('SELECT details,power_mode,wake_request_id FROM messages').fetchone(), ('keep',0,0))
        finally: conn.close()


if __name__ == '__main__': unittest.main()
