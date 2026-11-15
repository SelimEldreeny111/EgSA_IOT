"""Per-node health scores (R2.2, point 16).

One row per node of a company region, computed from the last 7 days of uplinks and the last 30 days of the
command journal — no firmware change, everything comes from data the server already stores:

* **Battery**: least-squares slope (V/day) over the window and the projected days until 3.3 V.
* **Resets**: growth of the watchdog and power-reset counters over the window.
* **Regularity**: uplinks received in the last 24 h against the number expected at the node's interval
  (the registry's ``report_interval_s``, or the median gap between uplinks).
* **Store-and-forward**: share of samples delivered late (measured more than two intervals before arrival).
* **Clock**: share of uplinks whose sample time came from a trusted node clock.
* **Commands**: acknowledged share of the commands that reached a final state in 30 days.
* **Config drift**: desired versus reported sampling/report interval (configuration watch).

The score (0-100) starts at 100 and loses points for each finding; ``grade`` is good (>= 80), fair (>= 60)
or poor. ``findings`` lists the reasons in plain words.
"""
from __future__ import annotations

import statistics
import time

from .alerts import LOW_BATTERY_V

WINDOW_DAYS = 7
COMMAND_DAYS = 30
FINAL_STATES = ("acknowledged", "rejected", "outcome_unknown", "expired")


def _slope_per_day(points: list[tuple[int, float]]) -> float | None:
    if len(points) < 6 or points[-1][0] - points[0][0] < 86400:
        return None
    xs = [p[0] / 86400 for p in points]
    ys = [p[1] for p in points]
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    den = sum((x - mx) ** 2 for x in xs)
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den if den else None


def grade(score: int) -> str:
    return "good" if score >= 80 else "fair" if score >= 60 else "poor"


class NodeHealth:
    def __init__(self, telemetry, commands, org, confwatch=None):
        self.telemetry = telemetry
        self.commands = commands
        self.org = org
        self.confwatch = confwatch

    def fleet(self, company: str, region: str, now: int | None = None) -> list[dict]:
        now = int(time.time() if now is None else now)
        since = now - WINDOW_DAYS * 86400
        registry = {int(n["node_id"]): n for n in self.org.list_nodes(company, region)} if self.org else {}
        per_node: dict[int, list] = {}
        with self.telemetry.connect(company) as db:
            for r in db.execute(
                    "SELECT node_id, timestamp, measured_at, battery_voltage, wdt_reset_count, power_reset_count, "
                    "rtc_valid, time_source FROM messages WHERE region=? AND timestamp>=? "
                    "AND type IN ('Status','Telemetry') ORDER BY node_id, timestamp", (region, since)):
                per_node.setdefault(int(r[0]), []).append(r)
        out = []
        for node_id in sorted(set(per_node) | set(registry)):
            out.append(self.node(company, region, node_id, per_node.get(node_id, []), registry.get(node_id), now))
        return out

    def node(self, company, region, node_id, rows, reg, now) -> dict:
        findings: list[str] = []
        score = 100
        name = (reg or {}).get("name") or f"Node {node_id}"
        if not rows:
            return {"node_id": node_id, "name": name, "score": 0, "grade": "poor", "uplinks_7d": 0,
                    "findings": [f"no uplinks in {WINDOW_DAYS} days"]}
        arrivals = [int(r[1]) for r in rows]
        gaps = sorted(b - a for a, b in zip(arrivals, arrivals[1:]) if b > a)
        interval = int((reg or {}).get("report_interval_s") or 0) or (int(statistics.median(gaps)) if gaps else 0)

        # battery
        battery = [(int(r[1]), float(r[3])) for r in rows if r[3] and r[3] > 0]
        slope = _slope_per_day(battery)
        last_v = battery[-1][1] if battery else None
        days_left = None
        if last_v is not None and slope is not None and slope < -0.001:
            days_left = max(0.0, (last_v - LOW_BATTERY_V) / -slope)
            if days_left < 30:
                score -= 25 if days_left < 7 else 12
                findings.append(f"battery reaches {LOW_BATTERY_V} V in about {days_left:.0f} days")
        if last_v is not None and last_v < LOW_BATTERY_V:
            score -= 20
            findings.append(f"battery low ({last_v:.2f} V)")

        # resets
        def growth(i):
            vals = [int(r[i]) for r in rows if r[i] is not None]
            return max(0, max(vals) - min(vals)) if vals else 0
        wdt, power = growth(4), growth(5)
        if wdt:
            score -= min(20, 4 * wdt)
            findings.append(f"{wdt} watchdog reset(s) in {WINDOW_DAYS} days")
        if power:
            score -= min(15, 2 * power)
            findings.append(f"{power} power reset(s) in {WINDOW_DAYS} days")

        # regularity (last 24 h, or since the first uplink if newer)
        regularity = None
        age = now - arrivals[-1]
        silent = bool(interval) and age > 6 * interval
        if interval:
            span = min(86400, now - arrivals[0])
            expected = max(1, span // interval)
            got = sum(1 for t in arrivals if t >= now - span)
            regularity = round(min(1.0, got / expected), 3)
        if silent:                      # one finding for a silent node, not also "missed uplinks"
            score -= 30
            findings.append(f"silent for {age // 3600} h" if age >= 7200 else f"silent for {age // 60} min")
        elif regularity is not None and regularity < 0.9:
            score -= min(30, round((0.9 - regularity) * 40))
            findings.append(f"{regularity:.0%} of expected uplinks in the last 24 h")

        # store-and-forward and clock
        late = sum(1 for r in rows if r[2] and interval and int(r[1]) - int(r[2]) > 2 * interval)
        sf_share = round(late / len(rows), 3)
        if sf_share > 0.2:
            score -= 5
            findings.append(f"{sf_share:.0%} of samples delivered from the node's store")
        trusted = sum(1 for r in rows if r[6])
        clock_share = round(trusted / len(rows), 3)
        if clock_share < 0.9:
            score -= 10
            findings.append(f"node clock trusted for only {clock_share:.0%} of uplinks")

        # commands
        stats = self.commands.journal.node_stats(company, node_id, now - COMMAND_DAYS * 86400, region=region)
        final = sum(stats.get(s, 0) for s in FINAL_STATES)
        cmd_rate = round(stats.get("acknowledged", 0) / final, 3) if final else None
        if cmd_rate is not None and final >= 3 and cmd_rate < 0.8:
            score -= round((0.8 - cmd_rate) * 40)
            findings.append(f"{cmd_rate:.0%} of commands acknowledged ({final} in {COMMAND_DAYS} days)")

        # configuration drift
        config = self.confwatch.state(company, region, node_id) if self.confwatch else None
        if config and any(v["drift"] for v in config.values()):
            score -= 10
            findings.append("reported interval differs from the one set")

        score = max(0, min(100, int(score)))
        return {"node_id": node_id, "name": name, "score": score, "grade": grade(score),
                "uplinks_7d": len(rows), "interval_s": interval or None, "last_seen_age_s": age,
                "battery_v": round(last_v, 3) if last_v is not None else None,
                "battery_slope_v_per_day": round(slope, 4) if slope is not None else None,
                "battery_days_left": round(days_left, 1) if days_left is not None else None,
                "wdt_resets_7d": wdt, "power_resets_7d": power, "regularity_24h": regularity,
                "store_forward_share": sf_share, "clock_trusted_share": clock_share,
                "command_success": cmd_rate, "commands_30d": final, "config": config,
                "findings": findings or ["no issues"]}
