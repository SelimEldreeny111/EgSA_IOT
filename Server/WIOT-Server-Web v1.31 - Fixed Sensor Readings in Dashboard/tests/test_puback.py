"""PUBACK races, bounded completion and off-network-thread journal work."""
from pathlib import Path
import sys
import threading
import unittest
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from mqtt_impl import MqttNodeClient


class PubackTests(unittest.TestCase):
    def setUp(self):
        self.transport=MqttNodeClient('unused',1883,b'0'*16,'test',['EgSA/+/+/#'])
        self.transport.encrypt_frame=lambda plain:{'payload':b'frame'}
        self.transport.client.publish=lambda *a,**kw:SimpleNamespace(rc=0,mid=42,is_published=lambda:False)

    def test_delayed_duplicate_puback_runs_once_off_network_thread(self):
        network=threading.get_ident(); completed=threading.Event(); threads=[]
        def callback(): threads.append(threading.get_ident()); completed.set()
        self.transport.publish_plaintext('topic',b'x',on_complete=callback)
        self.assertFalse(completed.is_set())
        for _ in range(2): self.transport._on_publish(None,None,42)
        self.assertTrue(completed.wait(2))
        self.transport._completions.join()
        self.assertEqual(len(threads),1)
        self.assertNotEqual(threads[0],network)

    def test_inline_early_puback_does_not_lose_completion(self):
        completed=threading.Event()
        def publish(*a,**kw):
            self.transport._on_publish(None,None,42)
            return SimpleNamespace(rc=0,mid=42,is_published=lambda:True)
        self.transport.client.publish=publish
        self.transport.publish_plaintext('topic',b'x',on_complete=completed.set)
        self.assertTrue(completed.wait(2))
        self.assertEqual(self.transport._pending_publish,{})

    def test_pending_window_is_bounded_before_transport_submission(self):
        self.transport._pending_publish={mid:lambda:None for mid in range(256)}
        with self.assertRaises(RuntimeError):
            self.transport.publish_plaintext('topic',b'x',on_complete=lambda:None)

    def test_failure_never_records_broker_receipt(self):
        self.transport.client.publish=lambda *a,**kw:SimpleNamespace(rc=4)
        with self.assertRaises(RuntimeError):
            self.transport.publish_plaintext('topic',b'x',on_complete=lambda:self.fail('False PUBACK'))
        self.assertEqual(self.transport._pending_publish,{})

    def test_non_qos1_cannot_be_used_as_command_receipt(self):
        with self.assertRaises(ValueError):
            self.transport.publish_plaintext('topic',b'x',qos=0,on_complete=lambda:None)
