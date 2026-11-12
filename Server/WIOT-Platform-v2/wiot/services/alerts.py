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
``leak_suspected`` critical  valve reported closed but flow >= 0.5 m3/h for 15+ minutes.
``no_flow``        warning   valve reported open but flow below 0.05 m3/h for 15+ minutes
                             (pump failure, closed upstream valve, blocked or empty line).
                             Both only on nodes that drive a valve: registered control nodes,
                             or unregistered nodes seen with an open valve in the last 7 days.
``night_flow``     warning   flow during the configured night hours (``WIOT_NIGHT_FLOW_HOURS``,
                             company local time) on a node whose valve is not open; off by default.
``frost_risk``     critical  forecast minimum <= ``WIOT_FROST_WARN_C`` today or tomorrow (farm site,
                             node 0).
``heat_stress``    warning   forecast maximum >= ``WIOT_HEAT_WARN_C`` today or tomorrow (node 0).
``foreign_command`` critical a command on a node's command topic that this server did not send.
``possible_replay`` warning  a Status message repeated after the node had already sent newer data.
                             The last two are *event* alerts: they open on the event and resolve
                             after 24 hours without another one.
"""
from __future__ import annotations

import logging
import statistics
import threading
import time
from datetime import datetime, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

log = logging.getLogger(__name__)

LOW_BATTERY_V = 3.3
BATTERY_CLEAR_V = LOW_BATTERY_V + 0.1   # hysteresis: do not flap around the threshold
FLOW_WINDOW_S = 3600
FLOW_JUMP_RATIO = 5.0
FLOW_FLOOR = 1.0                         # ignore readings below this (pump stopped, noise)
FLOW_MIN_JUMPS = 3
FLOW_MIN_REVERSALS = 2                   # a pump start or stop is one-way, not an oscillation
FLOW_MIN_READINGS = 6                    # too few readings: keep the current state
LEAK_WINDOW_S = 1800                     # look-back for the valve/flow rules
LEAK_MIN_SPAN_S = 900                    # the condition must last at least 15 minutes
LEAK_MIN_READINGS = 3
LEAK_FLOW_M3H = 0.5                      # flow with the valve closed
NO_FLOW_M3H = 0.05                       # "no flow" with the valve open
VALVE_EVIDENCE_S = 7 * 86400             # an unregistered node counts as a valve node if seen open
NIGHT_FLOW_M3H = 0.5
EVENT_KINDS = {"foreign_command": "critical", "possible_replay": "warning"}
EVENT_QUIET_S = 86400                    # event alerts resolve after a quiet day
WEATHER_KINDS = ("frost_risk", "heat_stress")


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


def valve_flow_verdict(readings: list[dict]) -> str | None:
    """``'leak'``, ``'no_flow'``, ``'normal'``, or None when there are too few usable readings.

    Usable: a flow meter is fitted, live flow is valid and the valve state is known (0 or 1).
    The condition must hold for every usable reading over at least ``LEAK_MIN_SPAN_S``."""
    usable = [r for r in readings if r["meter"] and r["flow_valid"] and r["valve"] in (0, 1)]
    if len(usable) < LEAK_MIN_READINGS or usable[-1]["t"] - usable[0]["t"] < LEAK_MIN_SPAN_S:
        return None
    if all(r["valve"] == 0 and r["flow"] >= LEAK_FLOW_M3H for r in usable):
        return "leak"
    if all(r["valve"] == 1 and r["flow"] < NO_FLOW_M3H for r in usable):
        return "no_flow"
    return "normal"


def night_hours(spec: str) -> tuple[int, int] | None:
    """Parse ``"HH-HH"`` (local hours, end exclusive, may wrap midnight); None when off or invalid."""
    try:
        a, b = (int(x) for x in (spec or "").strip().split("-"))
    except ValueError:
        return None
    return (a, b) if 0 <= a <= 23 and 0 <= b <= 24 and a != b else None


def in_night(hour: int, window: tuple[int, int]) -> bool:
    a, b = window
    return a <= hour < b if a < b else (hour >= a or hour < b)


def _zone(name: str) -> tzinfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return timezone.utc


class AlertMonitor:
    """Opens/resolves persistent alerts and publishes ``alert`` hub events on changes."""

    def __init__(self, telemetry, org, hub, companies, store, interval: float = 60.0, settings=None):
        self.telemetry, self.org, self.hub, self.companies = telemetry, org, hub, companies
        self.store = store
        self.settings = settings
        self.farm = None                  # FarmService, injected by the runtime (weather warnings)
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
            try:
                fired += self._check_events(company, now)
                fired += self._check_weather(company, now)
            except Exception:  # pragma: no cover
                log.exception("Company-level alert checks failed for %s", company)
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

        fired += self._check_valve_flow(company, region, node, base, now)
        return fired

    def _drives_valve(self, company: str, region: str, nid: int, now: int) -> bool:
        kind = self.org.node_type(company, region, nid) if hasattr(self.org, "node_type") else None
        if kind == "control":
            return True
        if kind == "monitoring":
            return False
        return self.telemetry.valve_seen_open(company, region, nid, now - VALVE_EVIDENCE_S)

    def _check_valve_flow(self, company: str, region: str, node: dict, base: dict, now: int) -> list[dict]:
        """Leak (closed valve, flow), no flow (open valve) and optional night flow."""
        nid, fired = node["node_id"], []
        if node.get("link_state") == "offline":
            return fired                      # stale readings say nothing about now
        readings = self.telemetry.valve_flow_readings(company, region, nid, now - LEAK_WINDOW_S)
        if not any(r["meter"] for r in readings):
            return fired
        if self._drives_valve(company, region, nid, now):
            verdict = valve_flow_verdict(readings)
            usable = [r for r in readings if r["meter"] and r["flow_valid"]]
            summary = {**base, "readings": len(usable), "window_s": LEAK_WINDOW_S,
                       "flow_m3h": round(statistics.median(r["flow"] for r in usable), 2) if usable else None}
            if verdict == "leak":
                fired += self._open(company, region, node, "leak_suspected", "critical",
                                    {**summary, "threshold_m3h": LEAK_FLOW_M3H, "valve": "closed"}, now)
            elif verdict is not None:
                fired += self._resolve(company, region, node, "leak_suspected", now)
            if verdict == "no_flow":
                fired += self._open(company, region, node, "no_flow", "warning",
                                    {**summary, "threshold_m3h": NO_FLOW_M3H, "valve": "open"}, now)
            elif verdict is not None:
                fired += self._resolve(company, region, node, "no_flow", now)
        window = night_hours(getattr(self.settings, "night_flow_hours", "") if self.settings else "")
        if window:
            tz = _zone(self.org.timezone(company) if hasattr(self.org, "timezone") else "UTC")
            night = [r for r in readings if r["meter"] and r["flow_valid"]
                     and in_night(datetime.fromtimestamp(r["t"], tz).hour, window)]
            recent = night[-LEAK_MIN_READINGS:]
            flowing = (len(recent) == LEAK_MIN_READINGS and recent[-1]["t"] >= now - 600
                       and all(r["flow"] >= NIGHT_FLOW_M3H and r["valve"] != 1 for r in recent))
            if flowing:
                fired += self._open(company, region, node, "night_flow", "warning", {
                    **base, "flow_m3h": round(recent[-1]["flow"], 2),
                    "night_hours": f"{window[0]:02d}-{window[1]:02d}", "threshold_m3h": NIGHT_FLOW_M3H}, now)
            elif not in_night(datetime.fromtimestamp(now, tz).hour, window) or (
                    recent and recent[-1]["flow"] < NIGHT_FLOW_M3H):
                fired += self._resolve(company, region, node, "night_flow", now)
        return fired

    # ------------------------------------------------------- company-level
    def _check_weather(self, company: str, now: int) -> list[dict]:
        if self.farm is None:
            return []
        warnings = self.farm.weather_warnings(company)
        if warnings is None:                  # no farm layout or no forecast: keep the current state
            return []
        region = warnings["region"]
        site = {"node_id": 0, "timestamp": None, "name": warnings.get("site")}
        fired, present = [], {w["kind"] for w in warnings["items"]}
        for w in warnings["items"]:
            details = {k: v for k, v in w.items() if k not in ("kind", "severity")}
            fired += self._open(company, region, site, w["kind"], w["severity"], details, now)
        for kind in WEATHER_KINDS:
            if kind not in present:
                fired += self._resolve(company, region, site, kind, now)
        return fired

    def record_event(self, company: str, region: str, node_id: int, kind: str, details: dict,
                     now: int | None = None) -> list[dict]:
        """Open (or refresh) an event alert; it resolves after ``EVENT_QUIET_S`` without a new event."""
        now = int(time.time() if now is None else now)
        previous = self.store.get_open(company, region, node_id, kind)
        count = int((previous or {}).get("details", {}).get("events", 0)) + 1
        node = {"node_id": node_id, "timestamp": now}
        return self._open(company, region, node, kind, EVENT_KINDS[kind],
                          {**details, "events": count, "last_event_at": now}, now)

    def _check_events(self, company: str, now: int) -> list[dict]:
        fired = []
        for alert in self.store.list(company, status="open"):
            if alert["kind"] in EVENT_KINDS and now - int(alert["updated_at"]) >= EVENT_QUIET_S:
                fired += self._resolve(company, alert["region"], {"node_id": alert["node_id"], "timestamp": None},
                                       alert["kind"], now)
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
