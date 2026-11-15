"""Hourly and daily summaries of node readings, and raw-data retention (R2.2, point 10).

``rollups`` (in each tenant database) holds, per node, metric and hour or day: the number of valid readings
and their mean, minimum and maximum, for every metric of ``SERIES_METRICS``. ``update`` processes messages
added since the last run (``rollup_state.last_id``) and recomputes every hour and day they touch from the raw
rows, so late store-and-forward samples are folded in correctly. Charts over more than 7 days read the
summaries (``TelemetryStore.series``), so they stay fast however old the data is.

``apply_retention`` deletes raw messages and meter samples older than a company's retention period, but only
rows already summarised; consumption periods and summaries are kept forever.
"""
from __future__ import annotations

import sqlite3
import time

from .telemetry_store import SERIES_METRICS

GRAINS = {"hour": 3600, "day": 86400}
LONG_RANGE_S = 7 * 86400          # charts longer than this read the summaries
MIN_RETENTION_DAYS = 365          # SR-06: keep at least 12 months of data

_DDL = (
    """CREATE TABLE IF NOT EXISTS rollups (
           grain TEXT NOT NULL, region TEXT NOT NULL, node_id INTEGER NOT NULL, metric TEXT NOT NULL,
           t INTEGER NOT NULL, n INTEGER NOT NULL, avg REAL, lo REAL, hi REAL,
           PRIMARY KEY (grain, region, node_id, metric, t))""",
    "CREATE TABLE IF NOT EXISTS rollup_state (key TEXT PRIMARY KEY, value INTEGER NOT NULL)",
    "CREATE INDEX IF NOT EXISTS idx_v2_messages_node_measured ON messages(region, node_id, measured_at)",
)
_SELECT = ", ".join(
    f"SUM(CASE WHEN {valid} THEN 1 ELSE 0 END), AVG(CASE WHEN {valid} THEN {expr} END), "
    f"MIN(CASE WHEN {valid} THEN {expr} END), MAX(CASE WHEN {valid} THEN {expr} END)"
    for expr, valid in SERIES_METRICS.values())


def ensure_schema(db: sqlite3.Connection) -> None:
    for ddl in _DDL:
        db.execute(ddl)


def _state(db, key: str, default: int = 0) -> int:
    row = db.execute("SELECT value FROM rollup_state WHERE key=?", (key,)).fetchone()
    return int(row[0]) if row else default


def _set_state(db, key: str, value: int) -> None:
    db.execute("INSERT INTO rollup_state(key, value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
               (key, int(value)))


def update(store, company: str, max_rows: int = 200_000) -> dict:
    """Fold messages added since the last run into the hourly and daily summaries."""
    started = time.perf_counter()
    with store.connect(company, write=True) as db:
        ensure_schema(db)
        last = _state(db, "last_id")
        rows = db.execute("SELECT id, region, node_id, measured_at FROM messages WHERE id>? "
                          "AND type IN ('Status','Telemetry') ORDER BY id LIMIT ?", (last, max_rows)).fetchall()
        if not rows:
            return {"company": company, "messages": 0, "buckets": 0, "seconds": 0.0}
        buckets = {(grain, r[1], int(r[2]), (int(r[3] or 0) // size) * size)
                   for r in rows for grain, size in GRAINS.items()}
        for grain, region, node, t in buckets:
            size = GRAINS[grain]
            vals = db.execute(f"SELECT {_SELECT} FROM messages WHERE region=? AND node_id=? "
                              "AND type IN ('Status','Telemetry') AND measured_at>=? AND measured_at<?",
                              (region, node, t, t + size)).fetchone()
            for i, metric in enumerate(SERIES_METRICS):
                n, avg, lo, hi = vals[4 * i: 4 * i + 4]
                if n:
                    db.execute("INSERT OR REPLACE INTO rollups(grain, region, node_id, metric, t, n, avg, lo, hi) "
                               "VALUES(?,?,?,?,?,?,?,?,?)", (grain, region, node, metric, t, int(n), avg, lo, hi))
                else:
                    db.execute("DELETE FROM rollups WHERE grain=? AND region=? AND node_id=? AND metric=? AND t=?",
                               (grain, region, node, metric, t))
        _set_state(db, "last_id", rows[-1][0])
    return {"company": company, "messages": len(rows), "buckets": len(buckets),
            "seconds": round(time.perf_counter() - started, 3)}


def series(store, company: str, region: str, node_id: int, metric: str, start: int, end: int,
           bucket_s: int) -> list[list] | None:
    """Chart points from the summaries, or None when they cannot serve this request."""
    if end - start <= LONG_RANGE_S or bucket_s < 3600 or metric not in SERIES_METRICS:
        return None
    grain = "day" if bucket_s >= 86400 else "hour"
    with store.connect(company) as db:
        try:
            rows = db.execute(
                "SELECT (t / ?) * ? AS tb, SUM(avg * n) / SUM(n), MIN(lo), MAX(hi), SUM(n) FROM rollups "
                "WHERE grain=? AND region=? AND node_id=? AND metric=? AND t BETWEEN ? AND ? GROUP BY tb ORDER BY tb",
                (bucket_s, bucket_s, grain, region, int(node_id), metric, int(start), int(end))).fetchall()
        except sqlite3.OperationalError:
            return None                    # summaries not built yet
    return [[r[0], r[1], r[2], r[3], r[4]] for r in rows] if rows else None


def apply_retention(store, company: str, days: int, now: int | None = None) -> dict:
    """Delete summarised raw rows older than ``days`` (0 = keep forever; minimum 365 days)."""
    if not days:
        return {"company": company, "retention_days": 0, "messages_deleted": 0, "samples_deleted": 0}
    days = max(int(days), MIN_RETENTION_DAYS)
    cutoff = int(time.time() if now is None else now) - days * 86400
    with store.connect(company, write=True) as db:
        ensure_schema(db)
        last = _state(db, "last_id")
        msgs = db.execute("DELETE FROM messages WHERE timestamp<? AND id<=?", (cutoff, last)).rowcount
        samples = db.execute("DELETE FROM meter_samples WHERE received_at<?", (cutoff,)).rowcount
    with store.connect(company, write=True) as db:
        db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    return {"company": company, "retention_days": days, "messages_deleted": msgs, "samples_deleted": samples}
