"""Small shared helpers: JSON serialisation, robust statistics, histograms, time zones."""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np

LOCAL_TZ = "Africa/Cairo"


def _round_float(x: float, digits: int) -> float | None:
    if x is None or not math.isfinite(x):
        return None
    if x == 0:
        return 0.0
    # Keep `digits` decimals but never lose more than ~6 significant figures on large numbers.
    return round(x, digits) if abs(x) < 1e6 else float(f"{x:.7g}")


def to_jsonable(obj: Any, digits: int = 4) -> Any:
    """Recursively convert numpy/pandas scalars to JSON-safe Python values (NaN/inf -> None)."""
    if obj is None or isinstance(obj, (str, bool)):
        return obj
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (int, np.integer)):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        return _round_float(float(obj), digits)
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v, digits) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [to_jsonable(v, digits) for v in obj]
    if isinstance(obj, np.ndarray):
        return [to_jsonable(v, digits) for v in obj.tolist()]
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    try:  # pandas NA / NaT
        import pandas as pd

        if pd.isna(obj):
            return None
    except (TypeError, ValueError):
        pass
    return str(obj)


def write_json(path: Path, obj: Any, digits: int = 4) -> None:
    """Write strictly valid JSON (``allow_nan=False``) after conversion."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = to_jsonable(obj, digits)
    path.write_text(json.dumps(data, indent=1, allow_nan=False, ensure_ascii=False), encoding="utf-8")


def percentiles(values: Iterable[float], qs: Sequence[float] = (50, 90, 99)) -> dict[str, float | None]:
    arr = np.asarray(list(values), dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return {f"p{int(q)}": None for q in qs}
    return {f"p{int(q)}": float(np.percentile(arr, q)) for q in qs}


def histogram(values: Iterable[float], edges: Sequence[float] | None = None, bins: int = 30,
              log: bool = False) -> dict[str, list]:
    """Histogram as ``{"edges": [...], "counts": [...]}`` (len(edges) == len(counts) + 1)."""
    arr = np.asarray(list(values), dtype=float)
    arr = arr[np.isfinite(arr)]
    if edges is None:
        if arr.size == 0:
            return {"edges": [], "counts": []}
        lo, hi = float(arr.min()), float(arr.max())
        if log:
            lo = max(lo, 1e-3)
            hi = max(hi, lo * 10)
            edges = np.logspace(math.log10(lo), math.log10(hi), bins + 1)
        else:
            if hi == lo:
                hi = lo + 1.0
            edges = np.linspace(lo, hi, bins + 1)
    counts, e = np.histogram(arr, bins=np.asarray(edges, dtype=float))
    return {"edges": [float(x) for x in e], "counts": [int(c) for c in counts]}


def wilson_ci(successes: int, n: int, z: float = 1.959964) -> tuple[float | None, float | None]:
    """Wilson score 95% interval for a binomial proportion."""
    if n <= 0:
        return None, None
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def downsample_indices(n: int, max_points: int) -> np.ndarray:
    """Evenly spaced indices (always keeping first and last) to cap a series length."""
    if n <= max_points:
        return np.arange(n)
    return np.unique(np.linspace(0, n - 1, max_points).round().astype(int))


def local_hour(epoch_seconds: Sequence[float] | np.ndarray) -> np.ndarray:
    import pandas as pd

    ts = pd.to_datetime(np.asarray(epoch_seconds, dtype="int64"), unit="s", utc=True)
    return np.asarray(ts.tz_convert(LOCAL_TZ).hour, dtype=int)


def local_day(epoch_seconds: Sequence[float] | np.ndarray) -> np.ndarray:
    """Local (Africa/Cairo) calendar day as ``YYYY-MM-DD`` strings."""
    import pandas as pd

    ts = pd.to_datetime(np.asarray(epoch_seconds, dtype="int64"), unit="s", utc=True)
    return np.asarray(ts.tz_convert(LOCAL_TZ).strftime("%Y-%m-%d"), dtype=object)
