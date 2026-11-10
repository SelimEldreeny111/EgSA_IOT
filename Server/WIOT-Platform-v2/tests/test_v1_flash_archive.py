"""Flash archive protocol/persistence tests; temporary SQLite, no hardware/broker."""
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # project root
from wiot.protocol import messages_pb2 as pb
from wiot.domain.command_queue import CommandQueue
from wiot.domain.flash_archive import FlashArchive


def record(index=1, sequence=None, total=2, request=91, generation=4):
    sequence = index if sequence is None else sequence
    msg = pb.Telemetry(node_id=2, timestamp=1800000000 + sequence,
        flow_rate=12.5, battery_voltage=3.7, sample_sequence=sequence,
        stored_sample=True, sample_time_valid=True)
    msg.history.CopyFrom(pb.HistoryInfo(request_id=request, generation=generation,
        sequence=sequence, index=index, total=total, day_key=20261030,
        kind=2, phase=2, ack_required=True))
    return msg


class FlashArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'flash.db'
        self.archive = FlashArchive(self.path)

    def accept(self, msg, company='Company_1', region='Region_1', node=2):
        return self.archive.accept(company, region, node, msg, now=1800000100)

    def end(self, total=2, result=0):
        m = pb.Telemetry(node_id=2)
        m.history.CopyFrom(pb.HistoryInfo(request_id=91, generation=4,
            total=total, index=total, kind=2, phase=3, result=result, ack_required=True))
        return m

    def test_ack_is_after_durable_commit_and_duplicates_survive_restart(self):
        _, ack = self.accept(record())
        self.assertEqual(ack, (91, (2 << 32) | 1))
        self.archive = FlashArchive(self.path)
        self.accept(record())
        self.assertEqual(len(self.archive.records('Company_1', 'Region_1', 2)), 1)
        self.accept(record(2))
        _, ack = self.accept(self.end())
        self.assertEqual(ack, (91, (3 << 32) | 2))
        transfer = self.archive.summary('Company_1', 'Region_1', 2)['transfers'][0]
        self.assertEqual((transfer['complete'], transfer['received']), (1, 2))

    def test_database_failure_returns_no_ack_or_partial_row(self):
        with patch.object(self.archive, '_db', side_effect=sqlite3.OperationalError('disk full')):
            with self.assertRaises(sqlite3.OperationalError):
                self.accept(record())
        self.assertEqual(self.archive.records('Company_1', 'Region_1', 2), [])

    def test_same_record_last_and_today_deduplicate_and_conflict_rolls_back(self):
        last = record(total=1)
        last.history.kind=1
        last.history.ack_required=False
        last.command_ack_request_id=87
        self.accept(last)
        self.accept(record())
        conflict = record()
        conflict.flow_rate=99
        with self.assertRaisesRegex(ValueError, 'different sample'):
            self.accept(conflict)
        self.assertEqual(len(self.archive.records('Company_1', 'Region_1', 2)), 1)

    def test_index_and_total_are_consistent(self):
        self.accept(record())
        for msg in (record(sequence=2), record(2, sequence=1), record(2, total=3), record(2, generation=5)):
            with self.subTest(msg=msg), self.assertRaises(ValueError):
                self.accept(msg)
        self.assertEqual(self.archive.summary('Company_1', 'Region_1', 2)['transfers'][0]['received'],1)

    def test_incomplete_cancelled_and_late_packets_never_claim_success(self):
        self.accept(record())
        self.accept(self.end())
        self.assertFalse(self.archive.summary('Company_1', 'Region_1', 2)['transfers'][0]['complete'])
        self.accept(self.end(result=4))
        self.accept(record(2))
        t=self.archive.summary('Company_1', 'Region_1', 2)['transfers'][0]
        self.assertEqual((t['complete'],t['phase'],t['result']),(0,3,4))

    def test_empty_transfer_is_complete(self):
        self.accept(self.end(total=0,result=1))
        self.assertTrue(self.archive.summary('Company_1', 'Region_1', 2)['transfers'][0]['complete'])

    def test_tenant_region_and_node_are_isolated(self):
        self.accept(record())
        for company,region,node in [('Company_2','Region_1',2),('Company_1','Region_2',2),('Company_1','Region_1',3)]:
            self.assertEqual(self.archive.records(company,region,node),[])
        with self.assertRaises(ValueError): self.accept(record(),node=3)

    def test_capacity_and_record_envelope_validation(self):
        msg=pb.Telemetry(node_id=2)
        msg.flash_log.CopyFrom(pb.FlashLogInfo(state=4,capacity_bytes=8388608,
            usable_bytes=7332864,used_bytes=512,free_bytes=7332352,
            record_count=1,maximum_records=14322))
        event,ack=self.accept(msg)
        self.assertEqual(event['memory']['state_name'],'Ready');self.assertIsNone(ack)
        msg.flash_log.free_bytes+=1
        with self.assertRaises(ValueError):self.accept(msg)
        for field,value in [('sample_time_valid',False),('stored_sample',False),('live_fallback',True),('sample_sequence',9)]:
            m=record();setattr(m,field,value)
            with self.subTest(field=field),self.assertRaises(ValueError):self.accept(m)

    def test_flash_commands_are_direct_and_not_automatically_retried(self):
        queue=CommandQueue(Path(self.temp.name)/'cmd.db')
        for step,(cmd_id,cmd_type) in enumerate([(9,'CLEAR_FLASH'),(10,'FLASH_STATUS'),(11,'FLASH_LAST'),(12,'FLASH_TODAY'),(13,'FLASH_CANCEL')]):
            t=1000+100*step  # after the previous command's ACK timeout: one flash command in flight per node
            with self.assertRaises(ValueError):
                queue.enqueue('Company_1',2,cmd_id,cmd_type,0,cmd_id,now=t,broadcast=True)
            queue.enqueue('Company_1',2,cmd_id,cmd_type,0,cmd_id,now=t,delivery='now')
            self.assertIsNotNone(queue.claim_immediate(cmd_id,now=t+1))
            self.assertIsNone(queue.claim_immediate(cmd_id,now=t+17))


if __name__ == '__main__': unittest.main()
