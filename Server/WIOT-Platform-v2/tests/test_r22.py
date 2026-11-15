"""Release 2.2: operations and data platform (points 7-11, 15, 16, 32)."""
from __future__ import annotations

import time

from wiot.protocol import messages_pb2 as pb
from wiot.services.commands import CommandRequest
from wiot.storage import rollups
from wiot.storage.telemetry_store import TelemetryStore

NOW = int(time.time())


def telemetry(node=2, ts=None, sampling_ms=60_000, report_ms=300_000, battery=3.9, flow=12.5, wdt=0) -> bytes:
    return pb.Telemetry(node_id=node, timestamp=int(time.time()) if ts is None else ts, sampling_rate=sampling_ms,
                        Transmission_rate=report_ms, battery_voltage=battery, sensor_id=1, flow_rate=flow,
                        flow_meter_type=1, flow_live_valid=True, rtc_valid=True, sample_time_valid=True,
                        sensor_mask=1, active_sensor_count=1, wdt_reset_count=wdt, power_mode=1).SerializeToString()


def status(node=2, ts=None, battery=3.9, flow=10.0, wdt=0) -> bytes:
    return pb.Status_Message(node_id=node, sensor_id=1, timestamp=int(time.time()) if ts is None else ts,
                             battery_voltage=battery, sensor_mask=1, active_sensor_count=1, flow_meter_type=1,
                             flow_live_valid=True, rtc_valid=True, sample_time_valid=True, flow_rate=flow,
                             wdt_reset_count=wdt, power_mode=1).SerializeToString()


def _store_rows(store, company, rows):
    """Write synthetic Status rows directly (node, received_at, measured_at, flow, battery)."""
    with store.connect(company, write=True) as db:
        for node, rx, measured, flow, battery in rows:
            db.execute("INSERT INTO messages(timestamp, type, node_id, flow, battery_voltage, measured_at, "
                       "flow_live_valid, region, rtc_valid) VALUES(?,?,?,?,?,?,1,'Region_1',1)",
                       (rx, "Status", node, flow, battery, measured))


# ------------------------------------------------------------------ point 9
def test_batched_writes_commit_on_flush_and_close(tmp_path):
    store = TelemetryStore(tmp_path / "m", lambda: ["Company_1"], batch_ms=5000)
    store.ensure("Company_1")
    for i in range(5):
        store.save_message(company="Company_1", region="Region_1", received_at=NOW + i,
                           msg_type="Status", node_id=1, sensor_id=1, fields={"flow": float(i), "measured_at": NOW + i})
    assert store.latest[("Company_1", "Region_1", 1)]["flow"] == 4.0          # visible at once in memory
    store.flush()
    rows, total = store.query_messages("Company_1", "Region_1")
    assert total == 5
    store.save_message(company="Company_1", region="Region_1", received_at=NOW + 9,
                       msg_type="Status", node_id=1, sensor_id=1, fields={"flow": 9.0, "measured_at": NOW + 9})
    store.close()
    assert store.query_messages("Company_1", "Region_1")[1] == 6


def test_fleet_cache_is_cleared_by_a_new_message(tmp_path):
    store = TelemetryStore(tmp_path / "m", lambda: ["Company_1"])
    store.ensure("Company_1")
    store.save_message(company="Company_1", region="Region_1", received_at=NOW,
                       msg_type="Status", node_id=1, sensor_id=1, fields={"flow": 1.0, "measured_at": NOW})
    assert len(store.fleet("Company_1", "Region_1")) == 1
    store.save_message(company="Company_1", region="Region_1", received_at=NOW, msg_type="Status", node_id=2,
                       sensor_id=1, fields={"flow": 1.0, "measured_at": NOW})
    assert len(store.fleet("Company_1", "Region_1")) == 2


# ----------------------------------------------------------------- point 10
def test_rollups_summarise_late_samples_and_serve_long_charts(tmp_path):
    store = TelemetryStore(tmp_path / "m", lambda: ["Company_1"])
    store.ensure("Company_1")
    base = (NOW // 86400 - 20) * 86400
    rows = [(1, base + h * 3600 + 60, base + h * 3600, float(h % 24), 3.9) for h in range(20 * 24)]
    _store_rows(store, "Company_1", rows)
    first = rollups.update(store, "Company_1")
    assert first["messages"] == len(rows)
    # a store-and-forward sample for an old hour arrives later: that hour is recomputed
    _store_rows(store, "Company_1", [(1, NOW, base + 5 * 3600 + 600, 100.0, 3.9)])
    assert rollups.update(store, "Company_1")["buckets"] == 2               # its hour and its day
    with store.connect("Company_1") as db:
        n, avg, hi = db.execute("SELECT n, avg, hi FROM rollups WHERE grain='hour' AND node_id=1 AND metric='flow' "
                                "AND t=?", (base + 5 * 3600,)).fetchone()
    assert (n, hi) == (2, 100.0) and abs(avg - 52.5) < 1e-9
    pts = store.series("Company_1", "Region_1", 1, "flow", base, base + 20 * 86400, 86400)
    assert len(pts) == 20 and pts[0][4] == 25                               # 24 hourly + the late sample
    assert rollups.series(store, "Company_1", "Region_1", 1, "flow", NOW - 3600, NOW, 60) is None  # short: raw


def test_retention_keeps_a_year_and_only_deletes_summarised_rows(tmp_path):
    store = TelemetryStore(tmp_path / "m", lambda: ["Company_1"])
    store.ensure("Company_1")
    old = NOW - 500 * 86400
    _store_rows(store, "Company_1", [(1, old, old, 1.0, 3.9), (1, NOW, NOW, 2.0, 3.9)])
    assert rollups.apply_retention(store, "Company_1", 30, NOW)["messages_deleted"] == 0   # not summarised yet
    rollups.update(store, "Company_1")
    result = rollups.apply_retention(store, "Company_1", 30, NOW)
    assert result["retention_days"] == 365 and result["messages_deleted"] == 1
    assert rollups.apply_retention(store, "Company_1", 0, NOW)["messages_deleted"] == 0       # 0 = keep forever
    with store.connect("Company_1") as db:
        assert db.execute("SELECT COUNT(*) FROM rollups WHERE t<?", (NOW - 400 * 86400,)).fetchone()[0] > 0


def test_company_retention_is_validated_and_supervisor_only(supervisor):
    r = supervisor.patch("/api/v2/org/companies/Company_1", json={"retention_days": 100})
    assert r.status_code == 400
    r = supervisor.patch("/api/v2/org/companies/Company_1", json={"retention_days": 730})
    assert r.status_code == 200 and r.json()["retention_days"] == 730
    assert supervisor.app.state.runtime.maintenance.retention_days("Company_1") == 730


def test_maintenance_cycle_and_api(supervisor):
    rt = supervisor.app.state.runtime
    rt.ingest.on_plaintext("wiot/Company_1/Region_1/2/status", status())
    r = supervisor.post("/api/v2/system/maintenance/run")
    assert r.status_code == 200, r.text
    body = r.json()
    assert not body["errors"] and sum(x["messages"] for x in body["rollups"]) >= 1


# ------------------------------------------------------------------ points 7, 8
def test_system_health_snapshot(supervisor):
    rt = supervisor.app.state.runtime
    rt.ingest.on_plaintext("wiot/Company_1/Region_1/2/status", status())
    h = supervisor.get("/api/v2/system/health").json()
    names = {c["name"] for c in h["checks"]}
    assert {"Broker", "Ingestion", "Disk", "Backups"} <= names
    assert h["overall"] in ("ok", "info", "warning", "critical")
    c1 = next(c for c in h["companies"] if c["company"] == "Company_1")
    assert c1["last_message_at"] and c1["db_bytes"] > 0


def test_system_health_is_supervisor_only(client):
    from conftest import login
    client.headers["X-CSRF-Token"] = login(client, "admin", "Admin-pass-123")
    assert client.get("/api/v2/system/health").status_code == 403


def test_public_status_page_and_availability(supervisor):
    rt = supervisor.app.state.runtime
    day0 = (NOW // 86400) * 86400
    for k in range(0, 3600, 300):                                      # one hour of samples today
        rt.system.sample(day0 + k, force=True)
    r = supervisor.get("/api/v2/public/status")
    assert r.status_code == 200
    body = r.json()
    assert body["overall"] in ("operational", "degraded", "outage")
    assert "Company_1" not in r.text                                   # no tenant data on the public page
    assert body["days"] and body["days"][-1]["platform"] > 0
    page = supervisor.get("/status")
    assert page.status_code == 200 and "status.js" in page.text


def test_public_status_can_be_turned_off(settings, monkeypatch):
    from fastapi.testclient import TestClient
    from wiot.app import create_app
    settings.status_public = False
    with TestClient(create_app(settings)) as c:
        assert c.get("/api/v2/public/status").status_code == 404
        assert c.get("/status").status_code == 404


# ----------------------------------------------------------------- point 15
def test_config_watch_resends_the_acknowledged_interval_once_a_day(supervisor):
    rt = supervisor.app.state.runtime
    j = rt.commands.journal
    item = rt.commands.submit(CommandRequest(company="Company_1", region="Region_1", node_id=2, cmd_type="STRAN",
                                             cmd_data=300, delivery="next_wake"), actor="operator")
    with j._db() as db:                       # the node acknowledged it on an earlier wake
        db.execute("UPDATE pending_commands SET state='acknowledged', attempts=1, acknowledged_at=? "
                   "WHERE request_id=?", (int(time.time()) - 3600, item["request_id"]))
    rt.confwatch.forget("Company_1", "Region_1", 2)
    rt.ingest.on_plaintext("wiot/Company_1/Region_1/2/data", telemetry(report_ms=300_000))
    assert not any(r["actor"] == "system:config-watch" for r in j.list("Company_1", 2, 50, region="Region_1"))
    rt.ingest.on_plaintext("wiot/Company_1/Region_1/2/data", telemetry(report_ms=900_000))   # reset on site
    auto = [r for r in j.list("Company_1", 2, 50, region="Region_1") if r["actor"] == "system:config-watch"]
    assert len(auto) == 1 and auto[0]["cmd_type"] == "STRAN" and auto[0]["cmd_data"] == 300
    assert auto[0]["delivery"] == "next_wake"
    rt.ingest.on_plaintext("wiot/Company_1/Region_1/2/data", telemetry(report_ms=900_000))
    assert len([r for r in j.list("Company_1", 2, 50, region="Region_1") if r["actor"] == "system:config-watch"]) == 1
    state = rt.confwatch.state("Company_1", "Region_1", 2)
    assert state["report_s"] == {"desired": 300, "reported": 900, "drift": True}
    stored = rt.telemetry.query_messages("Company_1", "Region_1", msg_type="Telemetry")[0][0]
    assert stored["transmission_rate_s"] == 900 and stored["sampling_rate_s"] == 60


def test_config_watch_does_nothing_without_an_acknowledged_value_or_when_off(supervisor):
    rt = supervisor.app.state.runtime
    rt.ingest.on_plaintext("wiot/Company_1/Region_1/3/data", telemetry(node=3, report_ms=900_000))
    assert not rt.commands.journal.list("Company_1", 3, 50, region="Region_1")
    rt.settings.config_watch = False
    assert rt.confwatch.observe("Company_1", "Region_1", 3, 60, 900) == []


# ----------------------------------------------------------------- point 16
def test_node_health_scores(supervisor):
    rt = supervisor.app.state.runtime
    store = rt.telemetry
    now = int(time.time())
    # node 1: healthy, every 5 min for 3 days; node 2: draining battery and watchdog resets
    rows = []
    for k in range(3 * 288):
        t = now - 3 * 86400 + k * 300
        rows.append((1, t, t, 10.0, 3.95))
        rows.append((2, t, t, 10.0, 3.80 - 0.10 * (k / 288)))
    _store_rows(store, "Company_1", rows)
    with store.connect("Company_1", write=True) as db:
        db.execute("UPDATE messages SET wdt_reset_count=CAST((timestamp-?)/86400 AS INTEGER) WHERE node_id=2",
                   (now - 3 * 86400,))
    data = supervisor.get("/api/v2/fleet/health", params={"company": "Company_1"}).json()
    n1 = next(n for n in data["nodes"] if n["node_id"] == 1)
    n2 = next(n for n in data["nodes"] if n["node_id"] == 2)
    assert n1["grade"] == "good" and n1["regularity_24h"] >= 0.95
    assert n2["battery_slope_v_per_day"] < -0.05 and n2["battery_days_left"] < 7
    assert n2["wdt_resets_7d"] >= 2 and n2["score"] < n1["score"] and n2["grade"] != "good"
    assert any("battery" in f for f in n2["findings"])


# ----------------------------------------------------------------- point 11
def test_loadtest_cli_is_registered():
    import wiot.__main__ as cli
    import pytest
    with pytest.raises(SystemExit) as exc:
        cli.main(["loadtest", "--help"])
    assert exc.value.code == 0
