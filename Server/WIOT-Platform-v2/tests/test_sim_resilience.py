"""The demo simulator must survive a short broker outage instead of exiting."""
import random
from types import SimpleNamespace

from wiot.protocol import messages_pb2
from wiot.sim.fleet import FleetSimulator


class FlakyClient:
    def __init__(self):
        self.up = True
        self.published = []

    def publish_plaintext(self, topic, payload, **_):
        if not self.up:
            raise RuntimeError("MQTT publish rejected (rc=4)")
        self.published.append(topic)


def test_publish_skips_frames_while_broker_is_down_and_resumes():
    sim = FleetSimulator.__new__(FleetSimulator)          # no network: inject a fake client
    sim.client, sim.drop_rate, sim.sent = FlakyClient(), 0, 0
    node = SimpleNamespace(topic_base="wiot/Demo/Region_1/1", rng=random.Random(1))
    msg = messages_pb2.Status_Message(node_id=1)

    sim._publish(node, msg, "status")
    sim.client.up = False
    sim._publish(node, msg, "status")                     # must not raise
    sim._publish(node, msg, "status")
    assert sim.missed == 2 and sim.sent == 1
    sim.client.up = True
    sim._publish(node, msg, "status")
    assert sim.sent == 2 and sim.missed == 0 and len(sim.client.published) == 2
