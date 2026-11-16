"""Crop care and records (R2.5, points 44, 46, 48 and 50).

* **Weather history**: each maintenance cycle stores the farm's daily weather (Open-Meteo: max / min temperature,
  rain, ET0) in ``crop_weather``, so season totals do not depend on the 7-day window of the forecast service.
* **Growing degree days** (point 44): GDD = sum(max(0, (Tmax + Tmin) / 2 - Tbase)) from the planting date, with
  Tmax capped at the crop's upper threshold (method of McMaster & Wilhelm, 1997).
* **Disease and pest risk** (point 44) from the 72-hour hourly forecast, with published rule-of-thumb models:
  potato / tomato late blight (Hutton criteria: two days with Tmin >= 10 °C and >= 6 h of RH >= 90 %), wheat
  yellow rust (night temperature 7-15 °C with >= 6 h RH >= 95 %), grape powdery mildew (Gubler-Thomas: >= 6
  consecutive hours at 21-30 °C on each of the coming days), grape / onion downy mildew (10-10-24 rule) and olive
  fruit fly activity (20-30 °C days; activity stops above 35 °C).
* **Farm diary** (point 46): operations per field (sowing, irrigation, fertiliser, plant protection, harvest,
  other), with product, active ingredient, dose and pre-harvest interval for sprays; a GlobalG.A.P.-style
  traceability report per field and season checks every harvest against the pre-harvest intervals.
* **Yields and water productivity** (point 48): harvest records in kg; water productivity = yield / applied water
  (kg/m³, from the field's flow meter) and yield / ETc.
* **WaPOR** (point 50): FAO WaPOR actual evapotranspiration and interception (AETI) per field and month, from a CSV
  exported from the WaPOR portal or from a configured API endpoint, compared with the water applied and ETc.
"""
from __future__ import annotations

import csv
import io
import json
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from . import agronomy as ag

# base and upper temperature thresholds for growing degree days (°C)
GDD_BASE = {"wheat": (0.0, 30.0), "barley": (0.0, 30.0), "maize": (10.0, 30.0), "potato": (7.0, 30.0),
            "tomato": (10.0, 30.0), "onion": (6.0, 30.0), "sugar beet": (4.0, 30.0), "cotton": (15.5, 32.0),
            "alfalfa": (5.0, 30.0), "citrus": (12.8, 35.0), "olive": (10.0, 35.0), "date palm": (18.0, 40.0),
            "grape": (10.0, 35.0)}
DIARY_TYPES = ("sowing", "irrigation", "fertiliser", "plant_protection", "harvest", "maintenance", "other")


def _run_hours(hours: list[dict], cond) -> int:
    best = cur = 0
    for h in hours:
        cur = cur + 1 if cond(h) else 0
        best = max(best, cur)
    return best


def disease_risks(crop: str | None, hourly: list[dict]) -> list[dict]:
    """Risk indicators for the next three days from the hourly forecast."""
    if not crop or not hourly:
        return []
    days: dict[str, list[dict]] = {}
    for h in hourly:
        if h.get("temp_c") is None:
            continue
        days.setdefault(str(h["time"])[:10], []).append(h)
    out = []

    def add(name, level, why):
        out.append({"risk": name, "level": level, "why": why})

    if crop in ("potato", "tomato"):
        hutton = [d for d, hs in days.items() if min(h["temp_c"] for h in hs) >= 10
                  and sum(1 for h in hs if (h.get("rh") or 0) >= 90) >= 6]
        if len(hutton) >= 2:
            add("Late blight", "high", f"Hutton criteria met on {', '.join(hutton[:3])}: protect with a fungicide")
        elif hutton:
            add("Late blight", "moderate", f"Warm humid day {hutton[0]}; watch for lesions")
    if crop in ("wheat", "barley"):
        rust = [d for d, hs in days.items() if _run_hours([h for h in hs if 7 <= h["temp_c"] <= 15],
                                                            lambda h: (h.get("rh") or 0) >= 95) >= 6]
        if rust:
            add("Yellow (stripe) rust", "high" if len(rust) >= 2 else "moderate",
                f"Cool nights with long leaf wetness on {', '.join(rust[:3])}")
    if crop == "grape":
        gt = [d for d, hs in days.items() if _run_hours(hs, lambda h: 21 <= h["temp_c"] <= 30) >= 6]
        if len(gt) >= 3:
            add("Powdery mildew", "high", "Gubler-Thomas index rising: 3 days with 6 h at 21-30 °C")
        elif gt:
            add("Powdery mildew", "moderate", f"{len(gt)} favourable day(s) in the forecast")
    if crop in ("grape", "onion"):
        rain = sum(h.get("rain_mm") or 0 for h in hourly[:24])
        if rain >= 10 and min(h["temp_c"] for h in hourly[:24] if h.get("temp_c") is not None) >= 10:
            add("Downy mildew", "high", f"10-10-24 rule: {rain:.0f} mm rain above 10 °C in 24 h")
    if crop == "olive":
        tmax = [max(h["temp_c"] for h in hs) for hs in days.values()]
        if tmax and max(tmax) > 35:
            add("Olive fruit fly", "low", "Heat above 35 °C suppresses fly activity")
        elif tmax and sum(1 for t in tmax if 20 <= t <= 30) >= 2:
            add("Olive fruit fly", "moderate", "Mild days (20-30 °C) favour adult activity: check traps")
    return out


def gdd(days: list[dict], crop: str, since: date) -> float:
    base, upper = GDD_BASE.get(crop, (10.0, 30.0))
    total = 0.0
    for d in days:
        if d["date"] < since.isoformat() or d.get("tmax") is None or d.get("tmin") is None:
            continue
        tmax, tmin = min(float(d["tmax"]), upper), max(float(d["tmin"]), base)
        total += max(0.0, (tmax + tmin) / 2 - base)
    return round(total, 1)


class CropCare:
    def __init__(self, main, telemetry, farm, water, org):
        self.main = main
        self.telemetry = telemetry
        self.farm = farm
        self.water = water
        self.org = org

    def init_schema(self) -> None:
        with self.main.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS crop_weather (company TEXT NOT NULL, date TEXT NOT NULL, tmax REAL, tmin REAL,
                    rain_mm REAL, et0_mm REAL, PRIMARY KEY (company, date));
                CREATE TABLE IF NOT EXISTS crop_diary (id INTEGER PRIMARY KEY AUTOINCREMENT, company TEXT NOT NULL,
                    zone_id TEXT NOT NULL, date TEXT NOT NULL, type TEXT NOT NULL, data TEXT NOT NULL DEFAULT '{}',
                    operator TEXT, created_by TEXT NOT NULL, created_at INTEGER NOT NULL);
                CREATE INDEX IF NOT EXISTS crop_diary_by_zone ON crop_diary(company, zone_id, date);
                CREATE TABLE IF NOT EXISTS crop_wapor (company TEXT NOT NULL, zone_id TEXT NOT NULL, month TEXT NOT NULL,
                    aeti_mm REAL NOT NULL, source TEXT NOT NULL, PRIMARY KEY (company, zone_id, month));
            """)

    # ------------------------------------------------------------- weather
    def record_weather(self, company: str) -> int:
        layout = self.farm.store.get(company)
        if layout is None:
            return 0
        wx = self.farm.weather.get(*layout.site.center)
        if not wx.get("available"):
            return 0
        rows = [(company, d["date"], d.get("tmax"), d.get("tmin"), d.get("rain_mm"), d.get("et0_mm"))
                for d in (wx.get("past_daily") or [])]
        with self.main.connect() as db:
            db.executemany("INSERT INTO crop_weather(company, date, tmax, tmin, rain_mm, et0_mm) VALUES(?,?,?,?,?,?) "
                           "ON CONFLICT(company, date) DO UPDATE SET tmax=excluded.tmax, tmin=excluded.tmin, "
                           "rain_mm=excluded.rain_mm, et0_mm=excluded.et0_mm", rows)
        return len(rows)

    def weather_days(self, company: str, since: date) -> list[dict]:
        with self.main.connect() as db:
            return [dict(r) for r in db.execute("SELECT date, tmax, tmin, rain_mm, et0_mm FROM crop_weather WHERE "
                                                "company=? AND date>=? ORDER BY date", (company, since.isoformat()))]

    # ---------------------------------------------------------- field status
    def field_status(self, company: str) -> list[dict]:
        layout = self.farm.store.get(company)
        if layout is None:
            return []
        wx = self.farm.weather.get(*layout.site.center)
        today = self.water._today(company)
        out = []
        for z in layout.zones:
            prof = self.water.profile(company, z.id)
            crop = ag.crop_key(prof.get("crop") or z.crop)
            planting = date.fromisoformat(prof["planting_date"]) if prof.get("planting_date") else today.replace(month=1, day=1)
            days = self.weather_days(company, planting) if crop else []
            out.append({"zone_id": z.id, "name": z.name, "crop": crop, "since": planting.isoformat(),
                        "gdd": gdd(days, crop, planting) if crop else None, "gdd_days": len(days),
                        "gdd_base_c": GDD_BASE.get(crop or "", (None,))[0],
                        "risks": disease_risks(crop, wx.get("hourly") or []) if wx.get("available") else []})
        return out

    # --------------------------------------------------------------- diary
    def add_entry(self, company: str, data: dict, actor: str) -> dict:
        zones = {z.id for z in (self.farm.store.get(company).zones if self.farm.store.get(company) else [])}
        if data.get("zone_id") not in zones:
            raise ValueError("Choose a field")
        if data.get("type") not in DIARY_TYPES:
            raise ValueError("Unknown operation type")
        try:
            day = date.fromisoformat(str(data.get("date")))
        except ValueError as exc:
            raise ValueError("Date must be YYYY-MM-DD") from exc
        detail = {k: data[k] for k in ("product", "active_ingredient", "dose", "unit", "phi_days", "quantity_kg",
                                        "water_m3", "method", "notes", "target", "lot") if data.get(k) not in (None, "")}
        if data["type"] == "plant_protection":
            if not detail.get("product"):
                raise ValueError("Plant protection needs the product name")
            if detail.get("phi_days") is not None and not 0 <= int(detail["phi_days"]) <= 365:
                raise ValueError("Pre-harvest interval must be 0..365 days")
        if data["type"] == "harvest" and detail.get("quantity_kg") is not None and float(detail["quantity_kg"]) < 0:
            raise ValueError("Harvest quantity cannot be negative")
        with self.main.connect() as db:
            entry_id = db.execute("INSERT INTO crop_diary(company, zone_id, date, type, data, operator, created_by, "
                                  "created_at) VALUES(?,?,?,?,?,?,?,?)",
                                  (company, data["zone_id"], day.isoformat(), data["type"], json.dumps(detail),
                                   str(data.get("operator") or actor)[:80], actor, int(time.time()))).lastrowid
        return self.get_entry(company, entry_id)

    def get_entry(self, company: str, entry_id: int) -> dict:
        with self.main.connect() as db:
            r = db.execute("SELECT * FROM crop_diary WHERE id=? AND company=?", (entry_id, company)).fetchone()
        if r is None:
            raise LookupError("Entry not found")
        d = dict(r)
        d.update(json.loads(d.pop("data") or "{}"))
        return d

    def delete_entry(self, company: str, entry_id: int) -> None:
        with self.main.connect() as db:
            if not db.execute("DELETE FROM crop_diary WHERE id=? AND company=?", (entry_id, company)).rowcount:
                raise LookupError("Entry not found")

    def entries(self, company: str, zone_id: str | None = None, start: str | None = None, end: str | None = None) -> list[dict]:
        q, p = "SELECT * FROM crop_diary WHERE company=?", [company]
        if zone_id:
            q += " AND zone_id=?"
            p.append(zone_id)
        if start:
            q += " AND date>=?"
            p.append(start)
        if end:
            q += " AND date<=?"
            p.append(end)
        with self.main.connect() as db:
            rows = [dict(r) for r in db.execute(q + " ORDER BY date DESC, id DESC LIMIT 2000", p)]
        for r in rows:
            r.update(json.loads(r.pop("data") or "{}"))
        return rows

    def traceability(self, company: str, zone_id: str, start: str, end: str) -> dict:
        """GlobalG.A.P.-style record for one field and season: operations, sprays and the PHI check."""
        ops = sorted(self.entries(company, zone_id, start, end), key=lambda r: (r["date"], r["id"]))
        sprays = [o for o in ops if o["type"] == "plant_protection"]
        harvests = [o for o in ops if o["type"] == "harvest"]
        checks = []
        for h in harvests:
            for s in sprays:
                if s["date"] <= h["date"] and s.get("phi_days") is not None:
                    safe_from = (date.fromisoformat(s["date"]) + timedelta(days=int(s["phi_days"]))).isoformat()
                    checks.append({"harvest": h["date"], "spray": s["date"], "product": s.get("product"),
                                   "phi_days": int(s["phi_days"]), "safe_from": safe_from, "ok": h["date"] >= safe_from})
        layout = self.farm.store.get(company)
        zone = next((z for z in (layout.zones if layout else []) if z.id == zone_id), None)
        water = self.water._zone_volume(company, zone, date.fromisoformat(start), date.fromisoformat(end) + timedelta(days=1)) if zone else 0.0
        return {"company": company, "zone_id": zone_id, "field": zone.name if zone else zone_id,
                "area_ha": round(zone.area_ha(), 2) if zone else None, "start": start, "end": end, "operations": ops,
                "phi_checks": checks, "phi_ok": all(c["ok"] for c in checks), "water_m3": round(water, 1),
                "harvest_kg": round(sum(float(h.get("quantity_kg") or 0) for h in harvests), 1)}

    # ----------------------------------------------------- water productivity
    def productivity(self, company: str, year: int | None = None) -> list[dict]:
        layout = self.farm.store.get(company)
        if layout is None:
            return []
        today = self.water._today(company)
        out = []
        for z in layout.zones:
            prof = self.water.profile(company, z.id)
            crop = ag.crop_key(prof.get("crop") or z.crop)
            planting = date.fromisoformat(prof["planting_date"]) if prof.get("planting_date") else date((year or today.year), 1, 1)
            end = today
            if crop and ag.CROPS[crop].stages and prof.get("planting_date"):
                end = min(today, planting + timedelta(days=sum(ag.CROPS[crop].stages) + 30))
            harvests = [e for e in self.entries(company, z.id, planting.isoformat(), end.isoformat()) if e["type"] == "harvest"]
            kg = sum(float(h.get("quantity_kg") or 0) for h in harvests)
            m3 = self.water._zone_volume(company, z, planting, end + timedelta(days=1))
            days = self.weather_days(company, planting)
            etc_mm = 0.0
            if crop:
                for d in days:
                    if d["date"] <= end.isoformat() and d.get("et0_mm") is not None:
                        etc_mm += float(d["et0_mm"]) * ag.crop_stage(crop, planting if prof.get("planting_date") else None,
                                                                    date.fromisoformat(d["date"]))["kc"]
            area = z.area_ha()
            out.append({"zone_id": z.id, "name": z.name, "crop": crop, "from": planting.isoformat(), "to": end.isoformat(),
                        "yield_kg": round(kg, 1), "yield_t_ha": round(kg / 1000 / area, 2) if area and kg else None,
                        "water_m3": round(m3, 1), "wp_kg_m3": round(kg / m3, 2) if m3 and kg else None,
                        "etc_mm": round(etc_mm, 1), "etc_days": len(days),
                        "wp_etc_kg_m3": round(kg / (etc_mm * 10 * area), 2) if etc_mm and area and kg else None})
        return out

    # --------------------------------------------------------------- WaPOR
    def import_wapor_csv(self, company: str, text: str) -> int:
        """CSV with columns field (zone id or name), month (YYYY-MM) and aeti_mm (FAO WaPOR AETI, monthly)."""
        layout = self.farm.store.get(company)
        if layout is None:
            raise ValueError("This company has no farm layout")
        by_name = {z.name.lower(): z.id for z in layout.zones} | {z.id.lower(): z.id for z in layout.zones}
        rows = []
        for i, r in enumerate(csv.DictReader(io.StringIO(text)), start=2):
            key = (r.get("field") or r.get("zone_id") or "").strip().lower()
            zone_id = by_name.get(key)
            month = (r.get("month") or "").strip()[:7]
            try:
                datetime.strptime(month, "%Y-%m")
                aeti = float(r.get("aeti_mm") or r.get("AETI") or "")
            except ValueError as exc:
                raise ValueError(f"Line {i}: month must be YYYY-MM and aeti_mm a number") from exc
            if zone_id is None:
                raise ValueError(f"Line {i}: unknown field '{key}'")
            rows.append((company, zone_id, month, aeti, "csv"))
        if not rows:
            raise ValueError("The file has no rows")
        with self.main.connect() as db:
            db.executemany("INSERT OR REPLACE INTO crop_wapor(company, zone_id, month, aeti_mm, source) VALUES(?,?,?,?,?)", rows)
        return len(rows)

    def wapor_comparison(self, company: str, months: int = 12) -> list[dict]:
        layout = self.farm.store.get(company)
        if layout is None:
            return []
        with self.main.connect() as db:
            rows = [dict(r) for r in db.execute("SELECT zone_id, month, aeti_mm, source FROM crop_wapor WHERE company=? "
                                                "ORDER BY month DESC LIMIT ?", (company, months * max(1, len(layout.zones))))]
        zones = {z.id: z for z in layout.zones}
        out = []
        for r in rows:
            z = zones.get(r["zone_id"])
            if z is None:
                continue
            start = date.fromisoformat(r["month"] + "-01")
            end = (start + timedelta(days=32)).replace(day=1)
            m3 = self.water._zone_volume(company, z, start, end)
            area = z.area_ha()
            applied = m3 / (area * 10) if area else None
            prof = self.water.profile(company, z.id)
            crop = ag.crop_key(prof.get("crop") or z.crop)
            planting = date.fromisoformat(prof["planting_date"]) if prof.get("planting_date") else None
            etc = sum(float(d["et0_mm"] or 0) * (ag.crop_stage(crop, planting, date.fromisoformat(d["date"]))["kc"] if crop else 1.0)
                      for d in self.weather_days(company, start) if d["date"] < end.isoformat())
            out.append({**r, "field": z.name, "applied_mm": round(applied, 1) if applied is not None else None,
                        "etc_mm": round(etc, 1) if etc else None,
                        "ratio_applied_to_aeti": round(applied / r["aeti_mm"], 2) if applied and r["aeti_mm"] else None})
        return out

    def farmer_today(self, company: str, region: str) -> dict:
        """Point 61: one card per field saying what to do today, in plain words."""
        ov = self.farm.overview(company, region)
        if not ov.get("configured"):
            return {"configured": False, "fields": []}
        status = {s["zone_id"]: s for s in self.field_status(company)}
        cards = []
        for z in ov["zones"]:
            risks = status.get(z["id"], {}).get("risks", [])
            if z["status"] in ("offline", "no_data"):
                action, level = "check_device", "warning"
            elif z["status"] == "sensor_fault":
                action, level = "check_sensor", "warning"
            elif z["status"] == "no_probe":
                action, level = "no_probe", "info"
            elif z["status"] == "dry" and not z.get("irrigating"):
                action, level = "irrigate", "action"
            elif z["status"] == "wet" and z.get("irrigating"):
                action, level = "stop", "action"
            elif z.get("irrigating"):
                action, level = "irrigating", "ok"
            else:
                action, level = "nothing", "ok"
            cards.append({"id": z["id"], "name": z["name"], "crop": z.get("crop"), "action": action, "level": level,
                          "moisture": z.get("moisture"), "runtime_min": z.get("runtime_min"), "deficit_mm": z.get("deficit_mm"),
                          "risks": [r for r in risks if r["level"] in ("high", "moderate")],
                          "rain_next_24h_mm": (ov.get("weather") or {}).get("rain_next_24h_mm")})
        tz = ZoneInfo(self.org.timezone(company) if self.org else "Africa/Cairo")
        return {"configured": True, "site": ov["site"]["name"], "date": datetime.now(tz).date().isoformat(),
                "weather": {k: (ov.get("weather") or {}).get("current", {}).get(k) for k in ("temp_c", "label", "icon")},
                "warnings": ov.get("weather_warnings") or [], "fields": cards}
