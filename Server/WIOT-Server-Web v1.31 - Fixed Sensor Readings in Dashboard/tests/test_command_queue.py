"""Mailbox contract tests; no broker, credentials, or production database."""

from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from command_queue import CommandQueue


class CommandQueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.queue = CommandQueue(Path(self.temp.name) / 'commands.db')

    def test_dispatch_requires_matching_application_ack(self):
        self.queue.enqueue('Company_1', 7, 5, 'VALVE', 1, 42, now=1000)
        self.assertIsNone(self.queue.claim_on_status('Company_1', 8, now=1001))
        item = self.queue.claim_on_status('Company_1', 7, now=1001)
        self.assertEqual((item['request_id'], item['cmd_data']), (42, 1))
        self.assertIsNone(self.queue.claim_on_status('Company_1', 7, now=1002))
        self.assertFalse(self.queue.acknowledge('Company_2', 7, 42, 5, now=1002))
        self.assertFalse(self.queue.acknowledge('Company_1', 8, 42, 5, now=1002))
        self.assertFalse(self.queue.acknowledge('Company_1', 7, 42, 6, now=1002))
        self.assertTrue(self.queue.acknowledge('Company_1', 7, 42, 5, now=1002))
        self.assertFalse(self.queue.acknowledge('Company_1', 7, 42, 5, now=1003))
        self.assertIsNone(self.queue.claim_on_status('Company_1', 7, now=1017))
        self.assertEqual(self.queue.get(42, 'Company_1', 7)['state'], 'acknowledged')

    def test_lost_ack_retries_on_later_status_and_expiry_stops_it(self):
        self.queue.enqueue('Company_1', 7, 1, 'SRATE', 60, 43, ttl_seconds=60, now=1000)
        self.assertIsNotNone(self.queue.claim_on_status('Company_1', 7, now=1001))
        self.assertIsNone(self.queue.claim_on_status('Company_1', 7, now=1015))
        self.assertIsNotNone(self.queue.claim_on_status('Company_1', 7, now=1016))
        self.assertEqual(self.queue.get(43, 'Company_1', 7, now=1016)['attempts'], 2)
        self.assertIsNone(self.queue.claim_on_status('Company_1', 7, now=1060))
        self.assertEqual(self.queue.get(43, 'Company_1', 7)['state'], 'expired')
        self.assertFalse(self.queue.acknowledge('Company_1', 7, 43, 1, now=1061))

    def test_invalid_ttl_and_tenant_scoping(self):
        for ttl in (True, 0, 59, 604801, '3600'):
            with self.subTest(ttl=ttl), self.assertRaises(ValueError):
                self.queue.enqueue('Company_1', 7, 1, 'SRATE', 60, 44, ttl, now=1000)
        self.queue.enqueue('Company_1', 7, 1, 'SRATE', 60, 44, now=1000)
        self.assertIsNone(self.queue.get(44, 'Company_2', 7))
        self.assertIsNone(self.queue.get(44, 'Company_1', 8))

    def test_explicit_node_rejection_is_terminal(self):
        self.queue.enqueue('Company_1', 7, 5, 'VALVE', 1, 45, now=1000)
        self.queue.claim_on_status('Company_1', 7, now=1001)
        self.assertTrue(self.queue.acknowledge(
            'Company_1', 7, 45, 5, success=False, now=1002))
        self.assertEqual(self.queue.get(45, 'Company_1', 7)['state'], 'rejected')
        self.assertIsNone(self.queue.claim_on_status('Company_1', 7, now=1016))

    def test_inspection_expires_offline_command_without_status(self):
        self.queue.enqueue('Company_1', 7, 1, 'SRATE', 60, 46, 60, now=1000)
        self.assertEqual(self.queue.get(46, 'Company_1', 7, now=1059)['state'], 'pending')
        self.assertEqual(self.queue.get(46, 'Company_1', 7, now=1060)['state'], 'expired')

    def test_old_valve_command_is_not_repeated_after_a_newer_opposite_command(self):
        self.queue.enqueue('Company_1', 7, 5, 'VALVE', 1, 49, 60, now=1000)
        self.assertEqual(self.queue.claim_on_status('Company_1', 7, now=1001)['request_id'], 49)
        self.queue.enqueue('Company_1', 7, 5, 'VALVE', 0, 50, 60, now=1002)
        self.assertEqual(self.queue.claim_on_status('Company_1', 7, now=1016)['request_id'], 50)
        self.assertTrue(self.queue.acknowledge('Company_1', 7, 50, 5, now=1017))
        self.assertIsNone(self.queue.claim_on_status('Company_1', 7, now=1032))
        self.assertEqual(self.queue.get(49, 'Company_1', 7, now=1032)['attempts'], 1)
        self.assertEqual(self.queue.get(49, 'Company_1', 7, now=1060)['state'], 'expired')

    def test_wake_is_not_automatically_repeated_after_lost_ack(self):
        self.queue.enqueue('Company_1', 7, 6, 'WAKE', 30, 47, 60, now=1000)
        self.assertIsNotNone(self.queue.claim_on_status('Company_1', 7, now=1001))
        self.assertIsNone(self.queue.claim_on_status('Company_1', 7, now=1016))
        self.assertEqual(self.queue.get(47, 'Company_1', 7, now=1016)['attempts'], 1)
        # A lost WAKE must not block later, independent value-setting commands.
        self.queue.enqueue('Company_1', 7, 1, 'SRATE', 60, 48, 60, now=1002)
        self.assertEqual(self.queue.claim_on_status('Company_1', 7, now=1017)['request_id'], 48)
        self.assertTrue(self.queue.acknowledge('Company_1', 7, 47, 6, now=1018))


if __name__ == '__main__':
    unittest.main()
