"""Gateway heartbeat persistence, silence detection and tenant routing without live hardware."""
import importlib
import logging
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import messages_pb2
from gateway_status import GatewayStatusStore
from input_validation import parse_topic
from mqtt_impl import MqttNodeClient


def heartbeat(gateway=1, **values):
    message = messages_pb2.Gateway_Status(gateway_id=gateway, uptime_seconds=300,
        heartbeat_sequence=1, heartbeat_interval_seconds=60, uplink_transport=1)
    for field, value in values.items():
        setattr(message, field, value)
    return message


class GatewayStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = GatewayStatusStore(Path(self.temp.name) / 'gateways.db')

    def tearDown(self):
        self.temp.cleanup()

    def test_no_nodes_needed_and_freshness_boundaries(self):
        self.store.accept('Company_1', 'Region_1', 1, heartbeat(), received_at=1000)
        for age, state in [(0, 'online'), (119, 'online'), (120, 'overdue'),
                           (179, 'overdue'), (180, 'offline')]:
            row = self.store.list('Company_1', 'Region_1', True, now=1000 + age)[0]
            self.assertEqual(row['state'], state)
            self.assertFalse(row['has_node_uplink'])
            self.assertEqual(row['received_node_frames'], 0)
        self.assertEqual(self.store.list('Company_1', 'Region_1', False, now=1001)[0]['state'], 'unobserved')
        self.assertEqual(self.store.list('Company_1', 'Region_1', True, observed_since=1001, now=1002)[0]['state'], 'unobserved')

    def test_reboot_upsert_and_durable_tenant_isolation(self):
        for company, region, gateway in [('Company_1', 'Region_1', 1),
                ('Company_2', 'Region_1', 1), ('Company_1', 'Region_2', 1), ('Company_1', 'Region_1', 2)]:
            self.store.accept(company, region, gateway, heartbeat(gateway), received_at=1000)
        self.store.accept('Company_1', 'Region_1', 1,
                          heartbeat(uptime_seconds=2, power_reset_count=4, uplink_transport=2), received_at=1010)
        reopened = GatewayStatusStore(self.store.path)
        rows = reopened.list('Company_1', 'Region_1', True, now=1011)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['uptime_seconds'], 2)
        self.assertEqual(rows[0]['transport'], 'SIM800')
        self.assertEqual(rows[0]['power_reset_count'], 4)
        self.assertEqual(reopened.regions('Company_1'), {'Region_1', 'Region_2'})
        self.assertEqual(len(reopened.list('Company_2', 'Region_1', True, now=1011)), 1)

    def test_validation_precedes_persistence(self):
        for message in [heartbeat(gateway=2), heartbeat(heartbeat_interval_seconds=0),
                heartbeat(uplink_transport=3), heartbeat(last_node_age_seconds=1),
                heartbeat(has_node_uplink=True, last_node_age_seconds=301)]:
            with self.assertRaises(ValueError):
                self.store.accept('Company_1', 'Region_1', 1, message)
        self.assertEqual(self.store.list('Company_1', 'Region_1', True), [])

    def test_topic_identity_is_distinct_from_nodes(self):
        self.assertEqual(parse_topic('wiot/Company_1/Region_1/gateway/1/status'),
            ('Company_1', 'Region_1', 1, 'gateway_status'))
        for path in ['gateway/0/status', 'gateway/01/status', 'gateway/65536/status',
                     'gateway/1/data', 'gateway/1/status/x', 'Gateway/1/status']:
            with self.assertRaises(ValueError):
                parse_topic('wiot/Company_1/Region_1/' + path)

    def test_retained_heartbeat_cannot_refresh_life(self):
        client = MqttNodeClient.__new__(MqttNodeClient)
        client.on_status = Mock()
        client.on_plaintext = Mock()
        message = Mock(topic='wiot/Company_1/Region_1/gateway/1/status', retain=True, payload=b'x' * 49)
        client._on_message(None, None, message)
        client.on_plaintext.assert_not_called()


class GatewayServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.env = patch.dict(os.environ, {key: 'isolated-gateway-fixture' for key in
            ('WIOT_ADMIN_PASSWORD', 'WIOT_SUPERVISOR_PASSWORD', 'WIOT_MONITOR_PASSWORD', 'WIOT_FLASK_SECRET_KEY')})
        cls.env.start()
        old = os.getcwd()
        try:
            os.chdir(cls.temp.name)
            cls.server = importlib.import_module('server_web')
        finally:
            os.chdir(old)
        for handler in logging.getLogger().handlers[:]:
            handler.close()
            logging.getLogger().removeHandler(handler)
        logging.basicConfig(filename=str(Path(cls.temp.name) / 'system.log'), level=logging.INFO)
        cls.server.MAIN_DB_FILE = str(Path(cls.temp.name) / 'iot_data.db')
        cls.server.MESSAGE_DB_DIR = str(Path(cls.temp.name) / 'messages_dbs')
        cls.server._initialized_company_dbs.clear()
        cls.server.init_db()

    @classmethod
    def tearDownClass(cls):
        logging.shutdown()
        cls.env.stop()
        cls.temp.cleanup()

    def test_real_ingress_routes_to_gateway_store_and_authorized_api(self):
        server = self.server
        with patch.object(server, 'save_message') as save_sensor, patch.object(server, 'command_mailbox') as commands:
            server.on_mqtt_plaintext('wiot/Company_1/Region_9/gateway/1/status', heartbeat().SerializeToString())
            save_sensor.assert_not_called()
            commands.assert_not_called()
        client = server.app.test_client()
        self.assertEqual(client.get('/api/gateways').status_code, 302)
        with client.session_transaction() as session:
            session.update(username='tenant_admin', role='admin', company='Company_1')
        with patch.object(server, 'mqtt_client', Mock(is_connected=Mock(return_value=True))):
            data = client.get('/api/gateways?company=Company_2&region=Region_9').get_json()
            self.assertEqual(data['company'], 'Company_1')
            self.assertEqual(data['gateways'][0]['state'], 'online')
        regions = client.get('/api/regions').get_json()['regions']
        self.assertIn('Region_9', regions)
