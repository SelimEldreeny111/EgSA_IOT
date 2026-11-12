"""Automatic node clock synchronisation (R2.1, point 12).

A node journals samples and stamps its reports only while its RTC is trusted, and the RTC
(internal LSI oscillator) drifts: in the Oct-Nov 2026 data node clocks ran up to 30 minutes
ahead of the server. This service watches every Status uplink and queues an STIME command
(next-wake delivery, released right after the node's uplink) when

* the node reports that its clock is not trusted (``rtc_valid``/``sample_time_valid`` off), or
* the node's clock is off by more than ``WIOT_CLOCK_SYNC_DRIFT_S``.

Drift estimate: ``offset = receive_time - node_timestamp`` for each trusted Status. Reports of
stored samples arrive late on purpose (store-and-forward), so a single offset says little; the
smallest offset over the last readings is the clock error plus the shortest delivery delay.
A node is *ahead* when that minimum is below ``-drift``; it is *behind* when it exceeds
``drift + 2 x the node's report interval``.

Guards: one automatic STIME per node per ``WIOT_CLOCK_SYNC_MIN_INTERVAL_S`` (30 minutes for an
unset clock), none while an STIME is still pending for the node, none while a flash history
download is running (extra downlinks collide with its per-row ACKs), none when disabled.
Every automatic STIME goes through the command journal and the audit trail like an operator's.
"""
from __future__ import annotations

import logging
import statistics
import threading
import time
from collections import deque

log = logging.getLogger(__name__)

WINDOW = 10            # trusted readings kept per node
MIN_READINGS = 3       # readings needed before judging drift
UNSET_RETRY_S = 1800   # retry interval for a node whose clock is not set at all
SYSTEM_ACTOR = "system:clock-sync"


class ClockSync:
    def __init__(self, settings, commands, logs=None, audit=None):
        self.settings = settings
        self.commands = commands          # CommandService
        self.logs = logs                  # LogBuffer
        self.audit = audit                # callable(actor, action, company=, target=, details=)
        self._offsets: dict[tuple, deque] = {}
        self._arrivals: dict[tuple, deque] = {}
        self._last_sync: dict[tuple, int] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ input
    def observe(self, company: str, region: str, node_id: int, node_ts: int, trusted: bool,
                now: int | None = None) -> dict | None:
        """Record one Status; queue an STIME if needed. Returns the decision (or None)."""
        if not getattr(self.settings, "clock_sync", False) or not node_id:
            return None
        now = int(time.time() if now is None else now)
        key = (company, region, int(node_id))
        with self._lock:
            arrivals = self._arrivals.setdefault(key, deque(maxlen=WINDOW + 1))
            arrivals.append(now)
            if trusted and node_ts > 0:
                self._offsets.setdefault(key, deque(maxlen=WINDOW)).append(now - int(node_ts))
            decision = self._judge(key, trusted, now)
        if decision is None:
            return None
        return self._sync(key, decision, now)

    # ------------------------------------------------------------------ rules
    def _report_interval(self, key) -> float:
        arrivals = list(self._arrivals.get(key, ()))
        gaps = [b - a for a, b in zip(arrivals, arrivals[1:]) if b > a]
        return statistics.median(gaps) if gaps else 0.0

    def _judge(self, key, trusted: bool, now: int) -> dict | None:
        drift = int(self.settings.clock_sync_drift_s)
        if not trusted:
            if now - self._last_sync.get(key, 0) < UNSET_RETRY_S:
                return None
            return {"reason": "clock_unset"}
        offsets = self._offsets.get(key)
        if not offsets or len(offsets) < MIN_READINGS:
            return None
        if now - self._last_sync.get(key, 0) < int(self.settings.clock_sync_min_interval_s):
            return None
        smallest = min(offsets)
        if smallest < -drift:
            return {"reason": "clock_ahead", "offset_s": int(-smallest)}
        allowance = drift + 2 * self._report_interval(key)
        if smallest > allowance:
            return {"reason": "clock_behind", "offset_s": int(smallest), "allowance_s": int(allowance)}
        return None

    # ----------------------------------------------------------------- action
    def _sync(self, key, decision: dict, now: int) -> dict | None:
        from .commands import CommandError, CommandRequest  # import cycle: commands imports nothing of ours

        company, region, node_id = key
        try:
            if self.commands.has_active(company, region, node_id, "STIME"):
                return None
            transfer = self.commands.flash_transfer(company, region, node_id, now) if self.commands.flash_transfer else None
            if transfer:
                return None
            result = self.commands.submit(CommandRequest(company=company, region=region, node_id=node_id,
                                                         cmd_type="STIME", delivery="next_wake",
                                                         ttl_seconds=3600), actor=SYSTEM_ACTOR)
        except CommandError as exc:
            log.info("Automatic clock sync for %s/%s/%s not queued: %s", company, region, node_id, exc)
            return None
        except Exception:
            log.exception("Automatic clock sync failed for %s/%s/%s", company, region, node_id)
            return None
        with self._lock:
            self._last_sync[key] = now
            self._offsets.pop(key, None)        # the clock is about to change: start a new window
        decision = {**decision, "request_id": result.get("request_id")}
        text = {"clock_unset": "clock not set",
                "clock_ahead": f"clock {decision.get('offset_s')} s ahead",
                "clock_behind": f"clock {decision.get('offset_s')} s behind"}[decision["reason"]]
        if self.logs is not None:
            self.logs.emit(f"[CLOCK] Node {node_id} {text}; STIME queued for its next wake "
                           f"(request {decision['request_id']})", company=company)
        if self.audit is not None:
            try:
                self.audit(SYSTEM_ACTOR, "clock_sync_queued", company=company, target=f"{region}/{node_id}",
                           details=decision)
            except Exception:
                log.exception("Clock sync audit entry failed")
        return decision
