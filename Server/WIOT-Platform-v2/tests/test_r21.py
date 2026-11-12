"""Release 2.1: command fixes, automatic clock sync, security watch, farm and weather alerts."""
from __future__ import annotations

import io
import json
import time
from types import SimpleNamespace

import pytest

from wiot.domain.command_queue import ACK_TIMEOUT_SECONDS, CommandQueue, ack_timeout_for
from wiot.protocol import messages_pb2 as pb
from wiot.services.alerts import (AlertMonitor, EVENT_QUIET_S, in_night, night_hours, valve_flow_verdict)
from wiot.services.clocksync import ClockSync
from wiot.services.commands import CommandError, CommandRequest, CommandService
from wiot.services.farm import FarmService, WeatherClient
from wiot.storage.alert_store import AlertStore

NOW = 1_800_000_000


def status(node=2, ts=None, rtc=True, flow=0.0, valve=0, mode=5) -> bytes:
    return pb.Status_Message(
        node_id=node, sensor_id=1, timestamp=int(time.time()) if ts is None else ts, battery_voltage=3.9,
        sensor_mask=3, active_sensor_count=2, flow_meter_type=1, flow_live_valid=True, rtc_valid=rtc,
        sample_time_valid=rtc, flow_period_quality=1, flow_rate=flow, node_status=valve, power_mode=mode,
        power_state=1).SerializeToString()


def journal_rows(rt, node=2, company="Company_1"):
    return rt.commands.journal.list(company, node, 50, region="Region_1")


# ------------------------------------------------------------------ point 1
def test_interval_minimum_matches_the_node_firmware():
    base = dict(company="Company_1", region="Region_1", node_id=2)
    with pytest.raises(CommandError):
        CommandService.normalise(CommandRequest(**base, cmd_type="SRATE", cmd_data=9))
    with pytest.raises(CommandError):
        CommandService.normalise(CommandRequest(**base, cmd_type="STRAN", cmd_data=5))
    assert CommandService.normalise(CommandRequest(**base, cmd_type="STRAN", cmd_data=10)) == (2, 10)


# ----------------------------------------------------------------- point 13
def test_ack_deadline_follows_the_power_mode(tmp_path):
    assert ack_timeout_for(None) == ACK_TIMEOUT_SECONDS == ack_timeout_for(1) == ack_timeout_for("x")
    assert ack_timeout_for(3) == 60 and ack_timeout_for(5) == 90
    journal = CommandQueue(tmp_path / "j.db")
    r = journal.enqueue("Company_1", 2, 4, "GOSTM", 0, now=NOW, delivery="now")
    item = journal.claim_immediate(r["request_id"], NOW, ack_timeout=ack_timeout_for(5))
    assert item["ack_deadline"] == NOW + 90
    r2 = journal.enqueue("Company_1", 3, 4, "GOSTM", 0, now=NOW, delivery="now")
    assert journal.claim_immediate(r2["request_id"], NOW)["ack_deadline"] == NOW + ACK_TIMEOUT_SECONDS


def test_power_mode_comes_from_the_latest_uplink(supervisor):
    rt = supervisor.app.state.runtime
    rt.ingest.on_plaintext("wiot/Company_1/Region_1/2/status", status(mode=5))
    assert rt.telemetry.latest_power_mode("Company_1", "Region_1", 2) == 5
    assert rt.commands._ack_timeout("Company_1", "Region_1", 2) == 90
    assert rt.commands._ack_timeout("Company_1", "Region_1", 9) == ACK_TIMEOUT_SECONDS   # never seen


# ----------------------------------------------------------------- point 14
def test_auto_delivery_queues_when_the_node_is_probably_asleep(supervisor, monkeypatch):
    rt = supervisor.app.state.runtime
    monkeypatch.setattr(rt.commands.broker, "is_ready", lambda: True)
    rt.commands.risk = lambda c, r, n, t: {"tier": "UNLIKELY", "probability": 0.08}
    res = rt.commands.submit(CommandRequest(company="Company_1", region="Region_1", node_id=2, cmd_type="GOSTM",
                                            delivery="auto"), actor="op")
    assert res["queued"] and res["delivery"] == "next_wake"
    assert res["auto"]["tier"] == "UNLIKELY" and res["auto"]["chosen"] == "next_wake"
    rt.commands.risk = lambda c, r, n, t: {"tier": "LIKELY", "probability": 0.9}
    req = CommandRequest(company="Company_1", region="Region_1", node_id=2, cmd_type="GOSTM", delivery="auto")
    assert rt.commands._auto_delivery(req)[0] == "now"
    rt.commands.risk = lambda *a: (_ for _ in ()).throw(LookupError("model not trained"))
    assert rt.commands._auto_delivery(req)[0] == "now"                      # no estimate: as before
    monkeypatch.setattr(rt.commands.broker, "is_ready", lambda: False)
    assert rt.commands._auto_delivery(req)[0] == "next_wake"                # broker down: queue
    bcast = CommandRequest(company="Company_1", region="Region_1", node_id=1, cmd_type="SRATE", cmd_data=60,
                           delivery="auto", broadcast=True)
    assert rt.commands._auto_delivery(bcast)[0] == "now"


def test_api_accepts_auto_delivery(supervisor):
    r = supervisor.post("/api/v2/commands", json={"company": "Company_1", "region": "Region_1", "node_id": 2,
                                                  "cmd_type": "GOSTM", "delivery": "auto"})
    assert r.status_code == 202 and r.json()["delivery"] == "next_wake"     # broker down in tests: queued


# ----------------------------------------------------------------- point 12
def test_clock_sync_queues_stime_for_a_node_whose_clock_is_not_set(supervisor):
    rt = supervisor.app.state.runtime
    rt.ingest.on_plaintext("wiot/Company_1/Region_1/2/status", status(rtc=False, ts=0))
    rows = [r for r in journal_rows(rt) if r["cmd_type"] == "STIME"]
    assert len(rows) == 1 and rows[0]["delivery"] == "next_wake" and rows[0]["actor"] == "system:clock-sync"
    rt.ingest.on_plaintext("wiot/Company_1/Region_1/2/status", status(rtc=False, ts=0))
    assert len([r for r in journal_rows(rt) if r["cmd_type"] == "STIME"]) == 1   # pending one is enough


def test_clock_sync_detects_a_clock_running_ahead(supervisor):
    rt = supervisor.app.state.runtime
    for _ in range(3):
        rt.ingest.on_plaintext("wiot/Company_1/Region_1/3/status", status(node=3, ts=int(time.time()) + 900))
    rows = [r for r in journal_rows(rt, node=3) if r["cmd_type"] == "STIME"]
    assert len(rows) == 1


class FakeCommands:
    def __init__(self, transfer=None):
        self.submitted, self.flash_transfer = [], (lambda c, r, n, now: transfer)

    def has_active(self, *a):
        return False

    def submit(self, req, actor):
        self.submitted.append((req, actor))
        return {"request_id": len(self.submitted)}


def clock(transfer=None, drift=120):
    cmds = FakeCommands(transfer)
    s = SimpleNamespace(clock_sync=True, clock_sync_drift_s=drift, clock_sync_min_interval_s=6 * 3600)
    return ClockSync(s, cmds), cmds


def test_clock_sync_tolerates_store_and_forward_but_catches_a_lagging_clock():
    sync, cmds = clock()
    t = NOW
    for delay in (95, 30, 236, 12, 180, 60):          # stored samples arrive late; one is nearly fresh
        t += 120
        assert sync.observe("C", "R", 2, t - delay, True, t) is None
    assert cmds.submitted == []
    late, lcmds = clock()
    t = NOW
    for delay in (7200, 7300, 7250):                   # the node clock is two hours behind
        t += 120
        decision = late.observe("C", "R", 2, t - delay, True, t)
    assert decision["reason"] == "clock_behind" and len(lcmds.submitted) == 1
    assert lcmds.submitted[0][0].cmd_type == "STIME" and lcmds.submitted[0][0].delivery == "next_wake"
    for i in range(3):                                 # rate limit: nothing new within the interval
        assert late.observe("C", "R", 2, t + 600 * i - 7200, True, t + 600 * i) is None


def test_clock_sync_waits_while_a_flash_download_runs():
    sync, cmds = clock(transfer={"request": 7})
    assert sync.observe("C", "R", 2, 0, False, NOW) is None and cmds.submitted == []


# ------------------------------------------------------------ points 18, 19
def test_command_the_server_did_not_send_raises_an_event_alert(supervisor):
    rt = supervisor.app.state.runtime
    own = rt.commands.journal.enqueue("Company_1", 2, 4, "GOSTM", 0, delivery="now", region="Region_1")
    echo = pb.CMD_Message(node_id=2, cmd_id=4, cmd_data=0, request_id=own["request_id"]).SerializeToString()
    rt.ingest.on_plaintext("wiot/Company_1/Region_1/2/cmd", echo)
    assert not rt.alert_store.is_open("Company_1", "Region_1", 2, "foreign_command")
    forged = pb.CMD_Message(node_id=2, cmd_id=5, cmd_data=1, request_id=424242).SerializeToString()
    rt.ingest.on_plaintext("wiot/Company_1/Region_1/2/cmd", forged)
    rt.ingest.on_plaintext("wiot/Company_1/Region_1/2/cmd", forged)
    alert = rt.alert_store.get_open("Company_1", "Region_1", 2, "foreign_command")
    assert alert["severity"] == "critical" and alert["details"]["cmd"] == "VALVE" and alert["details"]["events"] == 2


def test_old_status_received_again_after_newer_data_is_flagged_and_not_processed(supervisor):
    rt = supervisor.app.state.runtime
    now = int(time.time())
    old, new = status(node=4, ts=now - 300), status(node=4, ts=now - 60)
    for frame in (old, new):
        rt.ingest.on_plaintext("wiot/Company_1/Region_1/4/status", frame)
    count = lambda: rt.telemetry.query_messages("Company_1", "Region_1", node_id=4, msg_type="Status")[1]
    before = count()
    assert before == 2
    rt.ingest.on_plaintext("wiot/Company_1/Region_1/4/status", old)        # replay of the older message
    assert count() == before
    assert rt.alert_store.is_open("Company_1", "Region_1", 4, "possible_replay")
    rt.ingest.on_plaintext("wiot/Company_1/Region_1/4/status", new)        # repeat of the newest: a duplicate
    assert count() == before + 1


def test_event_alerts_resolve_after_a_quiet_day(tmp_path):
    store = AlertStore(tmp_path / "a.db")
    store.init_schema()
    hub = SimpleNamespace(events=[], publish=lambda kind, data, company=None: hub.events.append(data))
    mon = AlertMonitor(SimpleNamespace(), SimpleNamespace(), hub, lambda: [], store)
    mon.record_event("Company_1", "Region_1", 2, "foreign_command", {"cmd": "VALVE"}, now=NOW)
    mon.record_event("Company_1", "Region_1", 2, "foreign_command", {"cmd": "VALVE"}, now=NOW + 100)
    assert len(hub.events) == 1                                            # opened once
    assert mon._check_events("Company_1", NOW + 100 + EVENT_QUIET_S - 1) == []
    fired = mon._check_events("Company_1", NOW + 100 + EVENT_QUIET_S)
    assert fired[0]["kind"] == "foreign_command_resolved"


# ------------------------------------------------------------------ point 33
def r(t, valve, flow, valid=True, meter=True):
    return {"t": NOW + t, "valve": valve, "flow": flow, "flow_valid": valid, "meter": meter}


def test_valve_flow_rules():
    leak = [r(i * 300, 0, 3.2) for i in range(5)]
    blocked = [r(i * 300, 1, 0.0) for i in range(5)]
    assert valve_flow_verdict(leak) == "leak" and valve_flow_verdict(blocked) == "no_flow"
    assert valve_flow_verdict([r(0, 1, 40), r(300, 1, 41), r(900, 1, 39)]) == "normal"
    assert valve_flow_verdict([r(0, 0, 3), r(300, 0, 3), r(600, 0, 3)]) is None    # under 15 minutes
    assert valve_flow_verdict([r(i * 300, 0, 3, meter=False) for i in range(5)]) is None
    assert valve_flow_verdict([r(0, 0, 3), r(300, 0, 0.1), r(900, 0, 3)]) == "normal"  # drained, then flow


class FakeTelemetry:
    def __init__(self, readings, seen_open=False):
        self.readings, self.seen_open = readings, seen_open

    def flow_readings(self, *a):
        return {}

    def valve_flow_readings(self, *a):
        return self.readings

    def valve_seen_open(self, *a):
        return self.seen_open


def monitor(tmp_path, telemetry, node_type="control", night=""):
    tmp_path.mkdir(parents=True, exist_ok=True)
    store = AlertStore(tmp_path / "a.db")
    store.init_schema()
    hub = SimpleNamespace(publish=lambda *a, **k: None)
    org = SimpleNamespace(node_type=lambda c, rg, n: node_type, timezone=lambda c: "Africa/Cairo")
    return AlertMonitor(telemetry, org, hub, lambda: ["Company_1"], store,
                        settings=SimpleNamespace(night_flow_hours=night)), store


def test_leak_and_no_flow_alerts_only_on_valve_nodes(tmp_path):
    node = {"node_id": 2, "link_state": "online", "timestamp": NOW, "battery_voltage": 3.9}
    mon, store = monitor(tmp_path, FakeTelemetry([r(i * 300, 0, 3.2) for i in range(5)]))
    mon._check_node("Company_1", "Region_1", node, NOW + 1500)
    assert store.get_open("Company_1", "Region_1", 2, "leak_suspected")["severity"] == "critical"
    mon.telemetry = FakeTelemetry([r(i * 300, 0, 0.0) for i in range(5)])
    mon._check_node("Company_1", "Region_1", node, NOW + 1600)
    assert not store.is_open("Company_1", "Region_1", 2, "leak_suspected")
    mon.telemetry = FakeTelemetry([r(i * 300, 1, 0.0) for i in range(5)])
    mon._check_node("Company_1", "Region_1", node, NOW + 1700)
    assert store.is_open("Company_1", "Region_1", 2, "no_flow")
    meter_only, store2 = monitor(tmp_path / "m", FakeTelemetry([r(i * 300, 0, 3.2) for i in range(5)]),
                                 node_type="monitoring")
    meter_only._check_node("Company_1", "Region_1", node, NOW + 1500)
    assert not store2.is_open("Company_1", "Region_1", 2, "leak_suspected")   # no valve: no leak rule


def test_night_flow_window():
    assert night_hours("00-04") == (0, 4) and night_hours("22-05") == (22, 5)
    assert night_hours("") is None and night_hours("25-03") is None and night_hours("x") is None
    assert in_night(2, (0, 4)) and not in_night(4, (0, 4)) and in_night(23, (22, 5)) and in_night(3, (22, 5))


# ------------------------------------------------------------- points 37, 45
def test_weather_warnings_and_their_alerts(settings, tmp_path):
    farm = FarmService(settings, SimpleNamespace(), SimpleNamespace(), SimpleNamespace())
    wx = {"available": True, "daily": [{"date": "2027-01-10", "tmin": 1.0, "tmax": 19.0},
                                       {"date": "2027-01-11", "tmin": 6.0, "tmax": 41.5},
                                       {"date": "2027-01-12", "tmin": -3.0, "tmax": 12.0}]}
    items = farm._weather_items(wx)
    assert [(i["kind"], i["date"]) for i in items] == [("frost_risk", "2027-01-10"), ("heat_stress", "2027-01-11")]
    assert farm._weather_items({"available": False}) == []
    mon, store = monitor(tmp_path, FakeTelemetry([]))
    mon.farm = SimpleNamespace(weather_warnings=lambda c: {"region": "Region_1", "site": "Farm", "items": items})
    mon._check_weather("Company_1", NOW)
    assert store.is_open("Company_1", "Region_1", 0, "frost_risk") and store.is_open("Company_1", "Region_1", 0,
                                                                                      "heat_stress")
    mon.farm = SimpleNamespace(weather_warnings=lambda c: {"region": "Region_1", "site": "Farm", "items": []})
    mon._check_weather("Company_1", NOW + 3600)
    assert not store.is_open("Company_1", "Region_1", 0, "frost_risk")


def test_irrigation_index(settings):
    from wiot.services.farm import Zone
    zone = Zone(id="p1", name="Pivot 1", crop="wheat", center=(22.25, 28.72), radius_m=100, node_id=2)
    area_ha = zone.area_ha()                              # ~3.14 ha
    past = [{"date": f"2027-01-0{d}", "et0_mm": 4.0, "rain_mm": 0} for d in range(1, 8)]
    need_mm = 7 * 4.0 * 1.15                              # wheat Kc 1.15
    per_day_m3 = need_mm * 1.1 * area_ha * 10 / 7         # 10 % over need
    rows = [{"period_key": d["date"], "volume_m3": per_day_m3} for d in past]
    tel = SimpleNamespace(consumption=lambda c, rg, period=None, node_id=None: rows)
    farm = FarmService(settings, SimpleNamespace(), tel, SimpleNamespace())
    idx = farm.irrigation_index("Company_1", zone, {"available": True, "past_daily": past})
    assert idx["status"] == "on_target" and idx["ratio"] == pytest.approx(1.1, abs=0.01)
    tel.consumption = lambda *a, **k: rows[:3]
    assert farm.irrigation_index("Company_1", zone, {"available": True, "past_daily": past})["status"] == \
        "insufficient_data"
    tel.consumption = lambda *a, **k: [{**x, "volume_m3": x["volume_m3"] / 2} for x in rows]
    assert farm.irrigation_index("Company_1", zone, {"available": True, "past_daily": past})["status"] == "under"
    assert farm.irrigation_index("Company_1", zone, {"available": False}) is None


def test_weather_client_separates_past_days_and_reads_rain_from_now(settings, monkeypatch):
    settings.weather_enabled = True
    hours = [f"2027-01-0{d}T{h:02d}:00" for d in (1, 2, 3) for h in range(24)]
    rain = [0.0] * 24 + [0.0] * 14 + [0.5] * 10 + [1.0] * 24              # rain from 2 Jan 14:00
    body = {"current": {"time": "2027-01-02T14:15", "temperature_2m": 20, "weather_code": 0, "is_day": 1},
            "hourly": {"time": hours, "precipitation": rain},
            "daily": {"time": ["2027-01-01", "2027-01-02", "2027-01-03"], "temperature_2m_max": [20, 21, 22],
                      "temperature_2m_min": [5, 6, 7], "precipitation_sum": [0, 5, 24],
                      "et0_fao_evapotranspiration": [3.1, 3.2, 3.3], "wind_speed_10m_max": [10, 10, 10],
                      "weather_code": [0, 0, 0]}}
    monkeypatch.setattr("wiot.services.farm.urllib.request.urlopen",
                        lambda req, timeout: io.BytesIO(json.dumps(body).encode()))
    wx = WeatherClient(settings).get(22.25, 28.72)
    assert [d["date"] for d in wx["past_daily"]] == ["2027-01-01"]
    assert wx["daily"][0]["date"] == "2027-01-02" and wx["et0_today_mm"] == 3.2
    assert wx["rain_next_24h_mm"] == pytest.approx(10 * 0.5 + 14 * 1.0)


# ------------------------------------------------------------------- point 6
def test_backup_is_encrypted_verified_and_restorable(supervisor, tmp_path):
    from wiot.storage.backup import create_backup, restore_backup, verify_backup
    rt = supervisor.app.state.runtime
    rt.ingest.on_plaintext("wiot/Company_1/Region_1/2/status", status())
    out = create_backup(rt.settings, tmp_path / "bk", password="correct horse", keep=2)
    assert out["encrypted"] and out["file"].endswith(".wbk") and out["databases"] >= 3
    assert out["integrity_problems"] == []
    assert b"CREATE TABLE" not in open(out["file"], "rb").read()          # nothing readable without the key
    ok = verify_backup(out["file"], "correct horse")
    assert ok["ok"] and ok["databases"] == out["databases"]
    with pytest.raises(ValueError, match="Wrong password"):
        verify_backup(out["file"], "wrong")
    damaged = tmp_path / "damaged.wbk"
    blob = bytearray(open(out["file"], "rb").read())
    blob[len(blob) // 2] ^= 0xFF
    damaged.write_bytes(bytes(blob))
    with pytest.raises(ValueError):
        verify_backup(damaged, "correct horse")
    truncated = tmp_path / "truncated.wbk"
    truncated.write_bytes(bytes(blob[: len(blob) // 3]))
    with pytest.raises(ValueError):
        verify_backup(truncated, "correct horse")
    restored = restore_backup(out["file"], tmp_path / "restored", "correct horse")
    assert (tmp_path / "restored" / "iot_data.db").exists() and restored["ok"]
    with pytest.raises(ValueError, match="not empty"):
        restore_backup(out["file"], tmp_path / "restored", "correct horse")
    for _ in range(3):
        time.sleep(1.05)
        create_backup(rt.settings, tmp_path / "bk", password=None, keep=2)
    assert len(list((tmp_path / "bk").iterdir())) == 2                        # pruned to the newest two


def test_tls_settings_come_in_pairs_and_force_secure_cookies(tmp_path):
    from wiot.config import Settings
    with pytest.raises(ValueError):
        Settings(_env_file=None, data_dir=tmp_path, tls_certfile=tmp_path / "c.pem")
    s = Settings(_env_file=None, data_dir=tmp_path, tls_certfile=tmp_path / "c.pem", tls_keyfile=tmp_path / "k.pem")
    assert s.cookie_secure


# ------------------------------------------------------------------- point 3
GATEWAY_LOG = """11/9/2026 12:38:10.900 [RX] - [INFO] rx_complete source=2 message=77 type=Telemetry fragments=3 bytes=74 logical_crc=verified
11/9/2026 12:38:11.300 [RX] - [INFO] tx topic=wiot/Company_1/Region_1/2/data bytes=81 queue_write=1 modem_write=1 elapsed_ms=301
11/9/2026 12:38:11.520 [RX] - [INFO] command_rx request=91 command=HISTORY_ACK target=2 scope=node
11/9/2026 12:38:11.530 [RX] - [INFO] downlink_wake_begin mode=1 probe_then_command bytes=33
continuation line without a time stamp
11/9/2026 12:38:12.100 [RX] - [INFO] downlink_wake_complete probe=1 command=1 mode_restored=0 node_execution=unconfirmed
11/9/2026 12:38:12.110 [RX] - [INFO] command_rx request=92 command=GOSTM target=3 scope=node
11/9/2026 12:50:00.000 [RX] - [INFO] command_rx request=93 command=HISTORY_ACK target=2 scope=node
"""


def test_flash_timeline_reads_the_gateway_serial_log(settings, tmp_path):
    from zoneinfo import ZoneInfo
    from wiot.tools.flash_timeline import format_text, gateway_events, parse_local, timeline
    log = tmp_path / "gw.txt"
    log.write_text(GATEWAY_LOG, encoding="utf-8")
    tz = ZoneInfo("Africa/Cairo")
    ev = gateway_events(log, 2, tz, parse_local("2026-11-09 12:37", tz), parse_local("2026-11-09 12:45", tz))
    whats = [e["what"] for e in ev]
    assert whats[0].startswith("radio message received: Telemetry from node 2")
    assert "command received over MQTT: HISTORY_ACK request 91" in whats
    assert any("probe sent, command sent" in w for w in whats)
    assert not any("GOSTM" in w for w in whats) and not any("request 93" in w for w in whats)  # other node / window
    out = timeline(settings, "Company_1", "Region_1", 2, "2026-11-09 12:37", "2026-11-09 12:45", log)
    assert out["summary"]["history_acks_at_gateway"] == 1 and out["summary"]["downlinks_transmitted"] == 1
    assert "Flash download timeline" in format_text(out)
