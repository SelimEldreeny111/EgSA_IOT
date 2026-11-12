"""Persistent fleet alerts: at most one open alert per (company, region, node, kind).

An alert opens when a condition is first seen and resolves when it clears, so a server
restart neither forgets a silent node nor re-sends its webhook. Operators can
acknowledge an open alert (it stays open until the condition clears).
"""
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import closing
from pathlib import Path

from ..protocol.topics import region_id
from ..protocol.validation import company_id

SEVERITIES = ("critical", "warning", "info")


class AlertStore:
    def __init__(self, path: Path):
        self.path = Path(path)

    def _db(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        return db

    def init_schema(self) -> None:
        with closing(self._db()) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company TEXT NOT NULL, region TEXT NOT NULL, node_id INTEGER NOT NULL,
                    kind TEXT NOT NULL, severity TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'open',
                    opened_at INTEGER NOT NULL, updated_at INTEGER NOT NULL, resolved_at INTEGER,
                    acknowledged_by TEXT, acknowledged_at INTEGER,
                    details TEXT NOT NULL DEFAULT '{}');
                CREATE UNIQUE INDEX IF NOT EXISTS alerts_one_open
                    ON alerts(company, region, node_id, kind) WHERE state='open';
                CREATE INDEX IF NOT EXISTS alerts_by_company ON alerts(company, state, opened_at DESC);
            """)
            db.commit()

    @staticmethod
    def _row(row: sqlite3.Row | None) -> dict | None:
        if row is None:
            return None
        out = dict(row)
        out["details"] = json.loads(out["details"] or "{}")
        return out

    def open(self, company: str, region: str, node_id: int, kind: str, severity: str,
             details: dict, now: int | None = None) -> tuple[dict, bool]:
        """Open (or refresh) the alert; returns (alert, newly_opened)."""
        company_id(company)
        region_id(region)
        if severity not in SEVERITIES:
            raise ValueError("Unknown alert severity")
        now = int(time.time() if now is None else now)
        body = json.dumps(details, separators=(",", ":"), default=str)
        with closing(self._db()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT id FROM alerts WHERE company=? AND region=? AND node_id=? AND kind=? "
                             "AND state='open'", (company, region, int(node_id), kind)).fetchone()
            if row:
                db.execute("UPDATE alerts SET updated_at=?, details=?, severity=? WHERE id=?",
                           (now, body, severity, row["id"]))
                alert_id, created = row["id"], False
            else:
                alert_id = db.execute(
                    "INSERT INTO alerts(company,region,node_id,kind,severity,opened_at,updated_at,details) "
                    "VALUES(?,?,?,?,?,?,?,?)", (company, region, int(node_id), kind, severity, now, now, body)).lastrowid
                created = True
            alert = self._row(db.execute("SELECT * FROM alerts WHERE id=?", (alert_id,)).fetchone())
        return alert, created

    def resolve(self, company: str, region: str, node_id: int, kind: str, now: int | None = None) -> dict | None:
        """Close the open alert, if any; returns it (now resolved) or None."""
        now = int(time.time() if now is None else now)
        with closing(self._db()) as db, db:
            row = db.execute("SELECT id FROM alerts WHERE company=? AND region=? AND node_id=? AND kind=? "
                             "AND state='open'", (company, region, int(node_id), kind)).fetchone()
            if not row:
                return None
            db.execute("UPDATE alerts SET state='resolved', resolved_at=?, updated_at=? WHERE id=?",
                       (now, now, row["id"]))
            return self._row(db.execute("SELECT * FROM alerts WHERE id=?", (row["id"],)).fetchone())

    def get_open(self, company: str, region: str, node_id: int, kind: str) -> dict | None:
        with closing(self._db()) as db:
            return self._row(db.execute("SELECT * FROM alerts WHERE company=? AND region=? AND node_id=? AND kind=? "
                                        "AND state='open'", (company, region, int(node_id), kind)).fetchone())

    def is_open(self, company: str, region: str, node_id: int, kind: str) -> bool:
        with closing(self._db()) as db:
            return db.execute("SELECT 1 FROM alerts WHERE company=? AND region=? AND node_id=? AND kind=? "
                              "AND state='open'", (company, region, int(node_id), kind)).fetchone() is not None

    def acknowledge(self, company: str, alert_id: int, actor: str, now: int | None = None) -> dict:
        now = int(time.time() if now is None else now)
        with closing(self._db()) as db, db:
            row = db.execute("SELECT * FROM alerts WHERE id=? AND company=?", (int(alert_id), company)).fetchone()
            if row is None:
                raise LookupError("Alert not found")
            if row["state"] != "open":
                raise ValueError("Only open alerts can be acknowledged")
            if not row["acknowledged_at"]:
                db.execute("UPDATE alerts SET acknowledged_by=?, acknowledged_at=? WHERE id=?",
                           (str(actor)[:80], now, row["id"]))
            return self._row(db.execute("SELECT * FROM alerts WHERE id=?", (row["id"],)).fetchone())

    def list(self, company: str, *, status: str = "open", region: str | None = None,
             since: int | None = None, limit: int = 200) -> list[dict]:
        """Open alerts, or every alert opened or resolved since ``since`` (status='all')."""
        where, params = ["company=?"], [company]
        if region:
            where.append("region=?")
            params.append(region)
        if status == "open":
            where.append("state='open'")
        elif since is not None:
            where.append("(state='open' OR updated_at>=?)")
            params.append(int(since))
        order = ("CASE state WHEN 'open' THEN 0 ELSE 1 END, "
                 "CASE severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END, opened_at DESC")
        with closing(self._db()) as db:
            rows = db.execute(f"SELECT * FROM alerts WHERE {' AND '.join(where)} ORDER BY {order} LIMIT ?",
                              (*params, int(limit))).fetchall()
        return [self._row(r) for r in rows]

    def summary(self, company: str, now: int | None = None) -> dict:
        now = int(time.time() if now is None else now)
        with closing(self._db()) as db:
            r = db.execute("""SELECT
                    SUM(state='open') AS open,
                    SUM(state='open' AND severity='critical') AS critical,
                    SUM(state='open' AND severity='warning') AS warning,
                    SUM(state='open' AND acknowledged_at IS NULL) AS unacknowledged,
                    SUM(state='resolved' AND resolved_at>=?) AS resolved_24h
                FROM alerts WHERE company=?""", (now - 86400, company)).fetchone()
        return {k: int(r[k] or 0) for k in ("open", "critical", "warning", "unacknowledged", "resolved_24h")}
