"""Usage metering per company (R2.3, point 28) — the basis for service plans and billing.

Counted in memory as events happen and added to ``usage_daily`` (main database) by every maintenance cycle:
uplinks stored, uplink bytes (encrypted frame size on the air/satellite link), commands sent, API calls and
data exports. Each flush also records the day's active nodes and the company database size. Days are UTC.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone

COUNTERS = ("messages", "bytes", "commands", "api_calls", "exports")


def _day(ts: float | None = None) -> str:
    return datetime.fromtimestamp(time.time() if ts is None else ts, timezone.utc).strftime("%Y-%m-%d")


class UsageMeter:
    def __init__(self, main, telemetry):
        self.main = main
        self.telemetry = telemetry
        self._pending: dict[tuple[str, str], dict[str, int]] = {}
        self._lock = threading.Lock()

    def init_schema(self) -> None:
        with self.main.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS usage_daily (company TEXT NOT NULL, day TEXT NOT NULL, "
                       "messages INTEGER NOT NULL DEFAULT 0, bytes INTEGER NOT NULL DEFAULT 0, "
                       "commands INTEGER NOT NULL DEFAULT 0, api_calls INTEGER NOT NULL DEFAULT 0, "
                       "exports INTEGER NOT NULL DEFAULT 0, nodes_active INTEGER NOT NULL DEFAULT 0, "
                       "storage_bytes INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (company, day))")

    def backfill(self) -> int:
        """Once: fill uplinks and active nodes per day from the stored messages (history before metering)."""
        with self.main.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS usage_meta (key TEXT PRIMARY KEY, value TEXT)")
            if db.execute("SELECT 1 FROM usage_meta WHERE key='backfilled'").fetchone():
                return 0
            db.execute("INSERT INTO usage_meta(key, value) VALUES('backfilled', ?)", (_day(),))
        rows = 0
        for company in self.main.company_names():
            try:
                with self.telemetry.connect(company) as tdb:
                    days = tdb.execute("SELECT strftime('%Y-%m-%d', timestamp, 'unixepoch') AS d, COUNT(*), "
                                       "COUNT(DISTINCT region || '/' || node_id) FROM messages "
                                       "WHERE type IN ('Status','Telemetry') GROUP BY d").fetchall()
            except Exception:
                continue
            with self.main.connect() as db:
                db.executemany("INSERT OR IGNORE INTO usage_daily(company, day, messages, nodes_active) VALUES(?,?,?,?)",
                               [(company, d, n, a) for d, n, a in days if d])
            rows += len(days)
        return rows

    def count(self, company: str | None, counter: str, n: int = 1, ts: float | None = None) -> None:
        if not company or counter not in COUNTERS:
            return
        with self._lock:
            row = self._pending.setdefault((company, _day(ts)), dict.fromkeys(COUNTERS, 0))
            row[counter] += int(n)

    def flush(self, now: float | None = None) -> int:
        with self._lock:
            pending, self._pending = self._pending, {}
        today = _day(now)
        companies = set(self.main.company_names())
        with self.main.connect() as db:
            for (company, day), c in pending.items():
                db.execute("INSERT INTO usage_daily(company, day, messages, bytes, commands, api_calls, exports) "
                           "VALUES(?,?,?,?,?,?,?) ON CONFLICT(company, day) DO UPDATE SET "
                           "messages=messages+excluded.messages, bytes=bytes+excluded.bytes, "
                           "commands=commands+excluded.commands, api_calls=api_calls+excluded.api_calls, "
                           "exports=exports+excluded.exports", (company, day, *(c[k] for k in COUNTERS)))
            for company in companies:
                active, size = self._snapshot(company, now)
                db.execute("INSERT INTO usage_daily(company, day, nodes_active, storage_bytes) VALUES(?,?,?,?) "
                           "ON CONFLICT(company, day) DO UPDATE SET nodes_active=MAX(nodes_active, excluded.nodes_active), "
                           "storage_bytes=excluded.storage_bytes", (company, today, active, size))
        return len(pending)

    def _snapshot(self, company: str, now: float | None) -> tuple[int, int]:
        start = int((time.time() if now is None else now) // 86400 * 86400)
        try:
            with self.telemetry.connect(company) as db:
                active = db.execute("SELECT COUNT(DISTINCT region || '/' || node_id) FROM messages "
                                    "WHERE timestamp>=? AND type IN ('Status','Telemetry')", (start,)).fetchone()[0]
            path = self.telemetry.path_for(company)
            size = sum(p.stat().st_size for p in path.parent.glob(path.name + "*")) if path.exists() else 0
        except Exception:
            return 0, 0
        return int(active or 0), int(size)

    def report(self, company: str | None, days: int = 90, now: float | None = None) -> dict:
        self.flush(now)
        since = _day((time.time() if now is None else now) - days * 86400)
        q, params = "SELECT * FROM usage_daily WHERE day>=?", [since]
        if company:
            q += " AND company=?"
            params.append(company)
        with self.main.connect() as db:
            rows = [dict(r) for r in db.execute(q + " ORDER BY day, company", params)]
        months: dict[tuple[str, str], dict] = {}
        for r in rows:
            m = months.setdefault((r["company"], r["day"][:7]), {"company": r["company"], "month": r["day"][:7],
                                                                 **dict.fromkeys(COUNTERS, 0), "nodes_active_max": 0,
                                                                 "storage_bytes": 0})
            for k in COUNTERS:
                m[k] += r[k]
            m["nodes_active_max"] = max(m["nodes_active_max"], r["nodes_active"])
            m["storage_bytes"] = max(m["storage_bytes"], r["storage_bytes"])
        return {"days": rows, "months": sorted(months.values(), key=lambda m: (m["month"], m["company"]))}
