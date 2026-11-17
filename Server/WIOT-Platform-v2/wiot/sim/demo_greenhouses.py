"""Demo data for Track G on the Demo_AgriFarm tenant: four third-party devices and two greenhouses.

The devices are *unsigned* MQTT devices (no secrets to share with the simulator); ``python -m wiot
simulate`` publishes their JSON. The greenhouses sit west of the demo pivots, near gateway GW-01.
"""
from __future__ import annotations

import math

DEMO_COMPANY = "Demo_AgriFarm"
ORIGIN = (22.2475, 28.7040)          # south-west corner of house GH-1

DEVICES = [
    {"device_id": "GH1-CLIMATE", "name": "Tomato house climate", "model": "Milesight AM319", "interval_s": 60},
    {"device_id": "GH2-CLIMATE", "name": "Cucumber house climate", "model": "Generic climate sensor", "interval_s": 60},
    {"device_id": "GH1-SUBSTRATE", "name": "Tomato substrate probe", "model": "Dragino LSE01", "interval_s": 60,
     "mapping": [{"field": "water_SOIL", "metric": "soil_moisture_pct"}, {"field": "temp_SOIL", "metric": "soil_temp_c"},
                 {"field": "conduct_SOIL", "metric": "soil_ec_ds_m", "scale": 0.001}, {"field": "BatV", "metric": "battery_v"}]},
    {"device_id": "TANK-1", "name": "Irrigation tank", "model": "Dragino LDDS75", "interval_s": 60},
]


def _pt(x_m: float, y_m: float) -> list[float]:
    """Metres east/north of ORIGIN -> [lat, lon]."""
    lat0, lon0 = ORIGIN
    return [round(lat0 + y_m / 110540.0, 7), round(lon0 + x_m / (111320.0 * math.cos(math.radians(lat0))), 7)]


def _rect(x0, y0, x1, y1) -> list[list[float]]:
    return [_pt(x0, y0), _pt(x1, y0), _pt(x1, y1), _pt(x0, y1)]


def _benches(zone_id: str, x0: float, x1: float, y0: float, y1: float, width=1.6, path=0.8) -> list[dict]:
    out, x, n = [], x0, 1
    while x + width <= x1 + 1e-6:
        out.append({"id": f"{zone_id}-{n:02d}", "name": f"Bench {n}", "polygon": _rect(x, y0, x + width, y1)})
        x, n = x + width + path, n + 1
    return out


def layout() -> dict:
    return {"houses": [
        {"id": "GH-1", "name": "Tomato house", "kind": "glass", "crop": "Tomato", "notes": "Venlo glasshouse, 96 x 40 m",
         "polygon": _rect(0, 0, 96, 40), "attach": [{"kind": "device", "device_id": "GH1-CLIMATE"}],
         "zones": [
             {"id": "GH-1-A", "name": "Zone A", "crop": "Tomato", "polygon": _rect(2, 2, 47, 38),
              "attach": [{"kind": "device", "device_id": "GH1-SUBSTRATE"}], "benches": _benches("GH-1-A", 3, 46, 4, 36)},
             {"id": "GH-1-B", "name": "Zone B", "crop": "Tomato", "polygon": _rect(49, 2, 94, 38),
              "attach": [], "benches": _benches("GH-1-B", 50, 93, 4, 36)}]},
        {"id": "GH-2", "name": "Cucumber house", "kind": "poly", "crop": "Cucumber", "notes": "",
         "polygon": _rect(0, 52, 72, 82), "attach": [{"kind": "device", "device_id": "GH2-CLIMATE"}],
         "zones": [{"id": "GH-2-A", "name": "Zone A", "crop": "Cucumber", "polygon": _rect(2, 54, 70, 80), "attach": [],
                    "benches": _benches("GH-2-A", 3, 69, 56, 78, width=1.2, path=1.0)}]},
    ]}
