"""Agronomy science for irrigation planning (R2.4): pure functions, no I/O.

Sources
* FAO Irrigation and Drainage Paper 56 (Allen et al., 1998): stage lengths (Table 11), crop coefficients
  (Table 12), maximum root depth and depletion fraction p (Table 22), soil water characteristics (Table 19),
  the Kc curve (Fig. 25) and the daily root-zone water balance (Chapter 8).
* FAO Irrigation and Drainage Paper 29 Rev. 1 (Ayers & Westcot, 1985): crop salt tolerance (threshold ECe ``a``
  in dS/m and yield decline ``b`` in % per dS/m, after Maas & Hoffman), the leaching requirement
  LR = ECw / (5 ECe - ECw) and the yield potential Y = 100 - b (ECe - a).
* Regulated deficit irrigation (RDI) programmes follow published Mediterranean practice (Fereres & Soriano 2007;
  FAO-66 "Crop yield response to water", 2012) as month windows and a fraction of full ETc.

Values are typical; every field can override them (planting date, soil lab values, root depth).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class Crop:
    name: str
    stages: tuple[int, int, int, int] | None   # initial, development, mid, late (days); None = perennial
    kc: tuple[float, float, float]            # Kc ini, mid, end
    root_m: float                             # maximum effective root depth
    p: float                                  # depletion fraction before stress (RAW = p x TAW)
    ece_a: float                              # FAO-29 salinity threshold, dS/m
    ece_b: float                              # yield decline per dS/m above the threshold, %


CROPS: dict[str, Crop] = {
    "wheat": Crop("Wheat (winter)", (30, 140, 40, 30), (0.70, 1.15, 0.30), 1.5, 0.55, 6.0, 7.1),
    "barley": Crop("Barley", (15, 25, 50, 30), (0.30, 1.15, 0.25), 1.5, 0.55, 8.0, 5.0),
    "maize": Crop("Maize (grain)", (30, 40, 50, 30), (0.30, 1.20, 0.35), 1.7, 0.55, 1.7, 12.0),
    "potato": Crop("Potato", (25, 30, 45, 30), (0.50, 1.15, 0.75), 0.6, 0.35, 1.7, 12.0),
    "tomato": Crop("Tomato", (30, 40, 40, 25), (0.60, 1.15, 0.80), 1.0, 0.40, 2.5, 9.9),
    "onion": Crop("Onion (dry)", (15, 25, 70, 40), (0.70, 1.05, 0.75), 0.5, 0.30, 1.2, 16.0),
    "sugar beet": Crop("Sugar beet", (50, 40, 50, 40), (0.35, 1.20, 0.70), 1.0, 0.55, 7.0, 5.9),
    "cotton": Crop("Cotton", (30, 50, 60, 55), (0.35, 1.18, 0.60), 1.4, 0.65, 7.7, 5.2),
    "alfalfa": Crop("Alfalfa (per cutting cycle)", (10, 30, 25, 10), (0.40, 0.95, 0.90), 1.5, 0.55, 2.0, 7.3),
    "citrus": Crop("Citrus", None, (0.70, 0.65, 0.70), 1.2, 0.50, 1.7, 16.0),
    "olive": Crop("Olive", None, (0.65, 0.70, 0.70), 1.5, 0.65, 4.0, 7.0),
    "date palm": Crop("Date palm", None, (0.90, 0.95, 0.95), 2.0, 0.50, 4.0, 3.6),
    "grape": Crop("Grape (table)", None, (0.30, 0.85, 0.45), 1.5, 0.35, 1.5, 9.6),
}

# Volumetric water content at field capacity and wilting point (m3/m3), FAO-56 Table 19 mid-range values.
SOILS: dict[str, tuple[str, float, float]] = {
    "sand": ("Sand", 0.12, 0.045), "loamy sand": ("Loamy sand", 0.14, 0.06),
    "sandy loam": ("Sandy loam", 0.23, 0.10), "loam": ("Loam", 0.25, 0.12), "silt loam": ("Silt loam", 0.29, 0.15),
    "silt": ("Silt", 0.32, 0.15), "silty clay loam": ("Silty clay loam", 0.34, 0.21),
    "silty clay": ("Silty clay", 0.36, 0.23), "clay": ("Clay", 0.36, 0.22),
}

# Regulated deficit irrigation: (first month, last month, fraction of full ETc, phase); other months = 1.0.
DEFICIT: dict[str, dict] = {
    "olive_rdi": {"name": "Olive - RDI during pit hardening", "crop": "olive", "windows": [
        (7, 8, 0.60, "Pit hardening: least sensitive to water stress"), (11, 1, 0.70, "After harvest")]},
    "date_rdi": {"name": "Date palm - reduced after harvest", "crop": "date palm", "windows": [
        (11, 2, 0.70, "After harvest, before flowering")]},
    "grape_rdi": {"name": "Grape - RDI after fruit set", "crop": "grape", "windows": [
        (6, 7, 0.70, "Fruit set to veraison"), (9, 10, 0.50, "After harvest")]},
    "fixed_80": {"name": "Fixed 80 % of full irrigation", "crop": None, "windows": [(1, 12, 0.80, "All season")]},
}


def crop_key(name: str | None) -> str | None:
    key = (name or "").strip().lower()
    return key if key in CROPS else None


def _in_window(month: int, first: int, last: int) -> bool:
    return first <= month <= last if first <= last else month >= first or month <= last


# ---------------------------------------------------------------- crop calendar
def crop_stage(crop: str, planting: date | None, day: date) -> dict:
    """Growth stage and Kc (FAO-56 Fig. 25: flat initial, linear development, flat mid, linear late)."""
    c = CROPS[crop]
    if c.stages is None:                       # perennial: mid-season coefficient all year, ini in winter
        kc = c.kc[0] if day.month in (12, 1, 2) else c.kc[1]
        return {"stage": "perennial", "kc": kc, "day": None, "season_days": None, "harvest": None}
    if planting is None:
        return {"stage": "unknown", "kc": c.kc[1], "day": None, "season_days": sum(c.stages), "harvest": None}
    ini, dev, mid, late = c.stages
    n = (day - planting).days
    total = ini + dev + mid + late
    harvest = (planting + timedelta(days=total)).isoformat()
    if n < 0:
        return {"stage": "before planting", "kc": 0.0, "day": n, "season_days": total, "harvest": harvest}
    if n < ini:
        stage, kc = "initial", c.kc[0]
    elif n < ini + dev:
        stage, kc = "development", c.kc[0] + (n - ini) / dev * (c.kc[1] - c.kc[0])
    elif n < ini + dev + mid:
        stage, kc = "mid-season", c.kc[1]
    elif n < total:
        stage, kc = "late season", c.kc[1] + (n - ini - dev - mid) / late * (c.kc[2] - c.kc[1])
    else:
        stage, kc = "harvested", 0.0
    return {"stage": stage, "kc": round(kc, 3), "day": n, "season_days": total, "harvest": harvest}


def kc_curve(crop: str, planting: date | None, start: date, days: int = 365) -> list[dict]:
    return [{"date": (start + timedelta(days=i)).isoformat(), **crop_stage(crop, planting, start + timedelta(days=i))}
            for i in range(0, days, 7)]


# ------------------------------------------------------------------ soil profile
def soil_water(soil: dict | None, crop: str | None) -> dict:
    """Field capacity, wilting point (% volumetric), TAW and RAW (mm) and the refill point for one field."""
    soil = soil or {}
    texture = soil.get("texture") or "sandy loam"
    fc = soil.get("fc")
    wp = soil.get("wp")
    if fc is None or wp is None:
        _, fc_v, wp_v = SOILS.get(texture, SOILS["sandy loam"])
        fc, wp = fc_v * 100, wp_v * 100
    fc, wp = float(fc), float(wp)
    if not 0 <= wp < fc <= 60:
        raise ValueError("Wilting point must be below field capacity (volumetric %, 0..60)")
    c = CROPS.get(crop or "")
    root_m = float(soil.get("root_depth_m") or (c.root_m if c else 0.6))
    p = c.p if c else 0.5
    taw = 10 * (fc - wp) * root_m             # mm = 1000 * (theta_fc - theta_wp) * Zr, with theta in %
    return {"texture": texture, "fc": round(fc, 1), "wp": round(wp, 1), "root_depth_m": root_m, "p": p,
            "taw_mm": round(taw, 1), "raw_mm": round(p * taw, 1), "refill": round(fc - p * (fc - wp), 1)}


# --------------------------------------------------------------------- salinity
def salinity(crop: str | None, ece_dsm: float | None, ecw_dsm: float | None) -> dict | None:
    """FAO-29: yield potential at the measured soil salinity and the leaching requirement for the water."""
    c = CROPS.get(crop or "")
    if c is None or (ece_dsm is None and ecw_dsm is None):
        return None
    out = {"threshold_dsm": c.ece_a, "slope_pct": c.ece_b}
    if ece_dsm is not None:
        loss = max(0.0, c.ece_b * (ece_dsm - c.ece_a))
        out.update(ece_dsm=round(ece_dsm, 2), yield_potential_pct=round(max(0.0, 100 - loss), 1),
                   status="ok" if ece_dsm <= c.ece_a else "loss" if loss < 25 else "severe")
    if ecw_dsm is not None and ecw_dsm > 0:
        denom = 5 * c.ece_a - ecw_dsm
        lr = ecw_dsm / denom if denom > 0 else 0.9
        out.update(ecw_dsm=round(ecw_dsm, 2), leaching_requirement=round(min(0.9, lr), 3))
    return out


# ----------------------------------------------------------------------- deficit
def deficit_factor(programme: str | None, day: date) -> tuple[float, str | None]:
    prog = DEFICIT.get(programme or "")
    if not prog:
        return 1.0, None
    for first, last, factor, phase in prog["windows"]:
        if _in_window(day.month, first, last):
            return factor, phase
    return 1.0, None


# ---------------------------------------------------------------- water balance
def moisture_forecast(theta_now: float, soil: dict, days: list[dict], kc_for: callable,
                      deficit_for: callable = lambda d: 1.0, irrigation_mm: dict | None = None) -> list[dict]:
    """Daily root-zone balance (FAO-56 ch. 8, single Kc): theta[d+1] = theta[d] - (ETc - Pe - I) / (10 Zr).

    ``days``: forecast days with ``date``, ``et0_mm`` and ``rain_mm``. Effective rain Pe = 0.8 x rain above
    5 mm/day (light desert showers evaporate). Moisture is capped at field capacity (drainage) and at the
    wilting point. Returns one row per day with the end-of-day moisture and whether it is below refill."""
    irrigation_mm = irrigation_mm or {}
    theta = float(theta_now)
    out = []
    for d in days:
        day = date.fromisoformat(d["date"])
        etc = float(d.get("et0_mm") or 0) * kc_for(day) * deficit_for(day)
        rain = float(d.get("rain_mm") or 0)
        pe = 0.8 * rain if rain > 5 else 0.0
        irr = float(irrigation_mm.get(d["date"], 0))
        theta = theta - (etc - pe - irr) / (10 * soil["root_depth_m"])
        theta = max(soil["wp"], min(soil["fc"], theta))
        out.append({"date": d["date"], "etc_mm": round(etc, 2), "rain_mm": round(rain, 1), "irrigation_mm": irr,
                    "moisture": round(theta, 1), "below_refill": theta < soil["refill"]})
    return out


def refill_plan(forecast: list[dict], soil: dict, application_rate_mm_h: float, leaching: float = 0.0) -> dict | None:
    """First day the forecast drops below the refill point and the gross amount to bring it back to field
    capacity (net depth / (1 - leaching requirement))."""
    hit = next((d for d in forecast if d["below_refill"]), None)
    if hit is None:
        return None
    net_mm = (soil["fc"] - hit["moisture"]) * 10 * soil["root_depth_m"]
    gross = net_mm / (1 - min(leaching, 0.5))
    return {"date": hit["date"], "net_mm": round(net_mm, 1), "gross_mm": round(gross, 1),
            "leaching_mm": round(gross - net_mm, 1), "runtime_min": round(gross / application_rate_mm_h * 60)}
