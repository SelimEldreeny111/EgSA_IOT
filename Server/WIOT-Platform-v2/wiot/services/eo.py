"""Earth-observation data access (R2.7): open Sentinel-2, the Copernicus catalogue and the EUMETSAT Data Store.

* **Open Sentinel-2 NDVI** - Sentinel-2 L2A from the open Earth Search archive on AWS, no account needed. A STAC
  search finds the clear passes over a farm; only the pixels of the farm are read from the cloud-optimised GeoTIFFs
  (HTTP range requests: red, NIR and the scene classification), so a farm costs a few MB per pass instead of the
  1 GB product. Requires numpy (analytics extra).
* **Copernicus Data Space catalogue** - Sentinel-1/2/3 products over a farm from the public STAC catalogue, with a
  link that opens the date and place in the Copernicus Browser.
* **EUMETSAT Data Store** - collection list and product search are public; downloads use the EUMETSAT API key
  (consumer key and secret from api.eumetsat.int/api-key, set in ``.env``).

Only standard-library HTTP is used; every network call goes through an injectable ``http`` callable so the
tests run offline.
"""
from __future__ import annotations

import base64
import json
import logging
import math
import re
import struct
import time
import urllib.parse
import zlib
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger(__name__)

OPEN_SOURCE = "sentinel-2-open"            # sat_ndvi.source of the open-archive NDVI
SCL_CLEAR = (4, 5, 6, 7, 11)               # vegetation, not vegetated, water, unclassified, snow
CDSE_COLLECTIONS = {
    "sentinel-2-l2a": "Sentinel-2 L2A surface reflectance",
    "sentinel-1-grd": "Sentinel-1 GRD radar",
    "sentinel-3-sl-2-lst-ntc": "Sentinel-3 SLSTR land surface temperature",
    "sentinel-3-olci-2-lfr-ntc": "Sentinel-3 OLCI land vegetation (OGVI, OTCI)",
    "sentinel-3-syn-2-syn-ntc": "Sentinel-3 synergy surface reflectance",
}
BROWSER_DATASETS = {"sentinel-2-l2a": "S2_L2A_CDAS", "sentinel-1-grd": "S1_CDAS_IW_VVVH",
                    "sentinel-3-olci-2-lfr-ntc": "S3OLCI_CDAS", "sentinel-3-sl-2-lst-ntc": "S3SLSTR_CDAS"}
EUMETSAT_SUGGESTED = [
    ("EO:EUM:DAT:1088", "Land surface temperature, MTG (every 10 min)"),
    ("EO:EUM:DAT:0394", "Land surface temperature, MSG (every 15 min)"),
    ("EO:EUM:DAT:METOP:LSA-002", "Daily land surface temperature, Metop"),
    ("EO:EUM:DAT:1087", "Accumulated precipitation, MTG"),
    ("EO:EUM:DAT:1089", "Daily surface albedo, MTG"),
    ("EO:EUM:DAT:METOP:OAS025", "ASCAT soil moisture and winds, 25 km"),
    ("EO:EUM:DAT:0863", "SARAH-3 surface solar radiation"),
    ("EO:EUM:DAT:0921", "GIRAFE global rainfall"),
]
COLLECTION_RE = re.compile(r"^EO:EUM:DAT:[A-Z0-9:_.-]{2,40}$")
PRODUCT_RE = re.compile(r"^[A-Za-z0-9_,.:+=-]{4,200}$")


# ======================================================================= HTTP
def http_download(url: str, headers: dict, dest: Path, max_bytes: int, timeout: float = 120.0) -> tuple[int, int]:
    """Stream ``url`` into ``dest`` (written as .part, renamed when complete); refuses files over ``max_bytes``."""
    import urllib.error
    import urllib.request
    req = urllib.request.Request(url, headers=headers)
    part = dest.with_name(dest.name + ".part")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:         # noqa: S310 - configured provider URLs
            length = int(resp.headers.get("Content-Length") or 0)
            if length > max_bytes:
                raise ValueError(f"Product is {length / 1e6:.0f} MB, above the {max_bytes / 1e6:.0f} MB limit")
            done = 0
            with open(part, "wb") as fh:
                while chunk := resp.read(1 << 16):
                    done += len(chunk)
                    if done > max_bytes:
                        raise ValueError(f"Product is above the {max_bytes / 1e6:.0f} MB limit")
                    fh.write(chunk)
        part.replace(dest)
        return resp.status, done
    except urllib.error.HTTPError as exc:
        return exc.code, 0
    finally:
        if part.exists():
            part.unlink()


def safe_name(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("._")[:180] or "product"


# ======================================================================= UTM
def utm_zone(epsg: int) -> tuple[int, bool]:
    """(zone, southern hemisphere) of a WGS 84 / UTM EPSG code."""
    if 32601 <= epsg <= 32660:
        return epsg - 32600, False
    if 32701 <= epsg <= 32760:
        return epsg - 32700, True
    raise ValueError(f"Only WGS 84 / UTM grids are supported (EPSG:{epsg})")


def utm_forward(lat: float, lon: float, zone: int, south: bool = False) -> tuple[float, float]:
    """Latitude / longitude (WGS 84) to UTM easting / northing in metres (Krüger series, mm accuracy)."""
    a, f, k0 = 6378137.0, 1 / 298.257223563, 0.9996
    n = f / (2 - f)
    big_a = a / (1 + n) * (1 + n ** 2 / 4 + n ** 4 / 64)
    alpha = (n / 2 - 2 * n ** 2 / 3 + 5 * n ** 3 / 16, 13 * n ** 2 / 48 - 3 * n ** 3 / 5, 61 * n ** 3 / 240)
    phi, lam = math.radians(lat), math.radians(lon - (zone * 6 - 183))
    c = 2 * math.sqrt(n) / (1 + n)
    t = math.sinh(math.atanh(math.sin(phi)) - c * math.atanh(c * math.sin(phi)))
    xi_p, eta_p = math.atan2(t, math.cos(lam)), math.atanh(math.sin(lam) / math.sqrt(1 + t * t))
    xi = xi_p + sum(alpha[j] * math.sin(2 * (j + 1) * xi_p) * math.cosh(2 * (j + 1) * eta_p) for j in range(3))
    eta = eta_p + sum(alpha[j] * math.cos(2 * (j + 1) * xi_p) * math.sinh(2 * (j + 1) * eta_p) for j in range(3))
    return 500000.0 + k0 * big_a * eta, k0 * big_a * xi + (10000000.0 if south else 0.0)


# ======================================================================= Cloud-optimised GeoTIFF
_TYPES = {1: ("B", 1), 2: ("c", 1), 3: ("H", 2), 4: ("I", 4), 5: ("I", 8), 6: ("b", 1), 7: ("B", 1), 8: ("h", 2),
          9: ("i", 4), 10: ("i", 8), 11: ("f", 4), 12: ("d", 8), 16: ("Q", 8), 17: ("q", 8), 18: ("Q", 8)}


class Cog:
    """Window reads from a tiled GeoTIFF over HTTP range requests.

    Covers what the Sentinel-2 archives serve: classic or BigTIFF, tiled, one band of 8/16/32-bit integers,
    no compression or DEFLATE, with or without the horizontal predictor, georeferenced by tie point and
    pixel scale. Anything else raises ``ValueError`` instead of returning wrong numbers.
    """
    HEAD = 65536

    def __init__(self, url: str, http):
        self.url, self.http = url, http
        self._head = self._range(0, self.HEAD)
        order = self._head[:2]
        if order not in (b"II", b"MM"):
            raise ValueError("Not a TIFF file")
        self.e = "<" if order == b"II" else ">"
        version = struct.unpack(self.e + "H", self._head[2:4])[0]
        if version == 42:
            self.big, first = False, struct.unpack(self.e + "I", self._head[4:8])[0]
        elif version == 43:
            self.big, first = True, struct.unpack(self.e + "Q", self._head[8:16])[0]
        else:
            raise ValueError("Not a TIFF file")
        t = self.tags = self._ifd(first)
        if 322 not in t or 324 not in t:
            raise ValueError("Only tiled GeoTIFFs (COG) are supported")
        self.width, self.height = int(t[256][0]), int(t[257][0])
        self.tw, self.th = int(t[322][0]), int(t[323][0])
        bits, fmt = int(t.get(258, [8])[0]), int(t.get(339, [1])[0])
        self.compression, self.predictor = int(t.get(259, [1])[0]), int(t.get(317, [1])[0])
        if int(t.get(277, [1])[0]) != 1:
            raise ValueError("Only single-band files are supported")
        if self.compression not in (1, 8, 32946):
            raise ValueError(f"Unsupported TIFF compression {self.compression}")
        if self.predictor not in (1, 2):
            raise ValueError(f"Unsupported TIFF predictor {self.predictor}")
        if fmt not in (1, 2) or bits not in (8, 16, 32):
            raise ValueError("Unsupported sample format")
        self.dtype = f"{self.e}{'u' if fmt == 1 else 'i'}{bits // 8}"
        self.offsets, self.counts = t[324], t[325]
        if 33550 not in t or 33922 not in t:
            raise ValueError("The file has no georeference (tie point and pixel scale)")
        sx, sy = float(t[33550][0]), float(t[33550][1])
        tp = t[33922]
        self.res = (sx, sy)
        self.origin = (float(tp[3]) - float(tp[0]) * sx, float(tp[4]) + float(tp[1]) * sy)
        self.epsg = self._epsg(t.get(34735))
        self.tiles_across = -(-self.width // self.tw)

    # -------------------------------------------------- low level
    def _range(self, start: int, n: int) -> bytes:
        status, body = self.http("GET", self.url, {"Range": f"bytes={start}-{start + n - 1}"}, None)
        if status == 206:
            return body
        if status == 200:                                   # server ignored the range: slice the whole body
            return body[start:start + n]
        raise RuntimeError(f"HTTP {status} reading {self.url.rsplit('/', 1)[-1]}")

    def _bytes(self, off: int, n: int) -> bytes:
        return self._head[off:off + n] if off + n <= len(self._head) else self._range(off, n)

    def _ifd(self, off: int) -> dict[int, list]:
        e = self.e
        if self.big:
            count, size, start, inline, ptr = struct.unpack(e + "Q", self._bytes(off, 8))[0], 20, off + 8, 8, "Q"
        else:
            count, size, start, inline, ptr = struct.unpack(e + "H", self._bytes(off, 2))[0], 12, off + 2, 4, "I"
        raw = self._bytes(start, count * size)
        tags: dict[int, list] = {}
        for i in range(count):
            ent = raw[i * size:(i + 1) * size]
            if self.big:
                tag, typ, cnt = struct.unpack(e + "HHQ", ent[:12])
                val = ent[12:20]
            else:
                tag, typ, cnt = struct.unpack(e + "HHI", ent[:8])
                val = ent[8:12]
            if typ not in _TYPES:
                continue
            code, width = _TYPES[typ]
            nbytes = cnt * width
            data = val[:nbytes] if nbytes <= inline else self._bytes(struct.unpack(e + ptr, val)[0], nbytes)
            if typ == 2:
                tags[tag] = [data.rstrip(b"\0").decode("latin-1")]
            elif typ in (5, 10):
                nums = struct.unpack(e + code * (2 * cnt), data)
                tags[tag] = [nums[k] / nums[k + 1] if nums[k + 1] else 0.0 for k in range(0, 2 * cnt, 2)]
            else:
                tags[tag] = list(struct.unpack(e + code * cnt, data))
        return tags

    @staticmethod
    def _epsg(keys: list | None) -> int | None:
        if not keys:
            return None
        found = {int(keys[k]): int(keys[k + 3]) for k in range(4, len(keys) - 3, 4) if int(keys[k + 1]) == 0}
        return found.get(3072) or found.get(2048)

    def _tile(self, i: int):
        import numpy as np
        if i >= len(self.offsets) or self.counts[i] == 0:
            return np.zeros((self.th, self.tw), self.dtype)
        raw = self._range(int(self.offsets[i]), int(self.counts[i]))
        if self.compression in (8, 32946):
            raw = zlib.decompress(raw)
        a = np.frombuffer(raw, dtype=self.dtype, count=self.tw * self.th).reshape(self.th, self.tw)
        if self.predictor == 2:
            a = np.cumsum(a, axis=1, dtype=a.dtype)          # integer wrap-around undoes the differencing
        return a.astype(a.dtype.newbyteorder("="))

    # -------------------------------------------------- public
    def window(self, xmin: float, ymin: float, xmax: float, ymax: float) -> tuple[int, int, int, int]:
        """(col, row, width, height) covering a box in the file's coordinates."""
        rx, ry = self.res
        c0, c1 = math.floor((xmin - self.origin[0]) / rx), math.ceil((xmax - self.origin[0]) / rx)
        r0, r1 = math.floor((self.origin[1] - ymax) / ry), math.ceil((self.origin[1] - ymin) / ry)
        return c0, r0, c1 - c0, r1 - r0

    def read(self, col0: int, row0: int, w: int, h: int):
        """Pixels of a window; parts outside the image are 0 (no data)."""
        import numpy as np
        out = np.zeros((h, w), dtype=np.dtype(self.dtype).newbyteorder("="))
        xa, ya = max(col0, 0), max(row0, 0)
        xb, yb = min(col0 + w, self.width), min(row0 + h, self.height)
        if xa >= xb or ya >= yb:
            return out
        for ty in range(ya // self.th, (yb - 1) // self.th + 1):
            for tx in range(xa // self.tw, (xb - 1) // self.tw + 1):
                tile = self._tile(ty * self.tiles_across + tx)
                x0, y0 = max(xa, tx * self.tw), max(ya, ty * self.th)
                x1, y1 = min(xb, (tx + 1) * self.tw), min(yb, (ty + 1) * self.th)
                out[y0 - row0:y1 - row0, x0 - col0:x1 - col0] = \
                    tile[y0 - ty * self.th:y1 - ty * self.th, x0 - tx * self.tw:x1 - tx * self.tw]
        return out


def polygon_mask(cols: list[float], rows: list[float], shape: tuple[int, int]):
    """Pixels whose centres lie inside a polygon given in pixel units (even-odd rule)."""
    import numpy as np
    h, w = shape
    py, px = np.mgrid[0:h, 0:w].astype(np.float64) + 0.5
    inside = np.zeros(shape, dtype=bool)
    n = len(cols)
    for i in range(n):
        x1, y1, x2, y2 = cols[i], rows[i], cols[(i + 1) % n], rows[(i + 1) % n]
        if y1 == y2:
            continue
        crosses = (y1 > py) != (y2 > py)
        inside ^= crosses & (px < x1 + (py - y1) * (x2 - x1) / (y2 - y1))
    return inside


# ======================================================================= open Sentinel-2
def boa_offset(props: dict) -> int:
    """DN offset still in the pixels: ESA adds 1000 from processing baseline 04.00 (25 Jan 2022); Earth Search
    removes it when ``earthsearch:boa_offset_applied`` is true. Check the metadata, never assume."""
    if props.get("earthsearch:boa_offset_applied"):
        return 0
    try:
        return 1000 if float(props.get("s2:processing_baseline") or 0) >= 4.0 else 0
    except (TypeError, ValueError):
        return 0


class OpenSentinel2:
    """Sentinel-2 L2A over a farm from the open Earth Search archive on AWS (no account)."""

    def __init__(self, settings, http):
        self.settings, self.http = settings, http

    def search(self, bbox: list[float], start: date, end: date, max_cloud: float) -> list[dict]:
        body = {"collections": ["sentinel-2-l2a"], "bbox": bbox, "datetime": f"{start}T00:00:00Z/{end}T23:59:59Z",
                "query": {"eo:cloud_cover": {"lt": max_cloud}}, "limit": 200}
        status, raw = self.http("POST", self.settings.earthsearch_url.rstrip("/") + "/search",
                                {"Content-Type": "application/json", "Accept": "application/geo+json"},
                                json.dumps(body).encode())
        if status != 200:
            raise RuntimeError(f"Earth Search catalogue: HTTP {status}")
        out = []
        for f in json.loads(raw).get("features", []):
            p, a = f.get("properties", {}), f.get("assets", {})
            if not all(k in a for k in ("red", "nir", "scl")):
                continue
            epsg = p.get("proj:epsg") or int(str(p.get("proj:code") or "EPSG:0").split(":")[-1] or 0)
            out.append({"id": f["id"], "date": p["datetime"][:10], "datetime": p["datetime"],
                        "cloud": p.get("eo:cloud_cover"), "tile": p.get("s2:mgrs_tile") or f["id"].split("_")[1],
                        "epsg": int(epsg), "bbox": f.get("bbox"), "offset": boa_offset(p),
                        "platform": p.get("platform", ""),
                        "hrefs": {k: a[k]["href"] for k in ("red", "green", "blue", "nir", "scl", "thumbnail") if k in a}})
        return sorted(out, key=lambda s: s["datetime"])

    @staticmethod
    def best_per_day(scenes: list[dict], bbox: list[float]) -> list[dict]:
        """One scene per date: a tile whose footprint holds the whole farm, least cloud first."""
        best: dict[str, dict] = {}
        for s in scenes:
            b = s.get("bbox")
            if b and not (b[0] <= bbox[0] and b[1] <= bbox[1] and b[2] >= bbox[2] and b[3] >= bbox[3]):
                continue
            cur = best.get(s["date"])
            if cur is None or (s["cloud"] or 0) < (cur["cloud"] or 0):
                best[s["date"]] = s
        return [best[d] for d in sorted(best)]

    def _grid(self, scene: dict, zones: list[tuple[str, list]], margin_m: float = 20):
        zone_no, south = utm_zone(scene["epsg"])
        proj = [(zid, [utm_forward(lat, lon, zone_no, south) for lon, lat in ring]) for zid, ring in zones]
        xs = [p[0] for _, r in proj for p in r]
        ys = [p[1] for _, r in proj for p in r]
        return proj, (min(xs) - margin_m, min(ys) - margin_m, max(xs) + margin_m, max(ys) + margin_m)

    def read_bands(self, scene: dict, box: tuple[float, float, float, float], bands: tuple[str, ...]):
        """Reflectance of 10 m bands plus the clear-sky mask on one 10 m grid over ``box`` (UTM)."""
        import numpy as np
        first = Cog(scene["hrefs"][bands[0]], self.http)
        c0, r0, w, h = first.window(*box)
        if w * h > 4_000_000:
            raise ValueError("The area is too large for one read (about 20 x 20 km at most)")
        out = {}
        for i, b in enumerate(bands):
            cog = first if i == 0 else Cog(scene["hrefs"][b], self.http)
            if cog.res != first.res or cog.origin != first.origin:
                raise ValueError(f"Band {b} is not on the 10 m grid")
            dn = cog.read(c0, r0, w, h).astype(np.float32)
            out[b] = np.where(dn > 0, (dn - scene["offset"]) / 10000.0, np.nan)
        scl = Cog(scene["hrefs"]["scl"], self.http)
        x0, y0 = first.origin[0] + c0 * first.res[0], first.origin[1] - r0 * first.res[1]
        k = max(1, round(scl.res[0] / first.res[0]))
        sc0, sr0 = math.floor((x0 - scl.origin[0]) / scl.res[0]), math.floor((scl.origin[1] - y0) / scl.res[1])
        s = scl.read(sc0, sr0, -(-w // k) + 1, -(-h // k) + 1)
        s = np.repeat(np.repeat(s, k, axis=0), k, axis=1)
        dx = round((x0 - (scl.origin[0] + sc0 * scl.res[0])) / first.res[0])
        dy = round(((scl.origin[1] - sr0 * scl.res[1]) - y0) / first.res[1])
        s = s[dy:dy + h, dx:dx + w]
        valid = np.all([np.isfinite(out[b]) for b in bands], axis=0)
        out["clear"] = valid & np.isin(s, SCL_CLEAR)
        out["geo"] = (x0, y0, first.res[0], first.res[1], w, h)
        return out

    @staticmethod
    def pixel_ring(ring_xy: list[tuple[float, float]], geo) -> tuple[list[float], list[float]]:
        x0, y0, rx, ry, _, _ = geo
        return [(x - x0) / rx for x, _ in ring_xy], [(y0 - y) / ry for _, y in ring_xy]

    def field_stats(self, scene: dict, zones: list[tuple[str, list]]) -> list[dict]:
        """NDVI mean / min / max and clear-sky share of every field (rings in lon/lat) on one pass."""
        import numpy as np
        proj, box = self._grid(scene, zones)
        d = self.read_bands(scene, box, ("red", "nir"))
        ndvi = (d["nir"] - d["red"]) / np.maximum(d["nir"] + d["red"], 1e-6)
        rows = []
        for zid, ring in proj:
            cols, rws = self.pixel_ring(ring, d["geo"])
            m = polygon_mask(cols, rws, d["clear"].shape)
            n = int(m.sum())
            if not n:
                continue
            ok = m & d["clear"]
            v = ndvi[ok]
            rows.append({"zone_id": zid, "pixels": n, "clear_share": round(float(ok.sum()) / n, 3),
                         "mean": round(float(v.mean()), 4) if v.size else None,
                         "min": round(float(v.min()), 4) if v.size else None,
                         "max": round(float(v.max()), 4) if v.size else None})
        return rows

    def field_png(self, scene: dict, ring: list, kind: str) -> bytes:
        """True-colour or NDVI picture of one field (outside the field dimmed), 512 px wide."""
        import io

        import numpy as np
        from PIL import Image
        proj, box = self._grid(scene, [("f", ring)], margin_m=60)
        bands = ("red", "green", "blue") if kind == "truecolor" else ("red", "nir")
        missing = [b for b in bands + ("scl",) if b not in scene["hrefs"]]
        if missing:
            raise LookupError(f"This pass has no {', '.join(missing)} band in the archive")
        d = self.read_bands(scene, box, bands)
        if kind == "truecolor":
            rgb = np.dstack([np.nan_to_num(d[b]) for b in bands])
            img = np.clip(rgb / 0.3, 0, 1) ** (1 / 1.4)
        else:
            v = np.nan_to_num((d["nir"] - d["red"]) / np.maximum(d["nir"] + d["red"], 1e-6))
            stops = np.array([0.0, 0.2, 0.4, 0.6, 0.8])
            cols = np.array([[0.55, 0.34, 0.16], [0.87, 0.78, 0.58], [0.85, 0.91, 0.55], [0.40, 0.74, 0.39],
                             [0.10, 0.47, 0.22]])
            img = np.dstack([np.interp(v, stops, cols[:, i]) for i in range(3)])
            img[~d["clear"]] = (0.75, 0.75, 0.75)
        cols_, rows_ = self.pixel_ring(proj[0][1], d["geo"])
        inside = polygon_mask(cols_, rows_, d["clear"].shape)
        img[~inside] *= 0.45
        pic = Image.fromarray((img * 255).astype(np.uint8))
        scale = max(1, 512 // max(pic.size))
        pic = pic.resize((pic.width * scale, pic.height * scale), Image.NEAREST)
        buf = io.BytesIO()
        pic.save(buf, format="PNG")
        return buf.getvalue()


# ======================================================================= catalogues
def browser_link(collection: str, lat: float, lon: float, day: str, zoom: int = 13) -> str:
    q = {"zoom": zoom, "lat": round(lat, 5), "lng": round(lon, 5), "themeId": "DEFAULT-THEME",
         "fromTime": f"{day}T00:00:00.000Z", "toTime": f"{day}T23:59:59.999Z"}
    if collection in BROWSER_DATASETS:
        q["datasetId"] = BROWSER_DATASETS[collection]
    return "https://browser.dataspace.copernicus.eu/?" + urllib.parse.urlencode(q)


class Catalogue:
    """Copernicus Data Space STAC search (public) and the EUMETSAT Data Store (search public, download with key)."""

    def __init__(self, settings, http, download=http_download):
        self.settings, self.http, self.download = settings, http, download
        self._eum_token: tuple[float, str] | None = None
        self._eum_collections: tuple[float, list[dict]] | None = None

    # -------------------------------------------------- Copernicus
    def cdse_search(self, collection: str, bbox: list[float], start: date, end: date, limit: int = 50,
                    max_cloud: float | None = None) -> list[dict]:
        if collection not in CDSE_COLLECTIONS:
            raise ValueError(f"Unknown collection; use one of {', '.join(CDSE_COLLECTIONS)}")
        body = {"collections": [collection], "bbox": bbox, "datetime": f"{start}T00:00:00Z/{end}T23:59:59Z",
                "limit": max(1, min(limit, 100)), "sortby": [{"field": "properties.datetime", "direction": "desc"}]}
        if max_cloud is not None and collection == "sentinel-2-l2a":
            body["filter"] = {"op": "<=", "args": [{"property": "eo:cloud_cover"}, max_cloud]}
            body["filter-lang"] = "cql2-json"
        status, raw = self.http("POST", self.settings.cdse_stac_url.rstrip("/") + "/search",
                                {"Content-Type": "application/json", "Accept": "application/geo+json"},
                                json.dumps(body).encode())
        if status != 200:
            raise RuntimeError(f"Copernicus catalogue: HTTP {status}")
        lat, lon = (bbox[1] + bbox[3]) / 2, (bbox[0] + bbox[2]) / 2
        out = []
        for f in json.loads(raw).get("features", []):
            p = f.get("properties", {})
            day = str(p.get("datetime", ""))[:10]
            out.append({"id": f["id"], "datetime": p.get("datetime"), "platform": p.get("platform", ""),
                        "product_type": p.get("product:type", ""), "cloud": p.get("eo:cloud_cover"),
                        "grid": p.get("grid:code", ""), "orbit_state": p.get("sat:orbit_state"),
                        "relative_orbit": p.get("sat:relative_orbit"), "processing": p.get("processing:version"),
                        "browser": browser_link(collection, lat, lon, day) if day else None,
                        "stac": f"{self.settings.cdse_stac_url.rstrip('/')}/collections/{collection}/items/"
                                f"{urllib.parse.quote(f['id'])}"})
        return out

    # -------------------------------------------------- EUMETSAT
    @property
    def eumetsat_ready(self) -> bool:
        return bool(self.settings.eumetsat_key and self.settings.eumetsat_secret)

    def _eum(self, path: str) -> str:
        return self.settings.eumetsat_url.rstrip("/") + path

    def eumetsat_collections(self, query: str = "") -> list[dict]:
        if not self._eum_collections or time.time() > self._eum_collections[0]:
            status, raw = self.http("GET", self._eum("/data/browse/collections?format=json"),
                                    {"Accept": "application/json"}, None)
            if status != 200:
                raise RuntimeError(f"EUMETSAT Data Store: HTTP {status}")
            rows = [{"id": lk.get("title"), "title": lk.get("datasetTitle", ""), "products": lk.get("numberOfProducts")}
                    for lk in json.loads(raw).get("links", []) if str(lk.get("title", "")).startswith("EO:EUM")]
            self._eum_collections = (time.time() + 86400, rows)
        rows = self._eum_collections[1]
        q = query.strip().lower()
        return [r for r in rows if q in r["id"].lower() or q in r["title"].lower()] if q else rows

    def eumetsat_search(self, collection: str, bbox: list[float] | None, start: datetime, end: datetime,
                        limit: int = 20) -> dict:
        if not COLLECTION_RE.match(collection):
            raise ValueError("Collection ids look like EO:EUM:DAT:1088")
        q = {"pi": collection, "dtstart": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
             "dtend": end.strftime("%Y-%m-%dT%H:%M:%SZ"), "format": "json", "c": max(1, min(limit, 100)),
             "sort": "start,time,0"}
        if bbox:
            q["bbox"] = ",".join(f"{v:.5f}" for v in bbox)
        status, raw = self.http("GET", self._eum("/data/search-products/1.0.0/os?" + urllib.parse.urlencode(q)),
                                {"Accept": "application/json"}, None)
        if status != 200:
            raise RuntimeError(f"EUMETSAT search: HTTP {status}")
        data = json.loads(raw)
        out = []
        for f in data.get("features", []):
            p = f.get("properties", {})
            acq = (p.get("acquisitionInformation") or [{}])[0]
            span = str(p.get("date", "")).split("/")
            out.append({"id": p.get("identifier") or f.get("id"), "start": span[0], "end": span[-1],
                        "platform": (acq.get("platform") or {}).get("platformShortName", ""),
                        "instrument": (acq.get("instrument") or {}).get("instrumentShortName", ""),
                        "product_type": (p.get("productInformation") or {}).get("productType", ""),
                        "size_kb": (p.get("productInformation") or {}).get("size")})
        return {"total": data.get("totalResults"), "products": out}

    def _token(self) -> str:
        if self._eum_token and time.time() < self._eum_token[0]:
            return self._eum_token[1]
        s = self.settings
        basic = base64.b64encode(f"{s.eumetsat_key}:{s.eumetsat_secret.get_secret_value()}".encode()).decode()
        status, raw = self.http("POST", self._eum("/token"), {"Authorization": f"Basic {basic}",
                                "Content-Type": "application/x-www-form-urlencoded"}, b"grant_type=client_credentials")
        if status != 200:
            raise RuntimeError(f"EUMETSAT sign-in failed (HTTP {status}); check WIOT_EUMETSAT_KEY / _SECRET")
        data = json.loads(raw)
        self._eum_token = (time.time() + int(data.get("expires_in", 3600)) - 60, data["access_token"])
        return self._eum_token[1]

    def downloads_dir(self) -> Path:
        return Path(self.settings.data_dir) / "eo" / "eumetsat"

    def eumetsat_download(self, collection: str, product: str) -> dict:
        if not self.eumetsat_ready:
            raise LookupError("EUMETSAT downloads need WIOT_EUMETSAT_KEY and WIOT_EUMETSAT_SECRET")
        if not COLLECTION_RE.match(collection) or not PRODUCT_RE.match(product):
            raise ValueError("Invalid collection or product id")
        folder = self.downloads_dir() / safe_name(collection)
        folder.mkdir(parents=True, exist_ok=True)
        dest = folder / (safe_name(product) + ".zip")
        if dest.exists():
            return {"file": str(dest.relative_to(self.downloads_dir())), "bytes": dest.stat().st_size, "cached": True}
        url = self._eum("/data/download/1.0.0/collections/" + urllib.parse.quote(collection, safe="")
                        + "/products/" + urllib.parse.quote(product, safe=""))
        status, n = self.download(url, {"Authorization": f"Bearer {self._token()}"}, dest,
                                  self.settings.eo_download_max_mb * 1024 * 1024)
        if status != 200 or not dest.exists():
            raise RuntimeError(f"EUMETSAT download failed (HTTP {status})")
        return {"file": str(dest.relative_to(self.downloads_dir())), "bytes": n, "cached": False}

    def downloads(self) -> list[dict]:
        root = self.downloads_dir()
        if not root.exists():
            return []
        files = [p for p in root.rglob("*.zip") if p.is_file()]
        return [{"file": str(p.relative_to(root)).replace("\\", "/"), "collection": p.parent.name, "bytes": p.stat().st_size,
                 "time": int(p.stat().st_mtime)} for p in sorted(files, key=lambda p: -p.stat().st_mtime)][:200]


def farm_bbox(layout, zone_geometry) -> list[float] | None:
    """[west, south, east, north] around all fields of a layout, or None when it has no fields."""
    rings = [zone_geometry(z)["coordinates"][0] for z in layout.zones] if layout else []
    if not rings:
        return None
    xs = [p[0] for r in rings for p in r]
    ys = [p[1] for r in rings for p in r]
    return [min(xs), min(ys), max(xs), max(ys)]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def days_ago(n: int) -> date:
    return (utc_now() - timedelta(days=n)).date()
