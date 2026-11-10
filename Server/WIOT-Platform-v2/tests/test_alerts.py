"""Persistent fleet alerts: silent nodes (including at startup), low battery, unstable flow."""
from __future__ import annotations

import time

from conftest import PASSWORDS, login
from wiot.protocol import messages_pb2
from wiot.services.alerts import AlertMonitor, flow_jumps, flow_verdict
from wiot.storage.alert_store import AlertStore

API = "/api/v2"
NODE2_PATTERN = [80, 600, 4800, 10, 288, 36, 288, 80, 600, 4800, 10, 80]   # Company_1 node 2, 9 Nov
T0 = 1_800_000_000


def series(values, start=T0, step=30):
    return [(start + i * step, float(v)) for i, v in enumerate(values)]


def status(node: int, flow: float = 0.0, battery: float = 3.9) -> bytes:
    return messages_pb2.Status_Message(
        node_id=node, sensor_id=1, timestamp=int(time.time()), battery_voltage=battery, sensor_mask=3,
        active_sensor_count=2, flow_meter_type=1, flow_live_valid=True, rtc_valid=True, flow_period_quality=1,
        flow_rate=flow, node_status=0, power_mode=2, power_state=1).SerializeToString()


# ------------------------------------------------------------------ flow rule
def test_flow_rule_flags_the_node2_cycle():
    unstable, jumps = flow_verdict(series(NODE2_PATTERN))
    assert unstable and len(jumps) >= 6 and max(j["ratio"] for j in jumps) >= 8


def test_flow_rule_ignores_pump_start_stop_and_noise():
    start_stop = [0, 0, 2, 15, 600, 610, 605, 598, 602, 40, 3, 0, 0]       # ramps are one-way
    noisy = [600 + d for d in (0, 12, -9, 15, -14, 3, 8, -11, 6, 0)]
    assert flow_verdict(series(start_stop))[0] is False
    assert flow_verdict(series(noisy)) == (False, [])
    assert flow_verdict(series([600, 4800, 600]))[0] is None              # too few readings to judge
    assert flow_jumps(series([0, 4800, 0.5, 4800])) == []                  # below the floor: pump off


# ------------------------------------------------------------------- store
def test_store_keeps_one_open_alert_per_condition(tmp_path):
    store = AlertStore(tmp_path / "a.db")
    store.init_schema()
    a, created = store.open("Company_1", "Region_1", 2, "node_offline", "critical", {"x": 1}, now=T0)
    b, again = store.open("Company_1", "Region_1", 2, "node_offline", "critical", {"x": 2}, now=T0 + 60)
    assert created and not again and a["id"] == b["id"] and b["details"] == {"x": 2}
    store.acknowledge("Company_1", a["id"], "op", now=T0 + 70)
    assert store.summary("Company_1", now=T0 + 80) == {"open": 1, "critical": 1, "warning": 0,
                                                       "unacknowledged": 0, "resolved_24h": 0}
    assert store.resolve("Company_1", "Region_1", 2, "node_offline", now=T0 + 90)["state"] == "resolved"
    assert store.resolve("Company_1", "Region_1", 2, "node_offline", now=T0 + 91) is None
    c, reopened = store.open("Company_1", "Region_1", 2, "node_offline", "critical", {}, now=T0 + 100)
    assert reopened and c["id"] != a["id"] and c["acknowledged_at"] is None
    assert [x["id"] for x in store.list("Company_1", status="all", since=T0)] == [c["id"], a["id"]]
    assert store.list("Company_2") == []


# ----------------------------------------------------------------- monitor
def _offline(rt, nodes=(5,)):
    real = rt.telemetry.fleet
    rt.telemetry.fleet = lambda c, r: [{**n, "link_state": "offline" if n["node_id"] in nodes else n["link_state"]}
                                       for n in real(c, r)]


def test_node_already_silent_at_startup_is_reported_once(app, supervisor):
    rt = app.state.runtime
    rt.ingest.on_plaintext("wiot/Company_1/Region_1/5/status", status(5))
    _offline(rt)
    fired = rt.alerts.check()                      # first sweep after start: no baseline blind spot
    assert [(a["kind"], a["node_id"]) for a in fired] == [("node_offline", 5)]
    assert rt.alerts.check() == []                 # still silent: no repeat
    restarted = AlertMonitor(rt.telemetry, rt.org, rt.hub, rt.main.company_names, rt.alert_store)
    assert restarted.check() == []                 # a server restart does not re-send it


def test_node_coming_back_resolves_its_alert(app, supervisor):
    rt = app.state.runtime
    rt.ingest.on_plaintext("wiot/Company_1/Region_1/5/status", status(5))
    rt.alerts.check()
    key = ("Company_1", "Region_1", 5)
    rt.alerts.state[key] = "online"
    _offline(rt)
    fired = rt.alerts.check()
    assert any(a["kind"] == "node_offline" and a["node_id"] == 5 for a in fired)
    rt.telemetry.fleet = type(rt.telemetry).fleet.__get__(rt.telemetry)   # node reports again
    back = rt.alerts.check()
    assert [(a["kind"], a["severity"], a["state"]) for a in back] == [("node_online", "info", "resolved")]


def test_low_battery_opens_and_clears_with_hysteresis(app, supervisor):
    rt = app.state.runtime
    rt.ingest.on_plaintext("wiot/Company_1/Region_1/6/status", status(6, battery=3.2))
    assert [a["kind"] for a in rt.alerts.check()] == ["low_battery"]
    rt.ingest.on_plaintext("wiot/Company_1/Region_1/6/status", status(6, battery=3.35))
    assert rt.alerts.check() == []                 # above 3.3 V but inside the hysteresis band
    rt.ingest.on_plaintext("wiot/Company_1/Region_1/6/status", status(6, battery=3.8))
    assert [a["kind"] for a in rt.alerts.check()] == ["low_battery_resolved"]


def test_unstable_flow_is_flagged_and_cleared(app, supervisor):
    rt = app.state.runtime
    for flow in NODE2_PATTERN:
        rt.ingest.on_plaintext("wiot/Company_1/Region_1/2/status", status(2, flow=flow))
    fired = rt.alerts.check()
    flow_alert = next(a for a in fired if a["kind"] == "flow_unstable")
    assert flow_alert["node_id"] == 2 and flow_alert["details"]["jumps"] >= 6
    assert flow_alert["details"]["example"]["ratio"] >= 8
    rt.telemetry.flow_readings = lambda *a: {"1": series([600 + i for i in range(12)])}   # a clean hour
    assert [a["kind"] for a in rt.alerts.check()] == ["flow_unstable_resolved"]


# --------------------------------------------------------------------- API
def test_alerts_api_lists_and_acknowledges(app, supervisor, client):
    rt = app.state.runtime
    rt.ingest.on_plaintext("wiot/Company_1/Region_1/5/status", status(5))
    _offline(rt)
    rt.alerts.check()
    body = supervisor.get(f"{API}/alerts", params={"company": "Company_1"}).json()
    assert body["summary"]["open"] == 1 and body["summary"]["unacknowledged"] == 1
    alert = body["alerts"][0]
    assert alert["kind"] == "node_offline" and alert["node_id"] == 5
    r = supervisor.post(f"{API}/alerts/{alert['id']}/acknowledge", params={"company": "Company_1"})
    assert r.status_code == 200 and r.json()["acknowledged_by"] == "EgSA_Supervisor"
    assert supervisor.get(f"{API}/alerts", params={"company": "Company_1"}).json()["summary"]["unacknowledged"] == 0
    assert supervisor.post(f"{API}/alerts/999/acknowledge", params={"company": "Company_1"}).status_code == 404
    assert supervisor.get(f"{API}/alerts", params={"company": "Company_2"}).json()["alerts"] == []


def test_monitor_role_reads_alerts_but_cannot_acknowledge(app, client):
    rt = app.state.runtime
    rt.ingest.on_plaintext("wiot/Company_1/Region_1/5/status", status(5))
    _offline(rt)
    rt.alerts.check()
    csrf = login(client, "Super_User", PASSWORDS["WIOT_MONITOR_PASSWORD"])
    alerts = client.get(f"{API}/alerts", params={"company": "Company_1"}).json()["alerts"]
    r = client.post(f"{API}/alerts/{alerts[0]['id']}/acknowledge", params={"company": "Company_1"},
                    headers={"X-CSRF-Token": csrf})
    assert r.status_code == 403
