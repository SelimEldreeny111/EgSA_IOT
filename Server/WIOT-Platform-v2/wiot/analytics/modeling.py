"""Training and evaluation of the "Command Delivery Risk" model.

Protocol (all deterministic, seed :data:`SEED`):

1. Label every submitted, non-superseded command: positive = acknowledged by the node (late or not).
2. Temporal hold-out: the earliest ~72% of labelled commands (cut moved to an operator-session
   boundary so no burst straddles the split) train; the rest is touched exactly once at the end.
3. Inside train: 3x repeated 5-fold *grouped* CV, groups = operator burst sessions (commands
   separated by < 30 min), with a different random group->fold assignment per repeat.
4. Rank >= 8 candidates (+ top-3 log-odds ensemble + the operator's recency rule) by CV PR-AUC and
   select the simplest candidate within one paired standard error of the best (one-SE rule).
5. Feature-set experiments with the winner; the smallest set within one *paired* standard error of
   the best set is kept (one-SE rule on per-fold differences).
6. Calibration (identity vs Platt, chosen by cross-fitted Brier on the pooled OOF scores);
   operating threshold = Youden's J on the calibrated OOF probabilities (max-F1 is reported as a
   reference: with ~50% prevalence it degenerates towards "everything is delivered");
   tiers from OOF precision / NPV targets.
7. Refit on all train, evaluate once on the hold-out with 2,000 bootstrap resamples.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import numpy as np
import pandas as pd

from . import dataset as ds
from .common import downsample_indices
from .riskmodel import FittedRiskModel, Member, logit, make_preprocessor, output_to_feature_index, sigmoid

SEED = 20261105
N_SPLITS, N_REPEATS = 5, 3
SESSION_GAP_S = 1800
TRAIN_FRACTION = 0.72
N_BOOTSTRAP = 2000
TIER_PRECISION = 0.80      # LIKELY: OOF precision >= 80%
TIER_NPV = 0.80            # UNLIKELY: OOF share NOT delivered >= 80%
TIER_MIN_N = 10

FEATURE_SETS: dict[str, list[str]] = {
    "all": list(ds.FEATURES),
    "no_identity": [f for f in ds.FEATURES if f not in ds.IDENTITY_FEATURES],
    "no_ack_history": [f for f in ds.FEATURES if f not in ds.HISTORY_FEATURES],
    "no_identity_no_history": [f for f in ds.FEATURES if f not in ds.IDENTITY_FEATURES + ds.HISTORY_FEATURES],
    "link_only": ["s_since_uplink", "s_since_status", "uplinks_10m", "uplinks_60m", "recent_median_interval_s",
                  "last_uplink_was_ack", "last_power_mode", "last_power_state"],
}

CANDIDATE_LABELS = {
    "logreg": "Logistic regression (L2, scaled + one-hot)", "random_forest": "Random forest",
    "extra_trees": "Extra trees", "hist_gb": "HistGradientBoosting", "xgboost": "XGBoost",
    "lightgbm": "LightGBM", "knn": "k-NN (k=15, distance)", "svm_rbf": "SVM (RBF)",
}


# ---------------------------------------------------------------------------
# Candidates
# ---------------------------------------------------------------------------
def candidate_factories() -> dict[str, tuple[str, Callable[[int], Any]]]:
    """name -> (family, factory(seed)). Fixed, deliberately regularised settings for n ~ 300."""
    from lightgbm import LGBMClassifier
    from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier, RandomForestClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.neighbors import KNeighborsClassifier
    from sklearn.svm import SVC
    from xgboost import XGBClassifier

    return {
        "logreg": ("lr", lambda s: LogisticRegression(C=0.3, max_iter=5000)),
        "random_forest": ("rf", lambda s: RandomForestClassifier(
            n_estimators=300, min_samples_leaf=3, max_features="sqrt", random_state=s, n_jobs=4)),
        "extra_trees": ("et", lambda s: ExtraTreesClassifier(
            n_estimators=300, min_samples_leaf=3, max_features="sqrt", random_state=s, n_jobs=4)),
        "hist_gb": ("hgb", lambda s: HistGradientBoostingClassifier(
            learning_rate=0.05, max_iter=200, max_leaf_nodes=8, min_samples_leaf=10, l2_regularization=1.0,
            early_stopping=False, random_state=s)),
        "xgboost": ("xgb", lambda s: XGBClassifier(
            n_estimators=300, learning_rate=0.03, max_depth=3, subsample=0.8, colsample_bytree=0.8,
            min_child_weight=2, reg_lambda=1.0, eval_metric="logloss", tree_method="hist", random_state=s,
            n_jobs=4)),
        "lightgbm": ("lgbm", lambda s: LGBMClassifier(
            n_estimators=300, learning_rate=0.03, num_leaves=8, min_child_samples=10, subsample=0.8,
            subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0, random_state=s, n_jobs=1,
            deterministic=True, force_row_wise=True, verbose=-1)),
        "knn": ("knn", lambda s: KNeighborsClassifier(n_neighbors=15, weights="distance")),
        "svm_rbf": ("svm", lambda s: SVC(C=1.0, gamma="scale", probability=True, random_state=s)),
    }


# ---------------------------------------------------------------------------
# Split and folds
# ---------------------------------------------------------------------------
def sessions(submitted_at: np.ndarray, gap_s: int = SESSION_GAP_S) -> np.ndarray:
    """Operator burst-session id for time-sorted submission times (new session after a gap)."""
    t = np.asarray(submitted_at, dtype=float)
    return np.concatenate([[0], np.cumsum(np.diff(t) > gap_s)]).astype(int) if t.size else np.array([], int)


def temporal_split(submitted_at: np.ndarray, fraction: float = TRAIN_FRACTION,
                   lo: float = 0.70, hi: float = 0.75) -> int:
    """Number of (time-sorted) rows in train: ~``fraction``, moved to the nearest session boundary in [lo, hi]."""
    n = len(submitted_at)
    sess = sessions(submitted_at)
    boundaries = np.flatnonzero(np.diff(sess)) + 1   # first index of each new session
    ok = boundaries[(boundaries >= lo * n) & (boundaries <= hi * n)]
    target = int(round(fraction * n))
    return int(ok[np.argmin(np.abs(ok - target))]) if ok.size else target


def make_folds(groups: np.ndarray, n_splits: int = N_SPLITS, n_repeats: int = N_REPEATS,
               seed: int = SEED) -> list[tuple[int, np.ndarray, np.ndarray]]:
    """Repeated grouped K-fold: per repeat, shuffle groups then greedily balance fold sizes."""
    rng = np.random.default_rng(seed)
    uniq, counts = np.unique(groups, return_counts=True)
    folds = []
    for r in range(n_repeats):
        order = rng.permutation(len(uniq))
        load = np.zeros(n_splits)
        assign = {}
        for i in order:
            k = int(np.argmin(load + rng.random(n_splits) * 1e-6))
            assign[uniq[i]] = k
            load[k] += counts[i]
        fold_of = np.array([assign[g] for g in groups])
        for k in range(n_splits):
            folds.append((r, np.flatnonzero(fold_of != k), np.flatnonzero(fold_of == k)))
    return folds


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
def _safe_ap(y: np.ndarray, s: np.ndarray) -> float:
    from sklearn.metrics import average_precision_score

    return float(average_precision_score(y, s)) if 0 < y.sum() < len(y) else float("nan")


def _safe_auc(y: np.ndarray, s: np.ndarray) -> float:
    from sklearn.metrics import roc_auc_score

    return float(roc_auc_score(y, s)) if 0 < y.sum() < len(y) else float("nan")


def best_f1_threshold(y: np.ndarray, p: np.ndarray) -> tuple[float, float]:
    """(threshold, F1) maximising F1 for the rule ``p >= threshold``."""
    best_t, best_f = 0.5, -1.0
    for t in np.unique(p):
        pred = p >= t
        tp = int((pred & (y == 1)).sum())
        f = 2 * tp / max(1, pred.sum() + y.sum())
        if f > best_f + 1e-12:
            best_t, best_f = float(t), float(f)
    return best_t, best_f


def youden_threshold(y: np.ndarray, p: np.ndarray) -> float:
    from sklearn.metrics import roc_curve

    fpr, tpr, thr = roc_curve(y, p)
    return float(thr[np.argmax(tpr - fpr)])


def threshold_metrics(y: np.ndarray, pred: np.ndarray) -> dict[str, float]:
    y, pred = np.asarray(y).astype(int), np.asarray(pred).astype(bool)
    tp = int((pred & (y == 1)).sum()); fp = int((pred & (y == 0)).sum())
    fn = int((~pred & (y == 1)).sum()); tn = int((~pred & (y == 0)).sum())
    prec = tp / (tp + fp) if tp + fp else float("nan")
    rec = tp / (tp + fn) if tp + fn else float("nan")
    return {"precision": prec, "recall": rec,
            "f1": 2 * tp / (2 * tp + fp + fn) if (2 * tp + fp + fn) else float("nan"),
            "accuracy": (tp + tn) / max(1, len(y)), "specificity": tn / (tn + fp) if tn + fp else float("nan"),
            "tn": tn, "fp": fp, "fn": fn, "tp": tp}


def all_metrics(y: np.ndarray, score: np.ndarray, prob: np.ndarray, pred: np.ndarray) -> dict[str, float]:
    m = threshold_metrics(y, pred)
    return {"pr_auc": _safe_ap(y, score), "roc_auc": _safe_auc(y, score),
            "precision": m["precision"], "recall": m["recall"], "f1": m["f1"], "accuracy": m["accuracy"],
            "specificity": m["specificity"], "brier": float(np.mean((prob - y) ** 2))}


METRIC_NAMES = ["pr_auc", "roc_auc", "precision", "recall", "f1", "accuracy", "specificity", "brier"]


def bootstrap_compare(y: np.ndarray, model: tuple[np.ndarray, np.ndarray, np.ndarray],
                      base: tuple[np.ndarray, np.ndarray, np.ndarray], n_boot: int = N_BOOTSTRAP,
                      seed: int = SEED) -> dict[str, dict]:
    """Paired percentile bootstrap: metric CIs for model and baseline, plus model-minus-baseline deltas."""
    rng = np.random.default_rng(seed)
    point_m, point_b = all_metrics(y, *model), all_metrics(y, *base)
    draws_m = {k: [] for k in METRIC_NAMES}
    draws_b = {k: [] for k in METRIC_NAMES}
    n = len(y)
    for _ in range(n_boot):
        idx = rng.integers(0, n, n)
        yy = y[idx]
        if yy.sum() in (0, n):
            continue
        mm = all_metrics(yy, *(a[idx] for a in model))
        bb = all_metrics(yy, *(a[idx] for a in base))
        for k in METRIC_NAMES:
            draws_m[k].append(mm[k]); draws_b[k].append(bb[k])

    def ci(vals: list[float]) -> tuple[float, float]:
        arr = np.asarray(vals, dtype=float)
        arr = arr[np.isfinite(arr)]
        return (float(np.percentile(arr, 2.5)), float(np.percentile(arr, 97.5))) if arr.size else (np.nan, np.nan)

    out: dict[str, dict] = {"model": {}, "baseline": {}, "delta": {}}
    for k in METRIC_NAMES:
        lo, hi = ci(draws_m[k]); out["model"][k] = {"value": point_m[k], "ci_low": lo, "ci_high": hi}
        lo, hi = ci(draws_b[k]); out["baseline"][k] = {"value": point_b[k], "ci_low": lo, "ci_high": hi}
        d = np.asarray(draws_m[k]) - np.asarray(draws_b[k])
        lo, hi = ci(list(d))
        out["delta"][k] = {"value": point_m[k] - point_b[k], "ci_low": lo, "ci_high": hi,
                           "p_model_better": float(np.mean(d < 0) if k == "brier" else np.mean(d > 0))}
    out["n_resamples"] = len(draws_m["pr_auc"])
    return out


def curve_points(y: np.ndarray, score: np.ndarray, max_points: int = 100) -> dict[str, list]:
    from sklearn.metrics import precision_recall_curve, roc_curve

    prec, rec, _ = precision_recall_curve(y, score)
    order = np.argsort(rec, kind="stable")
    pr = np.column_stack([rec[order], prec[order]])
    fpr, tpr, _ = roc_curve(y, score)
    roc = np.column_stack([fpr, tpr])
    return {"pr": pr[downsample_indices(len(pr), max_points)].tolist(),
            "roc": roc[downsample_indices(len(roc), max_points)].tolist()}


def calibration_bins(y: np.ndarray, p: np.ndarray, n_bins: int = 10) -> list[dict]:
    bins = pd.qcut(p, q=n_bins, duplicates="drop")
    df = pd.DataFrame({"y": y, "p": p, "bin": bins})
    out = []
    for _, g in df.groupby("bin", observed=True):
        out.append({"mean_pred": float(g.p.mean()), "frac_pos": float(g.y.mean()), "n": int(len(g))})
    return out


# ---------------------------------------------------------------------------
# Baseline rule: "node uplinked within the last N seconds"
# ---------------------------------------------------------------------------
@dataclass
class RecencyRule:
    n_seconds: float
    rate_in: float
    rate_out: float

    @classmethod
    def fit(cls, s_since: np.ndarray, y: np.ndarray) -> "RecencyRule":
        best_n, best_f = float(np.median(s_since)), -1.0
        for n in np.unique(s_since):
            pred = s_since <= n
            f = 2 * int((pred & (y == 1)).sum()) / max(1, pred.sum() + y.sum())
            if f > best_f + 1e-12:
                best_n, best_f = float(n), f
        inside = s_since <= best_n
        rate = lambda mask: float((y[mask].sum() + 1) / (mask.sum() + 2))  # noqa: E731 - Laplace smoothing
        return cls(best_n, rate(inside), rate(~inside))

    def predict(self, s_since: np.ndarray) -> np.ndarray:
        return np.asarray(s_since) <= self.n_seconds

    def proba(self, s_since: np.ndarray) -> np.ndarray:
        return np.where(self.predict(s_since), self.rate_in, self.rate_out)

    @staticmethod
    def score(s_since: np.ndarray) -> np.ndarray:
        """Continuous ranking score used for PR/ROC curves: more recent uplink = higher."""
        return -np.log1p(np.asarray(s_since, dtype=float))


# ---------------------------------------------------------------------------
# Cross-validation
# ---------------------------------------------------------------------------
@dataclass
class CVResult:
    name: str
    oof_raw: np.ndarray            # (n_repeats, n) raw log-odds
    folds: list
    y: np.ndarray
    fold_score: np.ndarray | None = None   # optional separate ranking score (baseline)

    def fold_metrics(self) -> tuple[np.ndarray, np.ndarray]:
        aps, aucs = [], []
        for r, _, va in self.folds:
            s = (self.fold_score[r] if self.fold_score is not None else self.oof_raw[r])[va]
            aps.append(_safe_ap(self.y[va], s)); aucs.append(_safe_auc(self.y[va], s))
        return np.asarray(aps), np.asarray(aucs)

    @property
    def pooled_raw(self) -> np.ndarray:
        return self.oof_raw.mean(axis=0)

    def summary(self) -> dict[str, float]:
        aps, aucs = self.fold_metrics()
        p = sigmoid(self.pooled_raw)
        _, f1 = best_f1_threshold(self.y, p)
        n_ok = int(np.isfinite(aps).sum())
        return {"cv_pr_auc": float(np.nanmean(aps)), "cv_pr_auc_std": float(np.nanstd(aps, ddof=1)),
                "cv_pr_auc_se": float(np.nanstd(aps, ddof=1) / np.sqrt(max(1, n_ok))),
                "cv_roc_auc": float(np.nanmean(aucs)), "cv_brier": float(np.mean((p - self.y) ** 2)),
                "best_f1": f1, "n_folds": n_ok}


def fit_members(X: pd.DataFrame, y: np.ndarray, names: list[str], features: list[str],
                seed: int = SEED) -> tuple[Any, list[Member]]:
    numeric = [f for f in features if f in ds.NUMERIC]
    categorical = [f for f in features if f in ds.CATEGORICAL]
    prep = make_preprocessor(numeric, categorical, ds.LOG_FEATURES)
    z = np.asarray(prep.fit_transform(X[features]), dtype=float)
    factories = candidate_factories()
    members = []
    for name in names:
        family, factory = factories[name]
        est = factory(seed)
        est.fit(z, y)
        members.append(Member(family, est))
    return prep, members


def run_cv(X: pd.DataFrame, y: np.ndarray, folds: list, names: list[str], features: list[str],
           seed: int = SEED) -> dict[str, CVResult]:
    """Out-of-fold raw scores for each named candidate (preprocessing refit inside every fold)."""
    oof = {n: np.full((N_REPEATS, len(y)), np.nan) for n in names}
    for r, tr, va in folds:
        prep, members = fit_members(X.iloc[tr], y[tr], names, features, seed)
        z_va = np.asarray(prep.transform(X.iloc[va][features]), dtype=float)
        for name, m in zip(names, members):
            oof[name][r, va] = m.raw(z_va)
    return {n: CVResult(n, oof[n], folds, y) for n in names}


def ensemble_cv(results: dict[str, CVResult], members: list[str], name: str = "ensemble_top3") -> CVResult:
    first = results[members[0]]
    raw = np.mean([results[m].oof_raw for m in members], axis=0)
    return CVResult(name, raw, first.folds, first.y)


def baseline_cv(s_since: np.ndarray, y: np.ndarray, folds: list) -> CVResult:
    """Recency rule with N re-chosen on each fold's training part."""
    raw = np.full((N_REPEATS, len(y)), np.nan)
    score = np.tile(RecencyRule.score(s_since), (N_REPEATS, 1))
    for r, tr, va in folds:
        rule = RecencyRule.fit(s_since[tr], y[tr])
        raw[r, va] = logit(rule.proba(s_since[va]))
    return CVResult("baseline_recency_rule", raw, folds, y, fold_score=score)


def paired_vs_best(results: dict[str, CVResult]) -> dict[str, dict[str, float]]:
    """Per-fold paired PR-AUC differences of every result against the best one (same folds)."""
    fold_ap = {k: r.fold_metrics()[0] for k, r in results.items()}
    best = max(fold_ap, key=lambda k: np.nanmean(fold_ap[k]))
    out = {}
    for k, ap in fold_ap.items():
        d = ap - fold_ap[best]
        d = d[np.isfinite(d)]
        se = float(np.std(d, ddof=1) / np.sqrt(len(d))) if len(d) > 1 else 0.0
        out[k] = {"best": best, "mean_diff": float(d.mean()) if len(d) else 0.0, "se_diff": se}
    return out


#: Complexity order for the one-SE rule (lower = simpler / more transparent).
COMPLEXITY = {"logreg": 1, "knn": 2, "svm_rbf": 3, "hist_gb": 4, "xgboost": 4, "lightgbm": 4,
              "random_forest": 5, "extra_trees": 5, "ensemble_top3": 6}


def select_simplest(paired: dict[str, dict[str, float]], summ: dict[str, dict]) -> str:
    """Simplest candidate whose CV PR-AUC is within one paired SE of the best candidate."""
    ok = [k for k, v in paired.items() if v["mean_diff"] + v["se_diff"] >= 0]
    return min(ok, key=lambda k: (COMPLEXITY.get(k, 9), -summ[k]["cv_pr_auc"]))


def one_se_choice(results: dict[str, CVResult]) -> str:
    """Smallest feature set whose CV PR-AUC is within one *paired* SE of the best set.

    Fold-level PR-AUC varies mostly because sessions differ in prevalence, so the SE of the
    mean is dominated by between-fold heterogeneity; differences between feature sets are
    therefore judged on paired per-fold differences (same folds, same model).
    """
    paired = paired_vs_best(results)
    ok = [k for k, v in paired.items() if v["mean_diff"] + v["se_diff"] >= 0]
    return min(ok, key=lambda k: (len(FEATURE_SETS[k]), paired[k]["mean_diff"]))


# ---------------------------------------------------------------------------
# Calibration and tiers
# ---------------------------------------------------------------------------
def fit_platt(raw: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    from sklearn.linear_model import LogisticRegression

    lr = LogisticRegression(C=1e6, max_iter=5000).fit(raw.reshape(-1, 1), y)
    return float(lr.coef_[0, 0]), float(lr.intercept_[0])


def calibration_comparison(raw: np.ndarray, y: np.ndarray, groups: np.ndarray, seed: int = SEED) -> dict[str, float]:
    """Cross-fitted Brier score of no calibration, Platt and isotonic on OOF scores."""
    from sklearn.isotonic import IsotonicRegression

    folds = make_folds(groups, N_SPLITS, 1, seed + 1)
    p_platt, p_iso = np.zeros_like(raw), np.zeros_like(raw)
    for _, tr, va in folds:
        a, b = fit_platt(raw[tr], y[tr])
        p_platt[va] = sigmoid(a * raw[va] + b)
        iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(raw[tr], y[tr])
        p_iso[va] = iso.predict(raw[va])
    brier = lambda p: float(np.mean((p - y) ** 2))  # noqa: E731
    return {"none": brier(sigmoid(raw)), "platt": brier(p_platt), "isotonic": brier(p_iso)}


def choose_tiers(y: np.ndarray, p: np.ndarray, threshold: float) -> dict[str, float]:
    """LIKELY if p >= high (OOF precision >= 80%); UNLIKELY if p < low (OOF NPV >= 80%)."""
    grid = np.unique(np.round(p, 4))
    high = None
    for t in grid[grid >= threshold]:
        sel = p >= t
        if sel.sum() >= TIER_MIN_N and y[sel].mean() >= TIER_PRECISION:
            high = float(t)
            break
    low = None
    for t in grid[grid <= threshold][::-1]:
        sel = p < t
        if sel.sum() >= TIER_MIN_N and (1 - y[sel].mean()) >= TIER_NPV:
            low = float(t)
            break
    rule_high = "lowest p with OOF precision >= 0.80 (n >= 10)"
    rule_low = "highest p with OOF negative predictive value >= 0.80 (n >= 10)"
    if high is None:
        high, rule_high = float(min(0.99, threshold + 0.15)), "fallback: threshold + 0.15 (precision target unreachable)"
    if low is None:
        low, rule_low = float(max(0.01, threshold - 0.15)), "fallback: threshold - 0.15 (NPV target unreachable)"
    return {"likely": high, "unlikely": low, "likely_rule": rule_high, "unlikely_rule": rule_low}


def tier_of(p: float, tiers: dict[str, float]) -> str:
    if p >= tiers["likely"]:
        return "LIKELY"
    if p < tiers["unlikely"]:
        return "UNLIKELY"
    return "UNCERTAIN"


def tier_table(y: np.ndarray, p: np.ndarray, tiers: dict[str, float]) -> list[dict]:
    names = np.array([tier_of(float(v), tiers) for v in p])
    out = []
    for t in ("LIKELY", "UNCERTAIN", "UNLIKELY"):
        sel = names == t
        out.append({"tier": t, "n": int(sel.sum()), "share": float(sel.mean()) if len(p) else None,
                    "observed_ack_rate": float(y[sel].mean()) if sel.any() else None})
    return out


# ---------------------------------------------------------------------------
# Schema for the what-if UI
# ---------------------------------------------------------------------------
_STEP = {"battery_v": 0.01, "node_ack_rate": 0.01}


def feature_schema(X: pd.DataFrame, features: list[str]) -> list[dict]:
    schema = []
    for f in features:
        spec = next(s for s in ds.FEATURE_SPECS if s.name == f)
        col = X[f]
        if spec.kind == "category":
            opts = sorted(set(col.astype(str)))
            if f == "cmd_type":
                opts = sorted(set(opts) | set(ds.CMD_FAMILY))
            elif f == "cmd_family":
                opts = sorted(set(opts) | set(ds.CMD_FAMILY.values()))
            elif f == "last_power_mode":
                opts = sorted(set(opts) | set(ds.POWER_MODE_NAMES.values()))
            elif f == "last_power_state":
                opts = sorted(set(opts) | set(ds.POWER_STATE_NAMES.values()))
            schema.append({"name": f, "label": spec.label, "type": "category", "group": spec.group,
                           "default": str(col.astype(str).mode().iloc[0]), "min": None, "max": None,
                           "step": None, "options": opts})
        else:
            vals = pd.to_numeric(col, errors="coerce").dropna()
            lo, hi = float(vals.min()), float(vals.max())
            if f in ("node_ack_rate",):
                lo, hi = 0.0, 1.0
            if f == "hour_local":
                lo, hi = 0.0, 23.0
            if f.startswith("s_since") or f == "recent_median_interval_s":
                lo, hi = 0.0, float(ds.SECONDS_CAP)
            schema.append({"name": f, "label": spec.label, "type": "number", "group": spec.group,
                           "default": float(vals.median()), "min": lo, "max": hi,
                           "step": _STEP.get(f, 1.0), "options": None,
                           "scale": "log" if spec.log else "linear"})
    return schema


# ---------------------------------------------------------------------------
# End-to-end training
# ---------------------------------------------------------------------------
@dataclass
class TrainingOutput:
    model_json: dict
    model: FittedRiskModel
    extras: dict


def _member_names(selected: str, ranking: list[str]) -> list[str]:
    return ranking[:3] if selected == "ensemble_top3" else [selected]


def train_and_evaluate(X_all: pd.DataFrame, cmds: pd.DataFrame, seed: int = SEED,
                       log: Callable[[str], None] = print) -> TrainingOutput:
    lab = cmds["labelled"].to_numpy()
    X = X_all[lab].reset_index(drop=True)
    meta = cmds[lab].reset_index(drop=True)
    order = np.argsort(meta["submitted_at"].to_numpy(), kind="stable")
    X, meta = X.iloc[order].reset_index(drop=True), meta.iloc[order].reset_index(drop=True)
    y_all = meta["y_ack"].to_numpy(dtype=int)
    t_all = meta["submitted_at"].to_numpy()
    n_train = temporal_split(t_all)
    tr, te = np.arange(n_train), np.arange(n_train, len(meta))
    Xtr, ytr, Xte, yte = X.iloc[tr].reset_index(drop=True), y_all[tr], X.iloc[te].reset_index(drop=True), y_all[te]
    groups = sessions(t_all)[tr]
    folds = make_folds(groups, N_SPLITS, N_REPEATS, seed)
    log(f"  train={len(tr)} (pos {ytr.sum()}), test={len(te)} (pos {yte.sum()}), CV groups={len(np.unique(groups))}")

    # 1) candidates on all features
    names = list(candidate_factories())
    cv = run_cv(Xtr, ytr, folds, names, FEATURE_SETS["all"], seed)
    summ = {n: r.summary() for n, r in cv.items()}
    ranking = sorted(names, key=lambda n: -summ[n]["cv_pr_auc"])
    cv["ensemble_top3"] = ensemble_cv(cv, ranking[:3])
    summ["ensemble_top3"] = cv["ensemble_top3"].summary()
    s_tr = Xtr["s_since_uplink"].to_numpy()
    cv["baseline_recency_rule"] = baseline_cv(s_tr, ytr, folds)
    summ["baseline_recency_rule"] = cv["baseline_recency_rule"].summary()
    model_like = [n for n in summ if n != "baseline_recency_rule"]
    model_paired = paired_vs_best({n: cv[n] for n in model_like})
    selected = select_simplest(model_paired, summ)
    best_model = model_paired[selected]["best"]
    members = _member_names(selected, ranking)
    log(f"  CV ranking: " + ", ".join(f"{n}={summ[n]['cv_pr_auc']:.3f}" for n in sorted(summ, key=lambda k: -summ[k]['cv_pr_auc'])))

    # 2) feature-set experiments with the selected configuration
    fs_summ, fs_cv = {}, {}
    for fs_name, feats in FEATURE_SETS.items():
        res = run_cv(Xtr, ytr, folds, members, feats, seed) if fs_name != "all" else {m: cv[m] for m in members}
        r = ensemble_cv(res, members, selected) if len(members) > 1 else res[members[0]]
        fs_cv[fs_name], fs_summ[fs_name] = r, r.summary()
    # reference: logistic regression on the same sets (cheap, shows whether the winner's gains are robust)
    lr_fs = {}
    for fs_name, feats in FEATURE_SETS.items():
        lr_fs[fs_name] = (cv["logreg"] if fs_name == "all" else run_cv(Xtr, ytr, folds, ["logreg"], feats, seed)["logreg"]).summary()
    chosen_set = one_se_choice(fs_cv)
    fs_paired = paired_vs_best(fs_cv)
    features = FEATURE_SETS[chosen_set]
    log(f"  feature sets: " + ", ".join(f"{k}={v['cv_pr_auc']:.3f}" for k, v in fs_summ.items()) + f" -> {chosen_set}")

    # 3) calibration + threshold on pooled OOF of the chosen configuration
    oof_raw = fs_cv[chosen_set].pooled_raw
    calib_cmp = calibration_comparison(oof_raw, ytr, groups, seed)
    # Platt keeps explanations exactly additive; isotonic is reported for reference only.
    if calib_cmp["platt"] < calib_cmp["none"]:
        a, b = fit_platt(oof_raw, ytr)
        calib_desc = (f"Platt (sigmoid) fitted on pooled train out-of-fold scores; cross-fitted Brier "
                      f"{calib_cmp['platt']:.3f} vs {calib_cmp['none']:.3f} uncalibrated")
    else:
        a, b = 1.0, 0.0
        calib_desc = (f"none (identity mapping) - Platt ({calib_cmp['platt']:.3f}) and isotonic "
                      f"({calib_cmp['isotonic']:.3f}) did not "
                      f"improve the cross-fitted Brier score of the raw model ({calib_cmp['none']:.3f}) on train "
                      f"OOF scores, so raw log-odds are used as calibrated probabilities")
    p_oof = sigmoid(a * oof_raw + b)
    f1_threshold, f1_oof = best_f1_threshold(ytr, p_oof)
    threshold = youden_threshold(ytr, p_oof)
    oof_at_thr = threshold_metrics(ytr, p_oof >= threshold)
    oof_at_f1 = threshold_metrics(ytr, p_oof >= f1_threshold)
    tiers = choose_tiers(ytr, p_oof, threshold)

    # 4) refit on all train
    prep, fitted = fit_members(Xtr, ytr, members, features, seed)
    z_tr = np.asarray(prep.transform(Xtr[features]), dtype=float)
    rng = np.random.default_rng(seed)
    bg = z_tr[rng.choice(len(z_tr), size=min(100, len(z_tr)), replace=False)]
    model = FittedRiskModel(name=selected, features=features,
                            numeric=[f for f in features if f in ds.NUMERIC],
                            categorical=[f for f in features if f in ds.CATEGORICAL],
                            prep=prep, members=fitted, background=bg,
                            col_to_feature=output_to_feature_index(prep, features), platt_a=a, platt_b=b)

    # 5) hold-out, once
    p_te = model.predict_proba(Xte)
    rule = RecencyRule.fit(s_tr, ytr)
    s_te = Xte["s_since_uplink"].to_numpy()
    base_score, base_prob, base_pred = RecencyRule.score(s_te), rule.proba(s_te), rule.predict(s_te)
    boot = bootstrap_compare(yte, (p_te, p_te, p_te >= threshold), (base_score, base_prob, base_pred), seed=seed)
    cm_model = threshold_metrics(yte, p_te >= threshold)
    cm_base = threshold_metrics(yte, base_pred)
    f1thr_holdout = threshold_metrics(yte, p_te >= f1_threshold)
    curves_m, curves_b = curve_points(yte, p_te), curve_points(yte, base_score)

    # 6) explanations
    phi, base_val = model.contributions(Xtr)
    mean_abs = np.abs(phi).mean(axis=0)
    shap_global = sorted(({"feature": f, "label": ds.FEATURE_LABELS[f], "mean_abs_shap": float(v),
                           "mean_shap": float(phi[:, i].mean())} for i, (f, v) in enumerate(zip(features, mean_abs))),
                         key=lambda d: -d["mean_abs_shap"])[:15]
    additivity_err = float(np.max(np.abs(base_val + phi.sum(axis=1) - model.calibrated_logit(Xtr))))

    # 7) target variants (reported only; never used for selection)
    variants = []
    for target, label in (("y_ack", "acknowledged (late or on time) - primary"),
                          ("y_ontime", "acknowledged within the 30 s deadline only"),
                          ("y_reply", "any node reply (acknowledged or rejected)")):
        yv_all = meta[target].to_numpy(dtype=int)
        yv_tr, yv_te = yv_all[tr], yv_all[te]
        if target == "y_ack":
            cv_s = fs_summ[chosen_set]
        else:
            res = run_cv(Xtr, yv_tr, folds, members, features, seed)
            cv_s = (ensemble_cv(res, members) if len(members) > 1 else res[members[0]]).summary()
        prep_v, fit_v = fit_members(Xtr, yv_tr, members, features, seed)
        zv = np.asarray(prep_v.transform(Xte[features]), dtype=float)
        sv = np.mean([m.raw(zv) for m in fit_v], axis=0)
        variants.append({"target": target, "definition": label, "pos_train": int(yv_tr.sum()),
                         "pos_test": int(yv_te.sum()), "cv_pr_auc": cv_s["cv_pr_auc"],
                         "cv_pr_auc_std": cv_s["cv_pr_auc_std"], "holdout_pr_auc": _safe_ap(yv_te, sv),
                         "holdout_roc_auc": _safe_auc(yv_te, sv),
                         "holdout_prevalence": float(yv_te.mean())})

    # per-node hold-out breakdown (descriptive)
    per_node = []
    for key in sorted(set(meta["node_key"].iloc[te])):
        sel = (meta["node_key"].iloc[te] == key).to_numpy()
        per_node.append({"node_key": key, "n": int(sel.sum()), "ack_rate": float(yte[sel].mean()),
                         "mean_pred": float(p_te[sel].mean()),
                         "model_accuracy": float(((p_te[sel] >= threshold) == yte[sel]).mean()),
                         "baseline_accuracy": float((base_pred[sel] == yte[sel]).mean())})

    labels = dict(CANDIDATE_LABELS)
    labels["ensemble_top3"] = "Ensemble: mean log-odds of " + " + ".join(ranking[:3])
    labels["baseline_recency_rule"] = "Baseline rule: node uplinked within the last N s"
    candidates = []
    for n in sorted(summ, key=lambda k: -summ[k]["cv_pr_auc"]):
        s = summ[n]
        candidates.append({"name": n, "label": labels.get(n, n), "kind": "baseline" if n.startswith("baseline")
                           else ("ensemble" if n.startswith("ensemble") else "model"),
                           "cv_pr_auc": s["cv_pr_auc"], "cv_pr_auc_std": s["cv_pr_auc_std"],
                           "cv_roc_auc": s["cv_roc_auc"], "cv_brier": s["cv_brier"], "best_f1": s["best_f1"],
                           "paired_diff_vs_best": model_paired[n]["mean_diff"] if n in model_paired else None,
                           "paired_se": model_paired[n]["se_diff"] if n in model_paired else None,
                           "within_one_se": (model_paired[n]["mean_diff"] + model_paired[n]["se_diff"] >= 0)
                           if n in model_paired else None, "complexity": COMPLEXITY.get(n)})

    train_end, test_start = int(t_all[n_train - 1]), int(t_all[n_train])
    why = (f"One-SE rule: the best mean grouped-CV PR-AUC among {len(model_like)} model candidates was {best_model} "
           f"({summ[best_model]['cv_pr_auc']:.3f}); {selected} ({summ[selected]['cv_pr_auc']:.3f} +/- "
           f"{summ[selected]['cv_pr_auc_std']:.3f}) is the simplest candidate within one paired standard error of it "
           f"(paired difference {model_paired[selected]['mean_diff']:+.3f}, SE {model_paired[selected]['se_diff']:.3f}). "
           f"Feature set '{chosen_set}' = smallest set within one paired SE of the best set with that model.")
    model_json = {
        "task": "Command Delivery Risk: will a command published now be acknowledged by the node?",
        "target_definition": ("Submitted, non-superseded commands from command_lifecycle.db. Positive = state "
                              "'acknowledged' (node_ack / receipt success=1, on time or late). Negative = "
                              "'outcome_unknown' (no ACK within the 30 s deadline) or 'rejected'. Superseded "
                              "commands are excluded from the target."),
        "positive_label": "delivered (acknowledged)",
        "n_train": int(len(tr)), "n_test": int(len(te)), "pos_train": int(ytr.sum()), "pos_test": int(yte.sum()),
        "n_superseded_excluded": int((~lab).sum()),
        "split": {"method": f"temporal hold-out: earliest {len(tr)} labelled commands (~{len(tr) / len(meta):.0%}) "
                            f"train, latest {len(te)} test; cut placed on an operator-session boundary",
                  "train_end": train_end, "test_start": test_start,
                  "cv": f"{N_REPEATS}x repeated {N_SPLITS}-fold grouped CV on train; groups = operator burst "
                        f"sessions (gap > {SESSION_GAP_S // 60} min), {len(np.unique(groups))} sessions"},
        "candidates": candidates,
        "feature_set_experiments": [{"name": k, "n_features": len(FEATURE_SETS[k]), "features": FEATURE_SETS[k],
                                     "cv_pr_auc": v["cv_pr_auc"], "cv_pr_auc_std": v["cv_pr_auc_std"],
                                     "cv_roc_auc": v["cv_roc_auc"], "logreg_cv_pr_auc": lr_fs[k]["cv_pr_auc"],
                                     "paired_diff_vs_best": fs_paired[k]["mean_diff"],
                                     "paired_se": fs_paired[k]["se_diff"], "chosen": k == chosen_set}
                                    for k, v in fs_summ.items()],
        "selected": {"name": selected, "members": members, "feature_set": chosen_set, "features": features,
                     "why": why, "calibration": calib_desc,
                     "calibration_brier_crossfit": calib_cmp, "platt": {"a": a, "b": b},
                     "threshold": threshold,
                     "threshold_rule": ("Youden's J (max TPR - FPR) on calibrated train OOF probabilities. Max-F1 was "
                                        f"considered: it selects {f1_threshold:.2f}, flagging "
                                        f"{(oof_at_f1['tp'] + oof_at_f1['fp']) / len(ytr):.0%} of train commands as "
                                        f"delivered (OOF specificity {oof_at_f1['specificity']:.2f}), i.e. nearly "
                                        "'always send', so the balanced Youden point is used."),
                     "threshold_oof_metrics": {k: oof_at_thr[k] for k in ("precision", "recall", "f1", "specificity")},
                     "f1_threshold_reference": f1_threshold, "f1_threshold_oof_f1": f1_oof,
                     "holdout_at_f1_threshold_reference": {k: f1thr_holdout[k] for k in
                                                           ("precision", "recall", "f1", "accuracy", "specificity")},
                     "tiers": {"likely": tiers["likely"], "unlikely": tiers["unlikely"],
                               "likely_rule": tiers["likely_rule"], "unlikely_rule": tiers["unlikely_rule"]},
                     "tier_table_oof": tier_table(ytr, p_oof, tiers),
                     "tier_table_holdout": tier_table(yte, p_te, tiers)},
        "holdout": {"model": boot["model"], "baseline": boot["baseline"], "delta_model_minus_baseline": boot["delta"],
                    "n_bootstrap": boot["n_resamples"], "bootstrap": "paired percentile bootstrap over hold-out commands",
                    "baseline_definition": (f"Operator rule: predict delivered if the node's last uplink was within "
                                            f"N = {rule.n_seconds:.0f} s (N maximises F1 on train). PR/ROC use the "
                                            f"continuous recency score -log(1 + seconds since last uplink); Brier uses "
                                            f"the train delivery rate on each side of N ({rule.rate_in:.2f} / "
                                            f"{rule.rate_out:.2f})."),
                    "baseline_n_seconds": rule.n_seconds,
                    "prevalence": float(yte.mean()), "per_node": per_node},
        "confusion": {"model": {k: cm_model[k] for k in ("tn", "fp", "fn", "tp")},
                      "baseline": {k: cm_base[k] for k in ("tn", "fp", "fn", "tp")}},
        "curves": {"pr": {"model": curves_m["pr"], "baseline": curves_b["pr"]},
                   "roc": {"model": curves_m["roc"], "baseline": curves_b["roc"]}},
        "calibration": calibration_bins(ytr, p_oof),
        "shap_global": shap_global,
        "shap_units": "calibrated log-odds of delivery; base_value + sum(contributions) = logit(probability)",
        "shap_additivity_max_error": additivity_err,
        "target_variants": variants,
        "feature_schema": feature_schema(Xtr, features),
        "notes": [],
    }
    extras = {"threshold": threshold, "tiers": tiers, "rule": rule, "p_oof": p_oof, "y_oof": ytr, "p_te": p_te,
              "y_te": yte, "X_tr": Xtr, "X_te": Xte, "meta_te": meta.iloc[te].reset_index(drop=True),
              "meta_tr": meta.iloc[tr].reset_index(drop=True), "summ": summ, "fs_summ": fs_summ,
              "ranking": ranking, "phi_tr": phi, "selected": selected, "chosen_set": chosen_set,
              "base_score_te": base_score}
    return TrainingOutput(model_json, model, extras)
