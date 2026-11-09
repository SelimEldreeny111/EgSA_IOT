"""Serialisable "Command Delivery Risk" model with exact additive explanations.

A :class:`FittedRiskModel` holds one shared fitted preprocessor, one or more member
estimators (an ensemble averages the members' log-odds), and a Platt calibrator
``p = sigmoid(a * s + b)`` on the raw (uncalibrated) log-odds ``s``.

Explanations are additive in *calibrated log-odds*::

    base_value + sum(contributions) == a * s + b == logit(probability)

Per-member contributions in raw log-odds come from
- logistic regression: exact linear SHAP (``coef * (z - mean_background)``);
- XGBoost / LightGBM: native TreeSHAP (``pred_contribs`` / ``pred_contrib``), no ``shap`` import;
- RF / ExtraTrees / HistGradientBoosting: ``shap.TreeExplainer`` (imported lazily on first use);
  probability-space values are rescaled to log-odds so they still sum exactly;
- anything else (k-NN, SVM): single-baseline occlusion, rescaled to sum exactly.
Contributions of one-hot columns are summed back to the original feature.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

PROB_CLIP = 0.01  # probability-space members: logit(clip(p, 1%, 99%)) keeps log-odds finite


def safe_log1p(x: np.ndarray) -> np.ndarray:
    """``log1p`` of non-negative values (module-level so the preprocessor pickles)."""
    return np.log1p(np.clip(np.asarray(x, dtype=float), 0.0, None))


def logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(np.asarray(p, dtype=float), 1e-12, 1 - 1e-12)
    return np.log(p / (1 - p))


def sigmoid(z: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.asarray(z, dtype=float)))


def make_preprocessor(numeric: list[str], categorical: list[str], log_features: list[str]):
    """Median-impute + (log1p) + standardise numerics; one-hot categoricals (unknown -> all zeros)."""
    from sklearn.compose import ColumnTransformer
    from sklearn.impute import SimpleImputer
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import FunctionTransformer, OneHotEncoder, StandardScaler

    num_log = [f for f in numeric if f in log_features]
    num_lin = [f for f in numeric if f not in log_features]
    transformers = []
    if num_log:
        transformers.append(("log", Pipeline([
            ("impute", SimpleImputer(strategy="median", keep_empty_features=True)),
            ("log1p", FunctionTransformer(safe_log1p, feature_names_out="one-to-one")),
            ("scale", StandardScaler())]), num_log))
    if num_lin:
        transformers.append(("num", Pipeline([
            ("impute", SimpleImputer(strategy="median", keep_empty_features=True)),
            ("scale", StandardScaler())]), num_lin))
    if categorical:
        transformers.append(("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False), categorical))
    return ColumnTransformer(transformers, remainder="drop", verbose_feature_names_out=False)


def output_to_feature_index(prep, features: list[str]) -> np.ndarray:
    """For each transformed column, the index (into ``features``) of the source feature."""
    idx: list[int] = []
    for name, trans, cols in prep.transformers_:
        if name == "remainder" or trans == "drop":
            continue
        if name == "cat":
            for col, cats in zip(cols, trans.categories_):
                idx.extend([features.index(col)] * len(cats))
        else:
            idx.extend(features.index(c) for c in cols)
    return np.asarray(idx, dtype=int)


@dataclass
class Member:
    """One fitted estimator operating on the shared transformed matrix."""

    family: str          # lr | rf | et | hgb | xgb | lgbm | knn | svm
    estimator: Any
    _explainer: Any = field(default=None, repr=False, compare=False)

    def __getstate__(self) -> dict:
        state = self.__dict__.copy()
        state["_explainer"] = None  # never pickle SHAP explainers; rebuilt lazily
        return state

    # -- scores ------------------------------------------------------------
    def raw(self, z: np.ndarray) -> np.ndarray:
        """Raw log-odds of the positive class."""
        est = self.estimator
        if self.family in ("lr", "hgb"):
            return np.asarray(est.decision_function(z), dtype=float).ravel()
        if self.family == "xgb":
            return np.asarray(est.predict(z, output_margin=True), dtype=float).ravel()
        if self.family == "lgbm":
            return np.asarray(est.predict(z, raw_score=True), dtype=float).ravel()
        p = est.predict_proba(z)[:, 1]
        return logit(np.clip(p, PROB_CLIP, 1 - PROB_CLIP))

    # -- explanations ------------------------------------------------------
    def contributions(self, z: np.ndarray, background: np.ndarray, groups: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """(phi [n, n_columns], base [n]) in raw log-odds; ``base + phi.sum(1) == raw(z)``."""
        fam, est = self.family, self.estimator
        if fam == "lr":
            mu = background.mean(axis=0)
            coef = est.coef_.ravel()
            phi = (z - mu) * coef
            base = np.full(len(z), float(est.intercept_[0] + coef @ mu))
            return phi, base
        if fam == "xgb":
            import xgboost as xgb

            contrib = est.get_booster().predict(xgb.DMatrix(z), pred_contribs=True)
            return contrib[:, :-1], contrib[:, -1]
        if fam == "lgbm":
            contrib = np.asarray(est.predict(z, pred_contrib=True))
            return contrib[:, :-1], contrib[:, -1]
        if fam in ("rf", "et", "hgb"):
            try:
                return self._tree_shap(z)
            except Exception:  # pragma: no cover - fall back if shap is unavailable/unsupported
                pass
        return self._occlusion(z, background, groups)

    def _tree_shap(self, z: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        if self._explainer is None:
            import shap  # lazy: heavy import

            self._explainer = shap.TreeExplainer(self.estimator)
        ex = self._explainer
        vals = ex.shap_values(z, check_additivity=False)
        expected = np.atleast_1d(np.asarray(ex.expected_value, dtype=float))
        if isinstance(vals, list):           # older shap: list per class
            vals = np.asarray(vals[-1])
            expected = expected[-1:]
        vals = np.asarray(vals, dtype=float)
        if vals.ndim == 3:                   # (n, d, classes)
            vals = vals[:, :, -1]
            expected = expected[-1:]
        base0 = float(expected[-1])
        if self.family == "hgb":             # already raw log-odds
            return vals, np.full(len(z), base0)
        # probability space -> rescale to log-odds so that the sum stays exact
        p = np.clip(base0 + vals.sum(axis=1), PROB_CLIP, 1 - PROB_CLIP)
        p0 = float(np.clip(base0, PROB_CLIP, 1 - PROB_CLIP))
        s, s0 = logit(p), float(logit(p0))
        dp = p - p0
        scale = np.where(np.abs(dp) > 1e-9, (s - s0) / np.where(np.abs(dp) > 1e-9, dp, 1.0), 1.0 / (p0 * (1 - p0)))
        return vals * scale[:, None], np.full(len(z), s0)

    def _occlusion(self, z: np.ndarray, background: np.ndarray, groups: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        ref = background.mean(axis=0, keepdims=True)
        s = self.raw(z)
        s_ref = float(self.raw(ref)[0])
        n_groups = int(groups.max()) + 1
        deltas = np.zeros((len(z), n_groups))
        for g in range(n_groups):
            cols = groups == g
            zz = z.copy()
            zz[:, cols] = ref[:, cols]
            deltas[:, g] = s - self.raw(zz)
        total = deltas.sum(axis=1)
        target = s - s_ref
        scale = np.where(np.abs(total) > 1e-9, target / np.where(np.abs(total) > 1e-9, total, 1.0), 0.0)
        deltas *= scale[:, None]
        # spread over the group's first column (aggregation happens per group anyway)
        phi = np.zeros_like(z, dtype=float)
        for g in range(n_groups):
            first = np.flatnonzero(groups == g)[0]
            phi[:, first] = deltas[:, g]
        return phi, np.full(len(z), s_ref)


@dataclass
class FittedRiskModel:
    name: str
    features: list[str]
    numeric: list[str]
    categorical: list[str]
    prep: Any
    members: list[Member]
    background: np.ndarray            # transformed background sample (rows of Z)
    col_to_feature: np.ndarray        # transformed column -> index into `features`
    platt_a: float = 1.0
    platt_b: float = 0.0

    # -- core --------------------------------------------------------------
    def frame(self, X: pd.DataFrame | dict | list[dict]) -> pd.DataFrame:
        if isinstance(X, dict):
            X = pd.DataFrame([X])
        elif isinstance(X, list):
            X = pd.DataFrame(X)
        X = X.copy()
        for col in self.features:
            if col not in X:
                X[col] = np.nan if col in self.numeric else "UNKNOWN"
        for col in self.categorical:
            X[col] = X[col].astype(str)
        for col in self.numeric:
            X[col] = pd.to_numeric(X[col], errors="coerce").astype(float)
        return X[self.features]

    def transform(self, X: pd.DataFrame) -> np.ndarray:
        return np.asarray(self.prep.transform(self.frame(X)), dtype=float)

    def raw_score(self, X: pd.DataFrame) -> np.ndarray:
        z = self.transform(X)
        return np.mean([m.raw(z) for m in self.members], axis=0)

    def calibrated_logit(self, X: pd.DataFrame) -> np.ndarray:
        return self.platt_a * self.raw_score(X) + self.platt_b

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        return sigmoid(self.calibrated_logit(X))

    # -- explanations ------------------------------------------------------
    def contributions(self, X: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        """(phi [n, n_features], base [n]) in calibrated log-odds; rows sum to ``calibrated_logit``."""
        z = self.transform(X)
        phis, bases = [], []
        for m in self.members:
            phi, base = m.contributions(z, self.background, self.col_to_feature)
            phis.append(phi)
            bases.append(base)
        phi_cols = np.mean(phis, axis=0)
        base = np.mean(bases, axis=0)
        phi = np.zeros((len(z), len(self.features)))
        np.add.at(phi.T, self.col_to_feature, phi_cols.T)
        return self.platt_a * phi, self.platt_a * base + self.platt_b
