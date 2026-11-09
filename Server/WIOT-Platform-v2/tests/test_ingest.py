"""Ingestion path: wire-contract validation, persistence, ACK handling, queue release."""
from __future__ import annotations

import sqlite3
import time
from contextlib import closing

from wiot.protocol import messages_pb2
from wiot.protocol.transport import MqttNodeClient
from conftest import AES_KEY


def _status(node=2, **kw):
    msg = messages_pb2.Status_Message(node_id=node, sensor_id=1, timestamp=int(time.time()),
                                      battery_voltage=3.9, flow_rate=4.2, velocity=1.1,
                                      sensor_mask=1, active_sensor_count=1, flow_meter_type=1,
                                      flow_period_source=2, flow_live_valid=True, rtc_valid=True,
                                      flow_period_quality=1, power_mode=2, power_state=1, **kw)
    return msg.SerializeToString()


def _rows(app, company="Company_1"):
    path = app.state.runtime.telemetry.path_for(company)
    with closing(sqlite3.connect(path)) as db:
        db.row_factory = sqlite3.Row
        return [dict(r) for r in db.execute("SELECT * FROM messages ORDER BY id")]


def test_status_is_persisted_with_node_rtc(client, app):
    app.state.runtime.ingest.on_plaintext("wiot/Company_1/Region_1/2/status", _status())
    rows = _rows(app)
    assert len(rows) == 1
    row = rows[0]
    assert row["type"] == "Status" and row["node_id"] == 2 and row["time_source"] == "node_rtc"
    assert abs(row["flow"] - 4.2) < 1e-6 and row["power_mode"] == 2
    with closing(sqlite3.connect(app.state.runtime.telemetry.path_for("Company_1"))) as db:
        assert db.execute("SELECT COUNT(*) FROM meter_samples").fetchone()[0] == 1


def test_topic_payload_node_mismatch_is_dropped(client, app):
    app.state.runtime.ingest.on_plaintext("wiot/Company_1/Region_1/3/status", _status(node=2))
    assert _rows(app) == []


def test_unregistered_company_and_bad_topics_are_dropped(client, app):
    ingest = app.state.runtime.ingest
    ingest.on_plaintext("wiot/Unknown_Co/Region_1/2/status", _status())
    ingest.on_plaintext("EgSA/Company_1/2/Status", _status())
    ingest.on_plaintext("wiot/Company_1/Region_1/2/status", b"")
    assert _rows(app) == []


def test_invalid_enum_fails_closed(client, app):
    bad = messages_pb2.Status_Message(node_id=2, power_mode=9).SerializeToString()
    app.state.runtime.ingest.on_plaintext("wiot/Company_1/Region_1/2/status", bad)
    assert _rows(app) == []


def test_command_ack_marks_journal_and_is_not_a_meter_sample(client, app):
    runtime = app.state.runtime
    result = runtime.commands.journal.enqueue("Company_1", 2, 1, "SRATE", 60, delivery="now")
    runtime.commands.journal.claim_immediate(result["request_id"])
    ack = messages_pb2.Telemetry(node_id=2, sensor_id=1, timestamp=int(time.time()), flow_rate=1.0,
                                 sensor_mask=1, flow_meter_type=1, flow_live_valid=True,
                                 command_ack_request_id=result["request_id"], command_ack_cmd_id=1,
                                 command_ack_success=True)
    runtime.ingest.on_plaintext("wiot/Company_1/Region_1/2/data", ack.SerializeToString())
    item = runtime.commands.get(result["request_id"], "Company_1", "Region_1", 2)
    assert item["state"] == "acknowledged"
    rows = _rows(app)
    assert rows[-1]["time_source"] == "command_ack_cached" and rows[-1]["flow_live_valid"] == 0
    with closing(sqlite3.connect(runtime.telemetry.path_for("Company_1"))) as db:
        assert db.execute("SELECT COUNT(*) FROM meter_samples").fetchone()[0] == 0


def test_frame_roundtrip_matches_wire_format():
    key = bytes.fromhex(AES_KEY)
    frame = MqttNodeClient.encrypt_frame_static(_status(), key)
    payload = frame["payload"]
    assert payload[0] == 0x01 and len(payload) == 17 + frame["cipher_len"] and frame["cipher_len"] % 16 == 0
    client = MqttNodeClient("127.0.0.1", 1883, key, "t", [])
    plain = client.decrypt_frame_meta(payload)[0]
    assert messages_pb2.Status_Message.FromString(plain).node_id == 2


def test_fleet_and_series_endpoints(supervisor, app):
    for _ in range(3):
        app.state.runtime.ingest.on_plaintext("wiot/Company_1/Region_1/2/status", _status())
    fleet = supervisor.get("/api/v2/fleet", params={"company": "Company_1"}).json()
    assert fleet["summary"]["nodes"] == 1 and fleet["nodes"][0]["link_state"] == "online"
    series = supervisor.get("/api/v2/nodes/2/series", params={"company": "Company_1", "metric": "flow", "hours": 1}).json()
    assert series["points"] and abs(series["points"][-1][1] - 4.2) < 1e-6
    assert supervisor.get("/api/v2/nodes/2/series", params={"company": "Company_1", "metric": "nope"}).status_code == 400
