"""Third-party devices (Track G, point 53): metric catalog, payload decoding and signatures.

Off-the-shelf climate, water-quality and level devices report JSON over MQTT or LoRaWAN.
Their readings are stored per *metric* from the catalog below (one SI unit per metric), so
charts, the greenhouse map and later alert rules do not depend on any vendor's field names.

A device's ``mapping`` says which payload field feeds which metric (with an optional scale
and offset). Without a mapping, fields whose names match a catalog key or a common vendor
name (``temperature``, ``humidity``, ``co2``...) are mapped automatically.

Pure functions only: no I/O, no database.
"""
from __future__ import annotations

import hashlib
import hmac
import math
import re
from datetime import datetime, timezone

# key: (label, unit, valid min, valid max, decimals, group)
METRICS: dict[str, tuple[str, str, float, float, int, str]] = {
    "air_temp_c": ("Air temperature", "°C", -40, 85, 1, "climate"),
    "air_rh_pct": ("Relative humidity", "%", 0, 100, 0, "climate"),
    "co2_ppm": ("CO₂", "ppm", 0, 20000, 0, "climate"),
    "light_lux": ("Light", "lux", 0, 200000, 0, "climate"),
    "par_umol": ("PAR", "µmol/m²/s", 0, 3000, 0, "climate"),
    "vpd_kpa": ("VPD", "kPa", 0, 10, 2, "climate"),
    "air_pressure_hpa": ("Air pressure", "hPa", 300, 1100, 0, "climate"),
    "leaf_wetness_pct": ("Leaf wetness", "%", 0, 100, 0, "climate"),
    "wind_speed_m_s": ("Wind speed", "m/s", 0, 80, 1, "climate"),
    "rain_mm": ("Rain", "mm", 0, 500, 1, "climate"),
    "soil_moisture_pct": ("Soil moisture", "%", 0, 100, 1, "soil"),
    "soil_temp_c": ("Soil temperature", "°C", -20, 70, 1, "soil"),
    "soil_ec_ds_m": ("Soil EC", "dS/m", 0, 30, 2, "soil"),
    "water_temp_c": ("Water temperature", "°C", -5, 60, 1, "water"),
    "water_ph": ("pH", "pH", 0, 14, 2, "water"),
    "water_ec_ds_m": ("Water EC", "dS/m", 0, 200, 2, "water"),
    "water_do_mg_l": ("Dissolved oxygen", "mg/L", 0, 30, 2, "water"),
    "level_pct": ("Tank level", "%", 0, 100, 0, "tank"),
    "level_m": ("Water level", "m", 0, 200, 2, "tank"),
    "distance_mm": ("Distance", "mm", 0, 20000, 0, "tank"),
    "flow_l_min": ("Flow", "L/min", 0, 100000, 1, "tank"),
    "pressure_bar": ("Water pressure", "bar", 0, 100, 2, "tank"),
    "battery_v": ("Battery voltage", "V", 0, 60, 2, "device"),
    "battery_pct": ("Battery", "%", 0, 100, 0, "device"),
    "rssi_dbm": ("Signal (RSSI)", "dBm", -160, 0, 0, "device"),
    "snr_db": ("Signal-to-noise", "dB", -30, 30, 1, "device"),
}
GROUPS = {"climate": "Climate", "soil": "Soil", "water": "Water quality", "tank": "Tanks and flow", "device": "Device"}

# Vendor field names (lower case, last path segment) that map without configuration. Only
# names whose unit is unambiguous are listed: e.g. Dragino's ``conduct_SOIL`` is µS/cm, so it
# needs an explicit mapping with scale 0.001.
ALIASES: dict[str, str] = {
    "temperature": "air_temp_c", "temp": "air_temp_c", "air_temperature": "air_temp_c", "temp_c": "air_temp_c",
    "tempc_sht": "air_temp_c", "tempc_ds": "air_temp_c",
    "humidity": "air_rh_pct", "rh": "air_rh_pct", "relative_humidity": "air_rh_pct", "air_humidity": "air_rh_pct",
    "hum_sht": "air_rh_pct",
    "co2": "co2_ppm", "carbon_dioxide": "co2_ppm",
    "illumination": "light_lux", "illuminance": "light_lux", "lux": "light_lux", "light_lux": "light_lux",
    "par": "par_umol", "ppfd": "par_umol",
    "vpd": "vpd_kpa",
    "barometric_pressure": "air_pressure_hpa", "air_pressure": "air_pressure_hpa",
    "leaf_wetness": "leaf_wetness_pct",
    "wind_speed": "wind_speed_m_s",
    "rainfall": "rain_mm", "rain": "rain_mm",
    "soil_moisture": "soil_moisture_pct", "water_soil": "soil_moisture_pct", "vwc": "soil_moisture_pct",
    "soil_temperature": "soil_temp_c", "temp_soil": "soil_temp_c",
    "soil_ec": "soil_ec_ds_m",
    "water_temperature": "water_temp_c",
    "ph": "water_ph",
    "dissolved_oxygen": "water_do_mg_l",
    "tank_level": "level_pct",
    "distance": "distance_mm",
    "batv": "battery_v", "bat_v": "battery_v", "vbat": "battery_v", "battery_voltage": "battery_v",
    "battery": "battery_pct", "battery_level": "battery_pct", "bat_pct": "battery_pct",
}

DEVICE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,39}")
FIELD_RE = re.compile(r"[A-Za-z0-9_$@-]{1,64}(\.[A-Za-z0-9_$@-]{1,64}){0,4}")
MAX_MAPPING = 32
MAX_FIELDS = 200           # numeric fields considered per payload
_NUM = re.compile(r"\s*[-+]?(\d+(\.\d*)?|\.\d+)([eE][-+]?\d+)?\s*")


def check_device_id(value) -> str:
    if not isinstance(value, str) or not DEVICE_ID_RE.fullmatch(value):
        raise ValueError("Device ID must be 1..40 letters, digits, _ or -, starting with a letter or digit")
    return value


def check_dev_eui(value) -> str | None:
    if value in (None, ""):
        return None
    eui = re.sub(r"[\s:-]", "", str(value)).upper()
    if not re.fullmatch(r"[0-9A-F]{16}", eui):
        raise ValueError("DevEUI must be 16 hexadecimal characters")
    return eui


def check_mapping(value) -> list[dict]:
    """Normalise a mapping list: [{field, metric, scale, offset}]."""
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        raise ValueError("Mapping must be a list")
    if len(value) > MAX_MAPPING:
        raise ValueError(f"At most {MAX_MAPPING} mapped fields per device")
    out, seen = [], set()
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("Each mapping entry needs a field and a metric")
        field, metric = str(item.get("field") or "").strip(), str(item.get("metric") or "").strip()
        if not FIELD_RE.fullmatch(field):
            raise ValueError(f"Field '{field[:70]}' is not a valid name (use dots for nested fields, e.g. climate.co2)")
        if metric not in METRICS:
            raise ValueError(f"Unknown metric '{metric[:40]}'")
        try:
            scale = float(item.get("scale", 1) if item.get("scale") not in (None, "") else 1)
            offset = float(item.get("offset", 0) if item.get("offset") not in (None, "") else 0)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Scale and offset of '{field}' must be numbers") from exc
        if not (math.isfinite(scale) and math.isfinite(offset)) or scale == 0:
            raise ValueError(f"Scale of '{field}' must be a non-zero number")
        if field in seen:
            raise ValueError(f"Field '{field}' is mapped twice")
        seen.add(field)
        out.append({"field": field, "metric": metric, "scale": scale, "offset": offset})
    return out


def number(value) -> float | None:
    """A finite float from a JSON number or numeric string; None for anything else (bools too)."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        if isinstance(value, (int, float)):
            v = float(value)
        elif isinstance(value, str) and len(value) <= 32 and _NUM.fullmatch(value):
            v = float(value)
        else:
            return None
    except OverflowError:                   # a JSON integer too large for a float
        return None
    return v if math.isfinite(v) else None


def safe_text(value, limit: int = 64) -> str:
    """Text from a device or network server, cut and made encodable (lone surrogates would break JSON responses)."""
    return str(value or "")[:limit].encode("utf-8", "replace").decode("utf-8")


def flatten(obj, prefix: str = "", depth: int = 0, out: dict | None = None) -> dict[str, float]:
    """Numeric leaves of a decoded payload as {"a.b": value}; at most 5 levels and MAX_FIELDS fields."""
    out = {} if out is None else out
    if not isinstance(obj, dict) or depth > 4:
        return out
    for key, value in obj.items():
        if len(out) >= MAX_FIELDS:
            break
        key = str(key)
        try:
            key.encode("utf-8")            # lone surrogates ("\ud800") cannot be returned as JSON later
        except UnicodeEncodeError:
            continue
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            flatten(value, path, depth + 1, out)
        else:
            v = number(value)
            if v is not None and len(path) <= 160:
                out[path] = v
    return out


def auto_mapping(fields: dict[str, float]) -> list[dict]:
    """Mapping for fields whose last name segment is a catalog key or a known vendor name."""
    out, used = [], set()
    for path in fields:
        last = path.rsplit(".", 1)[-1].lower()
        metric = last if last in METRICS else ALIASES.get(last)
        if metric and metric not in used:
            used.add(metric)
            out.append({"field": path, "metric": metric, "scale": 1.0, "offset": 0.0})
    return out


def apply_mapping(fields: dict[str, float], mapping: list[dict]) -> tuple[dict[str, float], list[dict]]:
    """({metric: value}, rejected) — values outside a metric's valid range are rejected, not stored."""
    values, rejected = {}, []
    for m in mapping or auto_mapping(fields):
        raw = fields.get(m["field"])
        if raw is None:
            continue
        v = raw * m.get("scale", 1.0) + m.get("offset", 0.0)
        label, _unit, lo, hi, dec, _group = METRICS[m["metric"]]
        if not lo <= v <= hi:
            rejected.append({"field": m["field"], "metric": m["metric"], "value": round(v, 4)})
            continue
        values[m["metric"]] = round(v, max(dec + 2, 2))
    return values, rejected


def parse_time(value) -> int | None:
    """Unix seconds from epoch seconds/milliseconds or an ISO 8601 / RFC 3339 string."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            v = float(value)
        except OverflowError:
            return None
        if not math.isfinite(v):
            return None
        return int(v / 1000) if v > 1e12 else int(v)
    if isinstance(value, str) and len(value) <= 40:
        text = value.strip().replace("Z", "+00:00").replace("z", "+00:00")
        text = re.sub(r"(\.\d{6})\d+", r"\1", text)        # TTN sends nanoseconds
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            n = number(value)
            return parse_time(n) if n is not None else None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    return None


# ------------------------------------------------------------- MQTT envelope
def mqtt_signature(secret: str, topic: str, body: str) -> str:
    """HMAC-SHA256 over ``topic + "\\n" + body`` (hex). Binding the topic stops a signed message
    from being replayed under another device's topic."""
    return hmac.new(secret.encode(), (topic + "\n" + body).encode(), hashlib.sha256).hexdigest()


def verify_signature(secret: str, topic: str, body: str, sig) -> bool:
    if not isinstance(sig, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", sig):
        return False
    try:
        expected = mqtt_signature(secret, topic, body)
    except UnicodeEncodeError:              # lone surrogates in "p": cannot have been signed as UTF-8
        return False
    return hmac.compare_digest(expected, sig.lower())


# ------------------------------------------------------------ LoRaWAN servers
def _best_rx(rx: list) -> dict:
    """RSSI/SNR of the gateway that heard the uplink best."""
    best = None
    for g in rx if isinstance(rx, list) else []:
        if not isinstance(g, dict):
            continue
        rssi = number(g.get("rssi", g.get("channel_rssi")))
        if rssi is not None and (best is None or rssi > best[0]):
            best = (rssi, number(g.get("snr")))
    out = {}
    if best:
        out["rssi_dbm"] = best[0]
        if best[1] is not None:
            out["snr_db"] = best[1]
    return out


def parse_ttn(body: dict) -> dict | None:
    """The Things Stack v3 webhook. None for messages that are not uplinks (joins, acks...)."""
    up = body.get("uplink_message") if isinstance(body, dict) else None
    if not isinstance(up, dict):
        return None
    ids = body.get("end_device_ids")
    ids = ids if isinstance(ids, dict) else {}
    decoded = up.get("decoded_payload")
    return {"dev_eui": ids.get("dev_eui"), "external_id": safe_text(ids.get("device_id")),
            "measured_at": parse_time(up.get("received_at") or body.get("received_at")),
            "fields": flatten(decoded) if isinstance(decoded, dict) else {},
            "radio": _best_rx(up.get("rx_metadata")), "f_cnt": up.get("f_cnt")}


def parse_chirpstack(body: dict, event: str) -> dict | None:
    """ChirpStack v4 HTTP integration (JSON encoding). Handles ``up`` and ``status`` events."""
    if not isinstance(body, dict):
        return None
    info = body.get("deviceInfo")
    info = info if isinstance(info, dict) else {}
    base = {"dev_eui": info.get("devEui"), "external_id": safe_text(info.get("deviceName")),
            "measured_at": parse_time(body.get("time")), "radio": {}, "f_cnt": body.get("fCnt")}
    if event == "up":
        obj = body.get("object")
        return {**base, "fields": flatten(obj) if isinstance(obj, dict) else {}, "radio": _best_rx(body.get("rxInfo"))}
    if event == "status":
        level = number(body.get("batteryLevel"))
        return {**base, "fields": {"batteryLevel": level} if level is not None else {},
                "mapping": [{"field": "batteryLevel", "metric": "battery_pct", "scale": 1.0, "offset": 0.0}]}
    return None


def catalog() -> list[dict]:
    return [{"key": k, "label": v[0], "unit": v[1], "min": v[2], "max": v[3], "decimals": v[4], "group": v[5]}
            for k, v in METRICS.items()]
