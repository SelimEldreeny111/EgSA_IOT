"""Release 2.4: agronomy and water management (points 34-36, 38-43, 47)."""
from __future__ import annotations

import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from wiot.services import agronomy as ag
from wiot.services.farm import FarmLayout

LAYOUT = {
    "site": {"name": "Test farm", "center": [22.25, 28.72], "timezone": "Africa/Cairo"},
    "agronomy": {"root_zone_mm": 300, "application_rate_mm_h": 6.0, "pivot_flow_m3_h": 150},
    "zones": [
        {"id": "P1", "name": "Pivot 1", "crop": "wheat", "center": [22.25, 28.72], "radius_m": 300, "node_id": 2},
        {"id": "P2", "name": "Pivot 2", "crop": "olive", "center": [22.26, 28.73], "radius_m": 200, "node_id": 3},
    ],
}


@pytest.fixture()
def farm(supervisor):
    rt = supervisor.app.state.runtime
    rt.farm.store.put("Company_1", FarmLayout.model_validate(LAYOUT), "test")
    return supervisor


def add_day_totals(rt, node, days: dict[str, float], company="Company_1"):
    with rt.telemetry.connect(company, write=True) as db:
        for key, m3 in days.items():
            db.execute("INSERT OR REPLACE INTO consumption_periods(node_id, sensor_id, flow_meter_type, period_type, "
                       "period_key, volume_liters, source, quality, measured_at, updated_at, region) "
                       "VALUES(?,?,?,?,?,?,?,?,?,?,?)", (node, "1", 1, "day" if len(key) == 10 else "month", key,
                                                          int(m3 * 1000), 1, 1, int(time.time()), int(time.time()),
                                                          "Region_1"))


# ------------------------------------------------------------------ science
def test_crop_calendar_follows_fao56_kc_curve():
    planting = date(2026, 11, 1)
    assert ag.crop_stage("wheat", planting, planting)["kc"] == 0.70                       # initial
    dev = ag.crop_stage("wheat", planting, planting + timedelta(days=30 + 70))           # half-way development
    assert dev["stage"] == "development" and abs(dev["kc"] - (0.70 + 0.5 * 0.45)) < 1e-3
    assert ag.crop_stage("wheat", planting, planting + timedelta(days=180))["kc"] == 1.15  # mid-season
    late = ag.crop_stage("wheat", planting, planting + timedelta(days=225))
    assert late["stage"] == "late season" and 0.30 < late["kc"] < 1.15
    assert ag.crop_stage("wheat", planting, planting + timedelta(days=300))["stage"] == "harvested"
    assert ag.crop_stage("olive", None, date(2026, 7, 1))["kc"] == 0.70                   # perennial


def test_soil_profile_water_holding():
    s = ag.soil_water({"texture": "sand"}, "wheat")
    assert s["fc"] == 12.0 and s["wp"] == 4.5 and s["root_depth_m"] == 1.5
    assert s["taw_mm"] == pytest.approx(10 * 7.5 * 1.5) and s["raw_mm"] == pytest.approx(0.55 * 112.5, abs=0.1)
    lab = ag.soil_water({"fc": 30, "wp": 14, "root_depth_m": 0.8}, "potato")
    assert lab["taw_mm"] == 128.0 and lab["refill"] == pytest.approx(30 - 0.35 * 16, abs=0.05)
    with pytest.raises(ValueError):
        ag.soil_water({"fc": 10, "wp": 20}, "wheat")


def test_fao29_salinity_and_leaching():
    s = ag.salinity("maize", 3.7, 1.2)         # threshold 1.7 dS/m, slope 12 %
    assert s["yield_potential_pct"] == pytest.approx(100 - 12 * 2.0) and s["status"] == "loss"
    assert s["leaching_requirement"] == pytest.approx(1.2 / (5 * 1.7 - 1.2), abs=1e-3)
    assert ag.salinity("barley", 5.0, None)["status"] == "ok"


def test_deficit_programmes_and_month_windows():
    assert ag.deficit_factor("olive_rdi", date(2026, 7, 15)) == (0.60, "Pit hardening: least sensitive to water stress")
    assert ag.deficit_factor("olive_rdi", date(2026, 12, 15))[0] == 0.70            # window wraps over new year
    assert ag.deficit_factor("olive_rdi", date(2026, 4, 1)) == (1.0, None)
    assert ag.deficit_factor(None, date(2026, 4, 1)) == (1.0, None)


def test_moisture_forecast_and_refill_plan():
    soil = ag.soil_water({"fc": 30, "wp": 12, "root_depth_m": 0.5}, "tomato")       # refill 22.8 %
    days = [{"date": (date(2026, 6, 1) + timedelta(days=i)).isoformat(), "et0_mm": 8.0, "rain_mm": 0} for i in range(7)]
    fc = ag.moisture_forecast(28.0, soil, days, lambda d: 1.15)
    assert fc[0]["moisture"] == pytest.approx(28.0 - 9.2 / 5, abs=0.05)
    plan = ag.refill_plan(fc, soil, 6.0, leaching=0.2)
    assert plan and plan["date"] == "2026-06-03" and plan["gross_mm"] == pytest.approx(plan["net_mm"] / 0.8, abs=0.1)
    rainy = [{**d, "rain_mm": 30} for d in days]
    assert ag.refill_plan(ag.moisture_forecast(28.0, soil, rainy, lambda d: 1.15), soil, 6.0) is None


# ------------------------------------------------------------ field profiles
def test_field_profile_plan_and_farm_advice(farm):
    rt = farm.app.state.runtime
    planting = (date.today() - timedelta(days=200)).isoformat()
    r = farm.put("/api/v2/water/fields/P1", params={"company": "Company_1"}, json={
        "crop": "wheat", "planting_date": planting, "soil": {"texture": "loamy sand"},
        "salinity": {"ecw_dsm": 2.0}})
    assert r.status_code == 200, r.text
    plan = r.json()
    assert plan["stage"]["stage"] == "mid-season" and plan["stage"]["kc"] == 1.15
    assert plan["soil"]["taw_mm"] == pytest.approx(10 * 8 * 1.5) and plan["salinity"]["leaching_requirement"] > 0
    assert farm.put("/api/v2/water/fields/P1", params={"company": "Company_1"}, json={"soil": {"texture": "lava"}}).status_code == 400
    zone = rt.farm.store.get("Company_1").zones[0]
    assert rt.water.kc("Company_1", zone)[0] == 1.15 and rt.water.leaching("Company_1", zone) > 0
    fields = farm.get("/api/v2/water/fields", params={"company": "Company_1"}).json()["fields"]
    assert {f["id"] for f in fields} == {"P1", "P2"}
    assert farm.get("/api/v2/water/catalog").json()["crops"]["olive"]["perennial"] is True


# -------------------------------------------------------------- schedules
def test_schedule_opens_and_closes_the_valve_through_the_journal(farm):
    rt = farm.app.state.runtime
    tz = ZoneInfo("Africa/Cairo")
    now = datetime.now(tz).replace(second=0, microsecond=0)
    sch = farm.post("/api/v2/water/schedules", params={"company": "Company_1"}, json={
        "name": "Morning", "zone_id": "P1", "days": [now.weekday()], "start": now.strftime("%H:%M"), "duration_min": 30})
    assert sch.status_code == 201, sch.text
    assert sch.json()["next_runs"]
    t0 = int(now.timestamp()) + 60
    assert rt.water.run_schedules("Company_1", t0) == [f"open {sch.json()['id']}"]
    assert rt.water.run_schedules("Company_1", t0 + 60) == []                      # once per day
    rows = rt.commands.journal.list("Company_1", 2, 10, region="Region_1")
    assert rows[0]["cmd_type"] == "VALVE" and rows[0]["cmd_data"] == 1 and rows[0]["actor"] == "system:schedule"
    assert rt.water.run_schedules("Company_1", int(now.timestamp()) + 31 * 60) == [f"close {sch.json()['id']}"]
    rows = rt.commands.journal.list("Company_1", 2, 10, region="Region_1")
    assert rows[0]["cmd_data"] == 0
    log = farm.get(f"/api/v2/water/schedules/{sch.json()['id']}/log", params={"company": "Company_1"}).json()["log"]
    assert [entry["action"] for entry in log][:2] == ["close", "open"]


def test_schedule_skips_outside_rotation_window_and_on_rain(farm, monkeypatch):
    rt = farm.app.state.runtime
    tz = ZoneInfo("Africa/Cairo")
    now = datetime.now(tz).replace(second=0, microsecond=0)
    off_anchor = (now.date() - timedelta(days=5)).isoformat()     # 5 days on / 5 off: today is an off day
    rot = farm.post("/api/v2/water/rotations", params={"company": "Company_1"}, json={
        "name": "Canal A", "zone_ids": ["P1"], "on_days": 5, "off_days": 5, "anchor_date": off_anchor})
    assert rot.status_code == 201 and rot.json()["window"]["open"] is False
    sch = farm.post("/api/v2/water/schedules", params={"company": "Company_1"}, json={
        "name": "Evening", "zone_id": "P1", "days": [now.weekday()], "start": now.strftime("%H:%M"), "duration_min": 20}).json()
    assert rt.water.run_schedules("Company_1", int(now.timestamp()) + 30) == [f"skip {sch['id']}"]
    assert "rotation" in rt.water.get_item("Company_1", sch["id"])["state"]["last_result"]
    # rain forecast
    farm.delete(f"/api/v2/water/rotations/{rot.json()['id']}", params={"company": "Company_1"})
    monkeypatch.setattr(rt.farm.weather, "get", lambda lat, lon: {"available": True, "rain_next_24h_mm": 12.0, "daily": []})
    with rt.main.connect() as db:
        db.execute("UPDATE water_items SET state='{}' WHERE id=?", (sch["id"],))
    assert rt.water.run_schedules("Company_1", int(now.timestamp()) + 30) == [f"skip {sch['id']}"]
    assert "rain" in rt.water.get_item("Company_1", sch["id"])["state"]["last_result"]


def test_rotation_window_cycle():
    from wiot.services.water import WaterService
    rot = {"on_days": 3, "off_days": 4, "anchor_date": "2026-11-01", "from": "06:00", "to": "18:00"}
    tz = ZoneInfo("Africa/Cairo")
    assert WaterService.rotation_window(rot, datetime(2026, 11, 2, 9, 0, tzinfo=tz))["open"] is True
    assert WaterService.rotation_window(rot, datetime(2026, 11, 2, 20, 0, tzinfo=tz))["open"] is False
    off = WaterService.rotation_window(rot, datetime(2026, 11, 5, 9, 0, tzinfo=tz))
    assert off["open"] is False and off["next_window"] == "2026-11-08 06:00"


# ----------------------------------------------------- quotas, wells, costs
def test_quota_well_and_cost(farm):
    rt = farm.app.state.runtime
    today = rt.water._today("Company_1")
    days = {(today - timedelta(days=i)).isoformat(): 100.0 for i in range(min(today.day, 5))}
    add_day_totals(rt, 2, days)
    q = farm.post("/api/v2/water/quotas", params={"company": "Company_1"}, json={
        "name": "Monthly share", "period": "month", "volume_m3": len(days) * 100 * 1.05}).json()
    assert q["status"]["used_m3"] == len(days) * 100 and q["status"]["status"] == "near"
    w = farm.post("/api/v2/water/wells", params={"company": "Company_1"}, json={
        "name": "Well 1", "node_id": 2, "licence_m3_year": 50_000, "licence_start_month": today.month}).json()
    assert w["status"]["pumped_m3"] == len(days) * 100 and w["status"]["status"] in ("ok", "near")
    farm.put("/api/v2/water/tariffs", params={"company": "Company_1"},
             json={"water_price_m3": 0.5, "energy_price_kwh": 1.5, "pump_kw": 75})
    c = farm.get("/api/v2/water/costs", params={"company": "Company_1", "start": (today - timedelta(days=10)).isoformat()}).json()
    p1 = next(f for f in c["fields"] if f["zone_id"] == "P1")
    hours = len(days) * 100 / 150
    assert p1["water_m3"] == len(days) * 100 and p1["pump_hours"] == pytest.approx(hours, abs=0.1)
    assert p1["total_cost"] == pytest.approx(len(days) * 100 * 0.5 + hours * 75 * 1.5, abs=0.5)
    fired = rt.water.check_alerts(rt.alerts, "Company_1", int(time.time()))
    assert any(f["alert_kind"] == f"quota_{q['id']}" for f in fired)


def test_salinity_alert_from_the_soil_probe(farm):
    rt = farm.app.state.runtime
    farm.put("/api/v2/water/fields/P1", params={"company": "Company_1"}, json={"crop": "maize"})
    rt.telemetry.latest[("Company_1", "Region_1", 2)] = {"soil_moisture_temp_ec_valid": 1, "electrical_conductivity": 3700}
    fired = rt.water.check_alerts(rt.alerts, "Company_1", int(time.time()))
    sal = next(f for f in fired if f["alert_kind"] == "salinity_risk")
    assert sal["details"]["yield_potential_pct"] == pytest.approx(76.0) and sal["severity"] == "warning"


# ---------------------------------------------------------- utility (DMA)
def test_district_water_balance_and_billing_statement(farm):
    rt = farm.app.state.runtime
    month = time.strftime("%Y-%m")
    add_day_totals(rt, 10, {month: 1000.0})
    add_day_totals(rt, 11, {month: 450.0})
    add_day_totals(rt, 12, {month: 380.0})
    now = int(time.time())
    with rt.telemetry.connect("Company_1", write=True) as db:
        for node, a, b in ((11, 10_000_000, 10_450_000), (12, 5_000_000, 5_380_000)):
            for i, liters in enumerate((a, b)):
                db.execute("INSERT INTO meter_samples(received_at, measured_at, time_source, message_type, node_id, "
                           "sensor_id, flow_meter_type, forward_total_liters, flow_live_valid, period_totals_valid, "
                           "cumulative_totals_valid, rtc_valid, period_source, period_quality, alarm_flags, "
                           "sample_fingerprint) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                           (now, now - 3600 + i * 60, "node", "Status", node, "1", 2, liters, 1, 1, 1, 1, 1, 1, 0,
                            f"fp-{node}-{i}"))
    d = farm.post("/api/v2/water/districts", params={"company": "Company_1"}, json={
        "name": "DMA North", "inlet_nodes": [10], "customer_nodes": [11, 12], "customers": {"11": "School"}}).json()
    bal = farm.get(f"/api/v2/water/districts/{d['id']}/balance", params={"company": "Company_1", "month": month}).json()
    assert bal["system_input_m3"] == 1000 and bal["billed_m3"] == 830 and bal["non_revenue_pct"] == 17.0
    school = next(c for c in bal["customers"] if c["node_id"] == 11)
    assert school["customer"] == "School" and school["meter_difference_m3"] == 450.0
    x = farm.get(f"/api/v2/water/districts/{d['id']}/balance", params={"company": "Company_1", "month": month, "format": "xlsx"})
    assert x.status_code == 200 and x.content[:2] == b"PK"


def test_validation_errors(farm):
    bad = farm.post("/api/v2/water/schedules", params={"company": "Company_1"},
                    json={"name": "x", "zone_id": "nope", "days": [1], "start": "06:00", "duration_min": 30})
    assert bad.status_code == 400
    assert farm.post("/api/v2/water/unknown", params={"company": "Company_1"}, json={}).status_code == 404
