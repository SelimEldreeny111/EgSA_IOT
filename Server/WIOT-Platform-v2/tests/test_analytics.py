"""Tests for wiot.analytics: no-leakage feature builder, helpers, artifacts and predictor round-trip."""
from __future__ import annotations

import json
import math
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from wiot.analytics import dataset as ds
from wiot.analytics.descriptive import counter_events

PLATFORM = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("WIOT_ANALYTICS_DATA_DIR",
                               PLATFORM.parent / "WIOT-Server-Web v1.31 - Fixed Sensor Readings in Dashboard"))
OUT_DIR = Path(os.environ.get("WIOT_ANALYTICS_OUT", PLATFORM / "data" / "analytics"))
ARTIFACTS = ["summary", "link", "power", "sensors", "commands", "model", "firmware", "project"]

needs_data = pytest.mark.skipif(not (DATA_DIR / "command_lifecycle.db").exists(), reason="source databases not present")
needs_artifacts = pytest.mark.skipif(not (OUT_DIR / "model.joblib").exists(), reason="run the pipeline first")


# ---------------------------------------------------------------------------
# Synthetic timeline for the no-leakage tests
# ---------------------------------------------------------------------------
def _messages(extra: list[tuple] = ()) -> pd.DataFrame:
    rows = [  # (id, timestamp, type, power_mode, battery, time_source)
        (1, 100, "Status", 5, 3.70, "server_received"),
        (2, 200, "Status", 5, 3.69, "server_received"),
        (3, 205, "Command", 0, 0.0, "server_received"),       # history copy, never an uplink
        (4, 300, "Status", 3, 3.68, "server_received"),
        (5, 305, "Telemetry", 3, 3.68, "command_ack_cached"),
        *extra,
    ]
    df = pd.DataFrame(rows, columns=["id", "timestamp", "type", "power_mode", "battery_voltage", "time_source"])
    df["company"], df["region"], df["node_id"] = "C", "R", 7
    df["power_state"], df["details"] = 1, ""
    df["wake_remaining_seconds"] = df["wdt_reset_count"] = df["power_reset_count"] = 0
    return df


def _commands(c2_reply_at: float = np.nan) -> pd.DataFrame:
    return pd.DataFrame({
        "company": "C", "region": "R", "node_id": 7, "cmd_type": ["SRATE", "VALVE", "GOSTM"],
        "submitted_at": [150, 250, 290], "ack_deadline": [180, 280, 320],
        "reply_at": [160.0, c2_reply_at, 296.0], "reply_success": [1, 1 if c2_reply_at == c2_reply_at else 0, 1],
    })


def test_features_use_only_the_past():
    feats = ds.command_features(_commands(), _messages())
    c1, c2, c3 = (feats.iloc[i] for i in range(3))
    # c1 at t=150: one uplink (t=100), no previous commands
    assert c1["s_since_uplink"] == 50 and c1["uplinks_10m"] == 1
    assert c1["prev_cmd_acked"] == "none" and c1["node_ack_rate"] == 0.5
    # c2 at t=250: uplinks 100, 200 (the Command row at 205 is not an uplink); c1 replied at 160 -> ACKed
    assert c2["s_since_uplink"] == 50 and c2["uplinks_10m"] == 2
    assert c2["prev_cmd_acked"] == "yes" and c2["s_since_last_ack"] == 90
    assert c2["cmds_prev_5m"] == 1
    # c3 at t=290: last uplink is still t=200 (t=300/305 are in the future); c2's deadline passed -> not ACKed
    assert c3["s_since_uplink"] == 90 and c3["last_power_mode"] == "LORA_WOR_STOP"
    assert c3["prev_cmd_acked"] == "no"
    assert c3["node_ack_rate"] == pytest.approx((1 + 1) / (2 + 2))
    assert c3["last_uplink_was_ack"] == 0


def test_future_data_does_not_change_features():
    base = ds.command_features(_commands(), _messages())
    # add future uplinks, a late ACK for c2 arriving after c3 was sent, and later commands
    future_msgs = _messages(extra=[(6, 291, "Status", 1, 4.2, "server_received"),
                                   (7, 5000, "Telemetry", 1, 4.2, "command_ack_cached")])
    future_cmds = pd.concat([_commands(c2_reply_at=400.0), pd.DataFrame({
        "company": ["C"], "region": ["R"], "node_id": [7], "cmd_type": ["STIME"], "submitted_at": [600],
        "ack_deadline": [630], "reply_at": [601.0], "reply_success": [1]})], ignore_index=True)
    after = ds.command_features(future_cmds.iloc[:3], future_msgs, history=future_cmds)
    pd.testing.assert_frame_equal(base.drop(columns=["hour_local"]), after.drop(columns=["hour_local"]),
                                  check_dtype=False)


def test_unresolved_previous_command_is_ignored():
    cmds = pd.DataFrame({"company": "C", "region": "R", "node_id": 7, "cmd_type": ["SRATE", "STRAN"],
                         "submitted_at": [280, 290], "ack_deadline": [310, 320],
                         "reply_at": [295.0, np.nan], "reply_success": [1, 0]})
    f = ds.command_features(cmds, _messages())
    # at t=290 the SRATE sent at 280 has neither replied (295 is future) nor timed out (310)
    assert f.iloc[1]["prev_cmd_acked"] == "none" and f.iloc[1]["cmds_prev_5m"] == 1


def test_counter_events_increment_and_clear():
    ev, clears = counter_events(np.array([0, 10, 20, 30, 5000]), np.array([3, 3, 5, 0, 2]))
    assert ev == [(20, 2, 10), (5000, 2, 4970)]
    assert clears == [30]


# ---------------------------------------------------------------------------
# Real data (skipped when the databases are absent)
# ---------------------------------------------------------------------------
@needs_data
def test_live_features_equal_training_features():
    msgs, cmds = ds.load_messages(DATA_DIR), ds.load_commands(DATA_DIR)
    train = ds.command_features(cmds, msgs, history=cmds)
    for i in (5, 120, 300, len(cmds) - 1):
        r = cmds.iloc[i]
        live = ds.build_live_features(r.company, r.region, int(r.node_id), r.cmd_type, int(r.submitted_at), DATA_DIR)
        for k, v in live.items():
            t = train.iloc[i][k]
            if isinstance(v, float) and math.isnan(v):
                assert isinstance(t, float) and math.isnan(t)
            else:
                assert v == pytest.approx(t) if isinstance(v, float) else v == t, k


@needs_data
def test_databases_opened_read_only():
    con = ds.connect_ro(DATA_DIR / "command_lifecycle.db")
    try:
        with pytest.raises(Exception):
            con.execute("CREATE TABLE should_fail (x INTEGER)")
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Artifacts and predictor (skipped until the pipeline has run)
# ---------------------------------------------------------------------------
def _strict_load(path: Path):
    def bad(token):
        raise ValueError(f"non-finite number {token} in {path.name}")

    return json.loads(path.read_text(encoding="utf-8"), parse_constant=bad)


@needs_artifacts
def test_artifacts_exist_and_are_strict_json():
    for name in ARTIFACTS:
        data = _strict_load(OUT_DIR / f"{name}.json")
        assert isinstance(data, dict) and data, name
    summary = _strict_load(OUT_DIR / "summary.json")
    assert {"generated_at", "data_window", "counts", "headline", "nodes", "findings"} <= set(summary)
    model = _strict_load(OUT_DIR / "model.json")
    for key in ("candidates", "feature_set_experiments", "selected", "holdout", "confusion", "curves",
                "calibration", "shap_global", "feature_schema", "notes"):
        assert key in model, key
    assert len([c for c in model["candidates"] if c["kind"] != "baseline"]) >= 8
    assert len(model["curves"]["pr"]["model"]) <= 100 and len(model["curves"]["roc"]["model"]) <= 100
    assert (OUT_DIR / "REPORT.md").exists()


@needs_artifacts
def test_predictor_round_trip():
    from wiot.analytics.predictor import CommandRiskPredictor

    t0 = time.perf_counter()
    pred = CommandRiskPredictor.load(OUT_DIR)
    load_s = time.perf_counter() - t0
    schema = pred.feature_schema()
    assert schema and all({"name", "type", "default"} <= set(f) for f in schema)
    defaults = {f["name"]: f["default"] for f in schema}
    out = pred.predict(defaults)
    assert 0.0 <= out["probability"] <= 1.0
    assert out["tier"] in {"LIKELY", "UNCERTAIN", "UNLIKELY"}
    assert len(out["contributions"]) <= 10
    shaps = [abs(c["shap"]) for c in out["contributions"]]
    assert shaps == sorted(shaps, reverse=True)
    # exact additivity over all features, and agreement with the batch model
    phi, base = pred.model.contributions(pred.complete(defaults))
    logit = base[0] + phi[0].sum()
    assert 1 / (1 + math.exp(-logit)) == pytest.approx(out["probability"], abs=1e-4)
    assert float(pred.model.predict_proba(pred.complete(defaults))[0]) == pytest.approx(out["probability"], abs=1e-4)
    # a stale uplink must not look better than a fresh one, all else equal
    fresh = pred.predict({**defaults, "s_since_uplink": 5, "s_since_status": 5})["probability"]
    stale = pred.predict({**defaults, "s_since_uplink": 86400, "s_since_status": 86400, "uplinks_10m": 0,
                          "uplinks_60m": 0})["probability"]
    assert stale <= fresh
    assert load_s < 10  # typically ~1-2 s (dominated by importing scikit-learn)


@needs_artifacts
@needs_data
def test_predict_live_matches_offline_features():
    from wiot.analytics.predictor import CommandRiskPredictor

    pred = CommandRiskPredictor.load(OUT_DIR)
    out = pred.predict_live("Company_1", "Region_1", 2, "VALVE", now=1793700000, data_dir=DATA_DIR)
    assert 0.0 <= out["probability"] <= 1.0 and out["features"]["cmd_family"] == "valve"
