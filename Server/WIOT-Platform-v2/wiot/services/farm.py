"""Smart-agriculture layer: farm layout, weather/ET0, irrigation advisory,
soil-moisture automation and satellite-backhaul readiness.

Nothing here changes the field wire contract: zones and devices are a
geographic view over existing nodes, and automation issues ordinary VALVE
intents through the audited command journal.
"""
from __future__ import annotations

import json
import logging
import math
import re
import sqlite3
import threading
import time
import urllib.parse
import urllib.request
from contextlib import closing
from datetime import datetime, timezone, tzinfo
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator, model_validator

from ..config import PACKAGE_DIR, Settings
from ..protocol.topics import region_id
from ..protocol.validation import company_id
from ..storage.telemetry_store import TelemetryStore

log = logging.getLogger(__name__)
DEMO_FARM_COMPANY = "Demo_AgriFarm"
_ID = re.compile(r"[A-Za-z0-9_.\-]{1,32}")

# FAO-56 mid-season crop coefficients (Allen et al., 1998, Table 12).
KC_MID = {"wheat": 1.15, "alfalfa": 0.95, "potato": 1.15, "maize": 1.20, "tomato": 1.15,
          "sugar beet": 1.20, "citrus": 0.70, "olive": 0.70, "date palm": 0.95, "barley": 1.15}

WMO = {0: ("Clear", "sun"), 1: ("Mainly clear", "sun"), 2: ("Partly cloudy", "cloud-sun"), 3: ("Overcast", "cloud"),
       45: ("Fog", "fog"), 48: ("Rime fog", "fog"), 51: ("Light drizzle", "rain"), 53: ("Drizzle", "rain"),
       55: ("Dense drizzle", "rain"), 61: ("Light rain", "rain"), 63: ("Rain", "rain"), 65: ("Heavy rain", "rain"),
       71: ("Light snow", "snow"), 80: ("Rain showers", "rain"), 81: ("Rain showers", "rain"),
       82: ("Violent showers", "rain"), 95: ("Thunderstorm", "storm"), 96: ("Thunderstorm", "storm"),
       99: ("Thunderstorm", "storm")}


# --------------------------------------------------------------------- layout
class Site(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    location: str = Field("", max_length=160)
    center: tuple[float, float]
    zoom: int = Field(14, ge=3, le=19)
    timezone: str = Field("Africa/Cairo", max_length=64)


class Agronomy(BaseModel):
    root_zone_mm: float = Field(300, ge=50, le=2000)
    application_rate_mm_h: float = Field(6.5, gt=0, le=100)
    pivot_flow_m3_h: float = Field(180, gt=0, le=5000)


class Zone(BaseModel):
    id: str
    name: str = Field(min_length=1, max_length=80)
    crop: str = Field("", max_length=40)
    shape: Literal["circle", "polygon"] = "circle"
    center: tuple[float, float] | None = None
    radius_m: float | None = Field(None, ge=10, le=5000)
    polygon: list[tuple[float, float]] | None = None
    node_id: int | None = Field(None, ge=1, le=65535)
    region: str = "Region_1"
    moisture_min: float = Field(26, ge=0, le=100)
    moisture_max: float = Field(38, ge=0, le=100)
    auto_irrigation: bool = False

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not _ID.fullmatch(v):
            raise ValueError("Zone id must be 1..32 letters, digits, '.', '_' or '-'")
        return v

    @model_validator(mode="after")
    def _geometry(self) -> "Zone":
        region_id(self.region)
        if self.moisture_min >= self.moisture_max:
            raise ValueError(f"Zone {self.id}: moisture_min must be below moisture_max")
        if self.shape == "circle" and (self.center is None or self.radius_m is None):
            raise ValueError(f"Zone {self.id}: circle zones need center and radius_m")
        if self.shape == "polygon" and (not self.polygon or len(self.polygon) < 3):
            raise ValueError(f"Zone {self.id}: polygon zones need at least 3 points")
        return self

    def area_ha(self) -> float:
        if self.shape == "circle":
            return math.pi * (self.radius_m or 0) ** 2 / 1e4
        pts = self.polygon or []
        lat0 = sum(p[0] for p in pts) / len(pts)
        xy = [(p[1] * 111320 * math.cos(math.radians(lat0)), p[0] * 110574) for p in pts]
        return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(xy, xy[1:] + xy[:1]))) / 2 / 1e4


class Gateway(BaseModel):
    id: str
    name: str = Field(min_length=1, max_length=80)
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    backhaul: list[Literal["lora", "wifi", "cellular", "satellite", "ethernet"]] = ["lora", "cellular"]
    primary: Literal["wifi", "cellular", "satellite", "ethernet"] = "cellular"


class Device(BaseModel):
    node_id: int = Field(ge=1, le=65535)
    region: str = "Region_1"
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    label: str = Field("", max_length=80)
    gateway: str | None = None


class FarmLayout(BaseModel):
    site: Site
    agronomy: Agronomy = Agronomy()
    gateways: list[Gateway] = Field(default_factory=list, max_length=50)
    zones: list[Zone] = Field(default_factory=list, max_length=500)
    devices: list[Device] = Field(default_factory=list, max_length=2000)

    @model_validator(mode="after")
    def _unique(self) -> "FarmLayout":
        ids = [z.id for z in self.zones]
        if len(ids) != len(set(ids)):
            raise ValueError("Zone ids must be unique")
        return self


class FarmStore:
    def __init__(self, main_db: Path):
        self.path = Path(main_db)

    def init_schema(self) -> None:
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS farm_layouts (
                company TEXT PRIMARY KEY, layout TEXT NOT NULL,
                updated_at INTEGER NOT NULL, updated_by TEXT NOT NULL)""")
            db.commit()

    def get(self, company: str) -> FarmLayout | None:
        with closing(sqlite3.connect(self.path)) as db:
            row = db.execute("SELECT layout FROM farm_layouts WHERE company=?", (company,)).fetchone()
        return FarmLayout.model_validate_json(row[0]) if row else None

    def put(self, company: str, layout: FarmLayout, actor: str) -> None:
        company_id(company)
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("""INSERT INTO farm_layouts(company, layout, updated_at, updated_by) VALUES(?,?,?,?)
                          ON CONFLICT(company) DO UPDATE SET layout=excluded.layout,
                          updated_at=excluded.updated_at, updated_by=excluded.updated_by""",
                       (company, layout.model_dump_json(), int(time.time()), actor))
            db.commit()

    def seed_demo(self, companies: list[str]) -> bool:
        if DEMO_FARM_COMPANY not in companies or self.get(DEMO_FARM_COMPANY) is not None:
            return False
        data = json.loads((PACKAGE_DIR / "data" / "demo_farm_layout.json").read_text(encoding="utf-8"))
        self.put(DEMO_FARM_COMPANY, FarmLayout.model_validate(data), "seed")
        return True


# -------------------------------------------------------------------- weather
class WeatherClient:
    """Open-Meteo forecast (no key) with ET0 (FAO-56 Penman-Monteith); cached."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._cache: dict[tuple, tuple[float, dict]] = {}
        self._lock = threading.Lock()

    def get(self, lat: float, lon: float) -> dict:
        if not self.settings.weather_enabled:
            return {"available": False, "reason": "Weather integration disabled (WIOT_WEATHER_ENABLED=false)"}
        key = (round(lat, 2), round(lon, 2))
        with self._lock:
            hit = self._cache.get(key)
            if hit and time.time() - hit[0] < 1200:
                return hit[1]
        params = {
            "latitude": key[0], "longitude": key[1], "timezone": "auto", "forecast_days": 7,
            "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,wind_direction_10m,precipitation,weather_code,is_day",
            "hourly": "precipitation,precipitation_probability",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,et0_fao_evapotranspiration,"
                     "wind_speed_10m_max,weather_code,shortwave_radiation_sum",
        }
        url = f"{self.settings.weather_url}?{urllib.parse.urlencode(params)}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "WIOT-Platform/2 (agronomy)"})
            with urllib.request.urlopen(req, timeout=6) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            stale = hit[1] if hit else None
            if stale:
                return {**stale, "stale": True}
            return {"available": False, "reason": f"Weather service unreachable ({type(exc).__name__})"}
        cur, daily, hourly = raw.get("current", {}), raw.get("daily", {}), raw.get("hourly", {})
        code = int(cur.get("weather_code") or 0)
        days = []
        for i, date in enumerate(daily.get("time", [])):
            dcode = int((daily.get("weather_code") or [0])[i] or 0)
            days.append({"date": date, "tmax": daily["temperature_2m_max"][i], "tmin": daily["temperature_2m_min"][i],
                         "rain_mm": daily["precipitation_sum"][i], "et0_mm": daily["et0_fao_evapotranspiration"][i],
                         "wind_max": daily["wind_speed_10m_max"][i], "radiation_mj": daily.get("shortwave_radiation_sum", [None] * 7)[i],
                         "label": WMO.get(dcode, ("Unknown", "cloud"))[0], "icon": WMO.get(dcode, ("", "cloud"))[1]})
        rain_24 = sum(v or 0 for v in (hourly.get("precipitation") or [])[:24])
        data = {
            "available": True, "source": "Open-Meteo", "fetched_at": int(time.time()),
            "current": {"temp_c": cur.get("temperature_2m"), "humidity": cur.get("relative_humidity_2m"),
                        "wind_kmh": cur.get("wind_speed_10m"), "wind_dir": cur.get("wind_direction_10m"),
                        "precip_mm": cur.get("precipitation"), "is_day": bool(cur.get("is_day", 1)),
                        "label": WMO.get(code, ("Unknown", "cloud"))[0], "icon": WMO.get(code, ("", "cloud"))[1]},
            "daily": days, "rain_next_24h_mm": round(rain_24, 1),
            "et0_today_mm": days[0]["et0_mm"] if days else None,
        }
        with self._lock:
            self._cache[key] = (time.time(), data)
        return data


# ------------------------------------------------------------------ agronomy
def _moisture(row: dict) -> tuple[float | None, float | None, str | None]:
    if row.get("soil_moisture_temp_valid") and (row.get("soil_moisture") or 0) > 0:
        return float(row["soil_moisture"]), row.get("soil_temperature"), "HNDA"
    if row.get("soil_moisture_temp_ec_valid") and (row.get("ec_moisture") or 0) > 0:
        return float(row["ec_moisture"]), row.get("ec_temperature"), "Sondas"
    return None, None, None


def _kc(crop: str) -> float:
    return KC_MID.get((crop or "").strip().lower(), 1.0)


def _zone(name: str) -> tzinfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return timezone.utc


class FarmService:
    def __init__(self, settings: Settings, store: FarmStore, telemetry: TelemetryStore, weather: WeatherClient):
        self.node_type = None  # (company, region, node) -> 'monitoring' | 'control' | None
        self.settings = settings
        self.store = store
        self.telemetry = telemetry
        self.weather = weather
        self.commands = None          # injected by the runtime (avoids an import cycle)
        self.logs = None
        self.hub = None
        self.audit = None
        self._last_auto: dict[tuple[str, str], float] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------ overview
    def map_config(self) -> dict:
        s = self.settings
        return {"tiles": s.map_tile_url, "labels": s.map_labels_url, "attribution": s.map_attribution}

    def zone_state(self, zone: Zone, row: dict | None, layout: FarmLayout, wx: dict) -> dict:
        out = {**zone.model_dump(), "area_ha": round(zone.area_ha(), 1), "kc": _kc(zone.crop)}
        if row is None:
            out.update(status="no_data", advice="No uplink from this zone's node yet.", irrigating=False)
            return out
        moisture, soil_t, probe = _moisture(row)
        valve = int(row.get("node_status") or 0)
        link = row.get("link_state", "offline")
        live = link != "offline"  # an offline node's last flow/valve reading says nothing about now
        flow = float(row.get("flow") or 0) if live and row.get("flow_live_valid") else 0.0
        irrigating = live and (valve == 1 or flow > 0.5)
        # The node's day total only counts as "today" if that report was sent today (site time).
        tz = _zone(layout.site.timezone)
        ts = int(row.get("timestamp") or 0)
        today = ts > 0 and datetime.fromtimestamp(ts, tz).date() == datetime.now(tz).date()
        out.update(moisture=moisture, soil_temp=soil_t, probe=probe,
                   ec=row.get("electrical_conductivity") if row.get("soil_moisture_temp_ec_valid") else None,
                   valve={0: "closed", 1: "open", 2: "unknown", 3: "fault"}.get(valve, "unknown"),
                   flow_m3h=round(flow, 2), water_today_m3=round(float(row.get("flow_day") or 0), 2) if today else 0.0,
                   battery_v=row.get("battery_voltage"), link_state=link, last_seen=row.get("timestamp"),
                   power_mode=row.get("power_mode_name"), irrigating=irrigating)
        if moisture is None:
            out.update(status="sensor_fault", advice="Soil probe reports no valid moisture value — inspect the sensor.")
            return out
        lo, hi = zone.moisture_min, zone.moisture_max
        status = "dry" if moisture < lo else "wet" if moisture > hi else "optimal"
        if link == "offline":
            status = "offline"
        etc = (wx.get("et0_today_mm") or 0) * _kc(zone.crop) if wx.get("available") else None
        target = (lo + hi) / 2
        deficit_mm = max(0.0, (target - moisture) / 100 * layout.agronomy.root_zone_mm)
        runtime_min = deficit_mm / layout.agronomy.application_rate_mm_h * 60
        rain = wx.get("rain_next_24h_mm") or 0 if wx.get("available") else 0
        if status == "offline":
            advice = "Node offline — last reading may be stale; verify the link before acting."
        elif status == "dry" and rain >= deficit_mm > 0:
            advice = f"Dry, but {rain:.1f} mm rain is forecast in 24 h — hold irrigation."
        elif status == "dry":
            advice = (f"Irrigate ≈{runtime_min:.0f} min ({deficit_mm:.1f} mm) to reach {target:.0f}%."
                      if not irrigating else f"Irrigating — {deficit_mm:.1f} mm still needed to reach {target:.0f}%.")
        elif status == "wet" and irrigating:
            advice = "Above target band while irrigating — stop to avoid leaching and waterlogging."
        elif status == "wet":
            advice = "Above target band — no irrigation needed."
        else:
            advice = "Within target band — no action."
        out.update(status=status, deficit_mm=round(deficit_mm, 1), runtime_min=round(runtime_min),
                   etc_today_mm=round(etc, 2) if etc is not None else None, advice=advice)
        return out

    def overview(self, company: str, region: str) -> dict:
        layout = self.store.get(company)
        if layout is None:
            return {"company": company, "configured": False, "map": self.map_config()}
        fleet = {(n["node_id"]): n for n in self.telemetry.fleet(company, region)}
        wx = self.weather.get(*layout.site.center)
        zones = [self.zone_state(z, fleet.get(z.node_id) if z.region == region else None, layout, wx)
                 for z in layout.zones]
        for z in zones:  # monitoring nodes report sensors only; control nodes also drive the valve
            z["node_type"] = self.node_type(company, z["region"], z["node_id"]) if self.node_type and z.get("node_id") else None
        devices = []
        for d in layout.devices:
            n = fleet.get(d.node_id) if d.region == region else None
            devices.append({**d.model_dump(), "link_state": n["link_state"] if n else "offline",
                            "last_seen": n["timestamp"] if n else None,
                            "battery_v": n.get("battery_voltage") if n else None,
                            "power_mode": n.get("power_mode_name") if n else None})
        with_m = [z["moisture"] for z in zones if z.get("moisture") is not None]
        kpis = {
            "zones": len(zones), "area_ha": round(sum(z["area_ha"] for z in zones), 1),
            "irrigating": sum(1 for z in zones if z.get("irrigating")),
            "dry": sum(1 for z in zones if z["status"] == "dry"),
            "optimal": sum(1 for z in zones if z["status"] == "optimal"),
            "wet": sum(1 for z in zones if z["status"] == "wet"),
            "offline": sum(1 for z in zones if z["status"] in ("offline", "no_data")),
            "avg_moisture": round(sum(with_m) / len(with_m), 1) if with_m else None,
            "water_today_m3": round(sum(z.get("water_today_m3") or 0 for z in zones), 1),
            "flow_now_m3h": round(sum(z.get("flow_m3h") or 0 for z in zones), 1),
            "auto_zones": sum(1 for z in zones if z["auto_irrigation"]),
        }
        alerts = []
        for z in zones:
            if z["status"] == "dry" and not z.get("irrigating"):
                alerts.append({"level": "warning", "zone": z["id"], "message": f"{z['name']} below {z['moisture_min']}% soil moisture"})
            elif z["status"] == "wet" and z.get("irrigating"):
                alerts.append({"level": "serious", "zone": z["id"], "message": f"{z['name']} over-irrigating"})
            elif z["status"] in ("offline", "no_data"):
                alerts.append({"level": "critical", "zone": z["id"], "message": f"{z['name']} node not reporting"})
            elif z["status"] == "sensor_fault":
                alerts.append({"level": "serious", "zone": z["id"], "message": f"{z['name']} soil probe invalid"})
            if z.get("battery_v") and z["battery_v"] < 3.45:
                alerts.append({"level": "warning", "zone": z["id"], "message": f"{z['name']} battery {z['battery_v']:.2f} V"})
        return {"company": company, "region": region, "configured": True, "map": self.map_config(),
                "site": layout.site.model_dump(), "agronomy": layout.agronomy.model_dump(),
                "gateways": [g.model_dump() for g in layout.gateways], "devices": devices,
                "zones": zones, "kpis": kpis, "alerts": alerts, "weather": wx}

    def zone_history(self, company: str, zone_id: str, hours: float) -> dict:
        layout = self.store.get(company)
        zone = next((z for z in (layout.zones if layout else []) if z.id == zone_id), None)
        if zone is None or zone.node_id is None:
            raise LookupError("Unknown zone")
        end = int(time.time())
        start = end - int(hours * 3600)
        bucket = max(60, int(hours * 3600 / 180))
        series = {}
        for metric in ("soil_moisture", "ec_moisture", "flow", "soil_temperature", "electrical_conductivity"):
            series[metric] = self.telemetry.series(company, zone.region, zone.node_id, metric, start, end, bucket)
        moisture = series["soil_moisture"] if len(series["soil_moisture"]) >= len(series["ec_moisture"]) else series["ec_moisture"]
        return {"zone": zone.id, "bucket_s": bucket, "moisture": moisture, "flow": series["flow"],
                "soil_temp": series["soil_temperature"], "ec": series["electrical_conductivity"],
                "band": [zone.moisture_min, zone.moisture_max]}

    def update_zone(self, company: str, zone_id: str, changes: dict, actor: str) -> dict:
        with self._lock:
            layout = self.store.get(company)
            if layout is None:
                raise LookupError("No farm layout for this company")
            zones = [z.model_dump() for z in layout.zones]
            target = next((z for z in zones if z["id"] == zone_id), None)
            if target is None:
                raise LookupError("Unknown zone")
            if changes.get("auto_irrigation") and self.node_type is not None and target.get("node_id") \
                    and self.node_type(company, target["region"], target["node_id"]) == "monitoring":
                raise ValueError(f"{target['name']} is watched by a monitoring node (no valve); "
                                 "automatic irrigation needs a control node")
            target.update({k: v for k, v in changes.items() if v is not None})
            updated = FarmLayout.model_validate({**layout.model_dump(), "zones": zones})
            self.store.put(company, updated, actor)
        return next(z.model_dump() for z in updated.zones if z.id == zone_id)

    # ------------------------------------------------------------ automation
    def on_status(self, company: str, region: str, node_id: int, fields: dict) -> None:
        """Hysteresis control on each fresh Status: open below min, close above max."""
        layout = self.store.get(company)
        if layout is None or self.commands is None:
            return
        for zone in layout.zones:
            if not zone.auto_irrigation or zone.node_id != node_id or zone.region != region:
                continue
            if self.node_type is not None and self.node_type(company, region, node_id) == "monitoring":
                continue  # monitoring nodes have no valve
            moisture, _, _ = _moisture(fields)
            if moisture is None:
                continue
            valve = int(fields.get("node_status") or 0)
            want = 1 if moisture < zone.moisture_min and valve != 1 else 0 if moisture > zone.moisture_max and valve == 1 else None
            if want is None:
                continue
            key = (company, zone.id)
            now = time.time()
            if now - self._last_auto.get(key, 0) < self.settings.automation_min_interval_s:
                continue
            self._last_auto[key] = now
            self._issue(company, region, zone, want, moisture)

    def _issue(self, company: str, region: str, zone: Zone, want: int, moisture: float) -> None:
        from .commands import CommandRequest  # local import: commands imports nothing from farm
        try:
            result = self.commands.submit(CommandRequest(company=company, region=region, node_id=zone.node_id,
                                                         cmd_type="VALVE", cmd_data=want, delivery="next_wake",
                                                         ttl_seconds=3600), actor="automation")
        except Exception as exc:
            if self.logs:
                self.logs.emit(f"[AUTO] {zone.name}: valve command refused ({exc})", company=company, level="warning")
            return
        verb = "OPEN" if want else "CLOSE"
        msg = (f"[AUTO] {zone.name}: soil moisture {moisture:.1f}% "
               f"{'<' if want else '>'} {zone.moisture_min if want else zone.moisture_max}% → valve {verb} "
               f"(request {result['request_id']})")
        if self.logs:
            self.logs.emit(msg, company=company)
        if self.hub:
            self.hub.publish("automation", {"zone": zone.id, "action": verb.lower(), "moisture": moisture,
                                            "request_id": result["request_id"]}, company=company)
        if self.audit:
            self.audit("automation", "valve_" + verb.lower(), company=company, target=zone.id,
                       details={"moisture": moisture, "request_id": result["request_id"]})

    # ---------------------------------------------------------- satellite
    def connectivity(self, company: str, region: str, frame_stats: dict, budget: int) -> dict:
        layout = self.store.get(company)
        fleet = {n["node_id"]: n for n in self.telemetry.fleet(company, region)}
        gateways = {g.id: g for g in (layout.gateways if layout else [])}
        nodes = []
        for node_id, n in sorted(fleet.items()):
            dev = next((d for d in (layout.devices if layout else []) if d.node_id == node_id and d.region == region), None)
            stats = frame_stats.get((company, region, node_id))
            avg_frame = (stats["frame_bytes"] / stats["count"]) if stats else None
            avg_payload = (stats["payload_bytes"] / stats["count"]) if stats else None
            per_day = n.get("uplinks_24h") or 0
            interval = n.get("median_interval_s")
            planned = round(86400 / interval) if interval else per_day
            gw = gateways.get(dev.gateway) if dev and dev.gateway else None
            nodes.append({
                "node_id": node_id, "label": dev.label if dev else f"Node {node_id}",
                "gateway": gw.id if gw else None, "path": (["lora", "gateway", gw.primary] if gw else ["direct"]),
                "link_state": n["link_state"], "uplinks_24h": per_day, "reports_per_day": planned,
                "avg_payload_b": round(avg_payload, 1) if avg_payload else None,
                "avg_frame_b": round(avg_frame, 1) if avg_frame else None,
                "bytes_per_day": round(planned * avg_frame) if avg_frame else None,
                "fits_budget": planned <= budget,
                "budget_interval_s": math.ceil(86400 / budget),
            })
        frames = [x["avg_frame_b"] for x in nodes if x["avg_frame_b"]]
        avg_frame_all = round(sum(frames) / len(frames), 1) if frames else None
        readiness = [
            {"item": "Store-and-forward on the node", "ok": True,
             "detail": "SPI-flash telemetry log with 24 h retention and acknowledged history download"},
            {"item": "Sleep-aware command delivery", "ok": True,
             "detail": "Commands queue in the journal and release on the next Status (next-wake)"},
            {"item": "Compact encrypted frames", "ok": bool(avg_frame_all and avg_frame_all <= 160),
             "detail": f"Average AES-128 frame {avg_frame_all} B (protobuf + 17 B header)" if avg_frame_all
             else "No frames observed since server start"},
            {"item": "Latency-tolerant acknowledgements", "ok": True,
             "detail": "Late ACKs are reconciled to their request ID instead of being dropped"},
            {"item": "Delivery-risk scoring before send", "ok": True,
             "detail": "Model predicts whether a sleeping node will hear the command"},
            {"item": f"Reporting within {budget} msgs/day budget", "ok": all(x["fits_budget"] for x in nodes) if nodes else False,
             "detail": f"{sum(1 for x in nodes if not x['fits_budget'])} node(s) report more often than every "
                       f"{math.ceil(86400 / budget / 60)} min"},
        ]
        return {"company": company, "region": region, "budget_msgs_per_day": budget,
                "gateways": [g.model_dump() for g in gateways.values()], "nodes": nodes,
                "avg_frame_b": avg_frame_all, "readiness": readiness}
