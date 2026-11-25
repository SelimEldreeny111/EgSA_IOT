"""Gateway heartbeat persistence, silence detection and tenant routing without live hardware."""
import csv
import importlib
import io
import logging
import os
import sqlite3
from contextlib import closing
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

    def test_history_migrates_the_last_snapshot_and_keeps_subsequent_heartbeats(self):
        path = Path(self.temp.name) / 'legacy.db'
        msg = heartbeat()
        with closing(sqlite3.connect(path)) as db:
            db.execute("""CREATE TABLE gateway_status (
                company TEXT NOT NULL, region TEXT NOT NULL, gateway_id INTEGER NOT NULL,
                received_at REAL NOT NULL, payload BLOB NOT NULL,
                PRIMARY KEY(company,region,gateway_id))""")
            db.execute('INSERT INTO gateway_status VALUES (?,?,?,?,?)',
                       ('Company_1', 'Region_1', 1, 1000.75, msg.SerializeToString()))
            db.commit()

        store = GatewayStatusStore(path)
        msg.heartbeat_sequence = 2
        store.accept('Company_1', 'Region_1', 1, msg, received_at=1060.25, fingerprint=347)
        store.accept('Company_1', 'Region_1', 1, msg, received_at=1061.25, fingerprint=347)
        msg.heartbeat_sequence = 3
        store.accept('Company_1', 'Region_1', 1, msg, received_at=1060.25, fingerprint=348)
        rows, total = GatewayStatusStore(path).history('Company_1', 'Region_1', 1000, 1060)
        self.assertEqual(total, 3)
        self.assertEqual([row['heartbeat_sequence'] for row in rows], [3, 2, 1])
        self.assertEqual([row['received_at'] for row in rows], [1060.25, 1060.25, 1000.75])
        snapshot = store.list('Company_1', 'Region_1', True, now=1062)[0]
        self.assertEqual(snapshot['received_at'], 1060.25)
        self.assertEqual(snapshot['heartbeat_sequence'], 3)

    def test_validation_precedes_persistence(self):
        for message in [heartbeat(gateway=2), heartbeat(heartbeat_interval_seconds=0),
                heartbeat(uplink_transport=3), heartbeat(last_node_age_seconds=1),
                heartbeat(has_node_uplink=True, last_node_age_seconds=301)]:
            with self.assertRaises(ValueError):
                self.store.accept('Company_1', 'Region_1', 1, message)
        self.assertEqual(self.store.list('Company_1', 'Region_1', True), [])
        self.assertEqual(self.store.history('Company_1', 'Region_1', 0, 2000000000), ([], 0))

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

    def test_heartbeat_rows_mix_with_node_history_and_filter_on_api_and_export(self):
        server = self.server
        epoch = 1795000000
        for company, region, gateway, delta, fingerprint in (
            ('Company_1', 'Region_8', 2, 1.25, 701),
            ('Company_1', 'Region_8', 2, 3.25, 702),
            ('Company_1', 'Region_8', 2, 4.25, 702),  # Duplicate delivery of the same wire frame.
            ('Company_1', 'Region_7', 3, 4, 703),
            ('Company_2', 'Region_8', 4, 5, 704),
        ):
            packet = heartbeat(gateway, received_node_frames=24, forwarded_node_frames=23,
                               forward_failures=1, wdt_reset_count=6, power_reset_count=113,
                               has_node_uplink=True, last_node_age_seconds=19)
            with patch.object(server.time, 'time', return_value=epoch + delta):
                server.on_mqtt_plaintext(f'wiot/{company}/{region}/gateway/{gateway}/status',
                                         packet.SerializeToString(), fingerprint=fingerprint)
        server.save_message(epoch + 2, 'Status', 2, 'TUF', 12.5, 0, 0, 0, 0, '',
                            'Company_1', region='Region_8')

        client = server.app.test_client()
        with client.session_transaction() as session:
            session.update(username='tenant_admin', role='admin', company='Company_1')
        window = {'company': 'Company_2', 'region': 'Region_8', 'start': epoch, 'end': epoch + 3}
        page1 = client.get('/api/messages', query_string={**window, 'page_size': 2}).get_json()
        self.assertEqual(page1['total'], 3)
        self.assertEqual(page1['total_pages'], 2)
        self.assertEqual([row['type'] for row in page1['rows']], ['Gateway', 'Status'])
        latest, node = page1['rows']
        self.assertEqual((latest['company'], latest['gateway_id'], latest['transport']),
                         ('Company_1', 2, 'Wi-Fi'))
        self.assertEqual((latest['wdt_reset_count'], latest['power_reset_count']), (6, 113))
        self.assertIn('24 / 23', latest['details'])
        self.assertEqual(node['node_id'], 2)
        page2 = client.get('/api/messages', query_string={**window, 'page': 2, 'page_size': 2}).get_json()
        self.assertEqual([row['timestamp_epoch'] for row in page2['rows']], [epoch + 1])

        gateway_filter = {**window, 'type': 'Gateway'}
        self.assertEqual(client.get('/api/messages', query_string=gateway_filter).get_json()['total'], 2)
        self.assertEqual(client.get('/api/messages', query_string={**window, 'type': 'Status'}).get_json()['total'], 1)
        response = client.get('/export_csv', query_string=gateway_filter, buffered=True)
        with io.StringIO(response.get_data(as_text=True)) as csv_file:
            rows = list(csv.DictReader(csv_file))
        self.assertEqual([(row['Type'], row['Gateway ID'], row['Node ID']) for row in rows],
                         [('Gateway', '2', ''), ('Gateway', '2', '')])
        self.assertEqual(rows[0]['Last Node Uplink Age (s)'], '19')
        response.close()

        with client.session_transaction() as session:
            session.update(username='EgSA_Supervisor', role='admin')
        all_companies = client.get('/api/messages', query_string={
            'region': 'Region_8', 'start': epoch, 'end': epoch + 5, 'type': 'Gateway'}).get_json()
        self.assertEqual([row['company'] for row in all_companies['rows']], ['Company_2', 'Company_1', 'Company_1'])
