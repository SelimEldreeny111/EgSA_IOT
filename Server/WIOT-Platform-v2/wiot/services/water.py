"""Irrigation planning and water accounts (R2.4, points 34-36, 38-43, 47).

Per field (a farm-layout zone) a *profile* adds what the dashboard needs for agronomic advice: crop and planting
date (crop calendar with stage Kc, point 43), soil texture or lab values (point 47), irrigation-water and soil
salinity (FAO-29, point 34) and an optional deficit programme (point 39). From it the service computes the field
plan: today's Kc, water-holding capacity, a 7-day soil-moisture forecast with the date and amount of the next
irrigation (point 41) and the leaching requirement.

Per company:
* **schedules** (point 40): recurring irrigation (days, start time, duration) run through the command journal
  (VALVE open, then close), skipped when rain is forecast, outside the canal rotation window or above quota;
  every run and skip is logged;
* **canal rotations and quotas** (point 35): on/off day cycles with allowed hours; volume quotas per period;
* **wells** (point 36): pumped volume from the well's flow meter against the licence, with a projection;
* **tariffs and cost** (point 38): water price per m³ and pumping energy (kW x hours) per field and season;
* **utility accounting** (point 42): district meter areas (inlet meters vs customer meters) with monthly
  non-revenue water and a billing-grade customer statement (meter readings at period start and end).

Everything is stored in the main database (``water_*`` tables). Alerts (salinity, well licence, quota) are
raised through the alert monitor's company hooks.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import agronomy as ag

log = logging.getLogger(__name__)

SCHEDULE_ACTOR = "system:schedule"
QUOTA_WARN = 0.9


def _now() -> int:
    return int(time.time())


def _hhmm(value: str) -> tuple[int, int]:
    try:
        h, m = (int(x) for x in str(value).split(":"))
    except ValueError as exc:
        raise ValueError("Time must be HH:MM") from exc
    if not (0 <= h < 24 and 0 <= m < 60):
        raise ValueError("Time must be HH:MM")
    return h, m


class WaterService:
    def __init__(self, main, telemetry, farm, org, commands=None, logs=None, audit=None):
        self.main = main
        self.telemetry = telemetry
        self.farm = farm
        self.org = org
        self.commands = commands
        self.logs = logs
        self.audit = audit

    # ================================================================ schema
    def init_schema(self) -> None:
        with self.main.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS water_profiles (company TEXT NOT NULL, zone_id TEXT NOT NULL,
                    data TEXT NOT NULL, updated_at INTEGER NOT NULL, updated_by TEXT, PRIMARY KEY (company, zone_id));
                CREATE TABLE IF NOT EXISTS water_settings (company TEXT PRIMARY KEY, data TEXT NOT NULL,
                    updated_at INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS water_items (id INTEGER PRIMARY KEY AUTOINCREMENT, company TEXT NOT NULL,
                    kind TEXT NOT NULL, data TEXT NOT NULL, state TEXT NOT NULL DEFAULT '{}', enabled INTEGER NOT NULL DEFAULT 1,
                    created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL, updated_by TEXT);
                CREATE INDEX IF NOT EXISTS water_items_by_kind ON water_items(company, kind);
                CREATE TABLE IF NOT EXISTS water_log (id INTEGER PRIMARY KEY AUTOINCREMENT, company TEXT NOT NULL,
                    item_id INTEGER, ts INTEGER NOT NULL, action TEXT NOT NULL, detail TEXT);
                CREATE INDEX IF NOT EXISTS water_log_by_item ON water_log(company, item_id, id DESC);
            """)

    # ========================================================= field profiles
    def _layout(self, company: str):
        layout = self.farm.store.get(company)
        if layout is None:
            raise LookupError("This company has no farm layout yet")
        return layout

    def _zone(self, company: str, zone_id: str):
        zone = next((z for z in self._layout(company).zones if z.id == zone_id), None)
        if zone is None:
            raise LookupError("Unknown field")
        return zone

    def profile(self, company: str, zone_id: str) -> dict:
        with self.main.connect() as db:
            row = db.execute("SELECT data FROM water_profiles WHERE company=? AND zone_id=?", (company, zone_id)).fetchone()
        return json.loads(row[0]) if row else {}

    def set_profile(self, company: str, zone_id: str, data: dict, actor: str) -> dict:
        zone = self._zone(company, zone_id)
        clean: dict = {}
        crop = ag.crop_key(data.get("crop") or zone.crop)
        clean["crop"] = crop
        if data.get("planting_date"):
            try:
                clean["planting_date"] = date.fromisoformat(str(data["planting_date"])).isoformat()
            except ValueError as exc:
                raise ValueError("Planting date must be YYYY-MM-DD") from exc
        soil = data.get("soil") or {}
        if soil.get("texture") and soil["texture"] not in ag.SOILS and soil["texture"] != "custom":
            raise ValueError("Unknown soil texture")
        clean["soil"] = {k: soil[k] for k in ("texture", "fc", "wp", "root_depth_m") if soil.get(k) not in (None, "")}
        ag.soil_water(clean["soil"], crop)                       # validates fc / wp
        if clean["soil"].get("root_depth_m") is not None and not 0.1 <= float(clean["soil"]["root_depth_m"]) <= 4:
            raise ValueError("Root depth must be 0.1..4 m")
        sal = data.get("salinity") or {}
        clean["salinity"] = {}
        for k, lo, hi in (("ecw_dsm", 0, 20), ("ec_factor", 0.1, 10)):
            if sal.get(k) not in (None, ""):
                v = float(sal[k])
                if not lo <= v <= hi:
                    raise ValueError(f"{k} must be {lo}..{hi}")
                clean["salinity"][k] = v
        if data.get("deficit") and data["deficit"] not in ag.DEFICIT:
            raise ValueError("Unknown deficit programme")
        clean["deficit"] = data.get("deficit") or None
        with self.main.connect() as db:
            db.execute("INSERT INTO water_profiles(company, zone_id, data, updated_at, updated_by) VALUES(?,?,?,?,?) "
                       "ON CONFLICT(company, zone_id) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at, "
                       "updated_by=excluded.updated_by", (company, zone_id, json.dumps(clean), _now(), actor))
        return clean

    def _today(self, company: str) -> date:
        tz = self.org.timezone(company) if self.org else "Africa/Cairo"
        return datetime.now(ZoneInfo(tz)).date()

    def kc(self, company: str, zone, day: date | None = None) -> tuple[float, dict]:
        prof = self.profile(company, zone.id)
        crop = ag.crop_key(prof.get("crop") or zone.crop)
        if crop is None:
            return 1.0, {"stage": "unknown"}
        planting = date.fromisoformat(prof["planting_date"]) if prof.get("planting_date") else None
        st = ag.crop_stage(crop, planting, day or self._today(company))
        return st["kc"], st

    def leaching(self, company: str, zone) -> float:
        prof = self.profile(company, zone.id)
        sal = ag.salinity(ag.crop_key(prof.get("crop") or zone.crop), None, (prof.get("salinity") or {}).get("ecw_dsm"))
        return (sal or {}).get("leaching_requirement", 0.0)

    def field_plan(self, company: str, zone_id: str) -> dict:
        layout = self._layout(company)
        zone = self._zone(company, zone_id)
        prof = self.profile(company, zone_id)
        crop = ag.crop_key(prof.get("crop") or zone.crop)
        today = self._today(company)
        planting = date.fromisoformat(prof["planting_date"]) if prof.get("planting_date") else None
        stage = ag.crop_stage(crop, planting, today) if crop else {"stage": "unknown", "kc": 1.0}
        soil = ag.soil_water(prof.get("soil"), crop)
        fleet = {n["node_id"]: n for n in self.telemetry.fleet(company, zone.region)}
        row = fleet.get(zone.node_id) if zone.node_id else None
        theta = None
        ece = None
        if row:
            from .farm import _moisture
            theta, _, _ = _moisture(row)
            if row.get("soil_moisture_temp_ec_valid") and row.get("electrical_conductivity"):
                ece = float(row["electrical_conductivity"]) / 1000 * float((prof.get("salinity") or {}).get("ec_factor", 1.0))
        sal = ag.salinity(crop, ece, (prof.get("salinity") or {}).get("ecw_dsm"))
        factor, phase = ag.deficit_factor(prof.get("deficit"), today)
        wx = self.farm.weather.get(*layout.site.center)
        forecast, plan = [], None
        if theta is not None and wx.get("available"):
            kc_for = (lambda d: ag.crop_stage(crop, planting, d)["kc"]) if crop else (lambda d: 1.0)
            forecast = ag.moisture_forecast(theta, soil, wx.get("daily") or [], kc_for,
                                            lambda d: ag.deficit_factor(prof.get("deficit"), d)[0])
            plan = ag.refill_plan(forecast, soil, layout.agronomy.application_rate_mm_h,
                                  (sal or {}).get("leaching_requirement", 0.0))
        return {"zone": {"id": zone.id, "name": zone.name, "area_ha": round(zone.area_ha(), 2), "node_id": zone.node_id,
                         "region": zone.region, "band": [zone.moisture_min, zone.moisture_max]},
                "profile": prof, "crop": crop, "crop_name": ag.CROPS[crop].name if crop else None,
                "stage": stage, "soil": soil, "suggested_band": [soil["refill"], soil["fc"]],
                "moisture": theta, "salinity": sal,
                "deficit": {"programme": prof.get("deficit"), "factor": factor, "phase": phase,
                            "name": ag.DEFICIT.get(prof.get("deficit") or "", {}).get("name")},
                "forecast": forecast, "next_irrigation": plan,
                "kc_curve": ag.kc_curve(crop, planting, planting or today.replace(month=1, day=1), 365) if crop else [],
                "weather": wx.get("available", False)}

    def catalog(self) -> dict:
        return {"crops": {k: {"name": c.name, "perennial": c.stages is None, "stages": c.stages, "kc": c.kc,
                              "root_m": c.root_m, "p": c.p, "ece_threshold": c.ece_a, "ece_slope": c.ece_b}
                          for k, c in ag.CROPS.items()},
                "soils": {k: {"name": v[0], "fc": v[1] * 100, "wp": v[2] * 100} for k, v in ag.SOILS.items()},
                "deficit": {k: {"name": v["name"], "crop": v["crop"], "windows": v["windows"]} for k, v in ag.DEFICIT.items()}}

    # ============================================================== settings
    def settings_for(self, company: str) -> dict:
        with self.main.connect() as db:
            row = db.execute("SELECT data FROM water_settings WHERE company=?", (company,)).fetchone()
        base = {"currency": "EGP", "water_price_m3": 0.0, "energy_price_kwh": 0.0, "pump_kw": 0.0}
        return {**base, **(json.loads(row[0]) if row else {})}

    def set_settings(self, company: str, data: dict) -> dict:
        cur = self.settings_for(company)
        for k in ("water_price_m3", "energy_price_kwh", "pump_kw"):
            if k in data and data[k] is not None:
                v = float(data[k])
                if not 0 <= v <= 1e6:
                    raise ValueError(f"{k} must be 0 or more")
                cur[k] = v
        if data.get("currency"):
            cur["currency"] = str(data["currency"])[:8].upper()
        with self.main.connect() as db:
            db.execute("INSERT INTO water_settings(company, data, updated_at) VALUES(?,?,?) ON CONFLICT(company) "
                       "DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at", (company, json.dumps(cur), _now()))
        return cur

    # ================================================================= items
    KINDS = ("schedule", "rotation", "quota", "well", "dma")

    def list_items(self, company: str, kind: str) -> list[dict]:
        with self.main.connect() as db:
            rows = db.execute("SELECT * FROM water_items WHERE company=? AND kind=? ORDER BY id", (company, kind)).fetchall()
        return [self._item(r) for r in rows]

    @staticmethod
    def _item(r) -> dict:
        d = dict(r)
        return {"id": d["id"], "company": d["company"], "kind": d["kind"], "enabled": bool(d["enabled"]),
                **json.loads(d["data"]), "state": json.loads(d["state"] or "{}"), "updated_at": d["updated_at"]}

    def get_item(self, company: str, item_id: int) -> dict:
        with self.main.connect() as db:
            r = db.execute("SELECT * FROM water_items WHERE id=? AND company=?", (item_id, company)).fetchone()
        if r is None:
            raise LookupError("Not found")
        return self._item(r)

    def _validate(self, company: str, kind: str, d: dict) -> dict:
        zones = {z.id for z in (self.farm.store.get(company).zones if self.farm.store.get(company) else [])}
        name = str(d.get("name") or "").strip()[:80]
        if not name:
            raise ValueError("Name is required")
        if kind == "schedule":
            if d.get("zone_id") not in zones:
                raise ValueError("Choose a field")
            days = sorted({int(x) for x in d.get("days") or []})
            if not days or any(not 0 <= x <= 6 for x in days):
                raise ValueError("Choose at least one day")
            _hhmm(d.get("start") or "")
            dur = int(d.get("duration_min") or 0)
            if not 5 <= dur <= 1440:
                raise ValueError("Duration must be 5..1440 minutes")
            skip = float(d.get("skip_rain_mm") if d.get("skip_rain_mm") not in (None, "") else 5)
            return {"name": name, "zone_id": d["zone_id"], "days": days, "start": d["start"], "duration_min": dur,
                    "skip_rain_mm": skip, "respect_rotation": bool(d.get("respect_rotation", True)),
                    "respect_quota": bool(d.get("respect_quota", True))}
        if kind == "rotation":
            fields = [z for z in d.get("zone_ids") or [] if z in zones]
            on, off = int(d.get("on_days") or 0), int(d.get("off_days") or 0)
            if not fields or not 1 <= on <= 60 or not 0 <= off <= 60:
                raise ValueError("Choose fields and 1..60 days on, 0..60 days off")
            anchor = date.fromisoformat(str(d.get("anchor_date")))
            h1, h2 = _hhmm(d.get("from") or "00:00"), _hhmm(d.get("to") or "23:59")
            return {"name": name, "zone_ids": fields, "on_days": on, "off_days": off, "anchor_date": anchor.isoformat(),
                    "from": f"{h1[0]:02d}:{h1[1]:02d}", "to": f"{h2[0]:02d}:{h2[1]:02d}"}
        if kind == "quota":
            fields = [z for z in d.get("zone_ids") or [] if z in zones] or None
            period = d.get("period") or "month"
            if period not in ("month", "season", "year"):
                raise ValueError("Period must be month, season or year")
            vol = float(d.get("volume_m3") or 0)
            if vol <= 0:
                raise ValueError("Quota volume must be positive")
            start = date.fromisoformat(str(d.get("start_date") or date.today().replace(day=1).isoformat()))
            return {"name": name, "zone_ids": fields, "period": period, "volume_m3": vol, "start_date": start.isoformat(),
                    "season_days": int(d.get("season_days") or 120)}
        if kind == "well":
            node = int(d.get("node_id") or 0)
            if not 1 <= node <= 65535:
                raise ValueError("Choose the node that measures the well")
            lic = float(d.get("licence_m3_year") or 0)
            if lic <= 0:
                raise ValueError("Licensed volume must be positive")
            month = int(d.get("licence_start_month") or 1)
            return {"name": name, "region": d.get("region") or "Region_1", "node_id": node, "licence_m3_year": lic,
                    "licence_start_month": max(1, min(12, month)), "pump_kw": float(d.get("pump_kw") or 0),
                    "licence_no": str(d.get("licence_no") or "")[:40]}
        if kind == "dma":
            inlets = sorted({int(x) for x in d.get("inlet_nodes") or []})
            customers = sorted({int(x) for x in d.get("customer_nodes") or []} - set(inlets))
            if not inlets or not customers:
                raise ValueError("A district needs at least one inlet meter and one customer meter")
            return {"name": name, "region": d.get("region") or "Region_1", "inlet_nodes": inlets,
                    "customer_nodes": customers, "customers": {str(k): str(v)[:80] for k, v in (d.get("customers") or {}).items()}}
        raise ValueError("Unknown item kind")

    def save_item(self, company: str, kind: str, data: dict, actor: str, item_id: int | None = None) -> dict:
        if kind not in self.KINDS:
            raise ValueError("Unknown item kind")
        clean = self._validate(company, kind, data)
        enabled = int(bool(data.get("enabled", True)))
        with self.main.connect() as db:
            if item_id:
                if not db.execute("UPDATE water_items SET data=?, enabled=?, updated_at=?, updated_by=? WHERE id=? AND "
                                  "company=? AND kind=?", (json.dumps(clean), enabled, _now(), actor, item_id, company,
                                                           kind)).rowcount:
                    raise LookupError("Not found")
            else:
                item_id = db.execute("INSERT INTO water_items(company, kind, data, enabled, created_at, updated_at, "
                                     "updated_by) VALUES(?,?,?,?,?,?,?)", (company, kind, json.dumps(clean), enabled,
                                                                            _now(), _now(), actor)).lastrowid
        return self.get_item(company, item_id)

    def delete_item(self, company: str, item_id: int) -> None:
        with self.main.connect() as db:
            if not db.execute("DELETE FROM water_items WHERE id=? AND company=?", (item_id, company)).rowcount:
                raise LookupError("Not found")

    def _set_state(self, item_id: int, state: dict) -> None:
        with self.main.connect() as db:
            db.execute("UPDATE water_items SET state=? WHERE id=?", (json.dumps(state), item_id))

    def log_event(self, company: str, item_id: int | None, action: str, detail: str) -> None:
        with self.main.connect() as db:
            db.execute("INSERT INTO water_log(company, item_id, ts, action, detail) VALUES(?,?,?,?,?)",
                       (company, item_id, _now(), action, detail[:500]))
        if self.logs is not None:
            self.logs.emit(f"[SCHEDULE] {detail}", company=company)

    def item_log(self, company: str, item_id: int | None = None, limit: int = 100) -> list[dict]:
        q, p = "SELECT item_id, ts, action, detail FROM water_log WHERE company=?", [company]
        if item_id is not None:
            q += " AND item_id=?"
            p.append(item_id)
        with self.main.connect() as db:
            return [dict(r) for r in db.execute(q + " ORDER BY id DESC LIMIT ?", (*p, limit))]

    # ============================================================ volumes
    def day_volumes(self, company: str, region: str, node_id: int, start: date, end: date) -> dict[str, float]:
        """m³ per local day from the node's meter day totals (largest meter per day)."""
        out: dict[str, float] = {}
        for r in self.telemetry.consumption(company, region, period="day", node_id=node_id):
            key = r["period_key"]
            if start.isoformat() <= key < end.isoformat():
                out[key] = max(out.get(key, 0.0), float(r["volume_m3"] or 0))
        return out

    def _zone_volume(self, company: str, zone, start: date, end: date) -> float:
        if not zone.node_id:
            return 0.0
        return sum(self.day_volumes(company, zone.region, zone.node_id, start, end).values())

    # ============================================================ rotation
    @staticmethod
    def rotation_window(rot: dict, now_local: datetime) -> dict:
        cycle = rot["on_days"] + rot["off_days"]
        anchor = date.fromisoformat(rot["anchor_date"])
        n = (now_local.date() - anchor).days
        pos = n % cycle if cycle else 0
        on_day = pos < rot["on_days"]
        h1, h2 = _hhmm(rot["from"]), _hhmm(rot["to"])
        minutes = now_local.hour * 60 + now_local.minute
        in_hours = h1[0] * 60 + h1[1] <= minutes <= h2[0] * 60 + h2[1]
        if on_day:
            next_start = now_local.date() if minutes < h1[0] * 60 + h1[1] else now_local.date() + timedelta(days=1 if pos + 1 < rot["on_days"] else cycle - pos)
        else:
            next_start = now_local.date() + timedelta(days=cycle - pos)
        return {"open": on_day and in_hours, "on_day": on_day, "day_in_cycle": pos + 1, "cycle_days": cycle,
                "next_window": f"{next_start.isoformat()} {rot['from']}"}

    def rotation_for(self, company: str, zone_id: str) -> dict | None:
        return next((r for r in self.list_items(company, "rotation") if r["enabled"] and zone_id in r["zone_ids"]), None)

    # =============================================================== quota
    def quota_status(self, company: str, quota: dict, today: date | None = None) -> dict:
        today = today or self._today(company)
        start = date.fromisoformat(quota["start_date"])
        if quota["period"] == "month":
            start = today.replace(day=1)
            end = (start + timedelta(days=32)).replace(day=1)
        elif quota["period"] == "year":
            start = start.replace(year=today.year if (today.month, today.day) >= (start.month, start.day) else today.year - 1)
            end = start.replace(year=start.year + 1)
        else:
            end = start + timedelta(days=quota.get("season_days", 120))
        layout = self.farm.store.get(company)
        zones = [z for z in (layout.zones if layout else []) if not quota["zone_ids"] or z.id in quota["zone_ids"]]
        used = sum(self._zone_volume(company, z, start, min(end, today + timedelta(days=1))) for z in zones)
        elapsed = max(1, (min(today, end) - start).days + 1)
        total = max(1, (end - start).days)
        projected = used / elapsed * total
        share = used / quota["volume_m3"]
        return {"start": start.isoformat(), "end": end.isoformat(), "used_m3": round(used, 1),
                "quota_m3": quota["volume_m3"], "share": round(share, 3), "projected_m3": round(projected, 1),
                "status": "exceeded" if share >= 1 else "near" if share >= QUOTA_WARN or projected > quota["volume_m3"] else "ok"}

    # ================================================================ wells
    def well_status(self, company: str, well: dict, today: date | None = None) -> dict:
        today = today or self._today(company)
        m = well["licence_start_month"]
        start = date(today.year if today.month >= m else today.year - 1, m, 1)
        end = date(start.year + 1, m, 1)
        days = self.day_volumes(company, well["region"], well["node_id"], start, today + timedelta(days=1))
        used = sum(days.values())
        elapsed = max(1, (today - start).days + 1)
        projected = used / elapsed * (end - start).days
        share = used / well["licence_m3_year"]
        recent = [v for k, v in sorted(days.items())[-30:]]
        return {"year_start": start.isoformat(), "year_end": end.isoformat(), "pumped_m3": round(used, 1),
                "licence_m3": well["licence_m3_year"], "share": round(share, 3), "projected_m3": round(projected, 1),
                "avg_day_m3": round(sum(recent) / len(recent), 1) if recent else 0.0,
                "days_left": round((well["licence_m3_year"] - used) / (sum(recent) / len(recent))) if recent and sum(recent) > 0 and used < well["licence_m3_year"] else None,
                "status": "exceeded" if share >= 1 else "near" if share >= QUOTA_WARN or projected > well["licence_m3_year"] else "ok"}

    # ================================================================= cost
    def field_costs(self, company: str, start: date | None = None, end: date | None = None) -> dict:
        s = self.settings_for(company)
        layout = self._layout(company)
        today = self._today(company)
        flow = layout.agronomy.pivot_flow_m3_h
        rows = []
        for z in layout.zones:
            prof = self.profile(company, z.id)
            f_start = start or (date.fromisoformat(prof["planting_date"]) if prof.get("planting_date") else today.replace(month=1, day=1))
            f_end = end or today + timedelta(days=1)
            m3 = self._zone_volume(company, z, f_start, f_end)
            hours = m3 / flow if flow else 0.0
            kwh = hours * s["pump_kw"]
            water_cost = m3 * s["water_price_m3"]
            energy_cost = kwh * s["energy_price_kwh"]
            area = z.area_ha()
            rows.append({"zone_id": z.id, "name": z.name, "from": f_start.isoformat(), "to": f_end.isoformat(),
                         "water_m3": round(m3, 1), "pump_hours": round(hours, 1), "energy_kwh": round(kwh, 1),
                         "water_cost": round(water_cost, 2), "energy_cost": round(energy_cost, 2),
                         "total_cost": round(water_cost + energy_cost, 2),
                         "cost_per_ha": round((water_cost + energy_cost) / area, 2) if area else None,
                         "mm": round(m3 / (area * 10), 1) if area else None})
        return {"currency": s["currency"], "tariffs": s, "fields": rows,
                "total_cost": round(sum(r["total_cost"] for r in rows), 2), "water_m3": round(sum(r["water_m3"] for r in rows), 1)}

    # ======================================================= utility (DMA)
    def _month_volume(self, company: str, region: str, node_id: int, month: str) -> float | None:
        vals = [r for r in self.telemetry.consumption(company, region, period="month", node_id=node_id)
                if r["period_key"] == month]
        return sum(float(r["volume_m3"] or 0) for r in vals) if vals else None

    def _readings(self, company: str, node_id: int, start: int, end: int) -> tuple[float | None, float | None]:
        with self.telemetry.connect(company) as db:
            first = db.execute("SELECT forward_total_liters FROM meter_samples WHERE node_id=? AND measured_at>=? AND "
                               "measured_at<? AND cumulative_totals_valid=1 ORDER BY measured_at LIMIT 1",
                               (node_id, start, end)).fetchone()
            last = db.execute("SELECT forward_total_liters FROM meter_samples WHERE node_id=? AND measured_at>=? AND "
                              "measured_at<? AND cumulative_totals_valid=1 ORDER BY measured_at DESC LIMIT 1",
                              (node_id, start, end)).fetchone()
        conv = lambda r: round(r[0] / 1000, 3) if r and r[0] is not None else None   # noqa: E731
        return conv(first), conv(last)

    def utility_balance(self, company: str, dma: dict, month: str) -> dict:
        from .reports import month_bounds
        tz = self.org.timezone(company) if self.org else "Africa/Cairo"
        start, end = month_bounds(month, tz)
        inflow = [self._month_volume(company, dma["region"], n, month) for n in dma["inlet_nodes"]]
        customers = []
        for n in dma["customer_nodes"]:
            first, last = self._readings(company, n, start, end)
            vol = self._month_volume(company, dma["region"], n, month)
            customers.append({"node_id": n, "customer": dma.get("customers", {}).get(str(n), ""),
                              "reading_start_m3": first, "reading_end_m3": last,
                              "meter_difference_m3": round(last - first, 3) if first is not None and last is not None else None,
                              "consumption_m3": round(vol, 3) if vol is not None else None})
        system_input = sum(v for v in inflow if v is not None)
        billed = sum(c["consumption_m3"] or 0 for c in customers)
        nrw = system_input - billed
        return {"dma": dma["name"], "month": month, "system_input_m3": round(system_input, 3),
                "billed_m3": round(billed, 3), "non_revenue_m3": round(nrw, 3),
                "non_revenue_pct": round(100 * nrw / system_input, 1) if system_input > 0 else None,
                "inlets_reporting": sum(1 for v in inflow if v is not None), "inlets": len(inflow),
                "customers_reporting": sum(1 for c in customers if c["consumption_m3"] is not None),
                "customers": customers}

    # ======================================================== schedules
    def run_schedules(self, company: str, now: int | None = None) -> list[str]:
        """One scheduler tick (every minute from the alert monitor). Opens due valves and closes them later."""
        if self.commands is None:
            return []
        now = int(time.time() if now is None else now)
        tz = ZoneInfo(self.org.timezone(company) if self.org else "Africa/Cairo")
        local = datetime.fromtimestamp(now, tz)
        layout = self.farm.store.get(company)
        if layout is None:
            return []
        zones = {z.id: z for z in layout.zones}
        done = []
        for sch in self.list_items(company, "schedule"):
            st = dict(sch["state"])
            zone = zones.get(sch["zone_id"])
            if zone is None or not zone.node_id:
                continue
            # close a running irrigation when its time is up (also after the schedule was paused)
            if st.get("open_until") and now >= st["open_until"]:
                self._valve(company, zone, 0, sch, f"{sch['name']}: {zone.name} irrigation finished, valve closed")
                st.pop("open_until", None)
                self._set_state(sch["id"], st)
                done.append(f"close {sch['id']}")
                continue
            if not sch["enabled"] or local.weekday() not in sch["days"]:
                continue
            h, m = _hhmm(sch["start"])
            start_local = local.replace(hour=h, minute=m, second=0, microsecond=0)
            today = local.date().isoformat()
            if st.get("last_date") == today or not (start_local <= local < start_local + timedelta(minutes=30)):
                continue
            st["last_date"] = today
            reason = self._skip_reason(company, sch, zone, layout, local)
            if reason:
                st["last_result"] = f"skipped: {reason}"
                self._set_state(sch["id"], st)
                self.log_event(company, sch["id"], "skipped", f"{sch['name']}: {zone.name} skipped - {reason}")
                done.append(f"skip {sch['id']}")
                continue
            if self._valve(company, zone, 1, sch, f"{sch['name']}: {zone.name} irrigation started for "
                                                  f"{sch['duration_min']} min"):
                st["open_until"] = int(start_local.timestamp()) + sch["duration_min"] * 60
                st["last_result"] = "started"
            else:
                st["last_result"] = "command refused"
            self._set_state(sch["id"], st)
            done.append(f"open {sch['id']}")
        return done

    def _skip_reason(self, company, sch, zone, layout, local) -> str | None:
        wx = self.farm.weather.get(*layout.site.center)
        rain = wx.get("rain_next_24h_mm") if wx.get("available") else None
        if rain is not None and sch["skip_rain_mm"] and rain >= sch["skip_rain_mm"]:
            return f"{rain:.1f} mm rain forecast in 24 h"
        if sch.get("respect_rotation"):
            rot = self.rotation_for(company, zone.id)
            if rot and not self.rotation_window(rot, local)["open"]:
                return f"outside the canal rotation window ({rot['name']})"
        if sch.get("respect_quota"):
            for q in self.list_items(company, "quota"):
                if q["enabled"] and (not q["zone_ids"] or zone.id in q["zone_ids"]):
                    if self.quota_status(company, q, local.date())["status"] == "exceeded":
                        return f"water quota reached ({q['name']})"
        return None

    def _valve(self, company, zone, want: int, sch: dict, message: str) -> bool:
        from .commands import CommandError, CommandRequest
        try:
            res = self.commands.submit(CommandRequest(company=company, region=zone.region, node_id=zone.node_id,
                                                      cmd_type="VALVE", cmd_data=want, delivery="auto", ttl_seconds=3600),
                                       actor=SCHEDULE_ACTOR)
        except CommandError as exc:
            self.log_event(company, sch["id"], "refused", f"{sch['name']}: {zone.name} valve command refused ({exc})")
            return False
        self.log_event(company, sch["id"], "open" if want else "close", f"{message} (request {res.get('request_id')})")
        if self.audit is not None:
            self.audit(SCHEDULE_ACTOR, "schedule_valve_" + ("open" if want else "close"), company=company,
                       target=zone.id, details={"schedule": sch["id"], "request_id": res.get("request_id")})
        return True

    def next_runs(self, company: str, sch: dict, count: int = 3) -> list[str]:
        tz = ZoneInfo(self.org.timezone(company) if self.org else "Africa/Cairo")
        local = datetime.now(tz)
        h, m = _hhmm(sch["start"])
        out = []
        for i in range(0, 15):
            d = local.date() + timedelta(days=i)
            at = datetime(d.year, d.month, d.day, h, m, tzinfo=tz)
            if d.weekday() in sch["days"] and at > local:
                out.append(at.strftime("%Y-%m-%d %H:%M"))
            if len(out) >= count:
                break
        return out

    # =================================================== alert monitor hook
    def check_alerts(self, monitor, company: str, now: int) -> list[dict]:
        fired: list[dict] = []
        try:
            self.run_schedules(company, now)
        except Exception:
            log.exception("Irrigation schedules failed for %s", company)
        layout = self.farm.store.get(company)
        today = self._today(company)
        if layout is not None:
            for zone in layout.zones:
                if not zone.node_id:
                    continue
                prof = self.profile(company, zone.id)
                crop = ag.crop_key(prof.get("crop") or zone.crop)
                row = self.telemetry.latest.get((company, zone.region, zone.node_id))
                if not crop or not row or not row.get("soil_moisture_temp_ec_valid") or not row.get("electrical_conductivity"):
                    continue
                ece = float(row["electrical_conductivity"]) / 1000 * float((prof.get("salinity") or {}).get("ec_factor", 1.0))
                sal = ag.salinity(crop, ece, None)
                node = {"node_id": zone.node_id, "name": zone.name}
                if sal and sal["status"] != "ok":
                    fired += monitor._open(company, zone.region, node, "salinity_risk",
                                           "critical" if sal["status"] == "severe" else "warning",
                                           {"field": zone.name, "ece_dsm": sal["ece_dsm"], "threshold_dsm": sal["threshold_dsm"],
                                            "yield_potential_pct": sal["yield_potential_pct"], "crop": crop}, now)
                elif sal and ece <= sal["threshold_dsm"] * 0.95:
                    fired += monitor._resolve(company, zone.region, node, "salinity_risk", now)
        for well in self.list_items(company, "well"):
            if not well["enabled"]:
                continue
            st = self.well_status(company, well, today)
            node = {"node_id": well["node_id"], "name": well["name"]}
            if st["status"] != "ok":
                fired += monitor._open(company, well["region"], node, "well_licence",
                                       "critical" if st["status"] == "exceeded" else "warning",
                                       {"well": well["name"], "pumped_m3": st["pumped_m3"], "licence_m3": st["licence_m3"],
                                        "projected_m3": st["projected_m3"]}, now)
            else:
                fired += monitor._resolve(company, well["region"], node, "well_licence", now)
        region = layout.zones[0].region if layout and layout.zones else "Region_1"
        for q in self.list_items(company, "quota"):
            if not q["enabled"]:
                continue
            st = self.quota_status(company, q, today)
            node = {"node_id": 0, "name": q["name"]}
            kind = f"quota_{q['id']}"
            if st["status"] != "ok":
                fired += monitor._open(company, region, node, kind, "critical" if st["status"] == "exceeded" else "warning",
                                       {"quota": q["name"], "used_m3": st["used_m3"], "quota_m3": st["quota_m3"],
                                        "projected_m3": st["projected_m3"], "period_end": st["end"]}, now)
            else:
                fired += monitor._resolve(company, region, node, kind, now)
        return fired


def utc_day(ts: int) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).date().isoformat()
