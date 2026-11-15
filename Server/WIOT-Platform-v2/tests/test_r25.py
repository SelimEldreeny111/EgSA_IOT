"""Release 2.5: crop records, satellite data and regional views (points 44, 46, 48-52, 61, 62)."""
from __future__ import annotations

import io
import json
import time
from datetime import date, timedelta

import pytest

from wiot.services.cropcare import disease_risks, gdd
from wiot.services.farm import FarmLayout

LAYOUT = {
    "site": {"name": "Test farm", "location": "Owainat", "center": [22.25, 28.72], "timezone": "Africa/Cairo"},
    "agronomy": {"root_zone_mm": 300, "application_rate_mm_h": 6.0, "pivot_flow_m3_h": 150},
    "zones": [{"id": "P1", "name": "Pivot 1", "crop": "potato", "center": [22.25, 28.72], "radius_m": 300, "node_id": 2}],
}


@pytest.fixture()
def farm(supervisor):
    supervisor.app.state.runtime.farm.store.put("Company_1", FarmLayout.model_validate(LAYOUT), "test")
    return supervisor


def hours(day: str, temp: float, rh: float, n: int = 24, rain: float = 0.0):
    return [{"time": f"{day}T{h:02d}:00", "temp_c": temp, "rh": rh, "rain_mm": rain} for h in range(n)]


# ------------------------------------------------------------------ point 44
def test_disease_models_and_degree_days():
    humid = hours("2026-12-01", 14, 95) + hours("2026-12-02", 13, 92)
    blight = disease_risks("potato", humid)
    assert blight and blight[0]["risk"] == "Late blight" and blight[0]["level"] == "high"
    assert disease_risks("potato", hours("2026-12-01", 25, 40)) == []
    rust = disease_risks("wheat", hours("2026-12-01", 10, 97))
    assert rust[0]["risk"].startswith("Yellow") and rust[0]["level"] == "moderate"
    mildew = disease_risks("grape", hours("2026-06-01", 25, 50) + hours("2026-06-02", 26, 50) + hours("2026-06-03", 24, 50))
    assert mildew[0]["risk"] == "Powdery mildew" and mildew[0]["level"] == "high"
    days = [{"date": "2026-11-01", "tmax": 30, "tmin": 14}, {"date": "2026-11-02", "tmax": 40, "tmin": 20}]
    assert gdd(days, "maize", date(2026, 11, 1)) == pytest.approx((30 + 14) / 2 - 10 + (30 + 20) / 2 - 10)


def test_weather_history_and_field_status(farm, monkeypatch):
    rt = farm.app.state.runtime
    past = [{"date": (date.today() - timedelta(days=i)).isoformat(), "tmax": 28.0, "tmin": 12.0, "rain_mm": 0, "et0_mm": 5.0}
            for i in range(1, 6)]
    wx = {"available": True, "past_daily": past, "daily": [], "hourly": hours(date.today().isoformat(), 14, 95, 48),
          "rain_next_24h_mm": 0, "current": {}}
    monkeypatch.setattr(rt.farm.weather, "get", lambda lat, lon: wx)
    farm.put("/api/v2/water/fields/P1", params={"company": "Company_1"},
             json={"crop": "potato", "planting_date": (date.today() - timedelta(days=10)).isoformat()})
    assert rt.cropcare.record_weather("Company_1") == 5
    st = farm.get("/api/v2/crop/status", params={"company": "Company_1"}).json()["fields"][0]
    assert st["gdd"] == pytest.approx(5 * ((28 + 12) / 2 - 7)) and st["risks"][0]["risk"] == "Late blight"


# ------------------------------------------------------------- points 46, 48
def test_diary_traceability_phi_check_and_exports(farm):
    rt = farm.app.state.runtime
    add = lambda **kw: farm.post("/api/v2/crop/diary", params={"company": "Company_1"}, json={"zone_id": "P1", **kw})  # noqa: E731
    assert add(date="2026-03-01", type="plant_protection").status_code == 400                    # product required
    assert add(date="2026-03-01", type="plant_protection", product="Ridomil Gold", active_ingredient="metalaxyl-M",
               dose=2.5, unit="kg/ha", phi_days=14).status_code == 201
    assert add(date="2026-03-10", type="harvest", quantity_kg=12000).status_code == 201         # 9 days < PHI 14
    assert add(date="2026-03-20", type="harvest", quantity_kg=30000).status_code == 201
    rec = farm.get("/api/v2/crop/traceability", params={"company": "Company_1", "zone_id": "P1",
                                                         "start": "2026-01-01", "end": "2026-06-30"}).json()
    assert rec["harvest_kg"] == 42000 and rec["phi_ok"] is False
    assert [c["ok"] for c in rec["phi_checks"]] == [False, True]
    x = farm.get("/api/v2/crop/traceability", params={"company": "Company_1", "zone_id": "P1", "start": "2026-01-01",
                                                      "end": "2026-06-30", "format": "xlsx"})
    assert x.content[:2] == b"PK"
    p = farm.get("/api/v2/crop/traceability", params={"company": "Company_1", "zone_id": "P1", "start": "2026-01-01",
                                                      "end": "2026-06-30", "format": "pdf"})
    assert p.content.startswith(b"%PDF") and b"VIOLATION" in p.content
    entries = rt.cropcare.entries("Company_1", "P1")
    assert len(entries) == 3 and entries[0]["date"] == "2026-03-20"


def test_water_productivity(farm):
    rt = farm.app.state.runtime
    today = date.today()
    farm.put("/api/v2/water/fields/P1", params={"company": "Company_1"},
             json={"crop": "potato", "planting_date": (today - timedelta(days=20)).isoformat()})
    with rt.telemetry.connect("Company_1", write=True) as db:
        for i in range(1, 6):
            db.execute("INSERT INTO consumption_periods(node_id, sensor_id, flow_meter_type, period_type, period_key, "
                       "volume_liters, source, quality, measured_at, updated_at, region) VALUES(2,'1',1,'day',?,?,1,1,0,0,'Region_1')",
                       ((today - timedelta(days=i)).isoformat(), 200_000))
    farm.post("/api/v2/crop/diary", params={"company": "Company_1"},
              json={"zone_id": "P1", "date": today.isoformat(), "type": "harvest", "quantity_kg": 5000})
    row = farm.get("/api/v2/crop/productivity", params={"company": "Company_1"}).json()["fields"][0]
    assert row["water_m3"] == 1000 and row["wp_kg_m3"] == 5.0


# ------------------------------------------------------------------ point 50
def test_wapor_csv_import_and_comparison(farm):
    month = date.today().strftime("%Y-%m")
    csv_text = f"field,month,aeti_mm\nPivot 1,{month},112.5\n"
    r = farm.post("/api/v2/crop/wapor/import", params={"company": "Company_1"}, content=csv_text,
                  headers={"Content-Type": "text/csv"})
    assert r.status_code == 200 and r.json()["imported"] == 1
    rows = farm.get("/api/v2/crop/wapor", params={"company": "Company_1"}).json()["rows"]
    assert rows[0]["aeti_mm"] == 112.5 and rows[0]["field"] == "Pivot 1"
    bad = farm.post("/api/v2/crop/wapor/import", params={"company": "Company_1"}, content="field,month,aeti_mm\nX,2026-13,1\n")
    assert bad.status_code == 400


# ------------------------------------------------------------------ point 51
def _synthetic_farm() -> tuple[bytes, tuple]:
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (800, 800), (205, 180, 140))                      # desert
    d = ImageDraw.Draw(img)
    for cx, cy, r in ((200, 200, 120), (520, 230, 100), (380, 560, 140)):
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(70, 140, 55))     # irrigated discs
    buf = io.BytesIO()
    img.save(buf, "PNG")
    # 800 px = 4.0 km -> 5 m per pixel
    south, west = 22.0, 28.0
    north = south + 4000 / 110574
    east = west + 4000 / (111320 * 0.9271838545667874)                       # cos(22.017 deg)
    return buf.getvalue(), (south, west, north, east)


def test_pivot_detection_finds_the_discs(farm):
    image, (s, w, n, e) = _synthetic_farm()
    r = farm.post("/api/v2/satellite/pivots/detect", params={"south": s, "west": w, "north": n, "east": e},
                  content=image, headers={"Content-Type": "image/png"})
    assert r.status_code == 200, r.text
    circles = r.json()["circles"]
    assert len(circles) == 3
    radii = sorted(c["radius_m"] for c in circles)
    for got, want in zip(radii, (500, 600, 700)):
        assert abs(got - want) / want < 0.08
    added = farm.post("/api/v2/satellite/pivots/add", params={"company": "Company_1"}, json={"circles": circles, "crop": "wheat"})
    assert added.json()["added"] == 3
    zones = farm.app.state.runtime.farm.store.get("Company_1").zones
    assert [z.id for z in zones][-3:] == ["AUTO-01", "AUTO-02", "AUTO-03"]


# ------------------------------------------------------------------ point 49
def test_sentinel_ndvi_statistics_are_stored(farm):
    rt = farm.app.state.runtime
    rt.settings.sentinel_client_id = "cid"
    from pydantic import SecretStr
    rt.settings.sentinel_client_secret = SecretStr("sec")
    calls = []

    def fake(method, url, headers, body, timeout=60):
        calls.append(url)
        if url.endswith("/token"):
            return 200, json.dumps({"access_token": "tok", "expires_in": 600}).encode()
        assert headers["Authorization"] == "Bearer tok" and url.endswith("/api/v1/statistics")
        payload = json.loads(body)
        assert payload["input"]["bounds"]["geometry"]["type"] == "Polygon"
        return 200, json.dumps({"data": [
            {"interval": {"from": "2026-11-05T00:00:00Z"}, "outputs": {"ndvi": {"bands": {"B0": {"stats": {
                "min": 0.21, "max": 0.83, "mean": 0.66, "sampleCount": 1000, "noDataCount": 50}}}}}},
            {"interval": {"from": "2026-11-10T00:00:00Z"}, "outputs": {"ndvi": {"bands": {"B0": {"stats": {
                "min": 0.1, "max": 0.2, "mean": 0.15, "sampleCount": 1000, "noDataCount": 900}}}}}}]}).encode()

    rt.satellite.http = fake
    assert rt.satellite.fetch_ndvi("Company_1") == 1                                   # the cloudy pass is dropped
    d = farm.get("/api/v2/satellite/ndvi", params={"company": "Company_1"}).json()
    assert d["latest"]["P1"] == {"date": "2026-11-05", "mean": 0.66} and len(d["history"]) == 1


# ------------------------------------------------------------------ point 52
def test_wiot_sat_passes_and_products(farm):
    rt = farm.app.state.runtime
    now = int(time.time())
    assert farm.post("/api/v2/satellite/passes", json=[{"satellite": "WIOT-SAT", "station": "Cairo", "aos": now + 600,
                                                         "los": now + 1200, "max_elevation": 54.2}]).json()["imported"] == 1
    assert farm.get("/api/v2/satellite/passes").json()["passes"][0]["station"] == "Cairo"
    product = {"satellite": "WIOT-SAT", "pass_id": "P-0001", "received_at": now, "records": [
        {"company": "Company_1", "region": "Region_1", "node_id": 7, "measured_at": now - 3600, "type": "Status",
         "fields": {"battery_voltage": 3.81, "soil_moisture": 24.5, "soil_moisture_temp_valid": 1, "evil": "x"}},
        {"company": "Nope", "node_id": 1, "measured_at": now}]}
    r = farm.post("/api/v2/satellite/products", content=json.dumps(product), headers={"Content-Type": "application/json"})
    assert r.status_code == 200 and r.json() == {"pass_id": "P-0001", "records": 2, "stored": 1, "rejected": 1}
    rows, _ = rt.telemetry.query_messages("Company_1", "Region_1", node_id=7)
    assert rows[0]["time_source"] == "satellite" and rows[0]["soil_moisture"] == 24.5
    again = farm.post("/api/v2/satellite/products", content=json.dumps(product), headers={"Content-Type": "application/json"})
    assert again.status_code == 400
    assert farm.get("/api/v2/satellite/products").json()["products"][0]["pass_id"] == "P-0001"


# --------------------------------------------------------------- points 61, 62
def test_farmer_view_and_page(farm):
    rt = farm.app.state.runtime
    rt.ingest.on_plaintext("wiot/Company_1/Region_1/2/status", __import__("tests.test_r22", fromlist=["status"]).status())
    d = farm.get("/api/v2/farmer/today", params={"company": "Company_1"}).json()
    assert d["configured"] and d["fields"][0]["action"] in ("irrigate", "nothing", "check_sensor", "irrigating", "stop", "check_device")
    page = farm.get("/farmer")
    assert page.status_code == 200 and "farmer.js" in page.text


def test_regional_dashboard_hides_small_areas(farm):
    rt = farm.app.state.runtime
    data = farm.get("/api/v2/regional").json()
    area = data["areas"][0]
    assert area["suppressed"] is True and area["farms"] == 1 and "water_month_m3" not in area
    rt.settings.regional_min_farms = 1
    area = farm.get("/api/v2/regional").json()["areas"][0]
    assert area["suppressed"] is False and area["fields"] == 1 and area["area"].endswith("Owainat")


def test_regional_dashboard_needs_a_global_account(client):
    from conftest import login
    client.headers["X-CSRF-Token"] = login(client, "admin", "Admin-pass-123")
    assert client.get("/api/v2/regional").status_code == 403
