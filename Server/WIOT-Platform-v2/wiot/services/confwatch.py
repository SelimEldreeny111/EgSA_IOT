"""Configuration watch: desired versus reported node intervals (R2.2, point 15).

Every Telemetry uplink carries the node's sampling and report intervals (firmware ``samplingPeriodMs`` and
``Transmission_rate``, in milliseconds). The *desired* value of each is the last SRATE / STRAN the node
acknowledged (command journal). When the node reports something else — after a reset to defaults, a manual
change on site, or a lost command — the watch queues the desired value again for the node's next wake.

Guards: only when ``WIOT_CONFIG_WATCH`` is on; only once an SRATE / STRAN was acknowledged (no guessing);
at most one correction per node and command per day (journal, so it survives restarts); none while a command
of the same type is still active; none during a flash history download. Each correction is audited as
``system:config-watch`` and counted in ``wiot_config_corrections_total``.
"""
from __future__ import annotations

import logging
import threading
import time

from .metrics import CONFIG_CORRECTIONS

log = logging.getLogger(__name__)

SYSTEM_ACTOR = "system:config-watch"
CORRECTION_INTERVAL_S = 86400
DESIRED_CACHE_S = 300


class ConfigWatch:
    def __init__(self, settings, commands, logs=None, audit=None):
        self.settings = settings
        self.commands = commands
        self.logs = logs
        self.audit = audit
        self._reported: dict[tuple, dict] = {}
        self._desired: dict[tuple, tuple[float, dict]] = {}
        self._lock = threading.Lock()

    def desired(self, company: str, region: str, node_id: int, cmd_type: str) -> dict | None:
        key = (company, region, int(node_id), cmd_type)
        hit = self._desired.get(key)
        if hit and time.monotonic() - hit[0] < DESIRED_CACHE_S:
            return hit[1]
        row = self.commands.journal.last_acknowledged(company, node_id, cmd_type, region=region)
        self._desired[key] = (time.monotonic(), row)
        return row

    def forget(self, company: str, region: str, node_id: int) -> None:
        """Drop cached desired values (a new SRATE/STRAN was acknowledged)."""
        for t in ("SRATE", "STRAN"):
            self._desired.pop((company, region, int(node_id), t), None)

    def state(self, company: str, region: str, node_id: int) -> dict:
        """Desired and reported intervals of one node, for the node-health view."""
        rep = self._reported.get((company, region, int(node_id)), {})
        out = {}
        for t, field in (("SRATE", "sampling_s"), ("STRAN", "report_s")):
            d = self.desired(company, region, node_id, t)
            out[field] = {"desired": int(d["cmd_data"]) if d else None, "reported": rep.get(t),
                          "drift": bool(d and rep.get(t) and int(d["cmd_data"]) != rep.get(t))}
        return out

    def observe(self, company: str, region: str, node_id: int, sampling_s: int, report_s: int,
                now: int | None = None) -> list[dict]:
        now = int(time.time() if now is None else now)
        with self._lock:
            self._reported[(company, region, int(node_id))] = {"SRATE": sampling_s or None, "STRAN": report_s or None}
        if not getattr(self.settings, "config_watch", False):
            return []
        actions = []
        for cmd_type, reported in (("SRATE", sampling_s), ("STRAN", report_s)):
            if not reported:
                continue
            want = self.desired(company, region, node_id, cmd_type)
            if not want:
                continue
            if int(want["cmd_data"]) == int(reported):
                continue
            done = self._correct(company, region, node_id, cmd_type, int(want["cmd_data"]), int(reported), now)
            if done:
                actions.append(done)
        return actions

    def _correct(self, company, region, node_id, cmd_type, desired, reported, now) -> dict | None:
        from .commands import CommandError, CommandRequest

        try:
            last = self.commands.journal.last_by_actor(company, node_id, cmd_type, SYSTEM_ACTOR, region=region)
            if last and now - last < CORRECTION_INTERVAL_S:
                return None
            if self.commands.has_active(company, region, node_id, cmd_type):
                return None
            if self.commands.flash_transfer and self.commands.flash_transfer(company, region, node_id, now):
                return None
            result = self.commands.submit(CommandRequest(company=company, region=region, node_id=node_id,
                                                         cmd_type=cmd_type, cmd_data=desired, delivery="next_wake",
                                                         ttl_seconds=86400), actor=SYSTEM_ACTOR)
        except CommandError as exc:
            log.info("Configuration correction for %s/%s/%s not queued: %s", company, region, node_id, exc)
            return None
        except Exception:
            log.exception("Configuration correction failed for %s/%s/%s", company, region, node_id)
            return None
        CONFIG_CORRECTIONS.inc()
        decision = {"cmd_type": cmd_type, "desired_s": desired, "reported_s": reported,
                    "request_id": result.get("request_id")}
        label = "sampling" if cmd_type == "SRATE" else "report"
        if self.logs is not None:
            self.logs.emit(f"[CONFIG] Node {node_id} reports a {label} interval of {reported} s instead of "
                           f"{desired} s; {cmd_type} {desired} queued for its next wake", company=company)
        if self.audit is not None:
            try:
                self.audit(SYSTEM_ACTOR, "config_correction_queued", company=company, target=f"{region}/{node_id}",
                           details=decision)
            except Exception:
                log.exception("Configuration watch audit entry failed")
        return decision
