"""Analysis of a node's SPI-flash telemetry log, built from what the server already holds.

Inputs are the last ``FLASH_STATUS`` reply (chip/journal counters), the history
transfers, the archived samples downloaded with ``FLASH_TODAY``/``FLASH_LAST`` and
the receive times of the node's live uplinks.  Nothing here talks to the node.

Sections returned by :func:`analyse`:

* ``memory``     – chip health, capacity accounting and record fill;
* ``retention``  – the node's 24 h log window and a fill projection to its next clear;
* ``quality``    – samples the node could not log (RTC untrusted, journal busy/full);
* ``transfers``  – each history download with progress and outcome;
* ``generations``– per log generation: records held here, sequence gaps, spacing;
* ``metrics``    – min/mean/max of every archived measurement that was flagged valid;
* ``recovery``   – archived samples taken while the live link was silent (gap fill);
* ``series``     – time-ordered archived samples for charts (valid values only).
"""
from __future__ import annotations

import bisect
import statistics

from .flash_archive import MAX_RECORDS, RESULT_NAMES, STATE_NAMES

RECORD_BYTES = 512                 # one journal slot per sample (TelemetryJournal)
RETENTION_S = 86_400               # the node clears its log every 24 elapsed hours
SERIES_LIMIT = 4_000               # points sent to the browser per node
PHASES = {1: "Preparing", 2: "Receiving", 3: "Finished"}

# key, label, unit kind (units.js), validity flag in the stored Telemetry sample
METRICS = (
    ("flow_rate", "Flow rate", "flow", "flow_live_valid"),
    ("velocity", "Velocity", "velocity", "flow_live_valid"),
    ("battery_voltage", "Battery", "volt", None),
    ("soil_moisture", "Soil moisture (HNDA)", "pct", "soil_moisture_temp_valid"),
    ("soil_temperature", "Soil temperature (HNDA)", "temp", "soil_moisture_temp_valid"),
    ("ec_moisture", "Soil moisture (Sondas)", "pct", "soil_moisture_temp_ec_valid"),
    ("ec_temperature", "Soil temperature (Sondas)", "temp", "soil_moisture_temp_ec_valid"),
    ("electrical_conductivity", "Salinity (EC)", "ec", "soil_moisture_temp_ec_valid"),
)


def _value(data: dict, key: str, flag: str | None):
    if flag and not data.get(flag):
        return None
    v = data.get(key)
    if v is None:
        return None
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    if key == "battery_voltage" and v <= 0:
        return None
    return round(v, 4)


def _median_gap(epochs: list[int]) -> float | None:
    gaps = [b - a for a, b in zip(epochs, epochs[1:]) if b > a]
    return float(statistics.median(gaps)) if gaps else None


STALL_S = 600                      # no new row for 10 min: the node gave up (ACK timeout, reboot, link)


def transfer_state(t: dict, now: int | None = None) -> tuple[str, str]:
    """(badge class, label) for one history download."""
    result = RESULT_NAMES[t["result"]] if 0 <= t.get("result", 0) < len(RESULT_NAMES) else "Unknown"
    if t.get("complete"):
        return "good", "Complete" if t.get("result") == 0 else f"Complete · {result}"
    if t.get("phase") == 3:
        return "critical", f"Stopped · {result}"
    if t.get("result"):
        return "critical", f"Rejected · {result}"
    if now is not None and t.get("updated") and now - t["updated"] > STALL_S:
        return "neutral", "Stalled"
    return ("info", "Preparing") if t.get("phase") == 1 else ("warning", "Receiving")


def _memory(info: dict | None, received_at: int | None, now: int) -> dict | None:
    if not info:
        return None
    usable = info.get("usable_bytes") or 0
    max_records = info.get("maximum_records") or MAX_RECORDS
    state = info.get("state", 0)
    return {
        **info,
        "state_name": info.get("state_name") or (STATE_NAMES[state] if 0 <= state < len(STATE_NAMES) else "Unknown"),
        "jedec_hex": f"0x{int(info.get('jedec_id') or 0):06X}",
        "reserved_bytes": max(0, (info.get("capacity_bytes") or 0) - usable),
        "fill_pct": round(100.0 * (info.get("record_count") or 0) / max_records, 2) if max_records else None,
        "bytes_pct": round(100.0 * (info.get("used_bytes") or 0) / usable, 2) if usable else None,
        "received_at": received_at,
        "age_s": now - received_at if received_at else None,
    }


def _retention(mem: dict | None, now: int) -> dict | None:
    if not mem or not mem.get("retention_started_epoch"):
        return None
    start, clear = mem["retention_started_epoch"], mem.get("next_clear_epoch") or 0
    window = (clear - start) if clear > start else RETENTION_S
    # counters are as of the status reply, not "now"
    at = mem.get("received_at") or now
    elapsed = max(0, at - start)
    count, maximum = mem.get("record_count") or 0, mem.get("maximum_records") or MAX_RECORDS
    rate_h = count / (elapsed / 3600) if elapsed >= 60 and count else None
    projected = min(int(round(rate_h * window / 3600)), 10 ** 9) if rate_h else None
    overflow_at = int(start + maximum / rate_h * 3600) if rate_h and projected and projected > maximum else None
    return {
        "started": start, "next_clear": clear or start + window, "window_s": window,
        "elapsed_s": elapsed, "elapsed_pct": round(min(100.0, 100.0 * elapsed / window), 2),
        "clears_in_s": max(0, (clear or start + window) - now),
        "records_per_hour": round(rate_h, 1) if rate_h else None,
        "projected_records": projected,
        "projected_pct": round(100.0 * projected / maximum, 1) if projected is not None else None,
        "overflow_at": overflow_at,
    }


def _quality(mem: dict | None) -> dict | None:
    if not mem:
        return None
    stored, dropped = mem.get("record_count") or 0, mem.get("dropped_samples") or 0
    attempts = stored + dropped
    return {"stored": stored, "not_logged": dropped, "corrupt": mem.get("corrupt_records") or 0,
            "not_logged_pct": round(100.0 * dropped / attempts, 1) if attempts else None,
            "rtc_trusted": bool(mem.get("rtc_trusted")), "busy": bool(mem.get("busy"))}


def _generations(records: list[dict], current: int | None) -> list[dict]:
    by_gen: dict[int, list[dict]] = {}
    for r in records:
        by_gen.setdefault(r["generation"], []).append(r)
    out = []
    for gen in sorted(by_gen, reverse=True):
        rows = sorted(by_gen[gen], key=lambda r: r["sequence"])
        seqs = [r["sequence"] for r in rows]
        epochs = sorted(r["epoch"] for r in rows)
        span = seqs[-1] - seqs[0] + 1
        out.append({
            "generation": gen, "records": len(rows), "first_sequence": seqs[0], "last_sequence": seqs[-1],
            "missing_in_range": span - len(rows), "completeness_pct": round(100.0 * len(rows) / span, 1),
            "first_epoch": epochs[0], "last_epoch": epochs[-1], "days": sorted({r["day"] for r in rows if r["day"]}),
            "median_spacing_s": _median_gap(epochs), "current": gen == current,
        })
    return out


def _metrics(records: list[dict]) -> list[dict]:
    out = []
    for key, label, kind, flag in METRICS:
        vals = [v for v in (_value(r["data"], key, flag) for r in records) if v is not None]
        if not vals:
            continue
        out.append({"key": key, "label": label, "unit": kind, "samples": len(vals),
                    "min": min(vals), "mean": round(statistics.fmean(vals), 4), "max": max(vals)})
    return out


def _recovery(records: list[dict], live_times: list[int]) -> dict:
    if not records:
        return {"archived": 0, "covered": 0, "recovered": 0, "tolerance_s": None, "recovered_windows": []}
    # Each sample is matched with the transmission interval it was logged under, so adding
    # records from a later configuration never reclassifies older ones.
    def tolerance(r) -> int:
        tx_ms = int(r["data"].get("Transmission_rate") or 0)
        return int(max(60, 2 * tx_ms / 1000)) if tx_ms > 0 else 60

    tols = [tolerance(r) for r in records]
    tol = int(statistics.median(tols))
    live = sorted(live_times)
    covered, recovered = 0, []
    for r in sorted(records, key=lambda r: r["epoch"]):
        t = tolerance(r)
        i = bisect.bisect_left(live, r["epoch"] - t)
        if i < len(live) and live[i] <= r["epoch"] + t:
            covered += 1
        else:
            recovered.append(r["epoch"])
    windows: list[list[int]] = []          # contiguous silent stretches, for the chart
    for t in recovered:
        if windows and t - windows[-1][1] <= 3 * tol:
            windows[-1][1] = t
            windows[-1][2] += 1
        else:
            windows.append([t, t, 1])
    return {"archived": len(records), "covered": covered, "recovered": len(recovered), "tolerance_s": tol,
            "recovered_pct": round(100.0 * len(recovered) / len(records), 1),
            "recovered_windows": [{"start": a, "end": b, "samples": n} for a, b, n in windows[-50:]]}


def _series(records: list[dict]) -> list[dict]:
    rows = sorted(records, key=lambda r: (r["epoch"], r["generation"], r["sequence"]))
    if len(rows) > SERIES_LIMIT:                       # keep the shape, bound the payload
        step = len(rows) / SERIES_LIMIT
        rows = [rows[int(i * step)] for i in range(SERIES_LIMIT)]
    out = []
    for r in rows:
        point = {"t": r["epoch"], "gen": r["generation"], "seq": r["sequence"]}
        for key, _, _, flag in METRICS:
            point[key] = _value(r["data"], key, flag)
        point["forward_total_liters"] = r["data"].get("forward_total_liters")
        out.append(point)
    return out


def analyse(summary: dict, records: list[dict], live_times: list[int], now: int) -> dict:
    mem = _memory(summary.get("memory"), summary.get("received_at"), now)
    transfers = []
    for t in summary.get("transfers", []):
        cls, label = transfer_state(t, now)
        transfers.append({**t, "state_class": cls, "state": label, "phase_name": PHASES.get(t.get("phase"), "–"),
                          "result_name": RESULT_NAMES[t["result"]] if 0 <= t.get("result", 0) < len(RESULT_NAMES) else "Unknown",
                          "progress_pct": round(100.0 * t["received"] / t["total"], 1) if t.get("total") else None})
    return {
        "memory": mem,
        "retention": _retention(mem, now),
        "quality": _quality(mem),
        "transfers": transfers,
        "generations": _generations(records, mem.get("generation") if mem else None),
        "metrics": _metrics(records),
        "recovery": _recovery(records, live_times),
        "series": _series(records),
        "archived_total": len(records),
        "record_bytes": RECORD_BYTES,
        "now": now,
    }
