"""Background maintenance (R2.2, point 10).

Every ``WIOT_MAINTENANCE_INTERVAL_S`` (default 10 min) one thread:

1. folds new readings into the hourly and daily summaries of every company (``storage.rollups.update``);
2. applies each company's raw-data retention (``companies.retention_days``, else ``WIOT_RETENTION_DAYS``;
   0 keeps everything, any other value is raised to the 365-day minimum) — once a day;
3. records a status sample for the public status page (``SystemService.sample``);
4. runs ``PRAGMA optimize`` on the tenant databases once a day.

``python -m wiot maintain [--vacuum]`` runs the same cycle once from the command line (stop the server first
for ``--vacuum``, which rewrites each database to return deleted space to the disk).
"""
from __future__ import annotations

import logging
import threading
import time

from ..storage import rollups
from .metrics import MAINTENANCE_RUNS

log = logging.getLogger(__name__)

DAILY_S = 86400


class Maintenance:
    def __init__(self, settings, telemetry, main, org=None, system=None):
        self.settings = settings
        self.telemetry = telemetry
        self.main = main
        self.org = org
        self.system = system
        self.enabled = True
        self.extra: list = []        # callables(report, daily) run every cycle (usage, integrations, reports)
        self.last_run: dict | None = None
        self._last_daily = 0.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="maintenance", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def is_alive(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def _loop(self) -> None:
        self._stop.wait(20)                       # let the server finish starting
        while not self._stop.is_set():
            try:
                self.run_once()
            except Exception:
                log.exception("Maintenance cycle failed")
            self._stop.wait(self.settings.maintenance_interval_s)

    def retention_days(self, company: str) -> int:
        days = None
        if self.org is not None:
            info = self.org.get_company(company) or {}
            days = info.get("retention_days")
        return int(days if days is not None else self.settings.retention_days or 0)

    def run_once(self, *, daily: bool | None = None, vacuum: bool = False, now: int | None = None) -> dict:
        with self._lock:
            started = time.perf_counter()
            now = int(time.time() if now is None else now)
            daily = (time.monotonic() - self._last_daily >= DAILY_S or not self._last_daily) if daily is None else daily
            report: dict = {"at": now, "rollups": [], "retention": [], "errors": []}
            self.telemetry.flush()
            for company in self.main.company_names():
                try:
                    report["rollups"].append(rollups.update(self.telemetry, company))
                    if daily:
                        report["retention"].append(rollups.apply_retention(
                            self.telemetry, company, self.retention_days(company), now))
                        with self.telemetry.connect(company, write=True) as db:
                            db.execute("PRAGMA optimize")
                    if vacuum:
                        with self.telemetry.connect(company, write=True) as db:
                            db.isolation_level = None
                            db.execute("VACUUM")
                except Exception as exc:                  # one tenant must not stop the others
                    log.exception("Maintenance failed for %s", company)
                    report["errors"].append({"company": company, "error": f"{type(exc).__name__}: {exc}"})
            if daily:
                self._last_daily = time.monotonic()
            for task in self.extra:
                try:
                    task(report, daily)
                except Exception as exc:
                    log.exception("Maintenance task failed")
                    report["errors"].append({"company": None, "error": f"{getattr(task, '__name__', 'task')}: {exc}"})
            if self.system is not None:
                try:
                    self.system.sample(now)
                except Exception as exc:
                    log.exception("Status sample failed")
                    report["errors"].append({"company": None, "error": f"status sample: {exc}"})
            report["seconds"] = round(time.perf_counter() - started, 3)
            report["daily"] = daily
            MAINTENANCE_RUNS.labels("error" if report["errors"] else "ok").inc()
            self.last_run = report
            return report
