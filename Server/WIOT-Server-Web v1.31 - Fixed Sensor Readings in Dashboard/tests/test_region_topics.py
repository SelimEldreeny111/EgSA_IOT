"""Regional identity regressions: temporary SQLite only, no broker or live data."""
import importlib
from contextlib import closing
import logging
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import messages_pb2
from command_queue import CommandQueue
from input_validation import parse_topic
from region_topics import command_topic, migrate_region_storage, region_id, SUBSCRIPTIONS


class RegionContractTests(unittest.TestCase):
    def test_exact_topic_contract(self):
        for suffix, kind in [('data', 'telemetry'), ('status', 'status'), ('cmd', 'cmd')]:
            self.assertEqual(parse_topic(f'wiot/Company_1/Region_1/3/{suffix}'),
                             ('Company_1', 'Region_1', 3, kind))
        self.assertEqual(parse_topic('wiot/Company_1/Region_1/broadcast'),
                         ('Company_1', 'Region_1', 0, 'cmd'))
        self.assertEqual(command_topic('Company_1', 'Region_2', 3), 'wiot/Company_1/Region_2/3/cmd')
        self.assertEqual(command_topic('Company_1', 'Region_2', 0, True), 'wiot/Company_1/Region_2/broadcast')
        self.assertEqual(SUBSCRIPTIONS, ['wiot/+/+/+/data', 'wiot/+/+/+/status',
                                        'wiot/+/+/+/cmd', 'wiot/+/+/broadcast'])

    def test_reject_aliases_and_wildcards(self):
        for topic in ('EgSA/Company_1/3/Status', 'wiot/Company_1/3/status',
                      'wiot/Company_1//3/status', 'wiot/Company_1/+/3/status',
                      'wiot/Company_1/Region_1/03/status', 'wiot/Company_1/Region_1/3/Status',
                      'wiot/Company_1/Region_1/3/telemetry', 'wiot/Company_1/Region_1/broadcast/cmd',
                      'wiot/Company_1/Region_1/3/cmd/extra', 'wiot/Company_1/Region_1/0/data'):
            with self.subTest(topic=topic), self.assertRaises(ValueError): parse_topic(topic)
        for value in ('', ' Region_1', 'Region_1 ', '../r', '+', '#', 'r/2', None, 'x'*41):
            with self.subTest(value=value), self.assertRaises(ValueError): region_id(value)

    def test_queue_identity_ack_and_supersession_are_regional(self):
        with tempfile.TemporaryDirectory() as directory:
            queue = CommandQueue(Path(directory)/'queue.db')
            a = queue.enqueue('Company_1', 3, 1, 'SRATE', 10, region='Region_1')
            b = queue.enqueue('Company_1', 3, 1, 'SRATE', 20, region='Region_2')
            self.assertEqual(queue.list('Company_1')[0]['request_id'], a['request_id'])
            self.assertEqual(queue.get(a['request_id'], 'Company_1', 3)['state'], 'pending')
            self.assertIsNone(queue.get(a['request_id'], 'Company_1', 3, region='Region_2'))
            claimed = queue.claim_on_status('Company_1', 3, region='Region_2')
            self.assertEqual(claimed['request_id'], b['request_id'])
            self.assertFalse(queue.acknowledge('Company_1', 3, b['request_id'], 1, region='Region_1'))
            self.assertTrue(queue.acknowledge('Company_1', 3, b['request_id'], 1, region='Region_2'))

    def test_broadcast_scope_does_not_supersede_other_region(self):
        with tempfile.TemporaryDirectory() as directory:
            queue = CommandQueue(Path(directory)/'queue.db')
            a = queue.enqueue('Company_1', 3, 5, 'VALVE', 1, region='Region_1')
            b = queue.enqueue('Company_1', 3, 5, 'VALVE', 1, region='Region_2')
            broad = queue.enqueue('Company_1', 3, 5, 'VALVE', 0, delivery='now', broadcast=True, region='Region_2')
            self.assertEqual(queue.get(a['request_id'], 'Company_1', 3)['state'], 'pending')
            self.assertEqual(queue.get(b['request_id'], 'Company_1', 3, region='Region_2')['state'], 'superseded')
            queue.claim_immediate(broad['request_id'])
            self.assertFalse(queue.acknowledge('Company_1', 3, broad['request_id'], 5, region='Region_1'))
            self.assertTrue(queue.acknowledge('Company_1', 3, broad['request_id'], 5, region='Region_2'))

    def test_legacy_region_migration_preserves_periods_and_is_idempotent(self):
        with closing(sqlite3.connect(':memory:')) as db:
            db.executescript('''CREATE TABLE messages(id INTEGER PRIMARY KEY,node_id INTEGER);
                CREATE TABLE meter_samples(id INTEGER PRIMARY KEY,node_id INTEGER);
                CREATE TABLE consumption_periods(id INTEGER PRIMARY KEY,node_id INTEGER,
                    sensor_id TEXT,flow_meter_type INTEGER,period_type TEXT,period_key TEXT,
                    volume_liters INTEGER,UNIQUE(node_id,sensor_id,flow_meter_type,period_type,period_key));
                INSERT INTO consumption_periods VALUES(1,3,'1',2,'day','2026-10-26',1234);''')
            migrate_region_storage(db); migrate_region_storage(db)
            self.assertEqual(db.execute('SELECT region,volume_liters FROM consumption_periods').fetchone(), ('Region_1',1234))
            db.execute("INSERT INTO consumption_periods VALUES(2,3,'1',2,'day','2026-10-26',999,'Region_2')")
            self.assertEqual(db.execute('SELECT COUNT(*) FROM consumption_periods').fetchone()[0],2)


class RegionalServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        cls.env=patch.dict(os.environ,{key:'isolated-region-tests' for key in (
            'WIOT_ADMIN_PASSWORD','WIOT_SUPERVISOR_PASSWORD','WIOT_MONITOR_PASSWORD','WIOT_FLASK_SECRET_KEY')})
        cls.env.start()
        old=os.getcwd()
        try:
            os.chdir(cls.temp.name)
            cls.server=importlib.import_module('server_web')
        finally: os.chdir(old)
        for handler in logging.getLogger().handlers[:]:
            handler.close(); logging.getLogger().removeHandler(handler)
        logging.basicConfig(filename=str(Path(cls.temp.name)/'system.log'),level=logging.INFO)
        cls.server.MAIN_DB_FILE=str(Path(cls.temp.name)/'iot_data.db')
        cls.server.MESSAGE_DB_DIR=str(Path(cls.temp.name)/'messages_dbs')
        cls.server._initialized_company_dbs.clear()
        cls.server.init_db()
        cls.server.app.config['TESTING']=True

    @classmethod
    def tearDownClass(cls):
        logging.shutdown(); cls.env.stop(); cls.temp.cleanup()

    def client(self):
        client=self.server.app.test_client()
        with client.session_transaction() as session:
            session.update(username='tenant_admin',role='admin',company='Company_1')
        return client

    def test_region_control_and_company_authorization(self):
        client=self.client()
        html=client.get('/dashboard').data.decode()
        self.assertEqual(html.count('id="cfg-region"'),1)
        self.assertIn('handleRegionChange()',html)
        self.assertIn('id="region-options"',html)
        result=client.get('/api/regions',query_string={'company':'Company_2'})
        self.assertEqual(result.status_code,200)
        self.assertEqual(result.json['company'],'Company_1')

    def test_same_node_regions_database_latest_history_consumption_and_csv(self):
        server=self.server; client=self.client()
        for region, flow in [('Region_1',11),('Region_2',22)]:
            msg=messages_pb2.Status_Message(node_id=3,sensor_id=1,timestamp=1793000000,
                flow_rate=flow,flow_rate_per_day=flow,flow_rate_per_month=flow,flow_rate_per_year=flow,
                sensor_mask=8,active_sensor_count=1,flow_meter_type=2,flow_period_source=2,
                flow_live_valid=True,flow_period_totals_valid=True,rtc_valid=True,flow_period_quality=1,
                wdt_reset_count=flow,power_reset_count=flow+1)
            with patch.object(server,'emit_iot_message') as emit,patch.object(server,'dispatch_queued_command'):
                server.on_mqtt_plaintext(f'wiot/Company_1/{region}/3/status',msg.SerializeToString())
                self.assertEqual(emit.call_args.args[0]['Region'],region)
        for region, flow in [('Region_1',11),('Region_2',22)]:
            result=client.get('/api/node_latest',query_string={'company':'Company_1','region':region,'history_node':3}).json
            self.assertEqual(result['latest'][0]['flow'],flow)
            self.assertTrue(all(row['region']==region for row in result['history']))
            result=client.get('/api/messages',query_string={'region':region}).json
            self.assertTrue(all(row['region']==region for row in result['rows']))
            periods=client.get('/api/consumption',query_string={'region':region,'node_id':3}).json['rows']
            self.assertEqual(len(periods),3)
            self.assertTrue(all(row['volume_liters']==flow*1000 for row in periods))
            csv=client.get('/export_csv',query_string={'region':region}).data.decode()
            self.assertIn('Region',csv.splitlines()[0]); self.assertIn(region,csv)
            self.assertNotIn('Region_2' if region=='Region_1' else 'Region_1',csv)
        self.assertIn('Region_2',client.get('/api/regions').json['regions'])

    def test_immediate_command_and_regional_broadcast_topics(self):
        server=self.server; client=self.client()
        with tempfile.TemporaryDirectory() as directory:
            queue=CommandQueue(Path(directory)/'queue.db'); broker=Mock()
            broker.is_connected.return_value=True; broker.publish_plaintext.return_value={'mqtt_mid':7}
            with patch.object(server,'command_mailbox',return_value=queue),patch.object(server,'mqtt_client',broker):
                for broadcast,topic in [(False,'wiot/Company_1/Region_2/3/cmd'),(True,'wiot/Company_1/Region_2/broadcast')]:
                    result=client.post('/api/command',json={'company':'Company_1','region':'Region_2',
                        'node_id':3,'cmd_type':'GOSTM','cmd_data':0,'broadcast':broadcast})
                    self.assertEqual(result.status_code,200);self.assertTrue(result.json['success'])
                    self.assertEqual(broker.publish_plaintext.call_args.args[0],topic)
                count=broker.publish_plaintext.call_count
                for region in ('+','Region/2','',None):
                    self.assertEqual(client.post('/api/command',json={'company':'Company_1','region':region,
                        'node_id':3,'cmd_type':'GOSTM'}).status_code,400)
                self.assertEqual(broker.publish_plaintext.call_count,count)

    def test_wrong_region_ack_cannot_complete_or_dispatch_queued_command(self):
        server=self.server
        with tempfile.TemporaryDirectory() as directory:
            queue=CommandQueue(Path(directory)/'queue.db'); broker=Mock()
            broker.is_connected.return_value=True; broker.publish_plaintext.return_value={}
            item=queue.enqueue('Company_1',3,4,'GOSTM',0,region='Region_2')
            with patch.object(server,'command_mailbox',return_value=queue),patch.object(server,'mqtt_client',broker):
                server.dispatch_queued_command('Company_1',3,'Region_1');broker.publish_plaintext.assert_not_called()
                server.dispatch_queued_command('Company_1',3,'Region_2')
                self.assertEqual(broker.publish_plaintext.call_args.args[0],'wiot/Company_1/Region_2/3/cmd')
                msg=messages_pb2.Telemetry(node_id=3,command_ack_request_id=item['request_id'],
                    command_ack_cmd_id=4,command_ack_success=True)
                with patch.object(server,'save_message'),patch.object(server,'emit_iot_message'):
                    server.on_mqtt_plaintext('wiot/Company_1/Region_1/3/data',msg.SerializeToString())
                    self.assertEqual(queue.get(item['request_id'],'Company_1',3,region='Region_2')['state'],'dispatched')
                    server.on_mqtt_plaintext('wiot/Company_1/Region_2/3/data',msg.SerializeToString())
                    self.assertEqual(queue.get(item['request_id'],'Company_1',3,region='Region_2')['state'],'acknowledged')
