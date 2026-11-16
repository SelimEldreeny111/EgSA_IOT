"""Command delivery (2026-11-16): commands to LORA_WOR_STOP nodes are sent at once, like v1.31, and only one
command is on a gateway's radio at a time.

Field report: v2 held every command for node 3 (LORA_WOR_STOP) until its next Status (12 s to 6 min) and let
bursts of clicks reach the half-duplex LoRa link together, where most were never answered. Every node hears
every command and the gateway has no downlink queue or retry, so the rule is per gateway (company, region)."""
from __future__ import annotations

import os
import tempfile
import threading
import time

import pytest

from wiot.domain.command_queue import HELD_LIMIT_S, RADIO_BUSY_S, CommandQueue
from wiot.protocol.power import delivery_for_power_mode
from wiot.services.commands import CommandRequest


class Sent:
    """Stand-in MQTT client that records each published command topic."""

    def __init__(self):
        self.topics: list[str] = []

    def publish_plaintext(self, topic, payload, on_complete=None):
        self.topics.append(topic)
        if on_complete:
            on_complete()
        return {"mqtt_mid": len(self.topics)}


@pytest.fixture()
def live(supervisor, monkeypatch):
    rt = supervisor.app.state.runtime
    sent = Sent()
    monkeypatch.setattr(rt.commands.broker, "is_ready", lambda: True)
    monkeypatch.setattr(rt.commands.broker, "client", sent)
    monkeypatch.setattr(rt.commands, "_schedule_release", lambda *a, **k: None)   # no timers in tests
    return rt.commands, sent


def journal(tmp):
    return CommandQueue(os.path.join(tmp, "j.db"))


def test_delivery_follows_the_power_mode():
    assert [delivery_for_power_mode(m) for m in (1, 2, 3, 4, 5)] == ["now", "next_wake", "now", "next_wake", "now"]
    assert delivery_for_power_mode(None) is None and delivery_for_power_mode(0) is None


def test_auto_sends_wake_on_radio_nodes_now_and_queues_rtc_nodes(live):
    cmds, sent = live
    modes = {2: 5, 3: 4, 4: None}
    cmds.power_mode = lambda c, r, n: modes.get(n)
    cmds.risk = lambda c, r, n, t: {"tier": "UNLIKELY", "probability": 0.05}       # ignored once the mode is known
    req = lambda n: CommandRequest(company="Company_1", region="Region_1", node_id=n, cmd_type="GOSTM", delivery="auto")
    wor = cmds.submit(req(2), actor="op")
    assert wor["delivery"] == "now" and not wor["queued"] and wor["auto"]["power_mode"] == "LORA_WOR_STOP"
    assert sent.topics == ["wiot/Company_1/Region_1/2/cmd"]
    rtc = cmds.submit(req(3), actor="op")
    assert rtc["delivery"] == "next_wake" and rtc["queued"] and "radio is off" in rtc["auto"]["reason"]
    assert len(sent.topics) == 1
    unknown = cmds.submit(req(4), actor="op")                                      # unknown mode: the model decides
    assert unknown["delivery"] == "next_wake" and unknown["auto"]["tier"] == "UNLIKELY"


def test_one_command_on_the_gateway_radio(live):
    cmds, sent = live
    cmds.power_mode = lambda c, r, n: 5
    send = lambda t, d=None, n=3: cmds.submit(CommandRequest(company="Company_1", region="Region_1", node_id=n,
                                                             cmd_type=t, cmd_data=d, delivery="now"), actor="op")
    first = send("VALVE", 1)
    assert not first["queued"] and len(sent.topics) == 1
    burst = [send("SRATE", 60) for _ in range(5)]                                  # five fast clicks
    assert all(b["queued"] and b["held_behind"] == first["request_id"] for b in burst)
    rows = {r["request_id"]: r for r in cmds.journal.list("Company_1", 3, 20, region="Region_1")}
    assert [rows[b["request_id"]]["state"] for b in burst] == ["superseded"] * 4 + ["pending"]
    other = send("GOSTM", n=2)                                                     # another node, same gateway
    assert other["queued"] and len(sent.topics) == 1                               # nothing else went on air
    assert cmds.acknowledge("Company_1", "Region_1", 3, first["request_id"], 5, True)
    assert sent.topics == ["wiot/Company_1/Region_1/3/cmd"] * 2                    # the last click, once, first in line
    assert cmds.journal.get(burst[-1]["request_id"], "Company_1", 3, region="Region_1")["state"] == "dispatched"
    assert cmds.acknowledge("Company_1", "Region_1", 3, burst[-1]["request_id"], 1, True)
    assert sent.topics[-1] == "wiot/Company_1/Region_1/2/cmd"                      # then node 2's command
    assert cmds.submit(CommandRequest(company="Company_1", region="Region_2", node_id=3, cmd_type="GOSTM",
                                      delivery="now"), actor="op")["queued"] is False   # another gateway is free
    cancel = send("FLASH_CANCEL")                                                  # Cancel is never held
    assert not cancel["queued"]


def test_a_command_on_air_blocks_until_answered_or_for_at_most_the_busy_window():
    with tempfile.TemporaryDirectory() as tmp:
        q = journal(tmp)
        a = q.enqueue("Company_1", 3, 5, "VALVE", 1, now=1000, delivery="now", region="Region_1")["request_id"]
        assert q.claim_immediate(a, now=1000, ack_timeout=90, one_in_flight=True)["state"] == "dispatched"
        b = q.enqueue("Company_1", 3, 5, "VALVE", 0, now=1002, delivery="now", region="Region_1")["request_id"]
        held = q.claim_immediate(b, now=1002, ack_timeout=90, one_in_flight=True)
        assert held["blocked_by"]["request_id"] == a                               # superseded but still on air
        assert held["blocked_by"]["release_at"] == 1000 + RADIO_BUSY_S
        assert "blocked_by" in q.claim_held("Company_1", now=1030, region="Region_1", ack_timeout=90)
        assert q.held_count("Company_1", now=1030, region="Region_1") == 1
        released = q.claim_held("Company_1", now=1000 + RADIO_BUSY_S + 1, region="Region_1", ack_timeout=90)
        assert released["request_id"] == b and released["state"] == "dispatched"   # A unanswered: radio free again
        assert q.claim_held("Company_1", now=1050, region="Region_1") is None
        # a broadcast waits for the radio too, and blocks it until a node answers
        c = q.enqueue("Company_1", 3, 4, "GOSTM", 0, now=1060, delivery="now", broadcast=True, region="Region_1")
        assert "blocked_by" in q.claim_immediate(c["request_id"], now=1060, one_in_flight=True)
        assert q.claim_held("Company_1", now=1046 + RADIO_BUSY_S + 1, region="Region_1")["broadcast"] == 1


def test_first_come_first_served_and_held_commands_expire():
    with tempfile.TemporaryDirectory() as tmp:
        q = journal(tmp)
        a = q.enqueue("Company_1", 3, 4, "GOSTM", 0, now=1000, delivery="now", region="Region_1")["request_id"]
        q.claim_immediate(a, now=1000, ack_timeout=90, one_in_flight=True)
        b = q.enqueue("Company_1", 2, 7, "CLEAR_POWER_RESETS", 0, now=1001, delivery="now", region="Region_1")
        assert "blocked_by" in q.claim_immediate(b["request_id"], now=1001, one_in_flight=True)
        c = q.enqueue("Company_1", 4, 4, "GOSTM", 0, now=1060, delivery="now", region="Region_1")
        blocked = q.claim_immediate(c["request_id"], now=1060, one_in_flight=True)   # radio free, but b was first
        assert blocked["blocked_by"]["request_id"] == b["request_id"] and blocked["blocked_by"]["waiting"]
        assert q.claim_held("Company_1", now=1060, region="Region_1")["request_id"] == b["request_id"]
        d = q.enqueue("Company_1", 5, 4, "GOSTM", 0, now=1061, delivery="now", region="Region_1")
        q.claim_immediate(d["request_id"], now=1061, one_in_flight=True)
        q.held_count("Company_1", now=1061 + HELD_LIMIT_S, region="Region_1")
        assert q.claim_held("Company_1", now=1061 + HELD_LIMIT_S, region="Region_1") is None   # c and d expired
        rows = {r["request_id"]: r for r in q.list("Company_1", 4, 5, now=1061 + HELD_LIMIT_S, region="Region_1")}
        assert rows[c["request_id"]]["state"] == "expired" and "not sent" in rows[c["request_id"]]["reason"]


def test_status_release_waits_for_the_radio_and_listening_nodes_skip_the_status():
    with tempfile.TemporaryDirectory() as tmp:
        q = journal(tmp)
        a = q.enqueue("Company_1", 3, 5, "VALVE", 1, now=1000, delivery="now", region="Region_1")["request_id"]
        q.claim_immediate(a, now=1000, ack_timeout=90, one_in_flight=True)
        s = q.enqueue("Company_1", 3, 3, "STIME", 0, now=1003, delivery="next_wake", region="Region_1")["request_id"]
        blocked = q.claim_on_status("Company_1", 3, now=1005, region="Region_1", one_in_flight=True)
        assert blocked["blocked_by"]["request_id"] == a                            # no second downlink into a reply
        assert q.claim_on_status("Company_1", 3, now=1005, region="Region_1")["request_id"] == s   # old behaviour
        # a queued command of a listening node goes out when the radio is free, without waiting for a Status
        r = q.enqueue("Company_1", 2, 4, "GOSTM", 0, now=1010, delivery="next_wake", region="Region_1")["request_id"]
        assert q.claim_held("Company_1", now=1100, region="Region_1", listening=lambda n: False) is None
        got = q.claim_held("Company_1", now=1100, region="Region_1", listening=lambda n: n == 2,
                           ack_timeout=lambda n: 90)
        assert got["request_id"] == r and got["ack_deadline"] == 1190


def test_the_release_timer_fires_once_per_gateway(supervisor, monkeypatch):
    cmds = supervisor.app.state.runtime.commands
    fired = threading.Event()
    calls = []
    monkeypatch.setattr(cmds, "release_held", lambda c, r, n=None: (calls.append((c, r)), fired.set()))
    cmds._schedule_release("Company_1", "Region_1", None, delay=30)
    cmds._schedule_release("Company_1", "Region_1", time.time() - 5)            # radio already free: about 1 s
    assert fired.wait(5) and calls == [("Company_1", "Region_1")]
    time.sleep(0.2)
    assert calls == [("Company_1", "Region_1")] and ("Company_1", "Region_1") not in cmds._release_timers


def test_a_history_download_owns_the_radio_and_rtc_nodes_keep_their_status_window(live):
    cmds, sent = live
    modes = {3: 5, 4: 4}
    cmds.power_mode = lambda c, r, n: modes.get(n)
    rid = cmds.journal.enqueue("Company_1", 3, 12, "FLASH_TODAY", 0, delivery="now", region="Region_1")["request_id"]
    cmds.journal.claim_immediate(rid, ack_timeout=90)                              # a download, already answered:
    cmds.journal.acknowledge("Company_1", 3, rid, 12, region="Region_1")           # its rows are streaming now
    running = {"request": 77, "received": 3, "total": 40, "updated": int(time.time())}
    cmds.flash_transfer = lambda c, r, n, now: running if n == 3 else None
    held = cmds.submit(CommandRequest(company="Company_1", region="Region_1", node_id=4, cmd_type="GOSTM",
                                      delivery="now"), actor="op")
    assert held["queued"] and held["held_behind"] == 77 and "history download" in held["message"] and not sent.topics
    cmds.release_held("Company_1", "Region_1")
    assert not sent.topics                                                         # still downloading
    running = None
    cmds.flash_transfer = lambda c, r, n, now: running
    cmds.release_held("Company_1", "Region_1")
    assert sent.topics == ["wiot/Company_1/Region_1/4/cmd"]                        # download over: sent
    # an RTC node (mode 4) still gets its queued command in the window after its own Status
    q = cmds.submit(CommandRequest(company="Company_1", region="Region_1", node_id=4, cmd_type="STRAN",
                                   cmd_data=120, delivery="auto"), actor="op")
    assert q["delivery"] == "next_wake"
    cmds.dispatch_on_status("Company_1", "Region_1", 4)
    assert sent.topics[-1] == "wiot/Company_1/Region_1/4/cmd" and len(sent.topics) == 2
