"""Development broker bridge: forwards both ways, never loops, keeps payloads intact."""
from types import SimpleNamespace

import pytest

from wiot.sim.bridge import MqttBridge, parse_endpoint


class FakeClient:
    def __init__(self):
        self.published = []

    def publish(self, topic, payload, qos=0, retain=False):
        self.published.append((topic, payload, qos, retain))


def make_bridge():
    br = MqttBridge(("127.0.0.1", 1883), ("broker.example", 1883), ["wiot/Company_1/#"])
    local, upstream = FakeClient(), FakeClient()
    br._sides = {"local": (local, br._sides["local"][1]), "upstream": (upstream, br._sides["upstream"][1])}
    return br, local, upstream


def deliver(br, side, topic, payload, retain=False):
    other = "upstream" if side == "local" else "local"
    msg = SimpleNamespace(topic=topic, payload=payload, retain=retain)
    br._on_message(side, other)(None, None, msg)


def test_uplink_reaches_local_broker_and_its_echo_is_dropped():
    br, local, upstream = make_bridge()
    frame = b"\x01" + bytes(range(80))
    deliver(br, "upstream", "wiot/Company_1/Region_1/2/status", frame)
    assert local.published == [("wiot/Company_1/Region_1/2/status", frame, 1, False)]
    # the local broker hands the same frame back to the bridge's own subscription
    deliver(br, "local", "wiot/Company_1/Region_1/2/status", frame)
    assert upstream.published == []
    assert br.counts == {"up": 0, "down": 1}


def test_server_command_goes_upstream_once():
    br, local, upstream = make_bridge()
    cmd = b"\x01" + b"\xaa" * 32
    deliver(br, "local", "wiot/Company_1/Region_1/2/cmd", cmd)
    assert upstream.published == [("wiot/Company_1/Region_1/2/cmd", cmd, 1, False)]
    deliver(br, "upstream", "wiot/Company_1/Region_1/2/cmd", cmd)  # echo
    assert local.published == []
    # a genuinely new frame on the same topic (fresh AES IV) still crosses
    ack = b"\x01" + b"\xbb" * 32
    deliver(br, "upstream", "wiot/Company_1/Region_1/2/cmd", ack)
    assert local.published == [("wiot/Company_1/Region_1/2/cmd", ack, 1, False)]


def test_retained_flag_is_preserved():
    br, local, _ = make_bridge()
    deliver(br, "upstream", "wiot/Company_1/Region_1/broadcast", b"x", retain=True)
    assert local.published[0][3] is True


def test_endpoint_parsing_and_validation():
    assert parse_endpoint("broker.hivemq.com") == ("broker.hivemq.com", 1883)
    assert parse_endpoint("broker.hivemq.com:8883") == ("broker.hivemq.com", 8883)
    with pytest.raises(ValueError):
        MqttBridge(("127.0.0.1", 1883), ("x", 1883), [])
