"""Serves analysis artifacts, live KPIs and the command-delivery risk model."""
from __future__ import annotations

import json
import logging
import sqlite3
import subprocess
import sys
import threading
import time
from contextlib import closing
from pathlib import Path

from ..config import PROJECT_DIR, Settings
from ..storage.telemetry_store import TelemetryStore

log = logging.getLogger(__name__)
ARTIFACTS = ("summary", "link", "power", "sensors", "commands", "model", "firmware", "project")


class AnalyticsService:
    def __init__(self, settings: Settings, telemetry: TelemetryStore):
        self.settings = settings
        self.telemetry = telemetry
        self._cache: dict[str, tuple[float, dict]] = {}
        self._predictor = None
        self._predictor_mtime = 0.0
        self._lock = threading.Lock()
        self.job: dict = {"state": "idle"}

    @property
    def directory(self) -> Path:
        return self.settings.analytics_path

    # -------------------------------------------------------------- artifacts
    def artifact(self, name: str) -> dict:
        if name not in ARTIFACTS:
            raise LookupError("Unknown analytics artifact")
        path = self.directory / f"{name}.json"
        if not path.exists():
            raise LookupError(f"Artifact '{name}' has not been generated yet; run the analysis pipeline")
        mtime = path.stat().st_mtime
        cached = self._cache.get(name)
        if cached and cached[0] == mtime:
            return cached[1]
        data = json.loads(path.read_text(encoding="utf-8"))
        self._cache[name] = (mtime, data)
        return data

    def available(self) -> dict:
        out = {}
        for name in ARTIFACTS:
            path = self.directory / f"{name}.json"
            out[name] = int(path.stat().st_mtime) if path.exists() else None
        return out

    # -------------------------------------------------------------- predictor
    def predictor(self):
        model_path = self.directory / "model.joblib"
        if not model_path.exists():
            raise LookupError("Delivery-risk model not trained yet; run the analysis pipeline")
        mtime = model_path.stat().st_mtime
        with self._lock:
            if self._predictor is None or mtime != self._predictor_mtime:
                from ..analytics.predictor import CommandRiskPredictor  # heavy import, lazy
                self._predictor = CommandRiskPredictor.load(self.directory)
                self._predictor_mtime = mtime
            return self._predictor

    def predict_live(self, company: str, region: str, node_id: int, cmd_type: str) -> dict:
        predictor = self.predictor()
        result = predictor.predict_live(company, region, node_id, cmd_type, int(time.time()),
                                        str(self.settings.data_dir))
        return result

    def predict_features(self, features: dict) -> dict:
        return self.predictor().predict(features)

    def feature_schema(self) -> list:
        return self.predictor().feature_schema()

    # ------------------------------------------------------------- live KPIs
    def live_kpis(self, company: str | None) -> dict:
        now = int(time.time())
        activity = self.telemetry.activity(company, now - 86400)
        hourly = self.telemetry.hourly_counts(company, now - 48 * 3600)
        commands = self._command_stats(company, now - 7 * 86400)
        return {"generated_at": now, "window_hours": 24, "activity": activity,
                "hourly_uplinks": hourly, "commands_7d": commands}

    def _command_stats(self, company: str | None, since: int) -> dict:
        path = self.settings.command_db
        if not path.exists():
            return {}
        query = "SELECT state, COUNT(*) n FROM pending_commands WHERE created_at>=?"
        params: list = [since]
        if company:
            query += " AND company=?"
            params.append(company)
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
            counts = {row[0]: row[1] for row in db.execute(query + " GROUP BY state", params)}
        resolved = sum(counts.get(s, 0) for s in ("acknowledged", "rejected", "outcome_unknown"))
        return {"by_state": counts, "total": sum(counts.values()),
                "ack_rate": (counts.get("acknowledged", 0) / resolved) if resolved else None}

    # ---------------------------------------------------------------- retrain
    def start_retrain(self) -> dict:
        with self._lock:
            if self.job.get("state") == "running":
                return self.job
            self.job = {"state": "running", "started_at": time.time()}
        thread = threading.Thread(target=self._run_pipeline, name="wiot-analytics", daemon=True)
        thread.start()
        return self.job

    def _run_pipeline(self) -> None:
        repo_root = self.settings.repo_root or PROJECT_DIR.parent.parent
        source = self.settings.analytics_data_dir or self.settings.data_dir
        cmd = [sys.executable, "-m", "wiot.analytics.pipeline", "--data-dir", str(source),
               "--repo-root", str(repo_root), "--out", str(self.directory)]
        try:
            proc = subprocess.run(cmd, cwd=str(PROJECT_DIR), capture_output=True, text=True, timeout=1800)
            state = "succeeded" if proc.returncode == 0 else "failed"
            tail = (proc.stdout + proc.stderr)[-4000:]
        except Exception as exc:  # pragma: no cover - environment failure
            state, tail = "failed", f"{type(exc).__name__}: {exc}"
        self._cache.clear()
        self.job = {"state": state, "finished_at": time.time(), "output": tail,
                    "started_at": self.job.get("started_at")}
        log.info("Analytics pipeline finished: %s", state)
