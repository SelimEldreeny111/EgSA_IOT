"""Satellite layers for the Satellite viewer (R2.7): the Copernicus Browser's layers, rendered for any map view.

Each layer is defined once and used three ways:

* as a Sentinel Hub evalscript (Process API, with the Copernicus Data Space OAuth client);
* as a numpy function on Sentinel-2 L2A reflectances (open archive on AWS, no account);
* as a legend for the dashboard (colour ramps of the index layers).

The visualisations follow the Copernicus Browser / Sentinel Hub custom-script conventions (true colour with a 2.5
gain, the NDVI and moisture-index palettes, the Highlight Optimized Natural Color tone curve, the ESA scene
classification colours). Wildfires and NDSI are documented heuristics, not official products.
"""
from __future__ import annotations

import json
import re

# ----------------------------------------------------------------------------- missions (Sentinel Hub types)
MISSIONS = {
    "S2L2A": {"title": "Sentinel-2 L2A", "type": "sentinel-2-l2a", "stac": "sentinel-2-l2a", "cloud": True,
              "resolution": "10 m", "about": "Surface reflectance (atmospherically corrected), 13 bands, every 2–5 days"},
    "S2L1C": {"title": "Sentinel-2 L1C", "type": "sentinel-2-l1c", "stac": None, "cloud": True,
              "resolution": "10 m", "about": "Top-of-atmosphere reflectance, same passes as L2A"},
    "S1GRD": {"title": "Sentinel-1 GRD (radar)", "type": "sentinel-1-grd", "stac": "sentinel-1-grd", "cloud": False,
              "resolution": "10 m", "about": "C-band radar, VV + VH, through clouds, day and night, every 6–12 days"},
    "S3OLCI": {"title": "Sentinel-3 OLCI", "type": "sentinel-3-olci", "stac": "sentinel-3-olci-2-lfr-ntc", "cloud": False,
               "resolution": "300 m", "about": "Ocean and land colour, 21 bands, daily"},
    "S3SLSTR": {"title": "Sentinel-3 SLSTR", "type": "sentinel-3-slstr", "stac": "sentinel-3-sl-2-lst-ntc", "cloud": False,
                "resolution": "500 m – 1 km", "about": "Thermal infrared, daily (day and night)"},
}
S2_BANDS = ["B01", "B02", "B03", "B04", "B05", "B06", "B07", "B08", "B8A", "B09", "B11", "B12"]

# ----------------------------------------------------------------------------- colour ramps (value, 0xRRGGBB)
NDVI_RAMP = [(-0.5, 0x0C0C0C), (-0.2, 0xBFBFBF), (-0.1, 0xDBDBDB), (0.0, 0xEAEAEA), (0.025, 0xFFF9CC), (0.05, 0xEDE8B5),
             (0.075, 0xDDD89B), (0.1, 0xCCC682), (0.125, 0xBCB76B), (0.15, 0xAFC160), (0.175, 0xA3CC59), (0.2, 0x91BF51),
             (0.25, 0x7FB247), (0.3, 0x70A33F), (0.35, 0x609635), (0.4, 0x4F892D), (0.45, 0x3F7C23), (0.5, 0x306D1C),
             (0.55, 0x216011), (0.6, 0x0F540A), (1.0, 0x004400)]
MOISTURE_RAMP = [(-0.8, 0x800000), (-0.24, 0xFF0000), (-0.032, 0xFFFF00), (0.032, 0x00FFFF), (0.24, 0x0000FF), (0.8, 0x000080)]
NDWI_RAMP = [(-0.8, 0x008000), (0.0, 0xFFFFFF), (0.8, 0x0000CC)]
NDRE_RAMP = [(0.0, 0xF7FCB9), (0.15, 0xD9F0A3), (0.3, 0xADDD8E), (0.45, 0x41AB5D), (0.6, 0x006837)]
INDEX_RAMP = [(-1.0, 0x8C510A), (-0.3, 0xD8B365), (0.0, 0xF5F5F5), (0.3, 0x5AB4AC), (1.0, 0x01665E)]
S1_DB_RAMP = [(-25.0, 0x000000), (0.0, 0xFFFFFF)]
TEMP_RAMP = [(0.0, 0x313695), (15.0, 0x74ADD1), (25.0, 0xFFFFBF), (35.0, 0xF46D43), (50.0, 0xA50026)]
SCL_COLORS = {0: 0x000000, 1: 0xFF0000, 2: 0x2F2F2F, 3: 0x643200, 4: 0x00A000, 5: 0xFFE65A, 6: 0x0000FF, 7: 0x808080,
              8: 0xC0C0C0, 9: 0xFFFFFF, 10: 0x64C8FF, 11: 0xFF96FF}
SCL_NAMES = {0: "No data", 1: "Saturated / defective", 2: "Dark area", 3: "Cloud shadow", 4: "Vegetation", 5: "Not vegetated",
             6: "Water", 7: "Unclassified", 8: "Cloud (medium)", 9: "Cloud (high)", 10: "Thin cirrus", 11: "Snow / ice"}


def _hex(c: int) -> str:
    return f"#{c:06x}"


def _ramp_js(ramp) -> str:
    return "[" + ", ".join(f"[{v}, 0x{c:06x}]" for v, c in ramp) + "]"


def _legend_ramp(ramp, unit: str = "") -> dict:
    return {"kind": "ramp", "unit": unit, "stops": [{"value": v, "color": _hex(c)} for v, c in ramp]}


def _rgb_script(bands: list[str], gain: float = 2.5) -> str:
    ins = ", ".join(f'"{b}"' for b in bands)
    return ("//VERSION=3\nfunction setup() { return { input: [%s, \"dataMask\"], output: { bands: 4 } }; }\n"
            "function evaluatePixel(s) { return [%s, s.dataMask]; }" % (ins, ", ".join(f"{gain} * s.{b}" for b in bands)))


def _index_script(a: str, b: str, ramp, extra_bands: tuple = ()) -> str:
    ins = ", ".join(f'"{x}"' for x in dict.fromkeys([a, b, *extra_bands]))
    return ("//VERSION=3\nfunction setup() { return { input: [%s, \"dataMask\"], output: { bands: 4 } }; }\n"
            "const viz = new ColorRampVisualizer(%s);\n"
            "function evaluatePixel(s) { var v = (s.%s - s.%s) / (s.%s + s.%s + 1e-6); return [...viz.process(v), s.dataMask]; }"
            % (ins, _ramp_js(ramp), a, b, a, b))


HIGHLIGHT_SCRIPT = """//VERSION=3
// Highlight Optimized Natural Color: tone curve that keeps bright desert and clouds from burning out
function setup() { return { input: ["B04", "B03", "B02", "dataMask"], output: { bands: 4 } }; }
const maxR = 3.0, midR = 0.13, sat = 1.2, gamma = 1.8, gOff = 0.01;
const gOffPow = Math.pow(gOff, gamma), gOffRange = Math.pow(1 + gOff, gamma) - gOffPow;
const clip = (s) => s < 0 ? 0 : s > 1 ? 1 : s;
const adj = (a, tx, ty, maxC) => { var ar = clip(a / maxC); return ar * (ar * (tx / maxC + ty - 1) - ty) / (ar * (2 * tx / maxC - 1) - tx / maxC); };
const adjGamma = (b) => (Math.pow(b + gOff, gamma) - gOffPow) / gOffRange;
const sAdj = (a) => adjGamma(adj(a, midR, 1, maxR));
const satEnh = (r, g, b) => { const avg = (r + g + b) / 3.0 * (1 - sat); return [clip(avg + r * sat), clip(avg + g * sat), clip(avg + b * sat)]; };
const sRGB = (c) => c <= 0.0031308 ? 12.92 * c : 1.055 * Math.pow(c, 0.41666666666) - 0.055;
function evaluatePixel(s) { const c = satEnh(sAdj(s.B04), sAdj(s.B03), sAdj(s.B02)); return [sRGB(c[0]), sRGB(c[1]), sRGB(c[2]), s.dataMask]; }"""

WILDFIRE_SCRIPT = """//VERSION=3
// Natural colour with active-fire pixels: strong short-wave infrared (B12) above the near infrared (B8A)
function setup() { return { input: ["B02", "B03", "B04", "B08", "B8A", "B11", "B12", "dataMask"], output: { bands: 4 } }; }
function evaluatePixel(s) {
  if (s.B12 > 0.5 && s.B11 > 0.4) return [1, 1, 0, s.dataMask];
  if (s.B12 > 0.2 && s.B12 - s.B8A > 0.1 && s.B12 > s.B11) return [1, 0.2, 0, s.dataMask];
  return [2.5 * s.B04, 2.5 * s.B03, 2.5 * s.B02, s.dataMask];
}"""

NDSI_SCRIPT = """//VERSION=3
// Snow where NDSI > 0.42 (and bright in green), natural colour elsewhere
function setup() { return { input: ["B02", "B03", "B04", "B11", "dataMask"], output: { bands: 4 } }; }
function evaluatePixel(s) {
  var v = (s.B03 - s.B11) / (s.B03 + s.B11 + 1e-6);
  if (v > 0.42 && s.B03 > 0.1) return [0, 0.6, 1, s.dataMask];
  return [2.5 * s.B04, 2.5 * s.B03, 2.5 * s.B02, s.dataMask];
}"""

SCL_SCRIPT = ("//VERSION=3\nfunction setup() { return { input: [\"SCL\", \"dataMask\"], output: { bands: 4 } }; }\n"
              "const C = %s;\n"
              "function evaluatePixel(s) { var c = C[s.SCL] || 0; return [((c >> 16) & 255) / 255, ((c >> 8) & 255) / 255, (c & 255) / 255, s.dataMask]; }"
              % json.dumps({k: v for k, v in SCL_COLORS.items()}))

S1_DB = ("//VERSION=3\nfunction setup() { return { input: [\"%s\", \"dataMask\"], output: { bands: 4 } }; }\n"
         "function evaluatePixel(s) { var db = 10 * Math.log(Math.max(s.%s, 1e-5)) / Math.LN10; var v = Math.min(1, Math.max(0, (db + 25) / 25)); "
         "return [v, v, v, s.dataMask]; }")
S1_FALSE = """//VERSION=3
// Radar false colour: red = VV, green = VH, blue = VV / VH (bright green = vegetation volume, blue/purple = bare or urban)
function setup() { return { input: ["VV", "VH", "dataMask"], output: { bands: 4 } }; }
function evaluatePixel(s) {
  var r = Math.min(1, Math.sqrt(s.VV) * 2.5), g = Math.min(1, Math.sqrt(s.VH) * 5), b = Math.min(1, s.VV / (s.VH + 1e-6) / 20);
  return [r, g, b, s.dataMask];
}"""
SLSTR_TEMP = ("//VERSION=3\n// Brightness temperature of the 10.8 µm channel (S8), °C; close to the surface temperature on clear land\n"
              "function setup() { return { input: [\"S8\", \"dataMask\"], output: { bands: 4 } }; }\n"
              "const viz = new ColorRampVisualizer(%s);\n"
              "function evaluatePixel(s) { return [...viz.process(s.S8 - 273.15), s.dataMask]; }" % _ramp_js(TEMP_RAMP))

# ----------------------------------------------------------------------------- the catalogue
LAYERS: list[dict] = [
    # Sentinel-2 L2A: the Copernicus Browser list, plus two agriculture layers
    {"id": "TRUE_COLOR", "missions": ["S2L2A", "S2L1C"], "title": "True color", "about": "Based on bands B4, B3, B2",
     "script": _rgb_script(["B04", "B03", "B02"]), "open": True, "swatch": ["#6b5a43", "#a68f6c", "#3f5d34"]},
    {"id": "FALSE_COLOR", "missions": ["S2L2A", "S2L1C"], "title": "False color", "about": "Based on bands B8, B4, B3",
     "script": _rgb_script(["B08", "B04", "B03"]), "open": True, "swatch": ["#b3202a", "#e06666", "#7a2f2f"]},
    {"id": "HIGHLIGHT", "missions": ["S2L2A", "S2L1C"], "title": "Highlight Optimized Natural Color",
     "about": "Enhanced natural color visualisation", "script": HIGHLIGHT_SCRIPT, "open": True,
     "swatch": ["#57503d", "#8c826a", "#3c4b30"]},
    {"id": "NDVI", "missions": ["S2L2A", "S2L1C"], "title": "NDVI", "about": "Based on a combination of bands (B8 − B4)/(B8 + B4)",
     "script": _index_script("B08", "B04", NDVI_RAMP), "open": True, "legend": _legend_ramp(NDVI_RAMP),
     "swatch": ["#ddd89b", "#7fb247", "#0f540a"]},
    {"id": "WILDFIRES", "missions": ["S2L2A", "S2L1C"], "title": "Wildfires",
     "about": "Visualizes wildfires based on bands B02, B03, B04, B08, B8A, B11 and B12", "script": WILDFIRE_SCRIPT,
     "open": True, "swatch": ["#5c4d3a", "#ff3300", "#ffcc00"],
     "legend": {"kind": "classes", "items": [{"color": "#ff3300", "label": "Active fire"},
                                              {"color": "#ffff00", "label": "Intense fire"}]}},
    {"id": "FALSE_COLOR_URBAN", "missions": ["S2L2A", "S2L1C"], "title": "False color (urban)",
     "about": "Based on bands B12, B11, B4", "script": _rgb_script(["B12", "B11", "B04"]), "open": True,
     "swatch": ["#b88c78", "#7a6d8f", "#3f8a4a"]},
    {"id": "MOISTURE", "missions": ["S2L2A", "S2L1C"], "title": "Moisture index",
     "about": "Based on a combination of bands (B8A − B11)/(B8A + B11)", "script": _index_script("B8A", "B11", MOISTURE_RAMP),
     "open": True, "legend": _legend_ramp(MOISTURE_RAMP), "swatch": ["#ff0000", "#ffff00", "#0000ff"]},
    {"id": "SWIR", "missions": ["S2L2A", "S2L1C"], "title": "SWIR", "about": "Based on bands B12, B8A, B4",
     "script": _rgb_script(["B12", "B8A", "B04"]), "open": True, "swatch": ["#3e8a3a", "#7cc46f", "#b48a5c"]},
    {"id": "NDWI", "missions": ["S2L2A", "S2L1C"], "title": "NDWI", "about": "Based on a combination of bands (B3 − B8)/(B3 + B8)",
     "script": _index_script("B03", "B08", NDWI_RAMP), "open": True, "legend": _legend_ramp(NDWI_RAMP),
     "swatch": ["#008000", "#ffffff", "#0000cc"]},
    {"id": "NDSI", "missions": ["S2L2A", "S2L1C"], "title": "NDSI", "about": "Based on a combination of bands (B3 − B11)/(B3 + B11)",
     "script": NDSI_SCRIPT, "open": True, "swatch": ["#6b5a43", "#0099ff", "#ffffff"],
     "legend": {"kind": "classes", "items": [{"color": "#0099ff", "label": "Snow (NDSI > 0.42)"}]}},
    {"id": "SCL", "missions": ["S2L2A"], "title": "Scene classification map",
     "about": "Classification of Sentinel-2 data as result of ESA's Scene classification algorithm.", "script": SCL_SCRIPT,
     "open": True, "swatch": ["#00a000", "#ffe65a", "#c0c0c0"],
     "legend": {"kind": "classes", "items": [{"color": _hex(SCL_COLORS[k]), "label": SCL_NAMES[k]} for k in (4, 5, 6, 3, 8, 9, 10, 2, 7)]}},
    {"id": "AGRICULTURE", "missions": ["S2L2A", "S2L1C"], "title": "Agriculture", "about": "Based on bands B11, B8, B2 (healthy crops bright green)",
     "script": _rgb_script(["B11", "B08", "B02"]), "open": True, "swatch": ["#7a5a3a", "#3fbf3f", "#2f6f2f"]},
    {"id": "NDRE", "missions": ["S2L2A", "S2L1C"], "title": "NDRE (red edge)", "about": "Chlorophyll and nitrogen: (B8A − B5)/(B8A + B5)",
     "script": _index_script("B8A", "B05", NDRE_RAMP), "open": True, "legend": _legend_ramp(NDRE_RAMP),
     "swatch": ["#f7fcb9", "#addd8e", "#006837"]},
    # Sentinel-1 radar (gamma0, terrain corrected)
    {"id": "S1_VV", "missions": ["S1GRD"], "title": "VV decibel", "about": "Radar backscatter VV in dB (−25 to 0): wet soil and rough surfaces are bright",
     "script": S1_DB % ("VV", "VV"), "open": False, "legend": _legend_ramp(S1_DB_RAMP, "dB"), "swatch": ["#111111", "#777777", "#eeeeee"]},
    {"id": "S1_VH", "missions": ["S1GRD"], "title": "VH decibel", "about": "Cross-polarised backscatter in dB: rises with crop biomass",
     "script": S1_DB % ("VH", "VH"), "open": False, "legend": _legend_ramp(S1_DB_RAMP, "dB"), "swatch": ["#111111", "#666666", "#dddddd"]},
    {"id": "S1_FALSE", "missions": ["S1GRD"], "title": "False color (VV, VH, VV/VH)", "about": "Radar composite: green = vegetation, purple = bare soil or built-up",
     "script": S1_FALSE, "open": False, "swatch": ["#3a2a5a", "#4f9f4f", "#9f8fdf"]},
    # Sentinel-3
    {"id": "OLCI_TRUE", "missions": ["S3OLCI"], "title": "True color", "about": "Based on OLCI bands Oa08, Oa06, Oa04 (300 m)",
     "script": _rgb_script(["B08", "B06", "B04"], gain=2.5), "open": False, "swatch": ["#6b5a43", "#a68f6c", "#3a5f8f"]},
    {"id": "OLCI_NDVI", "missions": ["S3OLCI"], "title": "NDVI (OLCI)", "about": "(Oa17 − Oa08)/(Oa17 + Oa08), regional vegetation at 300 m",
     "script": _index_script("B17", "B08", NDVI_RAMP), "open": False, "legend": _legend_ramp(NDVI_RAMP),
     "swatch": ["#ddd89b", "#7fb247", "#0f540a"]},
    {"id": "SLSTR_TEMP", "missions": ["S3SLSTR"], "title": "Brightness temperature (°C)",
     "about": "Thermal channel S8 (10.8 µm), close to the surface temperature on clear land", "script": SLSTR_TEMP,
     "open": False, "legend": _legend_ramp(TEMP_RAMP, "°C"), "swatch": ["#74add1", "#ffffbf", "#f46d43"]},
    # Custom (all Sentinel-2 bands)
    {"id": "CUSTOM", "missions": ["S2L2A", "S2L1C"], "title": "Custom", "about": "Create custom visualisation: band composite, index, or your own evalscript",
     "script": None, "open": True, "swatch": ["#333333", "#888888", "#dddddd"]},
]
BY_ID = {(m, layer["id"]): layer for layer in LAYERS for m in layer["missions"]}
BAND_RE = re.compile(r"^(B0[1-9]|B1[0-2]|B8A)$")


def public_catalogue(open_available: bool, sentinelhub: bool) -> dict:
    """What the dashboard needs: missions, layers, legends, which renderer can draw each."""
    out = []
    for layer in LAYERS:
        out.append({"id": layer["id"], "missions": layer["missions"], "title": layer["title"], "about": layer["about"],
                    "legend": layer.get("legend"), "swatch": layer["swatch"],
                    "renderers": [r for r, ok in (("sentinelhub", sentinelhub), ("open", open_available and layer["open"])) if ok]})
    missions = [{"id": k, **{x: v[x] for x in ("title", "cloud", "resolution", "about")},
                 "renderers": [r for r, ok in (("sentinelhub", sentinelhub), ("open", open_available and k == "S2L2A")) if ok]}
                for k, v in MISSIONS.items()]
    return {"missions": missions, "layers": out, "bands": S2_BANDS}


def custom_script(mode: str, bands: list[str], ramp_name: str = "index") -> str:
    """Evalscript for the Custom layer: an RGB composite of 3 bands, or a normalised-difference index of 2."""
    if not all(BAND_RE.match(b) for b in bands):
        raise ValueError("Unknown band; use B01 to B12 or B8A")
    if mode == "composite" and len(bands) == 3:
        return _rgb_script(bands)
    if mode == "index" and len(bands) == 2:
        return _index_script(bands[0], bands[1], INDEX_RAMP)
    raise ValueError("Custom needs three bands for a composite or two for an index")


# ----------------------------------------------------------------------------- numpy versions (open archive)
def ramp_colors(values, ramp):
    import numpy as np
    xs = np.array([v for v, _ in ramp], dtype=np.float32)
    cs = np.array([[(c >> 16) & 255, (c >> 8) & 255, c & 255] for _, c in ramp], dtype=np.float32) / 255.0
    return np.dstack([np.interp(values, xs, cs[:, i]) for i in range(3)])


def _nd(a, b):
    import numpy as np
    return (a - b) / np.maximum(a + b, 1e-6)


def _rgb(*bands, gain=2.5):
    import numpy as np
    return np.clip(np.dstack([b * gain for b in bands]), 0, 1)


def _highlight(r, g, b):
    import numpy as np
    max_r, mid_r, sat, gamma, g_off = 3.0, 0.13, 1.2, 1.8, 0.01
    g_off_pow = g_off ** gamma
    g_off_range = (1 + g_off) ** gamma - g_off_pow

    def s_adj(a):
        ar = np.clip(a / max_r, 0, 1)
        tx, ty = mid_r, 1.0
        v = ar * (ar * (tx / max_r + ty - 1) - ty) / (ar * (2 * tx / max_r - 1) - tx / max_r)
        return ((np.maximum(v, 0) + g_off) ** gamma - g_off_pow) / g_off_range

    rr, gg, bb = s_adj(r), s_adj(g), s_adj(b)
    avg = (rr + gg + bb) / 3.0 * (1 - sat)
    c = np.clip(np.dstack([avg + rr * sat, avg + gg * sat, avg + bb * sat]), 0, 1)
    return np.where(c <= 0.0031308, 12.92 * c, 1.055 * np.power(c, 0.41666666666) - 0.055)


def render_numpy(layer_id: str, b: dict, custom: dict | None = None):
    """RGB (0-1) image of a layer from Sentinel-2 L2A reflectances ``b`` (dict band -> 2-D array, plus SCL)."""
    import numpy as np
    if layer_id == "TRUE_COLOR":
        return _rgb(b["B04"], b["B03"], b["B02"])
    if layer_id == "FALSE_COLOR":
        return _rgb(b["B08"], b["B04"], b["B03"])
    if layer_id == "HIGHLIGHT":
        return _highlight(b["B04"], b["B03"], b["B02"])
    if layer_id == "NDVI":
        return ramp_colors(_nd(b["B08"], b["B04"]), NDVI_RAMP)
    if layer_id == "WILDFIRES":
        img = _rgb(b["B04"], b["B03"], b["B02"])
        fire = (b["B12"] > 0.2) & (b["B12"] - b["B8A"] > 0.1) & (b["B12"] > b["B11"])
        img[fire] = (1, 0.2, 0)
        img[(b["B12"] > 0.5) & (b["B11"] > 0.4)] = (1, 1, 0)
        return img
    if layer_id == "FALSE_COLOR_URBAN":
        return _rgb(b["B12"], b["B11"], b["B04"])
    if layer_id == "MOISTURE":
        return ramp_colors(_nd(b["B8A"], b["B11"]), MOISTURE_RAMP)
    if layer_id == "SWIR":
        return _rgb(b["B12"], b["B8A"], b["B04"])
    if layer_id == "NDWI":
        return ramp_colors(_nd(b["B03"], b["B08"]), NDWI_RAMP)
    if layer_id == "NDSI":
        img = _rgb(b["B04"], b["B03"], b["B02"])
        img[(_nd(b["B03"], b["B11"]) > 0.42) & (b["B03"] > 0.1)] = (0, 0.6, 1)
        return img
    if layer_id == "SCL":
        scl = b["SCL"].astype(np.int64)
        lut = np.zeros((256, 3), dtype=np.float32)
        for k, c in SCL_COLORS.items():
            lut[k] = ((c >> 16) & 255, (c >> 8) & 255, c & 255)
        return lut[np.clip(scl, 0, 255)] / 255.0
    if layer_id == "AGRICULTURE":
        return _rgb(b["B11"], b["B08"], b["B02"])
    if layer_id == "NDRE":
        return ramp_colors(_nd(b["B8A"], b["B05"]), NDRE_RAMP)
    if layer_id == "CUSTOM" and custom:
        bands = custom["bands"]
        if custom["mode"] == "composite":
            return _rgb(*(b[x] for x in bands))
        return ramp_colors(_nd(b[bands[0]], b[bands[1]]), INDEX_RAMP)
    raise ValueError("This layer cannot be drawn from the open archive")


def bands_needed(layer_id: str, custom: dict | None = None) -> list[str]:
    need = {"TRUE_COLOR": ["B04", "B03", "B02"], "FALSE_COLOR": ["B08", "B04", "B03"], "HIGHLIGHT": ["B04", "B03", "B02"],
            "NDVI": ["B08", "B04"], "WILDFIRES": ["B02", "B03", "B04", "B8A", "B11", "B12"],
            "FALSE_COLOR_URBAN": ["B12", "B11", "B04"], "MOISTURE": ["B8A", "B11"], "SWIR": ["B12", "B8A", "B04"],
            "NDWI": ["B03", "B08"], "NDSI": ["B02", "B03", "B04", "B11"], "SCL": [], "AGRICULTURE": ["B11", "B08", "B02"],
            "NDRE": ["B8A", "B05"]}
    if layer_id == "CUSTOM":
        if not custom:
            raise ValueError("Choose the bands of the custom layer")
        return list(dict.fromkeys(custom["bands"]))
    return need[layer_id]
