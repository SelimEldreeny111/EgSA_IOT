"""Third-party device registry and readings (Track G, point 53).

* ``ext_devices`` / ``ext_sources`` live in the main database (``iot_data.db``) next to the
  node registry. MQTT devices that sign their messages keep their HMAC secret sealed with
  ``WIOT_SECRET_KEY``; LoRaWAN network-server keys are stored as SHA-256 hashes only.
* Readings live in each company's own database: ``ext_readings`` (raw, one row per metric),
  ``ext_hourly`` (count/sum/min/max per hour, kept when raw rows expire) and ``ext_latest``.

The tables are additive; a v1.31 server ignores them.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import threading
import time

from ..domain.ext_metrics import METRICS, check_dev_eui, check_device_id, check_mapping
from ..protocol.topics import region_id
from ..protocol.validation import company_id
from ..security import seal, unseal

PROTOCOLS = ("mqtt", "lorawan")
AUTH_MODES = ("hmac", "none")
SOURCE_KINDS = ("ttn", "chirpstack")
SOURCE_PREFIX = "wiotsrc_"          # never "wiot_": that prefix is an API token
MAX_DEVICES = 2000
MIN_RETENTION_DAYS = 365
RAW_POINTS = 20000                 # raw points per series request (the newest are kept)

EXT_DDL = (
    """CREATE TABLE IF NOT EXISTS ext_readings (
        id INTEGER PRIMARY KEY AUTOINCREMENT, device_id TEXT NOT NULL, metric TEXT NOT NULL,
        ts INTEGER NOT NULL, received_at INTEGER NOT NULL, value REAL NOT NULL,
        trusted INTEGER NOT NULL DEFAULT 1, source TEXT NOT NULL DEFAULT '',
        UNIQUE(device_id, metric, ts))""",
    "CREATE INDEX IF NOT EXISTS idx_ext_readings_ts ON ext_readings(ts)",
    """CREATE TABLE IF NOT EXISTS ext_hourly (
        device_id TEXT NOT NULL, metric TEXT NOT NULL, hour INTEGER NOT NULL,
        n INTEGER NOT NULL, sum REAL NOT NULL, min REAL NOT NULL, max REAL NOT NULL,
        PRIMARY KEY(device_id, metric, hour))""",
    """CREATE TABLE IF NOT EXISTS ext_latest (
        device_id TEXT NOT NULL, metric TEXT NOT NULL, ts INTEGER NOT NULL, received_at INTEGER NOT NULL,
        value REAL NOT NULL, trusted INTEGER NOT NULL DEFAULT 1, PRIMARY KEY(device_id, metric))""",
)


def ext_schema(db: sqlite3.Connection) -> None:
    """Called from the tenant database migration (``TelemetryStore._migrate``)."""
    for ddl in EXT_DDL:
        db.execute(ddl)


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def _text(value, limit: int, what: str) -> str:
    value = ("" if value is None else str(value)).strip()
    if len(value) > limit:
        raise ValueError(f"{what} is limited to {limit} characters")
    return value


def _point(lat, lon) -> tuple[float | None, float | None]:
    if lat in (None, "") and lon in (None, ""):
        return None, None
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError) as exc:
        raise ValueError("Latitude and longitude must both be numbers") from exc
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("Latitude must be -90..90 and longitude -180..180")
    return round(lat, 7), round(lon, 7)


class DeviceStore:
    def __init__(self, main, telemetry, secret_key: str):
        self.main, self.telemetry, self._secret = main, telemetry, secret_key
        self._lock = threading.Lock()
        self._cache: dict[str, dict[str, dict]] = {}          # company -> device_id -> row (with sealed secret)
        self._gen: dict[str, int] = {}                        # bumped on every registry write (stale-read guard)

    # ------------------------------------------------------------------ schema
    def init_schema(self) -> None:
        with self.main.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS ext_devices (
                company TEXT NOT NULL, device_id TEXT NOT NULL, name TEXT NOT NULL,
                protocol TEXT NOT NULL, auth TEXT NOT NULL DEFAULT 'hmac', secret TEXT,
                dev_eui TEXT, region TEXT, model TEXT NOT NULL DEFAULT '', lat REAL, lon REAL,
                mapping TEXT NOT NULL DEFAULT '[]', interval_s INTEGER NOT NULL DEFAULT 900,
                enabled INTEGER NOT NULL DEFAULT 1, notes TEXT NOT NULL DEFAULT '',
                created_at INTEGER NOT NULL, created_by TEXT NOT NULL, updated_at INTEGER NOT NULL,
                PRIMARY KEY (company, device_id))""")
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_ext_devices_eui ON ext_devices(company, dev_eui) "
                       "WHERE dev_eui IS NOT NULL")
            db.execute("CREATE TABLE IF NOT EXISTS ext_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            db.execute("""CREATE TABLE IF NOT EXISTS ext_sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT, company TEXT NOT NULL, name TEXT NOT NULL,
                kind TEXT NOT NULL, key_hash TEXT NOT NULL UNIQUE, prefix TEXT NOT NULL,
                created_by TEXT NOT NULL, created_at INTEGER NOT NULL, last_used_at INTEGER,
                revoked_at INTEGER, uplinks INTEGER NOT NULL DEFAULT 0)""")

    # ---------------------------------------------------------------- registry
    def _load(self, company: str) -> dict[str, dict]:
        with self._lock:
            hit = self._cache.get(company)
            gen = self._gen.get(company, 0)
        if hit is not None:
            return hit
        with self.main.connect() as db:
            rows = {r["device_id"]: self._row(r) for r in
                    db.execute("SELECT * FROM ext_devices WHERE company=? ORDER BY device_id", (company,))}
        with self._lock:
            if self._gen.get(company, 0) == gen:          # no write since the read began: safe to cache
                self._cache[company] = rows
        return rows

    def _forget(self, company: str) -> None:
        with self._lock:
            self._gen[company] = self._gen.get(company, 0) + 1
            self._cache.pop(company, None)

    def meta(self, key: str) -> str | None:
        with self.main.connect() as db:
            row = db.execute("SELECT value FROM ext_meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def set_meta(self, key: str, value: str) -> None:
        with self.main.connect() as db:
            db.execute("INSERT INTO ext_meta(key, value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                       (key, value))

    @staticmethod
    def _row(r) -> dict:
        d = dict(r)
        d["mapping"] = json.loads(d.get("mapping") or "[]")
        d["enabled"] = bool(d.get("enabled"))
        return d

    @staticmethod
    def public(d: dict) -> dict:
        out = {k: v for k, v in d.items() if k != "secret"}
        out["secret_set"] = bool(d.get("secret"))
        out["topic"] = f"wiotx/{d['company']}/{d['device_id']}/up" if d["protocol"] == "mqtt" else None
        return out

    def list(self, company: str) -> list[dict]:
        return list(self._load(company).values())

    def get(self, company: str, device_id: str) -> dict | None:
        return self._load(company).get(device_id)

    def by_eui(self, company: str, eui: str | None) -> dict | None:
        try:
            eui = check_dev_eui(eui)
        except ValueError:
            return None
        if not eui:
            return None
        return next((d for d in self._load(company).values() if d.get("dev_eui") == eui), None)

    def secret_of(self, device: dict) -> str | None:
        try:
            return unseal(self._secret, device["secret"]) if device.get("secret") else None
        except ValueError:
            return None

    def _clean(self, data: dict, current: dict | None) -> dict:
        merged = {**(current or {}), **data}          # callers pass only the fields that were sent
        protocol = merged.get("protocol") or "mqtt"
        if protocol not in PROTOCOLS:
            raise ValueError("Protocol must be mqtt or lorawan")
        auth = merged.get("auth") or "hmac"
        if protocol == "mqtt" and auth not in AUTH_MODES:
            raise ValueError("Security must be hmac (signed) or none (unsigned)")
        name = _text(merged.get("name"), 80, "Name")
        if not name:
            raise ValueError("Give the device a name")
        eui = check_dev_eui(merged.get("dev_eui"))
        if protocol == "lorawan" and not eui:
            raise ValueError("LoRaWAN devices need their DevEUI")
        region = merged.get("region") or None
        if region:
            region_id(region)
        lat, lon = _point(merged.get("lat"), merged.get("lon"))
        try:
            interval = int(merged.get("interval_s") or 900)
        except (TypeError, ValueError) as exc:
            raise ValueError("Reporting interval must be a whole number of seconds") from exc
        if not 10 <= interval <= 86400:
            raise ValueError("Reporting interval must be 10 s .. 24 h")
        return {"name": name, "protocol": protocol, "auth": auth if protocol == "mqtt" else "source",
                "dev_eui": eui if protocol == "lorawan" else None, "region": region,
                "model": _text(merged.get("model"), 80, "Model"), "lat": lat, "lon": lon,
                "mapping": check_mapping(merged.get("mapping")), "interval_s": interval,
                "enabled": merged.get("enabled") is not False, "notes": _text(merged.get("notes"), 500, "Notes")}

    def create(self, company: str, data: dict, actor: str) -> tuple[dict, str | None]:
        company_id(company)
        device_id = check_device_id(data.get("device_id"))
        clean = self._clean(data, None)
        if len(self._load(company)) >= MAX_DEVICES:
            raise ValueError(f"At most {MAX_DEVICES} third-party devices per company")
        secret = secrets.token_urlsafe(32) if clean["protocol"] == "mqtt" and clean["auth"] == "hmac" else None
        now = int(time.time())
        try:
            with self.main.connect() as db:
                db.execute(
                    "INSERT INTO ext_devices(company,device_id,name,protocol,auth,secret,dev_eui,region,model,lat,lon,"
                    "mapping,interval_s,enabled,notes,created_at,created_by,updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (company, device_id, clean["name"], clean["protocol"], clean["auth"],
                     seal(self._secret, secret) if secret else None, clean["dev_eui"], clean["region"], clean["model"],
                     clean["lat"], clean["lon"], json.dumps(clean["mapping"]), clean["interval_s"],
                     int(clean["enabled"]), clean["notes"], now, actor, now))
        except sqlite3.IntegrityError as exc:
            raise ValueError("A device with this ID or DevEUI is already registered") from exc
        finally:
            self._forget(company)
        return self.get(company, device_id), secret

    def update(self, company: str, device_id: str, data: dict) -> tuple[dict, str | None]:
        current = self.get(company, device_id)
        if current is None:
            raise LookupError("Unknown device")
        clean = self._clean(data, current)
        secret, sealed = None, current.get("secret")
        if clean["protocol"] != "mqtt" or clean["auth"] != "hmac":
            sealed = None
        elif not sealed:                       # switched to signed: issue a secret now
            secret = secrets.token_urlsafe(32)
            sealed = seal(self._secret, secret)
        try:
            with self.main.connect() as db:
                db.execute("UPDATE ext_devices SET name=?,protocol=?,auth=?,secret=?,dev_eui=?,region=?,model=?,lat=?,lon=?,"
                           "mapping=?,interval_s=?,enabled=?,notes=?,updated_at=? WHERE company=? AND device_id=?",
                           (clean["name"], clean["protocol"], clean["auth"], sealed, clean["dev_eui"], clean["region"],
                            clean["model"], clean["lat"], clean["lon"], json.dumps(clean["mapping"]), clean["interval_s"],
                            int(clean["enabled"]), clean["notes"], int(time.time()), company, device_id))
        except sqlite3.IntegrityError as exc:
            raise ValueError("Another device already uses this DevEUI") from exc
        finally:
            self._forget(company)
        return self.get(company, device_id), secret

    def rotate(self, company: str, device_id: str) -> str:
        device = self.get(company, device_id)
        if device is None:
            raise LookupError("Unknown device")
        if device["protocol"] != "mqtt" or device["auth"] != "hmac":
            raise ValueError("Only signed MQTT devices have a secret")
        secret = secrets.token_urlsafe(32)
        with self.main.connect() as db:
            db.execute("UPDATE ext_devices SET secret=?, updated_at=? WHERE company=? AND device_id=?",
                       (seal(self._secret, secret), int(time.time()), company, device_id))
        self._forget(company)
        return secret

    def delete(self, company: str, device_id: str) -> int:
        """Remove the device and its readings; returns the number of raw readings deleted."""
        try:
            with self.main.connect() as db:
                if not db.execute("DELETE FROM ext_devices WHERE company=? AND device_id=?", (company, device_id)).rowcount:
                    raise LookupError("Unknown device")
        finally:
            self._forget(company)
        with self.telemetry.connect(company, write=True) as db:
            n = db.execute("DELETE FROM ext_readings WHERE device_id=?", (device_id,)).rowcount
            db.execute("DELETE FROM ext_hourly WHERE device_id=?", (device_id,))
            db.execute("DELETE FROM ext_latest WHERE device_id=?", (device_id,))
        return n

    # ----------------------------------------------------------------- sources
    def create_source(self, company: str, name: str, kind: str, actor: str) -> dict:
        company_id(company)
        if kind not in SOURCE_KINDS:
            raise ValueError("Network server must be ttn or chirpstack")
        name = _text(name, 80, "Name")
        if not name:
            raise ValueError("Give the connection a name")
        key = SOURCE_PREFIX + secrets.token_urlsafe(32)
        now = int(time.time())
        with self.main.connect() as db:
            cur = db.execute("INSERT INTO ext_sources(company,name,kind,key_hash,prefix,created_by,created_at) "
                             "VALUES(?,?,?,?,?,?,?)", (company, name, kind, _hash(key), key[:14], actor, now))
        return {"id": cur.lastrowid, "key": key, "prefix": key[:14], "name": name, "kind": kind, "company": company,
                "created_at": now}

    def list_sources(self, company: str) -> list[dict]:
        with self.main.connect() as db:
            return [dict(r) for r in db.execute(
                "SELECT id, company, name, kind, prefix, created_by, created_at, last_used_at, revoked_at, uplinks "
                "FROM ext_sources WHERE company=? ORDER BY id DESC", (company,))]

    def revoke_source(self, company: str, source_id: int) -> None:
        with self.main.connect() as db:
            if not db.execute("UPDATE ext_sources SET revoked_at=? WHERE id=? AND company=? AND revoked_at IS NULL",
                              (int(time.time()), source_id, company)).rowcount:
                raise LookupError("Unknown or already revoked connection")

    def resolve_source(self, key: str) -> dict | None:
        if not key or not key.startswith(SOURCE_PREFIX) or len(key) > 120:
            return None
        with self.main.connect() as db:
            row = db.execute("SELECT * FROM ext_sources WHERE key_hash=?", (_hash(key),)).fetchone()
            if row is None or row["revoked_at"]:
                return None
            db.execute("UPDATE ext_sources SET uplinks=uplinks+1, last_used_at=? WHERE id=?", (int(time.time()), row["id"]))
            return dict(row)

    # ---------------------------------------------------------------- readings
    def save(self, company: str, device_id: str, ts: int, received_at: int, values: dict[str, float],
             trusted: bool, source: str) -> int:
        """Store one uplink; duplicates (same device, metric and time) are ignored. Returns rows added."""
        added = 0
        hour = ts - ts % 3600
        with self.telemetry.connect(company, write=True) as db:
            for metric, value in values.items():
                if metric not in METRICS:
                    continue
                cur = db.execute("INSERT OR IGNORE INTO ext_readings(device_id,metric,ts,received_at,value,trusted,source) "
                                 "VALUES(?,?,?,?,?,?,?)", (device_id, metric, ts, received_at, value, int(trusted), source))
                if not cur.rowcount:
                    continue
                added += 1
                db.execute("INSERT INTO ext_hourly(device_id,metric,hour,n,sum,min,max) VALUES(?,?,?,1,?,?,?) "
                           "ON CONFLICT(device_id,metric,hour) DO UPDATE SET n=n+1, sum=sum+excluded.sum, "
                           "min=MIN(min,excluded.min), max=MAX(max,excluded.max)", (device_id, metric, hour, value, value, value))
                db.execute("INSERT INTO ext_latest(device_id,metric,ts,received_at,value,trusted) VALUES(?,?,?,?,?,?) "
                           "ON CONFLICT(device_id,metric) DO UPDATE SET ts=excluded.ts, received_at=excluded.received_at, "
                           "value=excluded.value, trusted=excluded.trusted WHERE excluded.ts>=ext_latest.ts",
                           (device_id, metric, ts, received_at, value, int(trusted)))
        return added

    def latest(self, company: str) -> dict[str, dict]:
        """{device_id: {"last_seen": received_at, "measured_at": ts, "values": {metric: {...}}}}."""
        out: dict[str, dict] = {}
        with self.telemetry.connect(company) as db:
            for r in db.execute("SELECT device_id, metric, ts, received_at, value, trusted FROM ext_latest"):
                d = out.setdefault(r["device_id"], {"last_seen": 0, "measured_at": 0, "values": {}})
                d["values"][r["metric"]] = {"value": r["value"], "ts": r["ts"], "trusted": bool(r["trusted"])}
                d["last_seen"] = max(d["last_seen"], r["received_at"])
                d["measured_at"] = max(d["measured_at"], r["ts"])
        return out

    def last_ts(self, company: str, device_id: str) -> int | None:
        with self.telemetry.connect(company) as db:
            row = db.execute("SELECT MAX(ts) FROM ext_latest WHERE device_id=?", (device_id,)).fetchone()
        return row[0] if row and row[0] is not None else None

    def counts(self, company: str, since: int) -> dict[str, int]:
        with self.telemetry.connect(company) as db:
            return {r[0]: r[1] for r in db.execute(
                "SELECT device_id, COUNT(DISTINCT ts) FROM ext_readings WHERE ts>=? GROUP BY device_id", (since,))}

    def series(self, company: str, device_id: str, metric: str, since: int, until: int) -> dict:
        """Raw points up to 3 days; hourly mean/min/max for longer ranges."""
        if metric not in METRICS:
            raise ValueError("Unknown metric")
        with self.telemetry.connect(company) as db:
            if until - since <= 3 * 86400:
                rows = db.execute("SELECT ts, value FROM (SELECT ts, value FROM ext_readings WHERE device_id=? AND metric=? "
                                  "AND ts BETWEEN ? AND ? ORDER BY ts DESC LIMIT ?) ORDER BY ts",
                                  (device_id, metric, since, until, RAW_POINTS + 1)).fetchall()
                truncated = len(rows) > RAW_POINTS            # one extra row tells us; keep the newest points
                pts = [[r["ts"], r["value"]] for r in (rows[1:] if truncated else rows)]
                return {"resolution": "raw", "points": pts, "min": None, "max": None, "truncated": truncated}
            rows = db.execute("SELECT hour, n, sum, min, max FROM ext_hourly WHERE device_id=? AND metric=? "
                              "AND hour BETWEEN ? AND ? ORDER BY hour", (device_id, metric, since - since % 3600, until))
            pts, lo, hi = [], [], []
            for r in rows:
                pts.append([r["hour"] + 1800, r["sum"] / r["n"]])
                lo.append([r["hour"] + 1800, r["min"]])
                hi.append([r["hour"] + 1800, r["max"]])
            return {"resolution": "hourly", "points": pts, "min": lo, "max": hi}

    def apply_retention(self, company: str, days: int, now: int | None = None) -> int:
        """Delete raw readings older than ``days`` (0 = keep; minimum 365). Hourly summaries are kept."""
        if not days:
            return 0
        cutoff = int(time.time() if now is None else now) - max(int(days), MIN_RETENTION_DAYS) * 86400
        with self.telemetry.connect(company, write=True) as db:
            return db.execute("DELETE FROM ext_readings WHERE ts<?", (cutoff,)).rowcount
