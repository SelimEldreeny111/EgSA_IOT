"""Command lifecycle regression tests: temporary SQLite, no broker/production DB."""
from pathlib import Path
import sys
import tempfile
import unittest
import sqlite3
import hashlib
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # project root
from wiot.domain.command_queue import CommandQueue


class CommandLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.queue = CommandQueue(Path(self.temp.name) / 'commands.db')

    def test_old_rate_retry_does_not_block_new_operator_valve_request(self):
        self.queue.enqueue('Company_1', 7, 1, 'SRATE', 60, 1001, now=1000)
        self.queue.claim_on_status('Company_1', 7, now=1001)
        self.queue.enqueue('Company_1', 7, 5, 'VALVE', 0, 1002, now=1002)
        self.assertEqual(self.queue.claim_on_status('Company_1', 7, now=1017)['request_id'], 1002)

    def test_new_setting_supersedes_old_setting_for_same_node_only(self):
        self.queue.enqueue('Company_1', 7, 1, 'SRATE', 60, 1001, now=1000)
        self.queue.enqueue('Company_1', 8, 1, 'SRATE', 60, 1002, now=1001)
        self.queue.enqueue('Company_1', 7, 1, 'SRATE', 120, 1003, now=1002)
        self.assertEqual(self.queue.get(1001, 'Company_1', 7, now=1003)['state'], 'superseded')
        self.assertEqual(self.queue.claim_on_status('Company_1', 7, now=1003)['request_id'], 1003)
        self.assertEqual(self.queue.get(1002, 'Company_1', 8, now=1003)['state'], 'pending')

    def test_retry_count_is_bounded(self):
        self.queue.enqueue('Company_1', 7, 1, 'SRATE', 60, 1001, now=1000)
        for now in (1001, 1016, 1031):
            self.assertIsNotNone(self.queue.claim_on_status('Company_1', 7, now=now))
        self.assertIsNone(self.queue.claim_on_status('Company_1', 7, now=1046))

    def immediate(self, command='VALVE', data=1, request=1001, broadcast=False):
        ids={'VALVE':5,'STIME':3,'WAKE':6,'SRATE':1,'GOSTM':4}
        self.queue.enqueue('Company_1',7,ids[command],command,data,request,now=1000,
                           actor='operator',delivery='now',broadcast=broadcast)
        return self.queue.claim_immediate(request,now=1001)

    def test_broker_receipt_is_not_execution_and_ack_can_arrive_first(self):
        item=self.immediate()
        self.assertTrue(self.queue.confirm_publish(1001,item['attempts'],now=1002))
        self.assertEqual(self.queue.get(1001,'Company_1',7,now=1002)['state'],'dispatched')
        self.assertFalse(self.queue.confirm_publish(1001,1,now=1003))
        self.assertTrue(self.queue.acknowledge('Company_1',7,1001,5,now=1004))
        self.assertFalse(self.queue.acknowledge('Company_1',7,1001,5,now=1005))
        self.immediate(request=1002)
        self.queue.acknowledge('Company_1',7,1002,5,now=1002)
        self.queue.confirm_publish(1002,1,now=1003)
        self.assertEqual(self.queue.get(1002,'Company_1',7,now=1004)['state'],'acknowledged')

    def test_attempt_mid_is_auditable_but_not_execution_proof(self):
        self.immediate()
        self.assertTrue(self.queue.record_transport_mid(1001,1,42))
        self.assertFalse(self.queue.record_transport_mid(1001,2,43))
        item=self.queue.get(1001,'Company_1',7,now=1002)
        self.assertEqual(item['attempt_records'][0]['mqtt_mid'],42)
        self.assertEqual(item['state'],'dispatched')

    def test_timeout_is_unknown_not_success_failure_or_automatic_valve_retry(self):
        self.immediate()
        self.assertEqual(self.queue.get(1001,'Company_1',7,now=1031)['state'],'outcome_unknown')
        self.assertIsNone(self.queue.claim_immediate(1001,now=1032))
        self.assertIsNone(self.queue.claim_on_status('Company_1',7,now=1032))
        self.assertTrue(self.queue.acknowledge('Company_1',7,1001,5,now=1033))
        row=self.queue.get(1001,'Company_1',7,now=1034)
        self.assertEqual(row['state'],'acknowledged')
        self.assertTrue(row['receipts'][0]['late'])

    def test_time_is_frozen_once_and_never_automatically_retried(self):
        self.queue.enqueue('Company_1',7,3,'STIME',900,1001,now=1000)
        self.assertEqual(self.queue.claim_on_status('Company_1',7,now=1001)['cmd_data'],1001)
        self.assertIsNone(self.queue.claim_on_status('Company_1',7,now=1020))
        self.assertEqual(self.queue.get(1001,'Company_1',7,now=1031)['state'],'outcome_unknown')

    def test_superseded_late_ack_does_not_restore_old_intent(self):
        self.immediate()
        self.immediate(data=0,request=1002)
        self.assertTrue(self.queue.acknowledge('Company_1',7,1001,5,now=1003))
        self.assertEqual(self.queue.get(1001,'Company_1',7,now=1004)['state'],'superseded')

    def test_broadcast_has_individual_receipts_not_fleet_success(self):
        self.immediate(broadcast=True)
        self.assertFalse(self.queue.acknowledge('Company_2',7,1001,5,now=1002))
        self.assertFalse(self.queue.acknowledge('Company_1',7,1001,6,now=1002))
        for node in (7,8):
            self.assertTrue(self.queue.acknowledge('Company_1',node,1001,5,now=1003))
        row=self.queue.get(1001,'Company_1',0,now=1004)
        self.assertEqual(row['state'],'broadcast_partial')
        self.assertEqual(len(row['receipts']),2)
        self.assertTrue(row['outcome_uncertain'])
        self.assertIsNone(self.queue.get(1001,'Company_1',7,now=1004))

    def test_window_is_bounded_and_duplicate_request_id_is_rejected(self):
        for request in range(1,33):
            self.queue.enqueue('Company_1',7,4,'GOSTM',0,request,now=1000)
        with self.assertRaises(ValueError):
            self.queue.enqueue('Company_1',7,4,'GOSTM',0,33,now=1000)
        with self.assertRaises(ValueError):
            self.queue.enqueue('Company_1',8,4,'GOSTM',0,1,now=1000)

    def test_atomic_claim_under_concurrent_status(self):
        self.queue.enqueue('Company_1',7,5,'VALVE',1,1001,now=1000)
        with ThreadPoolExecutor(max_workers=8) as pool:
            results=list(pool.map(lambda _: self.queue.claim_on_status('Company_1',7,now=1001),range(8)))
        self.assertEqual(sum(result is not None for result in results),1)

    def test_legacy_import_is_read_only_idempotent_and_retires_old_settings(self):
        old=Path(self.temp.name)/'legacy.db'
        with closing(sqlite3.connect(old)) as db:
            db.execute('''CREATE TABLE pending_commands (request_id INTEGER PRIMARY KEY,company TEXT,
                node_id INTEGER,cmd_id INTEGER,cmd_type TEXT,cmd_data INTEGER,created_at INTEGER,
                expires_at INTEGER,next_attempt_at INTEGER,attempts INTEGER,state TEXT,acknowledged_at INTEGER)''')
            db.executemany('INSERT INTO pending_commands VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',[
                (1,'Company_1',7,1,'SRATE',60,1000,9000,1000,0,'pending',None),
                (2,'Company_1',7,1,'SRATE',120,1001,9001,1001,0,'pending',None),
                (3,'Company_1',7,6,'WAKE',30,1002,9002,1017,1,'dispatched',None)])
            db.commit()
        checksum=hashlib.sha256(old.read_bytes()).hexdigest()
        path=Path(self.temp.name)/'new.db'
        for _ in range(2):
            journal=CommandQueue(path,legacy_path=old)
            self.assertEqual(len(journal.list('Company_1',now=1003)),3)
        self.assertEqual(journal.get(1,'Company_1',7,now=1003)['state'],'superseded')
        self.assertEqual(journal.get(2,'Company_1',7,now=1003)['actor'],'legacy operator unknown')
        self.assertEqual(journal.claim_on_status('Company_1',7,now=1003)['request_id'],2)
        self.assertIsNone(journal.claim_on_status('Company_1',7,now=1004))
        self.assertEqual(hashlib.sha256(old.read_bytes()).hexdigest(),checksum)
        # Corruption must not silently produce an empty replacement or unsafe command.
        with closing(sqlite3.connect(old)) as db:
            db.execute("UPDATE pending_commands SET cmd_data=2,cmd_id=5,cmd_type='VALVE' WHERE request_id=1")
            db.commit()
        corrupt_checksum=hashlib.sha256(old.read_bytes()).hexdigest()
        with self.assertRaises(RuntimeError):
            CommandQueue(Path(self.temp.name)/'rejected-import.db',legacy_path=old)
        self.assertEqual(hashlib.sha256(old.read_bytes()).hexdigest(),corrupt_checksum)


if __name__ == '__main__':
    unittest.main()
