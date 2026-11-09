"""Serve-time "Command Delivery Risk" predictor.

Usage::

    from wiot.analytics.predictor import CommandRiskPredictor
    pred = CommandRiskPredictor.load("data/analytics")
    pred.feature_schema()                     # what-if form definition
    pred.predict({"cmd_type": "VALVE", "s_since_uplink": 12, ...})
    pred.predict_live("Company_1", "Region_1", 2, "VALVE", now=None, data_dir=...)

Only numpy/pandas/joblib are imported here; the model's own libraries (scikit-learn and,
depending on the winner, xgboost/lightgbm) are imported when ``model.joblib`` is unpickled,
and ``shap`` only on the first explanation that needs ``TreeExplainer``.
"""
from __future__ import annotations

import math
import time
from pathlib import Path
from typing import Any

MODEL_FILE = "model.joblib"
TOP_CONTRIBUTIONS = 10


class CommandRiskPredictor:
    """P(command is acknowledged) with tier and additive (SHAP) explanation."""

    def __init__(self, bundle: dict[str, Any]):
        self.bundle = bundle
        self.model = bundle["model"]
        self.threshold = float(bundle["threshold"])
        self.tiers = {k: float(bundle["tiers"][k]) for k in ("likely", "unlikely")}
        self._schema = bundle["feature_schema"]
        self._defaults = {f["name"]: f["default"] for f in self._schema}
        self._labels = bundle.get("labels", {})
        self._cmd_family = bundle.get("cmd_family", {})

    # -- construction ------------------------------------------------------
    @classmethod
    def load(cls, out_dir: str | Path) -> "CommandRiskPredictor":
        import joblib

        path = Path(out_dir) / MODEL_FILE
        if not path.exists():
            raise FileNotFoundError(f"{path} not found - run `python -m wiot.analytics.pipeline` first")
        return cls(joblib.load(path))

    def warmup(self) -> None:
        """Run one prediction so lazy imports (e.g. shap) and explainers are ready."""
        self.predict(dict(self._defaults))

    # -- metadata ----------------------------------------------------------
    def feature_schema(self) -> list[dict[str, Any]]:
        return [dict(f) for f in self._schema]

    @property
    def info(self) -> dict[str, Any]:
        b = self.bundle
        return {"model": b.get("model_name"), "trained_at": b.get("trained_at"), "threshold": self.threshold,
                "tiers": self.tiers, "features": list(self.model.features), "version": b.get("version")}

    # -- prediction --------------------------------------------------------
    def complete(self, features: dict[str, Any]) -> dict[str, Any]:
        """Fill missing features with schema defaults; derive cmd_family from cmd_type."""
        from .dataset import POWER_MODE_NAMES, POWER_STATE_NAMES

        row = {k: v for k, v in features.items() if v is not None}
        for name, default in self._defaults.items():
            row.setdefault(name, default)
        if "cmd_type" in row and str(row["cmd_type"]) in self._cmd_family:
            row["cmd_family"] = self._cmd_family[str(row["cmd_type"])]
        # accept numeric power mode/state codes as well as their names
        for key, names in (("last_power_mode", POWER_MODE_NAMES), ("last_power_state", POWER_STATE_NAMES)):
            val = row.get(key)
            if isinstance(val, (int, float)) or (isinstance(val, str) and val.isdigit()):
                row[key] = names.get(int(val), names[0])
        return row

    def tier(self, p: float) -> str:
        if p >= self.tiers["likely"]:
            return "LIKELY"
        if p < self.tiers["unlikely"]:
            return "UNLIKELY"
        return "UNCERTAIN"

    def predict(self, features: dict[str, Any]) -> dict[str, Any]:
        row = self.complete(features)
        phi, base = self.model.contributions(row)
        logit = float(base[0] + phi[0].sum())
        p = 1.0 / (1.0 + math.exp(-logit))
        contrib = []
        for i, name in enumerate(self.model.features):
            val = row.get(name)
            if hasattr(val, "item"):
                val = val.item()
            if isinstance(val, float) and not math.isfinite(val):
                val = None
            contrib.append({"feature": name, "label": self._labels.get(name, name), "value": val,
                            "shap": round(float(phi[0, i]), 5)})
        contrib.sort(key=lambda c: -abs(c["shap"]))
        base_value = float(base[0])
        return {"probability": round(p, 5), "tier": self.tier(p), "threshold": round(self.threshold, 5),
                "predicted_delivered": bool(p >= self.threshold),
                "contributions": contrib[:TOP_CONTRIBUTIONS], "base_value": round(base_value, 5),
                "base_probability": round(1.0 / (1.0 + math.exp(-base_value)), 5),
                "units": "log-odds (base_value + sum of all contributions = logit(probability))"}

    def predict_live(self, company: str, region: str, node_id: int, cmd_type: str, now: float | None = None,
                     data_dir: str | Path | None = None) -> dict[str, Any]:
        from .dataset import build_live_features

        if data_dir is None:
            data_dir = self.bundle.get("data_dir")
        now = int(time.time()) if now is None else int(now)
        feats = build_live_features(company, region, int(node_id), cmd_type, now, data_dir)
        out = self.predict(feats)
        out["features"] = {k: (None if isinstance(v, float) and not math.isfinite(v) else v) for k, v in feats.items()}
        out["as_of"] = now
        return out
