"""System health, status history and the public status page (R2.2, points 7 and 8).

``snapshot`` is the supervisor's System health page: broker, ingestion per company, databases, disk, backups
and background threads, each with a level (ok / warning / critical) and a reason. ``sample`` records one
status row every 5 minutes in ``status_history`` (main database); ``public_status`` turns that history into
the availability shown on the public ``/status`` page, which exposes service health only — no company names,
node data or counts.
"""
from __future__ import annotations

import shutil
import sqlite3
import time
from pathlib import Path

from .. import __version__
from .metrics import BACKUP_AGE, DISK_FREE_RATIO, INGEST_AGE

LEVELS = {"ok": 0, "info": 0, "warning": 1, "critical": 2}
SAMPLE_EVERY_S = 300
GAP_CAP_S = 3 * SAMPLE_EVERY_S          # a sample covers at most 15 minutes; longer gaps count as down
STALE_INGEST_S = 1800
BACKUP_WARN_S = 36 * 3600


def _worst(levels) -> str:
    return max(levels, key=lambda lv: LEVELS.get(lv, 0), default="ok")


class SystemService:
    def __init__(self, runtime):
        self.rt = runtime
        self.started_at = time.time()
        self._last_sample = 0.0

    # ------------------------------------------------------------- schema
    def init_schema(self) -> None:
        with self.rt.main.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS status_history (ts INTEGER PRIMARY KEY, broker INTEGER NOT NULL, "
                       "ingest INTEGER NOT NULL, overall TEXT NOT NULL)")

    # ------------------------------------------------------------ helpers
    def backup_dir(self) -> Path:
        s = self.rt.settings
        return Path(s.backup_dir or (s.data_dir / "backups"))

    def latest_backup(self) -> dict | None:
        folder = self.backup_dir()
        files = sorted(folder.glob("wiot-backup-*"), key=lambda p: p.stat().st_mtime) if folder.exists() else []
        if not files:
            return None
        f = files[-1]
        return {"file": f.name, "bytes": f.stat().st_size, "at": int(f.stat().st_mtime),
                "encrypted": f.suffix == ".wbk", "count": len(files)}

    def _last_message(self, company: str) -> int | None:
        latest = [r["timestamp"] for (c, _, _), r in list(self.rt.telemetry.latest.items()) if c == company]
        if latest:
            return max(latest)
        try:
            with self.rt.telemetry.connect(company) as db:
                row = db.execute("SELECT MAX(timestamp) FROM messages").fetchone()
            return int(row[0]) if row and row[0] else None
        except sqlite3.Error:
            return None

    # ----------------------------------------------------------- snapshot
    def snapshot(self, now: int | None = None) -> dict:
        now = int(time.time() if now is None else now)
        rt, s = self.rt, self.rt.settings
        checks = []
        broker = rt.broker.status()
        if broker["ready"]:
            checks.append({"name": "Broker", "level": "ok", "detail": f"connected to {broker.get('host')}:{broker.get('port')}"})
        elif s.mqtt_autoconnect:
            checks.append({"name": "Broker", "level": "critical", "detail": f"not connected ({broker['state']})"})
        else:
            checks.append({"name": "Broker", "level": "info", "detail": "not connected (autoconnect is off)"})

        companies = []
        for company in rt.main.company_names():
            last = self._last_message(company)
            age = now - last if last else None
            level = "ok"
            if broker["ready"] and age is not None and STALE_INGEST_S < age < 7 * 86400:
                level = "warning"
            path = rt.telemetry.path_for(company)
            size = path.stat().st_size + sum(p.stat().st_size for p in path.parent.glob(path.name + "-*")) \
                if path.exists() else 0
            companies.append({"company": company, "last_message_at": last, "age_s": age, "db_bytes": size,
                              "level": level})
            if last:
                INGEST_AGE.labels(company).set(age)
        stale = [c["company"] for c in companies if c["level"] != "ok"]
        checks.append({"name": "Ingestion", "level": "warning" if stale else "ok",
                       "detail": f"no data for over {STALE_INGEST_S // 60} min: {', '.join(stale)}" if stale
                       else "data arriving normally"})

        usage = shutil.disk_usage(s.data_dir)
        free = usage.free / usage.total if usage.total else 1.0
        DISK_FREE_RATIO.set(free)
        checks.append({"name": "Disk", "level": "critical" if free < 0.05 else "warning" if free < 0.10 else "ok",
                       "detail": f"{usage.free / 1e9:.1f} GB free of {usage.total / 1e9:.1f} GB ({free:.0%})"})

        backup = self.latest_backup()
        if backup is None:
            checks.append({"name": "Backups", "level": "warning", "detail": f"no backup in {self.backup_dir()}"})
        else:
            b_age = now - backup["at"]
            BACKUP_AGE.set(b_age)
            checks.append({"name": "Backups", "level": "warning" if b_age > BACKUP_WARN_S else "ok",
                           "detail": f"last {backup['file']} ({b_age // 3600} h ago, "
                                     f"{'encrypted' if backup['encrypted'] else 'NOT encrypted'})"})

        threads = []
        if s.alert_monitor:
            alive = bool(rt.alerts._thread and rt.alerts._thread.is_alive())
            threads.append(("Alert monitor", alive, "critical"))
        maint = getattr(rt, "maintenance", None)
        if maint is not None and maint.enabled:
            threads.append(("Maintenance", maint.is_alive(), "warning"))
        for name, alive, bad in threads:
            checks.append({"name": name, "level": "ok" if alive else bad, "detail": "running" if alive else "stopped"})

        dbs = {}
        for label, path in (("main", s.main_db), ("command journal", s.command_db), ("flash archive", s.flash_db)):
            p = Path(path)
            dbs[label] = p.stat().st_size if p.exists() else 0
        return {"version": __version__, "env": s.env, "now": now, "uptime_s": int(time.time() - self.started_at),
                "overall": _worst(c["level"] for c in checks), "checks": checks, "broker": broker,
                "companies": companies, "databases": dbs, "backup": backup,
                "websockets": rt.hub.connections, "ingest_batch_ms": s.ingest_batch_ms}

    # ------------------------------------------------------------ history
    def sample(self, now: int | None = None, force: bool = False) -> dict | None:
        now = int(time.time() if now is None else now)
        if not force and now - self._last_sample < SAMPLE_EVERY_S - 10:     # a timer may wake a little early
            return None
        snap = self.snapshot(now)
        levels = {c["name"]: c["level"] for c in snap["checks"]}
        row = {"ts": now, "broker": int(levels.get("Broker") in ("ok", "info")),
               "ingest": int(levels.get("Ingestion") == "ok"), "overall": snap["overall"]}
        with self.rt.main.connect() as db:
            db.execute("INSERT OR REPLACE INTO status_history(ts, broker, ingest, overall) VALUES(?,?,?,?)",
                       (row["ts"], row["broker"], row["ingest"], row["overall"]))
            db.execute("DELETE FROM status_history WHERE ts<?", (now - 400 * 86400,))
        self._last_sample = now
        return row

    def history(self, days: int = 30, now: int | None = None) -> list[dict]:
        now = int(time.time() if now is None else now)
        with self.rt.main.connect() as db:
            rows = db.execute("SELECT ts, broker, ingest, overall FROM status_history WHERE ts>=? ORDER BY ts",
                              (now - days * 86400,)).fetchall()
        return [dict(r) for r in rows]

    def public_status(self, days: int = 30, now: int | None = None) -> dict:
        """Service health for the public page: per day, the share of time in which each component was up.

        A sample (taken every 5 minutes) stands for the time until the next sample, at most ``GAP_CAP_S``; a longer
        gap without samples means the platform itself was down. Counting covered time instead of samples keeps
        the result right for any sampling cadence up to the cap (older data was sampled every 10 minutes)."""
        now = int(time.time() if now is None else now)
        rows = self.history(days, now)
        snap = self.snapshot(now)
        levels = {c["name"]: c["level"] for c in snap["checks"]}
        per_day: dict[int, list[tuple[int, int, int]]] = {}
        for i, r in enumerate(rows):
            nxt = rows[i + 1]["ts"] if i + 1 < len(rows) else now
            per_day.setdefault(r["ts"] // 86400, []).append((max(0, min(nxt - r["ts"], GAP_CAP_S)), r["broker"], r["ingest"]))
        first = rows[0]["ts"] if rows else now
        out_days = []
        for d in range((now // 86400) - days + 1, now // 86400 + 1):
            day_start = d * 86400
            if day_start + 86400 <= first:
                continue                                  # before monitoring began
            span = max(1, min(now, day_start + 86400) - max(day_start, first))
            got = per_day.get(d, [])
            share = lambda secs: round(min(1.0, secs / span), 4)      # noqa: E731
            out_days.append({"day": day_start, "platform": share(sum(g[0] for g in got)),
                             "ingestion": share(sum(g[0] for g in got if g[2])),
                             "broker": share(sum(g[0] for g in got if g[1]))})
        current = {"platform": "operational",
                   "ingestion": "operational" if levels.get("Ingestion") == "ok" else "degraded",
                   "broker": "operational" if levels.get("Broker") in ("ok", "info") else "outage"}
        overall = ("operational" if all(v == "operational" for v in current.values())
                   else "outage" if current["broker"] == "outage" else "degraded")
        return {"overall": overall, "components": current, "days": out_days, "updated_at": now,
                "version": __version__}

    def ingest_age_values(self) -> dict:
        return {c: self._last_message(c) for c in self.rt.main.company_names()}
