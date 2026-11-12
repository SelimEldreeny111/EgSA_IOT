"""Per-tenant telemetry databases (``messages_dbs/<tenant>.db``).

Schema and migrations are carried over unchanged from v1.31 so existing
company databases open in place; v2 adds WAL journaling and read indexes.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, Iterator

from ..protocol.flow_schema import flow_meter_name, period_quality_name, period_source_name
from ..protocol.power import POWER_MODES, POWER_STATES
from ..protocol.tenancy import database_path, preflight
from ..protocol.topics import DEFAULT_REGION, migrate_region_storage, region_id
from ..protocol.validation import company_id

log = logging.getLogger(__name__)

MESSAGE_COLUMNS = (
    "timestamp", "type", "node_id", "sensor_id", "flow", "velocity", "flow_day", "flow_month",
    "flow_year", "details", "company", "node_status", "soil_temperature", "soil_moisture",
    "soil_moisture_temp_valid", "ec_temperature", "ec_moisture", "electrical_conductivity",
    "soil_moisture_temp_ec_valid", "active_sensor_count", "sensor_mask", "battery_voltage",
    "measured_at", "time_source", "flow_meter_type", "flow_period_source", "flow_live_valid",
    "flow_period_totals_valid", "flow_cumulative_totals_valid", "rtc_valid",
    "forward_total_liters", "reverse_total_liters", "net_total_liters", "flow_period_quality",
    "flow_meter_alarm_flags", "legacy_flow_schema", "secondary_flow_json", "power_mode",
    "power_state", "wake_remaining_seconds", "wake_command_ack", "wake_request_id",
    "wdt_reset_count", "power_reset_count", "region",
)

_MESSAGES_DDL = """CREATE TABLE IF NOT EXISTS messages
    (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp INTEGER, type TEXT, node_id INTEGER,
     sensor_id TEXT, flow REAL, velocity REAL, flow_day REAL, flow_month REAL, flow_year REAL,
     details TEXT, company TEXT, node_status INTEGER DEFAULT 0, soil_temperature REAL,
     soil_moisture REAL, soil_moisture_temp_valid INTEGER, ec_temperature REAL, ec_moisture REAL,
     electrical_conductivity REAL, soil_moisture_temp_ec_valid INTEGER, active_sensor_count INTEGER,
     sensor_mask INTEGER, battery_voltage REAL, measured_at INTEGER, time_source TEXT,
     flow_meter_type INTEGER DEFAULT 0, flow_period_source INTEGER DEFAULT 0,
     flow_live_valid INTEGER DEFAULT 0, flow_period_totals_valid INTEGER DEFAULT 0,
     flow_cumulative_totals_valid INTEGER DEFAULT 0, rtc_valid INTEGER DEFAULT 0,
     forward_total_liters INTEGER DEFAULT 0, reverse_total_liters INTEGER DEFAULT 0,
     net_total_liters INTEGER DEFAULT 0, flow_period_quality INTEGER DEFAULT 0,
     flow_meter_alarm_flags INTEGER DEFAULT 0, legacy_flow_schema INTEGER DEFAULT 0,
     secondary_flow_json TEXT, power_mode INTEGER DEFAULT 0, power_state INTEGER DEFAULT 0,
     wake_remaining_seconds INTEGER DEFAULT 0, wake_command_ack INTEGER DEFAULT 0,
     wake_request_id INTEGER DEFAULT 0, wdt_reset_count INTEGER DEFAULT 0,
     power_reset_count INTEGER DEFAULT 0, region TEXT NOT NULL DEFAULT 'Region_1')"""

_ADDITIVE_COLUMNS = (
    ("soil_temperature", "REAL"), ("soil_moisture", "REAL"), ("soil_moisture_temp_valid", "INTEGER"),
    ("ec_temperature", "REAL"), ("ec_moisture", "REAL"), ("electrical_conductivity", "REAL"),
    ("soil_moisture_temp_ec_valid", "INTEGER"), ("active_sensor_count", "INTEGER"),
    ("sensor_mask", "INTEGER"), ("battery_voltage", "REAL"), ("measured_at", "INTEGER"),
    ("time_source", "TEXT"), ("flow_meter_type", "INTEGER DEFAULT 0"),
    ("flow_period_source", "INTEGER DEFAULT 0"), ("flow_live_valid", "INTEGER DEFAULT 0"),
    ("flow_period_totals_valid", "INTEGER DEFAULT 0"),
    ("flow_cumulative_totals_valid", "INTEGER DEFAULT 0"), ("rtc_valid", "INTEGER DEFAULT 0"),
    ("forward_total_liters", "INTEGER DEFAULT 0"), ("reverse_total_liters", "INTEGER DEFAULT 0"),
    ("net_total_liters", "INTEGER DEFAULT 0"), ("flow_period_quality", "INTEGER DEFAULT 0"),
    ("flow_meter_alarm_flags", "INTEGER DEFAULT 0"), ("legacy_flow_schema", "INTEGER DEFAULT 0"),
    ("secondary_flow_json", "TEXT"), ("power_mode", "INTEGER DEFAULT 0"),
    ("power_state", "INTEGER DEFAULT 0"), ("wake_remaining_seconds", "INTEGER DEFAULT 0"),
    ("wdt_reset_count", "INTEGER DEFAULT 0"), ("power_reset_count", "INTEGER DEFAULT 0"),
    ("wake_command_ack", "INTEGER DEFAULT 0"), ("wake_request_id", "INTEGER DEFAULT 0"),
)

_METER_DDL = """CREATE TABLE IF NOT EXISTS meter_samples
    (id INTEGER PRIMARY KEY AUTOINCREMENT, received_at INTEGER NOT NULL,
     measured_at INTEGER NOT NULL, time_source TEXT NOT NULL, message_type TEXT NOT NULL,
     node_id INTEGER NOT NULL, sensor_id TEXT NOT NULL, flow_meter_type INTEGER NOT NULL,
     flow_rate REAL, velocity REAL, volume_day REAL, volume_month REAL, volume_year REAL,
     forward_total_liters INTEGER, reverse_total_liters INTEGER, net_total_liters INTEGER,
     flow_live_valid INTEGER NOT NULL, period_totals_valid INTEGER NOT NULL,
     cumulative_totals_valid INTEGER NOT NULL, rtc_valid INTEGER NOT NULL,
     period_source INTEGER NOT NULL, period_quality INTEGER NOT NULL,
     alarm_flags INTEGER NOT NULL, sample_fingerprint TEXT NOT NULL UNIQUE)"""

_PERIODS_DDL = """CREATE TABLE IF NOT EXISTS consumption_periods
    (id INTEGER PRIMARY KEY AUTOINCREMENT, node_id INTEGER NOT NULL, sensor_id TEXT NOT NULL,
     flow_meter_type INTEGER NOT NULL, period_type TEXT NOT NULL, period_key TEXT NOT NULL,
     volume_liters INTEGER NOT NULL, source INTEGER NOT NULL, quality INTEGER NOT NULL,
     measured_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
     UNIQUE(node_id, sensor_id, flow_meter_type, period_type, period_key))"""

# Series metrics exposed to the dashboard: name -> (SQL expression, validity filter)
SERIES_METRICS: dict[str, tuple[str, str]] = {
    "flow": ("flow", "COALESCE(flow_live_valid,0)=1"),
    "velocity": ("velocity", "COALESCE(flow_live_valid,0)=1"),
    "battery_voltage": ("battery_voltage", "battery_voltage IS NOT NULL AND battery_voltage>0"),
    "soil_temperature": ("soil_temperature", "COALESCE(soil_moisture_temp_valid,0)=1"),
    "soil_moisture": ("soil_moisture", "COALESCE(soil_moisture_temp_valid,0)=1"),
    "ec_temperature": ("ec_temperature", "COALESCE(soil_moisture_temp_ec_valid,0)=1"),
    "ec_moisture": ("ec_moisture", "COALESCE(soil_moisture_temp_ec_valid,0)=1"),
    "electrical_conductivity": ("electrical_conductivity", "COALESCE(soil_moisture_temp_ec_valid,0)=1"),
    "flow_day": ("flow_day", "COALESCE(flow_period_totals_valid,0)=1"),
}


def _to_epoch(value) -> int:
    if value is None or value == "":
        return int(time.time())
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip()
    if text.lstrip("-").isdigit():
        return int(text)
    for parser in (lambda s: datetime.strptime(s, "%Y-%m-%d %H:%M:%S"), datetime.fromisoformat):
        try:
            return int(parser(text).timestamp())
        except ValueError:
            continue
    raise ValueError(f"Invalid timestamp: {text[:40]}")


def decorate_row(row: dict) -> dict:
    """Add display/derived fields to a raw ``messages`` row."""
    epoch = int(row.get("timestamp") or 0)
    row["timestamp_epoch"] = epoch
    row["received_iso"] = datetime.fromtimestamp(epoch).isoformat(timespec="seconds") if epoch else None
    row["power_mode_name"] = POWER_MODES.get(row.get("power_mode") or 0, "Unknown")
    row["power_state_name"] = POWER_STATES.get(row.get("power_state") or 0, "Unknown")
    row["flow_meter_name"] = flow_meter_name(row.get("flow_meter_type") or 0)
    raw = row.pop("secondary_flow_json", None)
    try:
        row["secondary_flow_meter"] = json.loads(raw) if raw else None
    except json.JSONDecodeError:
        row["secondary_flow_meter"] = None
    return row


class TelemetryStore:
    def __init__(self, messages_dir: Path, companies: Callable[[], list[str]]):
        self.messages_dir = Path(messages_dir)
        self._companies = companies
        self._ready: set[str] = set()
        self._lock = threading.Lock()

    # --------------------------------------------------------------- plumbing
    def preflight(self) -> list[dict]:
        return preflight(self._companies(), str(self.messages_dir))

    def path_for(self, company: str) -> Path:
        company_id(company)
        return Path(database_path(company, str(self.messages_dir), self._companies()))

    @contextmanager
    def connect(self, company: str, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        path = self.ensure(company) if write else self.path_for(company)
        if not write and not path.exists():
            path = self.ensure(company)
        db = sqlite3.connect(path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            yield db
            if write:
                db.commit()
        except Exception:
            if write:
                db.rollback()
            raise
        finally:
            db.close()

    def ensure(self, company: str) -> Path:
        path = self.path_for(company)
        if company in self._ready and path.exists():
            return path
        with self._lock:
            self.messages_dir.mkdir(parents=True, exist_ok=True)
            db = sqlite3.connect(path, timeout=10)
            try:
                self._migrate(db)
                db.commit()
            finally:
                db.close()
            self._ready.add(company)
        log.info("Tenant database ready: %s -> %s", company, path.name)
        return path

    @staticmethod
    def _migrate(db: sqlite3.Connection) -> None:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute(_MESSAGES_DDL)
        cols = {r[1].lower(): (r[2] or "").upper() for r in db.execute("PRAGMA table_info(messages)")}
        if cols.get("timestamp") != "INTEGER":
            raise RuntimeError("Legacy text-timestamp messages table: open it once with v1.31 to migrate")
        for name, ddl in _ADDITIVE_COLUMNS:
            if name not in cols:
                db.execute(f"ALTER TABLE messages ADD COLUMN {name} {ddl}")
        db.execute("UPDATE messages SET measured_at=timestamp WHERE measured_at IS NULL OR measured_at<=0")
        db.execute("UPDATE messages SET time_source='server_received' WHERE time_source IS NULL OR time_source=''")
        db.execute(_METER_DDL)
        db.execute("CREATE INDEX IF NOT EXISTS idx_meter_samples_node_time ON meter_samples(node_id, sensor_id, measured_at)")
        db.execute(_PERIODS_DDL)
        db.execute("CREATE INDEX IF NOT EXISTS idx_consumption_periods_lookup ON consumption_periods(node_id, sensor_id, period_type, period_key)")
        migrate_region_storage(db)
        db.execute("CREATE INDEX IF NOT EXISTS idx_v2_messages_time ON messages(region, timestamp)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_v2_messages_node_time ON messages(region, node_id, type, timestamp)")

    # ------------------------------------------------------------------ write
    def save_message(self, *, company: str, region: str, received_at: int, msg_type: str,
                     node_id: int, sensor_id, fields: dict, samples: Iterable[dict] = ()) -> None:
        """Persist one decoded message, its meter samples and period snapshots atomically."""
        region_id(region)
        row = {col: fields.get(col) for col in MESSAGE_COLUMNS}
        row.update(timestamp=int(received_at), type=msg_type, node_id=int(node_id),
                   sensor_id=str(sensor_id), company=company, region=region)
        row["measured_at"] = int(row["measured_at"] or received_at)
        row["time_source"] = row["time_source"] or "server_received"
        for key in ("flow", "velocity", "flow_day", "flow_month", "flow_year"):
            row[key] = row[key] if row[key] is not None else 0
        for key, default in (("node_status", 0), ("active_sensor_count", 1), ("sensor_mask", 1)):
            if row[key] is None:
                row[key] = default
        for key in MESSAGE_COLUMNS:
            if row[key] is None and key not in ("battery_voltage", "secondary_flow_json", "details"):
                row[key] = 0
        placeholders = ",".join("?" for _ in MESSAGE_COLUMNS)
        with self.connect(company, write=True) as db:
            db.execute(
                f"INSERT INTO messages ({','.join(MESSAGE_COLUMNS)}) VALUES ({placeholders})",
                tuple(row[c] for c in MESSAGE_COLUMNS),
            )
            for sample in samples:
                meta = sample["metadata"]
                if not meta.get("flow_meter_type") or not sample.get("fingerprint"):
                    continue
                db.execute(
                    """INSERT OR IGNORE INTO meter_samples
                       (received_at, measured_at, time_source, message_type, node_id, sensor_id,
                        flow_meter_type, flow_rate, velocity, volume_day, volume_month, volume_year,
                        forward_total_liters, reverse_total_liters, net_total_liters,
                        flow_live_valid, period_totals_valid, cumulative_totals_valid, rtc_valid,
                        period_source, period_quality, alarm_flags, sample_fingerprint, region)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (received_at, row["measured_at"], row["time_source"], msg_type, node_id,
                     str(sensor_id), meta["flow_meter_type"], sample["flow_rate"], sample["velocity"],
                     sample["volume_day"], sample["volume_month"], sample["volume_year"],
                     meta.get("forward_total_liters", 0), meta.get("reverse_total_liters", 0),
                     meta.get("net_total_liters", 0), meta.get("flow_live_valid", 0),
                     meta.get("flow_period_totals_valid", 0), meta.get("flow_cumulative_totals_valid", 0),
                     meta.get("rtc_valid", 0), meta.get("flow_period_source", 0),
                     meta.get("flow_period_quality", 0), meta.get("flow_meter_alarm_flags", 0),
                     sample["fingerprint"], region),
                )
                for period in sample.get("period_rows", ()):
                    db.execute(
                        """INSERT INTO consumption_periods
                           (region, node_id, sensor_id, flow_meter_type, period_type, period_key,
                            volume_liters, source, quality, measured_at, updated_at)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?)
                           ON CONFLICT(region, node_id, sensor_id, flow_meter_type, period_type, period_key)
                           DO UPDATE SET volume_liters=excluded.volume_liters, source=excluded.source,
                               quality=excluded.quality, measured_at=excluded.measured_at,
                               updated_at=excluded.updated_at
                           WHERE excluded.measured_at >= consumption_periods.measured_at""",
                        (region, node_id, str(sensor_id), meta["flow_meter_type"],
                         period["period_type"], period["period_key"], period["volume_liters"],
                         period["source"], period["quality"], row["measured_at"], received_at),
                    )

    # ------------------------------------------------------------------- read
    def _scoped_companies(self, company: str | None) -> list[str]:
        return [company] if company else self._companies()

    def query_messages(self, company: str | None, region: str, *, start=None, end=None,
                       msg_type: str | None = None, node_id: int | None = None,
                       limit: int = 50, offset: int = 0) -> tuple[list[dict], int]:
        start_ts = _to_epoch(start) if start not in (None, "") else 0
        end_ts = _to_epoch(end) if end not in (None, "") else 4102444799
        where = ["timestamp BETWEEN ? AND ?", "region = ?"]
        params: list = [start_ts, end_ts, region_id(region)]
        if msg_type:
            where.append("type = ?")
            params.append(msg_type)
        if node_id is not None:
            where.append("node_id = ?")
            params.append(node_id)
        clause = " AND ".join(where)
        companies = self._scoped_companies(company)
        total = 0
        rows: list[dict] = []
        for name in companies:
            with self.connect(name) as db:
                total += db.execute(f"SELECT COUNT(*) FROM messages WHERE {clause}", params).fetchone()[0]
                rows.extend(dict(r) for r in db.execute(
                    f"SELECT * FROM messages WHERE {clause} ORDER BY timestamp DESC, id DESC LIMIT ?",
                    [*params, offset + limit]))
        rows.sort(key=lambda r: (r["timestamp"] or 0, r["id"]), reverse=True)
        return [decorate_row(r) for r in rows[offset:offset + limit]], total

    def iter_export(self, company: str | None, region: str, start=None, end=None) -> Iterator[dict]:
        start_ts = _to_epoch(start) if start not in (None, "") else 0
        end_ts = _to_epoch(end) if end not in (None, "") else 4102444799
        for name in self._scoped_companies(company):
            with self.connect(name) as db:
                cursor = db.execute(
                    "SELECT * FROM messages WHERE timestamp BETWEEN ? AND ? AND region=? "
                    "ORDER BY timestamp DESC, id DESC", (start_ts, end_ts, region_id(region)))
                for row in cursor:
                    yield dict(row)

    def receive_times(self, company: str, region: str, node_id: int, start: int, end: int) -> list[int]:
        """Server receive times of one node's live uplinks (Status/Telemetry) in [start, end]."""
        with self.connect(company) as db:
            return [r[0] for r in db.execute(
                "SELECT timestamp FROM messages WHERE region=? AND node_id=? AND type IN ('Status','Telemetry') "
                "AND timestamp BETWEEN ? AND ? ORDER BY timestamp", (region_id(region), int(node_id), int(start), int(end)))]

    def flow_readings(self, company: str, region: str, node_id: int, since: int) -> dict[str, list[tuple[int, float]]]:
        """Live flow readings since ``since``, per sensor, in arrival order: {sensor: [(t, flow)]}."""
        out: dict[str, list[tuple[int, float]]] = {}
        with self.connect(company) as db:
            for t, sensor, flow in db.execute(
                    "SELECT timestamp, sensor_id, flow FROM messages WHERE region=? AND node_id=? "
                    "AND type IN ('Status','Telemetry') AND timestamp>=? AND flow IS NOT NULL ORDER BY id",
                    (region_id(region), int(node_id), int(since))):
                out.setdefault(str(sensor), []).append((int(t), float(flow)))
        return out

    def valve_flow_readings(self, company: str, region: str, node_id: int, since: int) -> list[dict]:
        """Live uplinks since ``since`` with the valve state and primary flow, oldest first.

        ``valve`` is the commanded valve state the node reports (0 closed, 1 open, 2 unknown,
        3 fault); ``flow_valid`` is the live-flow validity flag; ``meter`` is True when the
        sensor mask includes a flow meter (TUF bit 1 or Supmea bit 8)."""
        with self.connect(company) as db:
            rows = db.execute(
                "SELECT timestamp, node_status, flow, flow_live_valid, sensor_mask FROM messages "
                "WHERE region=? AND node_id=? AND type='Status' AND timestamp>=? ORDER BY id",
                (region_id(region), int(node_id), int(since))).fetchall()
        return [{"t": int(r[0]), "valve": int(r[1] or 0), "flow": float(r[2] or 0.0),
                 "flow_valid": bool(r[3]), "meter": bool(int(r[4] or 0) & 0x09)} for r in rows]

    def valve_seen_open(self, company: str, region: str, node_id: int, since: int) -> bool:
        """Has the node reported an open valve since ``since`` (evidence that it drives one)?"""
        with self.connect(company) as db:
            return db.execute("SELECT 1 FROM messages WHERE region=? AND node_id=? AND type='Status' "
                              "AND node_status=1 AND timestamp>=? LIMIT 1",
                              (region_id(region), int(node_id), int(since))).fetchone() is not None

    def latest_power_mode(self, company: str, region: str, node_id: int) -> int | None:
        """Power mode reported in the node's latest uplink (wire value), or None."""
        with self.connect(company) as db:
            row = db.execute("SELECT power_mode FROM messages WHERE region=? AND node_id=? "
                             "AND type IN ('Status','Telemetry') ORDER BY id DESC LIMIT 1",
                             (region_id(region), int(node_id))).fetchone()
        return int(row[0]) if row and row[0] else None

    def regions(self, company: str) -> list[str]:
        with self.connect(company) as db:
            found = {r[0] for r in db.execute("SELECT DISTINCT region FROM messages")}
        return sorted(found | {DEFAULT_REGION})

    def fleet(self, company: str, region: str) -> list[dict]:
        """Latest reading and uplink statistics for every node of one tenant/region."""
        region_id(region)
        now = int(time.time())
        with self.connect(company) as db:
            latest = [dict(r) for r in db.execute(
                """SELECT m.* FROM messages m JOIN (
                       SELECT node_id, MAX(id) AS max_id FROM messages
                       WHERE type IN ('Status','Telemetry') AND region=? GROUP BY node_id
                   ) l ON m.id = l.max_id ORDER BY m.node_id""", (region,))]
            stats = {r["node_id"]: dict(r) for r in db.execute(
                """SELECT node_id, COUNT(*) AS uplinks_24h, MIN(timestamp) AS first_24h
                   FROM messages WHERE type IN ('Status','Telemetry') AND region=? AND timestamp>=?
                   GROUP BY node_id""", (region, now - 86400))}
            totals = {r["node_id"]: dict(r) for r in db.execute(
                """SELECT node_id, COUNT(*) AS uplinks_total, MIN(timestamp) AS first_seen
                   FROM messages WHERE type IN ('Status','Telemetry') AND region=? GROUP BY node_id""",
                (region,))}
            intervals: dict[int, float] = {}
            for node in latest:
                ts = [r[0] for r in db.execute(
                    """SELECT timestamp FROM messages WHERE region=? AND node_id=?
                       AND type IN ('Status','Telemetry') ORDER BY id DESC LIMIT 25""",
                    (region, node["node_id"]))]
                gaps = sorted(a - b for a, b in zip(ts, ts[1:]) if a - b > 0)
                intervals[node["node_id"]] = gaps[len(gaps) // 2] if gaps else 0
        fleet = []
        for node in latest:
            nid = node["node_id"]
            decorate_row(node)
            age = now - (node["timestamp"] or 0)
            expected = max(intervals.get(nid) or 60, 30)
            node["last_seen_age_s"] = age
            node["median_interval_s"] = intervals.get(nid) or None
            node["link_state"] = ("online" if age <= 2.5 * expected
                                  else "late" if age <= 6 * expected else "offline")
            node.update(stats.get(nid, {"uplinks_24h": 0}))
            node.update(totals.get(nid, {}))
            fleet.append(node)
        return fleet

    def node_history(self, company: str, region: str, node_id: int, limit: int = 120) -> list[dict]:
        with self.connect(company) as db:
            rows = [dict(r) for r in db.execute(
                """SELECT * FROM messages WHERE node_id=? AND region=? AND type IN ('Status','Telemetry')
                   ORDER BY timestamp DESC, id DESC LIMIT ?""", (node_id, region_id(region), limit))]
        return [decorate_row(r) for r in reversed(rows)]

    def series(self, company: str, region: str, node_id: int, metric: str,
               start: int, end: int, bucket_s: int) -> list[list]:
        if metric not in SERIES_METRICS:
            raise ValueError(f"Unknown metric; choose one of {', '.join(SERIES_METRICS)}")
        expr, valid = SERIES_METRICS[metric]
        bucket_s = max(1, int(bucket_s))
        with self.connect(company) as db:
            rows = db.execute(
                f"""SELECT (measured_at / ?) * ? AS t, AVG({expr}) AS avg, MIN({expr}) AS lo,
                           MAX({expr}) AS hi, COUNT(*) AS n
                    FROM messages WHERE node_id=? AND region=? AND type IN ('Status','Telemetry')
                      AND measured_at BETWEEN ? AND ? AND {valid}
                    GROUP BY t ORDER BY t""",
                (bucket_s, bucket_s, node_id, region_id(region), start, end)).fetchall()
        return [[r["t"], r["avg"], r["lo"], r["hi"], r["n"]] for r in rows]

    def consumption(self, company: str, region: str, *, period: str | None = None,
                    node_id: int | None = None, flow_meter_type: int | None = None) -> list[dict]:
        query = "SELECT * FROM consumption_periods WHERE region=?"
        params: list = [region_id(region)]
        if node_id is not None:
            query += " AND node_id=?"
            params.append(node_id)
        if flow_meter_type is not None:
            query += " AND flow_meter_type=?"
            params.append(flow_meter_type)
        if period:
            query += " AND period_type=?"
            params.append(period)
        query += " ORDER BY period_key DESC, measured_at DESC LIMIT 1000"
        with self.connect(company) as db:
            rows = [dict(r) for r in db.execute(query, params)]
        for row in rows:
            row["volume_m3"] = row["volume_liters"] / 1000.0
            row["flow_meter_name"] = flow_meter_name(row["flow_meter_type"])
            row["source_name"] = period_source_name(row["source"])
            row["quality_name"] = period_quality_name(row["quality"])
        return rows

    def activity(self, company: str | None, since: int) -> dict:
        """Counts used by live KPIs."""
        out = {"status": 0, "telemetry": 0, "command": 0, "nodes": 0}
        for name in self._scoped_companies(company):
            with self.connect(name) as db:
                for row in db.execute(
                        "SELECT type, COUNT(*) n FROM messages WHERE timestamp>=? GROUP BY type", (since,)):
                    key = (row["type"] or "").lower()
                    if key in out:
                        out[key] += row["n"]
                out["nodes"] += db.execute(
                    "SELECT COUNT(DISTINCT region||'/'||node_id) FROM messages "
                    "WHERE timestamp>=? AND type IN ('Status','Telemetry')", (since,)).fetchone()[0]
        return out

    def hourly_counts(self, company: str | None, since: int) -> list[list[int]]:
        buckets: dict[int, int] = {}
        for name in self._scoped_companies(company):
            with self.connect(name) as db:
                for row in db.execute(
                        "SELECT (timestamp/3600)*3600 AS h, COUNT(*) n FROM messages "
                        "WHERE timestamp>=? AND type IN ('Status','Telemetry') GROUP BY h", (since,)):
                    buckets[row["h"]] = buckets.get(row["h"], 0) + row["n"]
        return [[h, buckets[h]] for h in sorted(buckets)]
