"""Descriptive analyses: fleet & link reliability, power & health, sensors, command outcomes."""
from __future__ import annotations

import json
from typing import Any

import numpy as np
import pandas as pd

from . import dataset as ds
from .common import downsample_indices, histogram, local_day, local_hour, percentiles, wilson_ci

INTERVAL_EDGES = [1, 2, 5, 10, 20, 30, 60, 120, 300, 600, 1800, 3600, 7200, 21600, 86400, 604800, 1e7]
LATENCY_EDGES = [-2000, -1000, -600, -300, -120, -60, -30, -10, 0, 10, 30, 60, 120, 300, 600, 1200, 3600, 86400]
ACK_LATENCY_EDGES = [0, 1, 2, 3, 4, 5, 6, 8, 10, 15, 20, 25, 30, 45, 60, 120, 300, 600, 1800, 7200]
PUBACK_EDGES = [0, 1, 2, 3, 5, 10, 30, 60]
RECENCY_BINS = [0, 10, 30, 60, 120, 300, 900, 3600, ds.SECONDS_CAP + 1]
MAX_BATTERY_POINTS = 500
ATTRIBUTABLE_GAP_S = 1800   # counter increments after a longer silence cannot be timed (node off / reflashed)
# Copied from wiot/protocol/flow_schema.py (PERIOD_QUALITY_NAMES) to keep analytics standalone.
PERIOD_QUALITY_NAMES = {0: "Invalid", 1: "Valid", 2: "Partial", 3: "Estimated", 4: "Counter reset",
                        5: "Anomaly", 6: "Time uncertain"}

SENSOR_CHANNELS: list[tuple[str, str, str]] = [
    ("flow_tuf", "m3/h", "TUF-2000B flow rate"), ("velocity_tuf", "m/s", "TUF-2000B velocity"),
    ("flow_supmea", "m3/h", "Supmea flow rate"), ("velocity_supmea", "m/s", "Supmea velocity"),
    ("battery_voltage", "V", "Battery voltage"),
    ("soil_temperature", "degC", "HNDA soil temperature"), ("soil_moisture", "%", "HNDA soil moisture"),
    ("ec_temperature", "degC", "Sondas temperature"), ("ec_moisture", "%", "Sondas moisture"),
    ("electrical_conductivity", "uS/cm", "Sondas electrical conductivity"),
]


def _node_meta(key: str) -> dict[str, Any]:
    company, region, node = key.split("/")
    return {"company": company, "region": region, "node_id": int(node)}


def uplinks(msgs: pd.DataFrame) -> pd.DataFrame:
    return msgs[msgs["is_uplink"]].copy()


# ---------------------------------------------------------------------------
# Fleet & link reliability
# ---------------------------------------------------------------------------
def node_link_stats(ts: np.ndarray) -> dict[str, Any]:
    """Inter-arrival statistics and hourly availability for one node's sorted uplink times."""
    ts = np.sort(np.asarray(ts, dtype="int64"))
    iv = np.diff(ts)
    iv = iv[iv > 0]
    med = float(np.median(iv)) if iv.size else None
    hours = np.unique(ts // 3600)
    span_h = int(ts.max() // 3600 - ts.min() // 3600 + 1) if ts.size else 0
    gaps = iv[iv > 3 * med] if med else np.array([])
    return {"median_interval_s": med, "p95_interval_s": float(np.percentile(iv, 95)) if iv.size else None,
            "gaps": int(gaps.size), "longest_gap_s": float(iv.max()) if iv.size else None,
            "availability_pct": 100.0 * hours.size / span_h if span_h else None,
            "intervals": iv}


def fleet_and_link(msgs: pd.DataFrame) -> tuple[list[dict], dict]:
    up = uplinks(msgs)
    per_node, nodes = [], []
    for key, g in msgs.groupby("node_key", sort=True):
        u = up[up["node_key"] == key]
        st = node_link_stats(u["timestamp"].to_numpy())
        days = pd.Series(local_day(u["timestamp"].to_numpy())).value_counts().sort_index()
        meta = _node_meta(key)
        has_meter = u["flow_meter_type"].fillna(0) > 0
        nodes.append({**meta, "key": key,
                      "first_seen": int(u["timestamp"].min()) if len(u) else int(g["timestamp"].min()),
                      "last_seen": int(u["timestamp"].max()) if len(u) else int(g["timestamp"].max()),
                      "messages": int(len(g)), "status": int((g["type"] == "Status").sum()),
                      "telemetry": int((g["type"] == "Telemetry").sum()),
                      "command_history_rows": int((g["type"] == "Command").sum()),
                      "ack_uplinks": int(u["is_ack"].sum()),
                      "availability_pct": st["availability_pct"], "median_interval_s": st["median_interval_s"],
                      "p95_interval_s": st["p95_interval_s"], "gaps": st["gaps"], "longest_gap_s": st["longest_gap_s"],
                      "active_days": int(days.size),
                      "rtc_valid_pct": 100.0 * float((u["rtc_valid"] == 1).mean()) if len(u) else None,
                      "flow_valid_pct": 100.0 * float((u.loc[has_meter, "flow_live_valid"] == 1).mean())
                      if has_meter.any() else None})
        per_node.append({"key": key, "company": meta["company"], "node_id": meta["node_id"],
                         "region": meta["region"],
                         "interval_hist": histogram(st["intervals"], edges=INTERVAL_EDGES),
                         "daily": [{"day": d, "count": int(c)} for d, c in days.items()]})
    return nodes, {"per_node": per_node, "heatmap": day_hour_heatmap(up["timestamp"].to_numpy()),
                   "store_forward": store_forward(up)}


def day_hour_heatmap(ts: np.ndarray) -> dict[str, list]:
    if len(ts) == 0:
        return {"days": [], "hours": list(range(24)), "counts": []}
    days = local_day(ts)
    hours = local_hour(ts)
    all_days = pd.date_range(min(days), max(days), freq="D").strftime("%Y-%m-%d").tolist()
    idx = {d: i for i, d in enumerate(all_days)}
    mat = np.zeros((len(all_days), 24), dtype=int)
    for d, h in zip(days, hours):
        mat[idx[d], h] += 1
    return {"days": all_days, "hours": list(range(24)), "counts": mat.tolist()}


def store_forward(up: pd.DataFrame) -> dict[str, Any]:
    """Server-received minus node-measured time for RTC-stamped uplinks (``time_source='node_rtc'``)."""
    sel = up[(up["time_source"] == "node_rtc") & (up["rtc_valid"] == 1)].copy()
    sel["latency"] = (sel["timestamp"] - sel["measured_at"]).astype(float)
    sel["mode"] = sel["power_mode"].fillna(0).astype(int).map(ds.POWER_MODE_NAMES)
    by_mode = []
    for mode, g in sel.groupby("mode", sort=True):
        lat = g["latency"].to_numpy()
        by_mode.append({"mode": mode, "n": int(lat.size), **percentiles(lat, (50, 90, 99)),
                        "min": float(lat.min()), "max": float(lat.max()),
                        "share_negative": float((lat < 0).mean())})
    excluded = int(((up["time_source"] == "node_rtc") & (up["rtc_valid"] != 1)).sum())
    return {"by_mode": by_mode, "hist": histogram(np.clip(sel["latency"], LATENCY_EDGES[0], LATENCY_EDGES[-1] - 1),
                                                  edges=LATENCY_EDGES),
            "n": int(len(sel)), "excluded_rtc_invalid": excluded,
            "note": "latency = server receive time - node RTC measurement time; negative values mean the node "
                    "RTC was ahead of the server clock (RTC offset), so values mix queueing delay and clock offset"}


# ---------------------------------------------------------------------------
# Power & health
# ---------------------------------------------------------------------------
def counter_events(ts: np.ndarray, values: np.ndarray) -> tuple[list[tuple[int, int, int]], list[int]]:
    """Reset events from a cumulative counter: increases are resets; a drop is an operator clear.

    After a drop the new value counts as resets since the clear. Returns
    ``([(t, delta, gap_s)], [t_clear])`` where ``gap_s`` is the time since the previous Status.
    """
    events, clears = [], []
    for i in range(1, len(values)):
        prev, cur = values[i - 1], values[i]
        gap = int(ts[i] - ts[i - 1])
        if cur > prev:
            events.append((int(ts[i]), int(cur - prev), gap))
        elif cur < prev:
            clears.append(int(ts[i]))
            if cur > 0:
                events.append((int(ts[i]), int(cur), gap))
    return events, clears


def power_health(msgs: pd.DataFrame) -> tuple[dict[str, dict], dict]:
    up = uplinks(msgs)
    battery, resets, clears, modes, per_node = [], [], [], [], {}
    for key, u in up.groupby("node_key", sort=True):
        meta = _node_meta(key)
        b = u[u["battery_voltage"].fillna(0) > 0]
        t, v = b["timestamp"].to_numpy(), b["battery_voltage"].to_numpy(dtype=float)
        idx = downsample_indices(len(t), MAX_BATTERY_POINTS)
        battery.append({"key": key, "company": meta["company"], "node_id": meta["node_id"],
                        "points": [[int(t[i]), round(float(v[i]), 4)] for i in idx]})
        slope = None
        if len(t) > 10 and (t.max() - t.min()) >= 86400:
            slope = float(np.polyfit((t - t.min()) / 86400.0, v * 1000.0, 1)[0])
        # counters: Status messages from firmware that reports them (legacy rows decode as 0)
        st = u[(u["type"] == "Status") & (u["power_mode"].fillna(0) != 0)].sort_values("timestamp")
        counts = {}
        for kind, col in (("wdt", "wdt_reset_count"), ("power", "power_reset_count")):
            ev, cl = counter_events(st["timestamp"].to_numpy(), st[col].fillna(0).to_numpy(dtype=int))
            resets.extend({"t": tt, "company": meta["company"], "node_id": meta["node_id"], "key": key,
                           "kind": kind, "delta": d, "gap_s": g, "attributable": g <= ATTRIBUTABLE_GAP_S}
                          for tt, d, g in ev)
            clears.extend({"t": tt, "company": meta["company"], "node_id": meta["node_id"], "key": key,
                           "kind": kind} for tt in cl)
            counts[kind] = int(sum(d for _, d, g in ev if g <= ATTRIBUTABLE_GAP_S))
            counts[kind + "_offline"] = int(sum(d for _, d, g in ev if g > ATTRIBUTABLE_GAP_S))
        mc = u.groupby([u["power_mode"].fillna(0).astype(int), u["power_state"].fillna(0).astype(int)]).size()
        for (mode, state), n in mc.items():
            modes.append({"key": key, "company": meta["company"], "node_id": meta["node_id"],
                          "mode": ds.POWER_MODE_NAMES.get(mode, str(mode)),
                          "state": ds.POWER_STATE_NAMES.get(state, str(state)), "count": int(n)})
        mode_counts = u["power_mode"].fillna(0).astype(int).map(ds.POWER_MODE_NAMES).value_counts()
        per_node[key] = {"battery_last": float(v[-1]) if len(v) else None,
                         "battery_min": float(v.min()) if len(v) else None,
                         "battery_max": float(v.max()) if len(v) else None,
                         "battery_slope_mv_per_day": slope, "wdt_resets": counts["wdt"],
                         "power_resets": counts["power"], "wdt_increments_after_gap": counts["wdt_offline"],
                         "power_increments_after_gap": counts["power_offline"],
                         "power_modes": {k: int(c) for k, c in mode_counts.items()}}
    resets.sort(key=lambda r: r["t"])
    return per_node, {"battery": battery, "resets": resets, "counter_clears": sorted(clears, key=lambda r: r["t"]),
                      "modes": modes,
                      "reset_note": "Resets are counter increments between consecutive Status messages of firmware "
                                    "that reports counters (power_mode != 0); a decrease is an operator clear "
                                    "(CLEAR_WDT_RESETS / CLEAR_POWER_RESETS) and the new value counts as resets since "
                                    "the clear. Only increments across a gap <= 30 min are 'attributable' (timed) and "
                                    "counted in per-node totals; increments after a longer silence (node off, "
                                    "re-flashed or EEPROM restored) are kept with attributable=false. Counter values at "
                                    "the first observation predate the window.",
                      "attributable_gap_s": ATTRIBUTABLE_GAP_S}


# ---------------------------------------------------------------------------
# Sensors
# ---------------------------------------------------------------------------
def sensor_samples(msgs: pd.DataFrame) -> pd.DataFrame:
    """One row per (non ACK-cached) uplink with validated channel values (NaN when invalid/missing)."""
    u = uplinks(msgs)
    u = u[u["time_source"] != "command_ack_cached"].copy()
    out = pd.DataFrame({"t": u["timestamp"].to_numpy(), "node_key": u["node_key"].to_numpy()}, index=u.index)
    live = u["flow_live_valid"].fillna(0) == 1
    mt = u["flow_meter_type"].fillna(0).astype(int)
    out["flow_tuf"] = u["flow"].where(live & (mt == 1))
    out["velocity_tuf"] = u["velocity"].where(live & (mt == 1))
    out["flow_supmea"] = u["flow"].where(live & (mt == 2))
    out["velocity_supmea"] = u["velocity"].where(live & (mt == 2))
    for i, raw in u["secondary_flow_json"].dropna().items():
        try:
            sec = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if int(sec.get("flow_meter_type", 0)) == 2 and int(sec.get("flow_live_valid", 0)) == 1:
            out.at[i, "flow_supmea"] = float(sec.get("flow_rate", np.nan))
            out.at[i, "velocity_supmea"] = float(sec.get("velocity", np.nan))
    out["battery_voltage"] = u["battery_voltage"].where(u["battery_voltage"].fillna(0) > 0)
    hnda = u["soil_moisture_temp_valid"].fillna(0) == 1
    for c in ("soil_temperature", "soil_moisture"):
        out[c] = u[c].where(hnda & (u[c].fillna(0) != 0))
    sondas = u["soil_moisture_temp_ec_valid"].fillna(0) == 1
    for c in ("ec_temperature", "ec_moisture", "electrical_conductivity"):
        out[c] = u[c].where(sondas & (u[c].fillna(0) != 0))
    return out.reset_index(drop=True)


def _channel_stats(x: pd.Series) -> dict[str, Any]:
    x = x.dropna().astype(float)
    if x.empty:
        return {"n": 0, "mean": None, "std": None, "min": None, "p50": None, "max": None}
    return {"n": int(x.size), "mean": float(x.mean()), "std": float(x.std(ddof=1)) if x.size > 1 else 0.0,
            "min": float(x.min()), "p50": float(x.median()), "max": float(x.max())}


def robust_z(samples: pd.DataFrame, channels: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Per-node robust z-scores (median / 1.4826*MAD, falling back to std, then 1)."""
    z = pd.DataFrame(index=samples.index, columns=channels, dtype=float)
    med = pd.DataFrame(index=samples.index, columns=channels, dtype=float)
    for _, g in samples.groupby("node_key"):
        for c in channels:
            x = g[c].astype(float)
            if x.notna().sum() == 0:
                continue
            m = float(x.median())
            scale = 1.4826 * float((x - m).abs().median())
            if not scale > 0:
                scale = float(x.std(ddof=0)) or 1.0
            z.loc[g.index, c] = (x - m) / scale
            med.loc[g.index, c] = m
    return z, med


def anomalies(samples: pd.DataFrame, channels: list[str], top: int = 25, seed: int = 20261105) -> list[dict]:
    from sklearn.ensemble import IsolationForest

    z, med = robust_z(samples, channels)
    has = samples[channels].notna().any(axis=1)
    zz = z[has].fillna(0.0).clip(-50, 50)
    if zz.empty:
        return []
    iso = IsolationForest(n_estimators=300, random_state=seed).fit(zz.to_numpy())
    score = -iso.score_samples(zz.to_numpy())
    order = np.argsort(-score)[:top]
    out = []
    for i in order:
        row_idx = zz.index[i]
        absz = z.loc[row_idx].abs()
        ch = str(absz.idxmax()) if absz.notna().any() else channels[0]
        meta = _node_meta(samples.at[row_idx, "node_key"])
        out.append({"t": int(samples.at[row_idx, "t"]), "company": meta["company"], "node_id": meta["node_id"],
                    "key": samples.at[row_idx, "node_key"], "score": float(score[i]), "channel": ch,
                    "value": float(samples.at[row_idx, ch]), "expected": float(med.at[row_idx, ch]),
                    "robust_z": float(z.at[row_idx, ch])})
    return out


def sensors_analysis(msgs: pd.DataFrame, meter_samples: pd.DataFrame) -> dict[str, Any]:
    s = sensor_samples(msgs)
    names = [c for c, _, _ in SENSOR_CHANNELS]
    channels = []
    for name, unit, label in SENSOR_CHANNELS:
        st = _channel_stats(s[name])
        channels.append({"name": name, "label": label, "unit": unit, **st,
                         "hist": histogram(s[name].dropna(), bins=30) if st["n"] else {"edges": [], "counts": []}})
    per_node = []
    for key, g in s.groupby("node_key", sort=True):
        meta = _node_meta(key)
        for name, unit, _ in SENSOR_CHANNELS:
            st = _channel_stats(g[name])
            if st["n"]:
                per_node.append({"key": key, **meta, "channel": name, "unit": unit, **st})
    present = [c for c in names if s[c].notna().sum() >= 30 and s[c].std(skipna=True) > 0]
    corr = s[present].corr(method="spearman", min_periods=30) if present else pd.DataFrame()
    matrix = [[None if pd.isna(corr.loc[a, b]) else float(corr.loc[a, b]) for b in present] for a in present]
    return {"channels": channels, "per_node": per_node,
            "correlation": {"channels": present, "matrix": matrix, "method": "spearman, pairwise, min 30 pairs"},
            "anomalies": anomalies(s, present),
            "anomaly_method": "IsolationForest (300 trees) on per-node robust z-scores of the channels; the "
                              "reported channel is the one with the largest |robust z|; 'expected' is the node median",
            "quality": data_quality(msgs, meter_samples), "n_samples": int(len(s))}


def data_quality(msgs: pd.DataFrame, meter_samples: pd.DataFrame) -> dict[str, Any]:
    u = uplinks(msgs)
    fresh = u[u["time_source"] != "command_ack_cached"]
    meter = fresh[fresh["flow_meter_type"].fillna(0) > 0]
    pq = meter["flow_period_quality"].fillna(0).astype(int).value_counts().sort_index()
    secondary = int(meter["secondary_flow_json"].notna().sum())
    derived = int(len(meter)) + secondary
    n_ms = int(len(meter_samples))
    per_node = []
    for key, g in u.groupby("node_key", sort=True):
        gm = g[(g["flow_meter_type"].fillna(0) > 0) & (g["time_source"] != "command_ack_cached")]
        per_node.append({"key": key, **_node_meta(key), "uplinks": int(len(g)),
                         "flow_live_valid_rate": float((gm["flow_live_valid"] == 1).mean()) if len(gm) else None,
                         "rtc_valid_rate": float((g["rtc_valid"] == 1).mean()),
                         "legacy_rows_share": float((g["power_mode"].fillna(0) == 0).mean())})
    return {
        "uplinks": int(len(u)), "ack_cached_uplinks": int(len(u) - len(fresh)),
        "flow_live_valid_rate": float((meter["flow_live_valid"] == 1).mean()) if len(meter) else None,
        "rtc_valid_rate": float((u["rtc_valid"] == 1).mean()) if len(u) else None,
        "period_quality": [{"code": int(k), "name": PERIOD_QUALITY_NAMES.get(int(k), str(k)), "count": int(v)}
                           for k, v in pq.items()],
        "alarm_flags_nonzero_share": float((meter["flow_meter_alarm_flags"].fillna(0) != 0).mean()) if len(meter) else None,
        "alarm_flags_values": {str(int(k)): int(v) for k, v in
                               meter["flow_meter_alarm_flags"].fillna(0).astype(int).value_counts().items()},
        "time_source": {str(k): int(v) for k, v in u["time_source"].value_counts().items()},
        "legacy_rows_share": float((u["power_mode"].fillna(0) == 0).mean()) if len(u) else None,
        "meter_samples_rows": n_ms, "message_derived_flow_samples": derived,
        "duplicate_share": float(max(0.0, 1 - n_ms / derived)) if derived else None,
        "duplicate_note": "message-derived flow samples = non-ACK uplinks with a flow meter + secondary-meter JSON "
                          "entries; meter_samples is the server's fingerprint-deduplicated store",
        "per_node": per_node,
    }


# ---------------------------------------------------------------------------
# Commands (descriptive)
# ---------------------------------------------------------------------------
def _outcome_row(g: pd.DataFrame) -> dict[str, Any]:
    acked = int((g["state"] == "acknowledged").sum())
    unknown = int((g["state"] == "outcome_unknown").sum())
    rejected = int((g["state"] == "rejected").sum())
    sup = int((g["state"] == "superseded").sum())
    resolved = acked + unknown + rejected
    lo, hi = wilson_ci(acked, resolved)
    return {"n": int(len(g)), "acked": acked, "unknown": unknown, "rejected": rejected, "superseded": sup,
            "ack_rate": acked / resolved if resolved else None, "ci_low": lo, "ci_high": hi}


def commands_analysis(cmds: pd.DataFrame, events: pd.DataFrame, features: pd.DataFrame) -> dict[str, Any]:
    c = cmds.copy()
    c["last_power_mode"] = features["last_power_mode"].to_numpy()
    c["s_since_uplink"] = features["s_since_uplink"].to_numpy()
    acked = c[c["state"] == "acknowledged"]
    ack_lat = (acked["acknowledged_at"] - acked["submitted_at"]).dropna().to_numpy(dtype=float)
    pub = (c["broker_confirmed_at"] - c["submitted_at"]).dropna().to_numpy(dtype=float)
    by_type = [{"cmd_type": k, "family": ds.CMD_FAMILY.get(k, "other"), **_outcome_row(g)}
               for k, g in c.groupby("cmd_type", sort=True)]
    by_node = [{"key": k, **_node_meta(k), **_outcome_row(g)} for k, g in c.groupby("node_key", sort=True)]
    by_mode = [{"mode": k, **_outcome_row(g)} for k, g in c.groupby("last_power_mode", sort=True)]
    c["recency_bin"] = pd.cut(c["s_since_uplink"], RECENCY_BINS, right=False)
    by_recency = [{"bin_low_s": int(b.left), "bin_high_s": int(b.right), **_outcome_row(g)}
                  for b, g in c.groupby("recency_bin", observed=True)]
    c["day"] = local_day(c["submitted_at"].to_numpy())
    daily = [{"day": d, "count": int(len(g)), "acked": int((g["state"] == "acknowledged").sum()),
              "unknown": int((g["state"] == "outcome_unknown").sum()),
              "rejected": int((g["state"] == "rejected").sum()),
              "superseded": int((g["state"] == "superseded").sum())} for d, g in c.groupby("day", sort=True)]
    ev_counts = events["event"].value_counts()
    unk_then_ack = set(events.loc[events["event"] == "outcome_unknown", "request_id"]) & \
        set(events.loc[events["event"] == "node_ack", "request_id"])
    late = int((acked["reply_late"].fillna(0) == 1).sum())
    totals = {s: int(n) for s, n in c["state"].value_counts().items()}
    totals.update({"total": int(len(c)), "labelled": int(c["labelled"].sum()),
                   "late_acks": late, "outcome_uncertain_flag": int(c["outcome_uncertain"].sum()),
                   "unknown_then_late_ack": int(len(unk_then_ack)),
                   "superseded_with_reply": int(((c["state"] == "superseded") & c["reply_at"].notna()).sum()),
                   "overall_ack_rate": _outcome_row(c)["ack_rate"],
                   "overall_ack_ci": list(wilson_ci(_outcome_row(c)["acked"], int(c["labelled"].sum())))})
    return {"totals": totals, "by_type": by_type, "by_node": by_node, "by_power_mode": by_mode,
            "by_recency": by_recency,
            "ack_latency": {**percentiles(ack_lat, (50, 90, 99)), "max": float(ack_lat.max()) if ack_lat.size else None,
                            "n": int(ack_lat.size), "hist": histogram(np.clip(ack_lat, 0, ACK_LATENCY_EDGES[-1] - 1),
                                                                      edges=ACK_LATENCY_EDGES)},
            "puback_latency": {**percentiles(pub, (50, 90, 99)), "max": float(pub.max()) if pub.size else None,
                               "n": int(pub.size), "hist": histogram(np.clip(pub, 0, PUBACK_EDGES[-1] - 1),
                                                                     edges=PUBACK_EDGES),
                               "note": "broker_confirmed_at and submitted_at are whole seconds"},
            "late_share": late / len(acked) if len(acked) else None,
            "daily": daily, "events": {str(k): int(v) for k, v in ev_counts.items()},
            "ack_rate_definition": "acknowledged / (acknowledged + outcome_unknown + rejected); superseded excluded; "
                                   "Wilson 95% CI"}
