"""Phase 1 security/correctness regressions: temporary data, no network or secrets."""
import importlib
import logging
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import messages_pb2
from mqtt_impl import MqttNodeClient


class ServerValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.old_cwd = os.getcwd()
        os.chdir(cls.temp.name)
        cls.env = patch.dict(os.environ, {name: 'isolated-phase1-fixture' for name in (
            'WIOT_ADMIN_PASSWORD', 'WIOT_SUPERVISOR_PASSWORD',
            'WIOT_MONITOR_PASSWORD', 'WIOT_FLASK_SECRET_KEY')})
        cls.env.start()
        cls.server = importlib.import_module('server_web')
        for handler in logging.getLogger().handlers[:]:
            handler.close()
            logging.getLogger().removeHandler(handler)
        logging.basicConfig(filename='system.log', level=logging.INFO)
        cls.server.MAIN_DB_FILE = str(Path(cls.temp.name) / 'iot_data.db')
        cls.server.MESSAGE_DB_DIR = str(Path(cls.temp.name) / 'messages_dbs')
        cls.server._initialized_company_dbs.clear()
        cls.server.init_db()

    @classmethod
    def tearDownClass(cls):
        logging.shutdown()
        os.chdir(cls.old_cwd)
        cls.env.stop()
        cls.temp.cleanup()

    def client(self, company='Company_1', username='tenant_admin', role='admin'):
        client = self.server.app.test_client()
        with client.session_transaction() as session:
            session.update(company=company, username=username, role=role)
        return client

    def test_infrastructure_logs_do_not_reach_company_sockets(self):
        tenant = self.server.socketio.test_client(self.server.app, flask_test_client=self.client())
        supervisor = self.server.socketio.test_client(self.server.app,
            flask_test_client=self.client(username='EgSA_Supervisor'))
        try:
            self.server.log_event('phase1-infrastructure-marker')
            self.assertFalse(any(x['name'] == 'system_log' for x in tenant.get_received()))
            self.assertTrue(any(x['name'] == 'system_log' for x in supervisor.get_received()))
        finally:
            tenant.disconnect(); supervisor.disconnect()

    def test_client_logs_are_tenant_scoped(self):
        a = self.server.socketio.test_client(self.server.app, flask_test_client=self.client())
        b = self.server.socketio.test_client(self.server.app,
            flask_test_client=self.client(company='Company_2'))
        try:
            a.emit('client_log', {'message': '<b>tenant-text-marker</b>'})
            self.assertTrue(any(x['name'] == 'system_log' for x in a.get_received()))
            self.assertFalse(any(x['name'] == 'system_log' for x in b.get_received()))
        finally:
            a.disconnect(); b.disconnect()

    def test_client_log_rejects_non_objects_and_bounds_input(self):
        a = self.server.socketio.test_client(self.server.app, flask_test_client=self.client())
        try:
            for value in (None, ['bad'], {'message': 12}, {'message': 'x' * 2049}):
                a.emit('client_log', value)
                self.assertFalse(any(x['name'] == 'system_log' for x in a.get_received()))
        finally:
            a.disconnect()

    def test_only_supervisor_can_replace_shared_broker(self):
        for username, role in [('tenant_admin', 'admin'), ('Super_User', 'monitor')]:
            with self.subTest(username=username), patch.object(self.server, 'MqttNodeClient') as mqtt:
                client = self.client(username=username, role=role)
                response = client.post('/api/connect', json={'aes_key': '00' * 16,
                    'company': 'Company_2'})
                self.assertEqual(response.status_code, 403)
                mqtt.assert_not_called()
                self.assertEqual(client.post('/api/disconnect').status_code, 403)

    def test_shared_log_export_is_supervisor_only(self):
        self.assertEqual(self.client().get('/export_log').status_code, 403)

    def test_new_tenant_paths_do_not_alias(self):
        names = ('Audit Space', 'Audit_Space', 'audit_space', 'CON', 'con')
        paths = [self.server.get_company_db_path(n).casefold() for n in names]
        self.assertEqual(len(paths), len(set(paths)))

    def test_exact_suffix_not_company_substring_selects_parser(self):
        msg = messages_pb2.Telemetry(node_id=7)
        with patch.object(self.server, 'save_message') as save, \
                patch.object(self.server, 'emit_iot_message'), \
                patch.object(self.server, 'dispatch_queued_command'):
            self.server.on_mqtt_plaintext('wiot/AuditStatusCompany/Region_1/7/data', msg.SerializeToString())
            self.assertEqual(save.call_args.args[1], 'Telemetry')

    def test_invalid_topics_never_reach_storage(self):
        msg = messages_pb2.Status_Message(node_id=7)
        topics = ('Other/Company_1/7/Status', 'wiot/Company_1/Region_1/7/status/extra',
            'EgSA/Company_1/7/notStatus', 'wiot/+/Region_1/7/status',
            'wiot/Company_1/Region_1/0/status', 'wiot/Company_1/Region_1/65536/status',
            'wiot/Company_1/Region_1/+7/status', 'wiot/__all__/Region_1/7/status')
        with patch.object(self.server, 'save_message') as save:
            for topic in topics:
                with self.subTest(topic=topic):
                    self.server.on_mqtt_plaintext(topic, msg.SerializeToString())
                    save.assert_not_called()

    def test_bad_numeric_and_enum_measurements_are_quarantined(self):
        for field, value in [('flow_rate', float('nan')), ('battery_voltage', float('inf')),
                ('sensor_mask', 16), ('node_status', 4), ('active_sensor_count', 5),
                ('power_mode', 6), ('forward_total_liters', 2**63), ('timestamp', 2**63)]:
            with self.subTest(field=field), patch.object(self.server, 'save_message') as save, \
                    patch.object(self.server, 'emit_iot_message') as emit:
                msg = messages_pb2.Status_Message(node_id=7)
                setattr(msg, field, value)
                self.server.on_mqtt_plaintext('wiot/Company_1/Region_1/7/status', msg.SerializeToString())
                save.assert_not_called(); emit.assert_not_called()

    def test_secondary_nan_is_also_rejected(self):
        msg = messages_pb2.Status_Message(node_id=7)
        msg.secondary_flow_meter.flow_rate = float('nan')
        with patch.object(self.server, 'save_message') as save:
            self.server.on_mqtt_plaintext('wiot/Company_1/Region_1/7/status', msg.SerializeToString())
            save.assert_not_called()

    def test_every_command_rejects_boolean_or_fractional_node_ids(self):
        fake = SimpleNamespace(is_connected=lambda: True, publish_plaintext=Mock())
        with patch.object(self.server, 'mqtt_client', fake):
            for value in (True, 1.7, '1.7', 0, 65536):
                response = self.client().post('/api/command', json=dict(
                    node_id=value, cmd_type='GOSTM', company='Company_1', broadcast=False))
                self.assertEqual(response.status_code, 400, value)
            fake.publish_plaintext.assert_not_called()

    def test_browser_headers(self):
        response = self.client().get('/static/js/app.js')
        self.assertEqual(response.headers.get('X-Content-Type-Options'), 'nosniff')
        self.assertIn("object-src 'none'", response.headers.get('Content-Security-Policy', ''))
        response.close()

    def test_ui_broker_controls_and_input_ids_match_authorization(self):
        for username in ('tenant_admin', 'EgSA_Supervisor'):
            response = self.client(username=username).get('/dashboard')
            html = response.get_data(as_text=True)
            self.assertEqual(html.count('id="cfg-broker"'), int(username == 'EgSA_Supervisor'))
            self.assertEqual(html.count('id="btn-connect"'), int(username == 'EgSA_Supervisor'))
            self.assertIn('/static/js/safe_html.js', html)
            response.close()

    def test_bad_json_and_cross_origin_api_requests_are_controlled(self):
        supervisor = self.client(username='EgSA_Supervisor')
        for route in ('/api/users', '/api/companies', '/api/set_company', '/api/connect', '/api/command'):
            for value in ([], None, 'text', {'company': []}):
                self.assertEqual(supervisor.post(route, json=value).status_code, 400, (route, value))
        response = supervisor.post('/api/disconnect', headers={'Origin': 'https://other.example'})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(supervisor.get('/api/messages?company=../other').status_code, 400)

    def test_company_admin_does_not_receive_tenant_registry_or_broker_details(self):
        response = self.client().get('/api/companies').get_json()
        self.assertEqual([x['name'] for x in response['companies']], ['Company_1'])
        fake = SimpleNamespace(is_connected=lambda: True)
        with patch.object(self.server, 'mqtt_client', fake):
            self.assertNotIn('broker', self.client().get('/api/broker_status').get_json())

    def test_monitor_can_switch_socket_room_without_restarting_broker(self):
        client = self.client(username='Super_User', role='monitor')
        socket = self.server.socketio.test_client(self.server.app, flask_test_client=client)
        try:
            self.assertTrue(socket.emit('select_company', {'company': 'Company_2'}, callback=True)['success'])
            socket.get_received()
            self.server.emit_iot_message({'Company': 'Company_1'}, 'Company_1')
            self.assertFalse(socket.get_received())
            self.server.emit_iot_message({'Company': 'Company_2'}, 'Company_2')
            self.assertTrue(any(x['name'] == 'iot_message' for x in socket.get_received()))
            self.assertFalse(socket.emit('select_company', {'company': '__all__'}, callback=True)['success'])
        finally:
            socket.disconnect()

    def test_broadcast_command_echo_is_separate_from_ordinary_topic_ids(self):
        for node in (0, 7):
            msg = messages_pb2.CMD_Message(node_id=node, cmd_id=4)
            with patch.object(self.server, 'save_message') as save, \
                    patch.object(self.server, 'emit_iot_message'):
                self.server.on_mqtt_plaintext('wiot/Company_1/Region_1/broadcast', msg.SerializeToString())
                self.assertEqual(save.call_args.args[1], 'Command')

    def test_valid_negative_reverse_flow_and_legacy_defaults_are_retained(self):
        msg = messages_pb2.Status_Message(node_id=7, flow_rate=-12.5, net_total_liters=-150)
        with patch.object(self.server, 'save_message') as save, \
                patch.object(self.server, 'emit_iot_message'), \
                patch.object(self.server, 'dispatch_queued_command'):
            self.server.on_mqtt_plaintext('wiot/Company_1/Region_1/7/status', msg.SerializeToString())
            self.assertEqual(save.call_args.args[4], -12.5)

    def test_telemetry_reports_rate_in_milliseconds_not_command_seconds(self):
        for rate in (0, 5000, 3600000, 86400000):
            msg = messages_pb2.Telemetry(node_id=7, sampling_rate=rate, Transmission_rate=rate)
            with patch.object(self.server, 'save_message') as save, \
                    patch.object(self.server, 'emit_iot_message'):
                self.server.on_mqtt_plaintext('wiot/Company_1/Region_1/7/data', msg.SerializeToString())
                self.assertTrue(save.called, rate)
        for rate in (1, 4999, 86400001):
            msg = messages_pb2.Telemetry(node_id=7, sampling_rate=rate)
            with patch.object(self.server, 'save_message') as save:
                self.server.on_mqtt_plaintext('wiot/Company_1/Region_1/7/data', msg.SerializeToString())
                save.assert_not_called()


class MqttReadinessTests(unittest.TestCase):
    def setUp(self):
        logger = patch('mqtt_impl.logger')
        logger.start()
        self.addCleanup(logger.stop)

    def client(self, subscribe_result=0):
        with patch('mqtt_impl.mqtt.Client') as paho:
            paho.return_value.is_connected.return_value = True
            paho.return_value.subscribe.return_value = (subscribe_result, 42)
            client = MqttNodeClient('example.invalid', 1883, b'0' * 16,
                'phase1-test', ['EgSA/+/+/#'], on_status=Mock())
        return client

    def test_immediate_subscription_failure_is_not_ready(self):
        client = self.client(4)
        client._on_connect(client.client, None, {}, 0)
        self.assertFalse(client.is_connected())

    def test_waits_for_successful_suback(self):
        client = self.client()
        client._on_connect(client.client, None, {}, 0)
        self.assertFalse(client.is_connected())
        client._on_subscribe(client.client, None, 42, [1])
        self.assertTrue(client.is_connected())
        client._on_disconnect(client.client, None, 0)
        self.assertFalse(client.is_connected())

    def test_rejected_suback_is_not_ready(self):
        client = self.client()
        client._on_connect(client.client, None, {}, 0)
        client._on_subscribe(client.client, None, 42, [128])
        self.assertFalse(client.is_connected())

    def test_missing_suback_times_out_and_unknown_mid_cannot_enable_ready(self):
        client = self.client()
        client._on_connect(client.client, None, {}, 0)
        client._on_subscribe(client.client, None, 999, [1])
        self.assertFalse(client.is_connected())
        client._subscription_timeout()
        self.assertFalse(client.is_connected())
        client.client.disconnect.assert_called()

    def test_multiple_subscriptions_all_require_success(self):
        client = self.client()
        client.subscribe_topics = ['wiot/+/Region_1/+/status', 'wiot/+/Region_1/+/data']
        client.client.subscribe.side_effect = [(0, 1), (0, 2)]
        client._on_connect(client.client, None, {}, 0)
        client._on_subscribe(client.client, None, 1, [0])
        self.assertFalse(client.is_connected())
        client._on_subscribe(client.client, None, 2, [1])
        self.assertTrue(client.is_connected())


class TenantStorageTests(unittest.TestCase):
    def test_existing_unique_database_is_preserved(self):
        from tenant_storage import database_path
        import sqlite3
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'Company_1.db'
            with __import__('contextlib').closing(sqlite3.connect(path)) as conn:
                conn.execute('CREATE TABLE messages(company TEXT)')
                conn.execute("INSERT INTO messages VALUES ('Company_1')")
                conn.commit()
            before = path.read_bytes()
            self.assertEqual(Path(database_path('Company_1', directory, ['Company_1'])), path)
            self.assertEqual(path.read_bytes(), before)

    def test_ambiguous_legacy_file_is_never_opened_for_other_tenant(self):
        from tenant_storage import database_path, preflight
        import sqlite3
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'Audit_Space.db'
            with __import__('contextlib').closing(sqlite3.connect(path)) as conn:
                conn.execute('CREATE TABLE messages(company TEXT)')
                conn.execute("INSERT INTO messages VALUES ('Audit Space')")
                conn.commit()
            before = path.read_bytes()
            owners = ['Audit Space', 'Audit_Space']
            self.assertTrue(preflight(owners, directory))
            for owner in owners:
                with self.assertRaises(ValueError): database_path(owner, directory, owners)
            self.assertEqual(path.read_bytes(), before)

    def test_mixed_or_unregistered_legacy_owner_is_rejected(self):
        from tenant_storage import database_path
        import sqlite3
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'Audit_Space.db'
            with __import__('contextlib').closing(sqlite3.connect(path)) as conn:
                conn.execute('CREATE TABLE messages(company TEXT)')
                conn.execute("INSERT INTO messages VALUES ('Audit Space')")
                conn.commit()
            with self.assertRaises(ValueError): database_path('Audit_Space', directory)


if __name__ == '__main__':
    unittest.main()
