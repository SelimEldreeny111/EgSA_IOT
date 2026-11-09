"""Smart-agriculture layer: layout, advisory, automation, satellite sizing, weather."""
from __future__ import annotations

import io
import json
import sqlite3
import time
from contextlib import closing

import pytest

from conftest import PASSWORDS, login
from wiot.config import PACKAGE_DIR
from wiot.protocol import messages_pb2
from wiot.services.farm import FarmLayout, WeatherClient

DEMO = json.loads((PACKAGE_DIR / "data" / "demo_farm_layout.json").read_text(encoding="utf-8"))


def _layout(**zone_overrides) -> dict:
    data = json.loads(json.dumps(DEMO))
    data["zones"] = data["zones"][:2]
    data["devices"] = data["devices"][:2]
    data["zones"][0].update(zone_overrides)
    return data


def _status(node: int, moisture: float, valve: int = 0) -> bytes:
    return messages_pb2.Status_Message(
        node_id=node, sensor_id=1, timestamp=int(time.time()), battery_voltage=3.9, sensor_mask=3,
        active_sensor_count=2, flow_meter_type=1, flow_live_valid=True, rtc_valid=True, flow_period_quality=1,
        flow_rate=180.0 if valve else 0.0, soil_moisture=moisture, soil_temperature=24.0,
        soil_moisture_temp_valid=1, node_status=valve, power_mode=2, power_state=1).SerializeToString()


def test_demo_layout_is_valid_and_matches_real_pivots():
    layout = FarmLayout.model_validate(DEMO)
    assert len(layout.zones) == 6
    assert all(370 <= z.radius_m <= 400 for z in layout.zones)          # detected centre-pivot radii
    assert 270 < sum(z.area_ha() for z in layout.zones) < 290
    assert layout.gateways[0].backhaul == ["lora", "cellular", "satellite"]


@pytest.mark.parametrize("bad", [
    {"moisture_min": 40, "moisture_max": 30},
    {"radius_m": None},
    {"id": "bad id!"},
])
def test_layout_validation_rejects_bad_zones(bad):
    with pytest.raises(ValueError):
        FarmLayout.model_validate(_layout(**bad))


def test_layout_requires_writer_and_roundtrips(client):
    csrf = login(client, "Super_User", PASSWORDS["WIOT_MONITOR_PASSWORD"])
    r = client.put("/api/v2/farm/layout", params={"company": "Company_1"}, json=_layout(), headers={"X-CSRF-Token": csrf})
    assert r.status_code == 403
    csrf = login(client, "admin", PASSWORDS["WIOT_ADMIN_PASSWORD"])
    r = client.put("/api/v2/farm/layout", params={"company": "Company_1"}, json=_layout(), headers={"X-CSRF-Token": csrf})
    assert r.status_code == 200 and r.json()["zones"] == 2
    got = client.get("/api/v2/farm/layout", params={"company": "Company_1"}).json()
    assert got["layout"]["zones"][0]["id"] == "P-08" and "arcgisonline" in got["map"]["tiles"]
    assert client.get("/api/v2/farm/layout", params={"company": "Company_2"}).status_code == 403


def test_overview_advice_and_alerts(supervisor, app):
    rt = app.state.runtime
    rt.farm.store.put("Company_1", FarmLayout.model_validate(_layout()), "test")
    rt.ingest.on_plaintext("wiot/Company_1/Region_1/1/status", _status(1, 20.0))          # dry (band 26-38)
    rt.ingest.on_plaintext("wiot/Company_1/Region_1/2/status", _status(2, 45.0, valve=1))  # wet + irrigating
    o = supervisor.get("/api/v2/farm/overview", params={"company": "Company_1"}).json()
    z = {x["id"]: x for x in o["zones"]}
    assert z["P-08"]["status"] == "dry" and "Irrigate" in z["P-08"]["advice"]
    assert z["P-08"]["deficit_mm"] == pytest.approx((32 - 20) / 100 * 300, rel=0.01)
    assert z["P-10"]["status"] == "wet" and z["P-10"]["irrigating"] and "stop" in z["P-10"]["advice"]
    assert o["kpis"]["irrigating"] == 1 and o["kpis"]["dry"] == 1
    assert {a["level"] for a in o["alerts"]} == {"warning", "serious"}
    assert o["weather"]["available"] is False


def test_automation_opens_below_band_and_closes_above(client, app):
    rt = app.state.runtime
    rt.farm.store.put("Company_1", FarmLayout.model_validate(_layout(auto_irrigation=True)), "test")

    def journal():
        with closing(sqlite3.connect(rt.settings.command_db)) as db:
            return db.execute("SELECT cmd_type, cmd_data, actor, delivery, state FROM pending_commands "
                              "WHERE company='Company_1' AND node_id=1 ORDER BY id").fetchall()

    rt.ingest.on_plaintext("wiot/Company_1/Region_1/1/status", _status(1, 22.0))
    assert journal()[-1][:4] == ("VALVE", 1, "automation", "next_wake")
    rt.ingest.on_plaintext("wiot/Company_1/Region_1/1/status", _status(1, 21.0))   # rate-limited: no duplicate
    assert len(journal()) == 1
    rt.farm._last_auto.clear()
    rt.ingest.on_plaintext("wiot/Company_1/Region_1/1/status", _status(1, 30.0, valve=1))  # inside band: hold
    assert len(journal()) == 1
    rt.ingest.on_plaintext("wiot/Company_1/Region_1/1/status", _status(1, 41.0, valve=1))  # above band: close
    assert journal()[-1][:3] == ("VALVE", 0, "automation")
    actions = [a["action"] for a in rt.main.list_audit("Company_1")]
    assert "valve_open" in actions and "valve_close" in actions


def test_zone_patch_updates_band(supervisor, app):
    app.state.runtime.farm.store.put("Company_1", FarmLayout.model_validate(_layout()), "test")
    r = supervisor.patch("/api/v2/farm/zones/P-08", params={"company": "Company_1"},
                         json={"moisture_min": 20, "moisture_max": 30, "auto_irrigation": True})
    assert r.status_code == 200 and r.json()["auto_irrigation"] is True
    bad = supervisor.patch("/api/v2/farm/zones/P-08", params={"company": "Company_1"},
                           json={"moisture_min": 35, "moisture_max": 30})
    assert bad.status_code == 400


def test_connectivity_counts_encrypted_frame_sizes(supervisor, app):
    rt = app.state.runtime
    rt.farm.store.put("Company_1", FarmLayout.model_validate(_layout()), "test")
    payload = _status(1, 30.0)
    rt.ingest.on_plaintext("wiot/Company_1/Region_1/1/status", payload)
    c = supervisor.get("/api/v2/farm/connectivity", params={"company": "Company_1", "budget": 48}).json()
    node = next(n for n in c["nodes"] if n["node_id"] == 1)
    assert node["avg_payload_b"] == len(payload)
    assert node["avg_frame_b"] == 17 + 16 * (len(payload) // 16 + 1)
    assert node["path"] == ["lora", "gateway", "cellular"]
    assert any(r["item"].startswith("Compact encrypted frames") and r["ok"] for r in c["readiness"])


def test_weather_client_parses_open_meteo_and_caches(settings, monkeypatch):
    settings.weather_enabled = True
    body = {"current": {"temperature_2m": 24.1, "relative_humidity_2m": 30, "wind_speed_10m": 12,
                        "wind_direction_10m": 10, "precipitation": 0, "weather_code": 1, "is_day": 1},
            "hourly": {"precipitation": [0.2] * 48},
            "daily": {"time": ["2026-11-08"], "temperature_2m_max": [27], "temperature_2m_min": [12],
                      "precipitation_sum": [0], "et0_fao_evapotranspiration": [5.2], "wind_speed_10m_max": [18],
                      "weather_code": [0], "shortwave_radiation_sum": [17.5]}}
    calls = []

    def fake(req, timeout):
        calls.append(req.full_url)
        return io.BytesIO(json.dumps(body).encode())
    monkeypatch.setattr("wiot.services.farm.urllib.request.urlopen", fake)
    w = WeatherClient(settings)
    a = w.get(22.2559, 28.7198)
    b = w.get(22.2561, 28.7201)               # same 0.01 deg cell -> cached
    assert a["available"] and a["et0_today_mm"] == 5.2 and a["rain_next_24h_mm"] == 4.8
    assert a["current"]["label"] == "Mainly clear" and b is a and len(calls) == 1
    assert "et0_fao_evapotranspiration" in calls[0]


def test_public_map_and_csp_allow_tile_host(client):
    m = client.get("/api/v2/public/map").json()
    assert len(m["center"]) == 2 and "{z}" in m["tiles"]
    csp = client.get("/healthz").headers["Content-Security-Policy"]
    assert "https://server.arcgisonline.com" in csp and "script-src 'self'" in csp


def test_offline_node_is_not_reported_as_irrigating_or_watering_today():
    """A node that stopped reporting days ago must not count as irrigating now or as water applied today."""
    from wiot.services.farm import FarmService
    layout = FarmLayout.model_validate(json.loads((PACKAGE_DIR / "data" / "demo_farm_layout.json").read_text(encoding="utf-8")))
    zone = layout.zones[0]
    stale = {"node_status": 1, "flow": 42.0, "flow_live_valid": 1, "flow_day": 787.0, "soil_moisture": 30.0,
             "soil_moisture_temp_valid": 1, "timestamp": int(time.time()) - 11 * 86400, "link_state": "offline"}
    out = FarmService.zone_state(object.__new__(FarmService), zone, stale, layout, {"available": False})
    assert out["irrigating"] is False and out["flow_m3h"] == 0 and out["water_today_m3"] == 0
    assert out["status"] == "offline"
    fresh = {**stale, "timestamp": int(time.time()), "link_state": "online"}
    out = FarmService.zone_state(object.__new__(FarmService), zone, fresh, layout, {"available": False})
    assert out["irrigating"] is True and out["flow_m3h"] == 42.0 and out["water_today_m3"] == 787.0
