"""Fleet alert monitor: silent nodes, low batteries and implausible flow readings.

Every minute the monitor evaluates each node and opens or resolves persistent alerts
(:class:`~wiot.storage.alert_store.AlertStore`). Only the opening and the clearing of an
alert publish an ``alert`` hub event (and therefore a webhook), so a condition that lasts
for days, or survives a server restart, is reported once.

Kinds
-----
``node_offline``   critical  no uplink for 6 x the node's usual interval (``link_state``).
                             Clearing publishes ``node_online``.
``low_battery``    warning   battery below 3.3 V while the node is reporting.
``flow_unstable``  warning   the flow reading jumps by x5 or more between consecutive
                             uplinks, repeatedly and in both directions, within an hour.
                             Real pipe flow ramps; it does not oscillate like that, so the
                             cause is the meter, its wiring/Modbus settings or a simulator.
"""
from __future__ import annotations

import logging
import threading
import time

log = logging.getLogger(__name__)

LOW_BATTERY_V = 3.3
BATTERY_CLEAR_V = LOW_BATTERY_V + 0.1   # hysteresis: do not flap around the threshold
FLOW_WINDOW_S = 3600
FLOW_JUMP_RATIO = 5.0
FLOW_FLOOR = 1.0                         # ignore readings below this (pump stopped, noise)
FLOW_MIN_JUMPS = 3
FLOW_MIN_REVERSALS = 2                   # a pump start or stop is one-way, not an oscillation
FLOW_MIN_READINGS = 6                    # too few readings: keep the current state


def flow_jumps(readings: list[tuple[int, float]], ratio: float = FLOW_JUMP_RATIO,
               floor: float = FLOW_FLOOR) -> list[dict]:
    """Consecutive readings that both exceed ``floor`` and differ by ``ratio`` or more."""
    out, prev = [], None
    for t, flow in readings:
        if prev is not None and prev >= floor and flow >= floor:
            hi, lo = max(prev, flow), min(prev, flow)
            if hi / lo >= ratio:
                out.append({"at": t, "from": round(prev, 3), "to": round(flow, 3), "ratio": round(hi / lo, 1),
                            "up": flow > prev})
        prev = flow
    return out


def flow_verdict(readings: list[tuple[int, float]]) -> tuple[bool | None, list[dict]]:
    """(unstable?, jumps). ``None`` when there are too few readings to judge."""
    if len(readings) < FLOW_MIN_READINGS:
        return None, []
    jumps = flow_jumps(readings)
    reversals = sum(1 for a, b in zip(jumps, jumps[1:]) if a["up"] != b["up"])
    return len(jumps) >= FLOW_MIN_JUMPS and reversals >= FLOW_MIN_REVERSALS, jumps


class AlertMonitor:
    """Opens/resolves persistent alerts and publishes ``alert`` hub events on changes."""

    def __init__(self, telemetry, org, hub, companies, store, interval: float = 60.0):
        self.telemetry, self.org, self.hub, self.companies = telemetry, org, hub, companies
        self.store = store
        self.interval = interval
        self.state: dict[tuple, str] = {}     # last link state per node (diagnostics/tests)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="alert-monitor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(self.interval if self.state else 5):
            try:
                self.check()
            except Exception:  # pragma: no cover
                log.exception("Alert monitor failed")

    def check(self, now: int | None = None) -> list[dict]:
        now = int(time.time() if now is None else now)
        fired: list[dict] = []
        for company in self.companies():
            regions = sorted(set(self.telemetry.regions(company)) | set(self.org.region_ids(company)))
            for region in regions:
                for node in self.telemetry.fleet(company, region):
                    try:
                        fired += self._check_node(company, region, node, now)
                    except Exception:  # pragma: no cover - one bad node must not stop the sweep
                        log.exception("Alert check failed for %s/%s/%s", company, region, node.get("node_id"))
        return fired

    # ------------------------------------------------------------------ rules
    def _check_node(self, company: str, region: str, node: dict, now: int) -> list[dict]:
        nid = node["node_id"]
        link = node.get("link_state", "offline")
        self.state[(company, region, nid)] = link
        base = {"name": node.get("name"), "last_seen": node.get("timestamp")}
        fired = []

        if link == "offline":
            fired += self._open(company, region, node, "node_offline", "critical", {
                **base, "silent_s": node.get("last_seen_age_s"), "interval_s": node.get("median_interval_s")}, now)
        else:
            fired += self._resolve(company, region, node, "node_offline", now, cleared_kind="node_online")

        battery = node.get("battery_voltage")
        if link != "offline" and battery and 0 < battery < LOW_BATTERY_V:
            fired += self._open(company, region, node, "low_battery", "warning",
                                {**base, "battery_v": round(battery, 2), "threshold_v": LOW_BATTERY_V}, now)
        elif battery and battery >= BATTERY_CLEAR_V:
            fired += self._resolve(company, region, node, "low_battery", now)

        judged, unstable = [], []        # per sensor: (sensor, jumps, readings)
        for sensor, readings in self.telemetry.flow_readings(company, region, nid, now - FLOW_WINDOW_S).items():
            verdict, jumps = flow_verdict(readings)
            if verdict is not None:
                judged.append((sensor, jumps, len(readings)))
                if verdict:
                    unstable.append((sensor, jumps, len(readings)))
        if unstable:
            sensor, jumps, count = max(unstable, key=lambda s: len(s[1]))
            biggest = max(jumps, key=lambda j: j["ratio"])
            fired += self._open(company, region, node, "flow_unstable", "warning", {
                **base, "sensor_id": sensor, "jumps": len(jumps), "readings": count,
                "window_s": FLOW_WINDOW_S, "ratio": FLOW_JUMP_RATIO,
                "example": {k: biggest[k] for k in ("from", "to", "ratio", "at")}}, now)
        elif judged and not any(jumps for _, jumps, _ in judged):
            fired += self._resolve(company, region, node, "flow_unstable", now)   # a clean hour of readings
        return fired

    # ------------------------------------------------------------- plumbing
    def _open(self, company, region, node, kind, severity, details, now) -> list[dict]:
        alert, created = self.store.open(company, region, node["node_id"], kind, severity, details, now)
        return [self._fire(company, region, node, alert, kind, severity)] if created else []

    def _resolve(self, company, region, node, kind, now, cleared_kind=None) -> list[dict]:
        alert = self.store.resolve(company, region, node["node_id"], kind, now)
        if alert is None:
            return []
        return [self._fire(company, region, node, alert, cleared_kind or f"{kind}_resolved", "info")]

    def _fire(self, company: str, region: str, node: dict, alert: dict, kind: str, severity: str) -> dict:
        details = alert.get("details") or {}
        data = {"kind": kind, "severity": severity, "region": region, "node_id": node["node_id"],
                "last_seen": node.get("timestamp"), "alert_id": alert["id"], "alert_kind": alert["kind"],
                "state": alert["state"], "details": details}
        if "battery_v" in details:
            data["battery_v"] = details["battery_v"]
        self.hub.publish("alert", data, company=company)
        return data
