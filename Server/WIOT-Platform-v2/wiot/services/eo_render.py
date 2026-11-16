"""Satellite viewer (R2.7): render any layer for any map view, and list every dataset available over a farm.

Rendering (``SatelliteViewer.render``):

* **Sentinel Hub** (Copernicus Data Space OAuth client configured): one Process API request per view, in Web
  Mercator (EPSG:3857) so the picture lies exactly on the dashboard map. A date gives that day's pass; without a
  date the least-cloudy (Sentinel-2) or most recent pass of the last 30 days is drawn.
* **Open archive** (no account; Sentinel-2 L2A only): the bands are read from the cloud-optimised GeoTIFFs of one
  Earth Search scene, from the overview level that matches the zoom, and the layer is computed with numpy.

Protection of the server and of the shared Copernicus account:

* at most ``OPEN_SLOTS`` open-archive and ``SH_SLOTS`` Sentinel Hub images are drawn at the same time (a request
  that finds no free slot within ``SLOT_WAIT_S`` gets :class:`Busy`, HTTP 503 with Retry-After);
* open-archive images are at most ``OPEN_MAX_PX`` pixels on their longest side (bounded memory);
* Sentinel Hub images are charged against daily processing-unit allowances, per company and for the whole server
  (``WIOT_VIEWER_COMPANY_DAILY_PU``, ``WIOT_VIEWER_DAILY_PU``; :class:`QuotaExceeded`, HTTP 429);
* rendered images are cached on disk (``data/satellite/render``: the newest ``CACHE_FILES`` images, at most
  ``WIOT_VIEWER_CACHE_MB``). The cache is best effort: a cache error never fails a request.

Availability (``SatelliteViewer.availability``): passes and products over the farm from the Copernicus Data Space
catalogue (Sentinel-1, -2, -3), Earth Search (Landsat 8/9), the EUMETSAT Data Store (Meteosat and Metop products)
and what the server itself holds (stored NDVI, WIOT-SAT products) - fetched in parallel within one deadline and
cached for 20 minutes (2 minutes when a catalogue failed).
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import math
import os
import re
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import wait as wait_futures
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .eo import Cog, OpenSentinel2, utm_forward_np, utm_zone
from .eo_layers import BY_ID, MISSIONS, bands_needed, custom_script, render_numpy

log = logging.getLogger(__name__)
R_EARTH = 6378137.0
MAX_PX = 1600                               # largest side of an image (Sentinel Hub)
OPEN_MAX_PX = 1024                          # open archive: drawn with numpy on this server, so memory is bounded
CACHE_FILES = 600                           # newest images kept on disk (and at most WIOT_VIEWER_CACHE_MB)
OPEN_MAX_SPAN_DEG = 0.6                     # open archive: one scene, at most about 60 km across
OPEN_SLOTS, SH_SLOTS = 2, 4                 # images drawn at the same time on the whole server
SLOT_WAIT_S = 15                            # wait for a free slot before answering "busy"
AVAIL_DAYS = (30, 90, 180, 365)             # periods of the availability timeline
AVAIL_TTL_OK, AVAIL_TTL_FAILED = 1200, 120  # seconds an answer is reused (shorter when a catalogue failed)
AVAIL_DEADLINE_S = 60                       # all catalogues together
AVAIL_MAX_ENTRIES = 64
STAC_MAX_ITEMS = 2000                       # per collection and period: about 5 a day over a year
PU_BAND_RE = re.compile(r'"(B0[1-9]|B1[0-2]|B8A|VV|VH|HH|HV|Oa\d\d|S[1-9]|F[12]|SCL|CLM|CLP)"')


class ViewerInputError(ValueError):
    """A request the viewer cannot draw (HTTP 400)."""


class NoImagery(LookupError):
    """No data for this view, satellite or date (HTTP 404)."""


class Busy(Exception):
    """Every drawing slot is in use (HTTP 503 with Retry-After)."""


class QuotaExceeded(Exception):
    """A daily allowance of Sentinel Hub processing units is used up (HTTP 429)."""


def to_mercator(lon: float, lat: float) -> tuple[float, float]:
    lat = max(min(lat, 85.0), -85.0)
    return R_EARTH * math.radians(lon), R_EARTH * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


def from_mercator_np(x, y):
    import numpy as np
    return np.degrees(x / R_EARTH), np.degrees(2 * np.arctan(np.exp(y / R_EARTH)) - math.pi / 2)


def processing_units(width: int, height: int, script: str | None) -> float:
    """Sentinel Hub's estimate: one unit per 512 x 512 pixels and per 3 input bands (at least one)."""
    bands = len(set(PU_BAND_RE.findall(script or ""))) or 1
    return max(0.01, width * height / (512 * 512) * max(1.0, bands / 3))


def _ring_contains(ring, x: float, y: float) -> bool:
    inside = False
    for (x1, y1, *_), (x2, y2, *_) in zip(ring, list(ring[1:]) + list(ring[:1])):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


def covers(scene: dict, x: float, y: float) -> bool:
    """True when the point (lon, lat) lies in the scene's data footprint (its bounding box if no footprint is given).

    A Sentinel-2 tile at the edge of an orbit's swath holds data only in a slanted strip; its bounding box still
    covers the whole tile, so the box alone would pick passes that are empty over the view."""
    geom = scene.get("geometry") or {}
    if geom.get("type") == "Polygon":
        polygons = [geom.get("coordinates") or []]
    elif geom.get("type") == "MultiPolygon":
        polygons = geom.get("coordinates") or []
    else:
        b = scene.get("bbox")
        return not b or (b[0] <= x <= b[2] and b[1] <= y <= b[3])
    return any(p and _ring_contains(p[0], x, y) and not any(_ring_contains(h, x, y) for h in p[1:]) for p in polygons)


class SatelliteViewer:
    def __init__(self, settings, satellite, catalogue):
        self.settings = settings
        self.sat = satellite                 # SatelliteService: Sentinel Hub token and HTTP (self.sat.http)
        self.cat = catalogue
        self._avail: dict[tuple, tuple[float, dict]] = {}
        self._avail_guard = threading.Lock()
        self._avail_locks: dict[tuple, threading.Lock] = {}
        self._open_slots = threading.BoundedSemaphore(OPEN_SLOTS)
        self._sh_slots = threading.BoundedSemaphore(SH_SLOTS)
        self._evict_lock = threading.Lock()
        self._budget_lock = threading.Lock()
        self._budget: dict[str, dict[str, float]] = {}       # UTC day -> {"*" or company: processing units}

    # ------------------------------------------------------------------ helpers
    @property
    def sh_enabled(self) -> bool:
        """WIOT_SATELLITE_PROVIDER auto or sentinelhub, with the Copernicus OAuth client."""
        return self.settings.satellite_provider in ("auto", "sentinelhub") and self.sat.sentinel_ready

    @property
    def open_available(self) -> bool:
        """WIOT_SATELLITE_PROVIDER auto or open, with numpy and Pillow installed (Sentinel-2 L2A only)."""
        if self.settings.satellite_provider not in ("auto", "open"):
            return False
        try:
            import numpy  # noqa: F401
            from PIL import Image  # noqa: F401
        except ImportError:
            return False
        return True

    def provider(self, mission: str) -> str | None:
        """auto: Sentinel Hub when the client is set, else the open archive; open / sentinelhub: only that one; off: none."""
        if self.sh_enabled:
            return "sentinelhub"
        if mission == "S2L2A" and self.open_available:
            return "open"
        return None

    def cache_dir(self) -> Path:
        d = Path(self.settings.data_dir) / "satellite" / "render"
        d.mkdir(parents=True, exist_ok=True)
        return d

    # ------------------------------------------------------------------ disk cache (best effort)
    def _cache_get(self, path: Path) -> tuple[bytes, dict] | None:
        """One file per image: a JSON line with the metadata, then the PNG. Anything unreadable is a miss."""
        try:
            raw = path.read_bytes()
        except OSError:
            return None
        head, sep, data = raw.partition(b"\n")
        if not sep or not data.startswith(b"\x89PNG"):
            return None
        try:
            return data, json.loads(head)
        except ValueError:
            return None

    def _cache_put(self, path: Path, data: bytes, extra: dict) -> None:
        tmp = path.with_name(f"{path.stem}.{os.getpid()}-{threading.get_ident()}.tmp")
        try:
            tmp.write_bytes(json.dumps(extra).encode() + b"\n" + data)
            os.replace(tmp, path)                            # readers never see half a file
        except OSError as exc:
            log.warning("Satellite image cache: could not store %s (%s)", path.name, exc.strerror or exc)
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            return
        self._evict()

    def _evict(self) -> None:
        """Keep the newest CACHE_FILES images within WIOT_VIEWER_CACHE_MB; one clean-up at a time; never raises."""
        if not self._evict_lock.acquire(blocking=False):
            return                                           # another request is cleaning up already
        try:
            entries, stale = [], time.time() - 3600
            with os.scandir(self.cache_dir()) as it:
                for de in it:
                    try:
                        if not de.is_file():
                            continue
                        st = de.stat()
                        if de.name.endswith(".tmp"):
                            if st.st_mtime < stale:          # left by a crash
                                os.unlink(de.path)
                        elif not de.name.endswith(".cache"):
                            os.unlink(de.path)               # files of an older cache format
                        else:
                            entries.append((st.st_mtime, st.st_size, de.path))
                    except OSError:
                        continue                             # removed by someone else meanwhile
            entries.sort(reverse=True)                       # newest first
            limit, total = self.settings.viewer_cache_mb * 1024 * 1024, 0
            for i, (_, size, p) in enumerate(entries):
                total += size
                if i >= CACHE_FILES or total > limit:
                    try:
                        os.unlink(p)
                    except OSError:
                        pass
        except OSError as exc:
            log.warning("Satellite image cache: clean-up failed (%s)", exc.strerror or exc)
        finally:
            self._evict_lock.release()

    # ------------------------------------------------------------------ Sentinel Hub allowances
    def _check_budget(self, company: str | None, pu: float) -> None:
        s, day = self.settings, datetime.now(timezone.utc).date().isoformat()
        with self._budget_lock:
            for old in [d for d in self._budget if d != day]:
                del self._budget[old]
            used = self._budget.setdefault(day, {})
            if s.viewer_daily_pu and used.get("*", 0.0) + pu > s.viewer_daily_pu:
                raise QuotaExceeded(f"Today's Sentinel Hub allowance of this server is used up ({s.viewer_daily_pu:g} "
                                    "processing units); it starts again at 00:00 UTC")
            if s.viewer_company_daily_pu and company and used.get(company, 0.0) + pu > s.viewer_company_daily_pu:
                raise QuotaExceeded(f"Today's Sentinel Hub allowance of this company is used up "
                                    f"({s.viewer_company_daily_pu:g} processing units); it starts again at 00:00 UTC")

    def _charge(self, company: str | None, pu: float) -> None:
        day = datetime.now(timezone.utc).date().isoformat()
        with self._budget_lock:
            used = self._budget.setdefault(day, {})
            used["*"] = used.get("*", 0.0) + pu
            if company:
                used[company] = used.get(company, 0.0) + pu

    def usage_today(self) -> dict[str, float]:
        with self._budget_lock:
            return dict(self._budget.get(datetime.now(timezone.utc).date().isoformat(), {}))

    # ------------------------------------------------------------------ render
    def render(self, mission: str, layer_id: str, bbox: tuple[float, float, float, float], width: int, height: int,
               day: str | None = None, max_cloud: float = 30.0, custom: dict | None = None,
               evalscript: str | None = None, company: str | None = None) -> tuple[bytes, dict]:
        """PNG of ``layer_id`` over ``bbox`` = (west, south, east, north) in degrees, ``width`` x ``height`` pixels.

        ``company`` is charged for Sentinel Hub images that are not in the cache."""
        if mission not in MISSIONS:
            raise ViewerInputError("Unknown mission")
        layer = BY_ID.get((mission, layer_id))
        if layer is None:
            raise ViewerInputError("This layer does not exist for this mission")
        w, s, e, n = (float(v) for v in bbox)
        if not all(math.isfinite(v) for v in (w, s, e, n)) or not (-180 <= w < e <= 180 and -85 <= s < n <= 85):
            raise ViewerInputError("Invalid map bounds")
        bbox = (w, s, e, n)
        width, height = max(16, min(int(width), MAX_PX)), max(16, min(int(height), MAX_PX))
        max_cloud = int(round(min(max(float(max_cloud), 0.0), 100.0)))     # the same value in the key and the request
        if day:
            try:
                day = date.fromisoformat(day).isoformat()                       # "20261110" or "2026-W45-1" -> YYYY-MM-DD
            except ValueError:
                raise ViewerInputError("The date must be YYYY-MM-DD") from None
        provider = self.provider(mission)
        if provider is None:
            raise NoImagery("Satellite imagery is not configured on this server (Copernicus OAuth client, or "
                            "WIOT_SATELLITE_PROVIDER=open for Sentinel-2 from the open archive)")
        if layer_id == "CUSTOM" and not (custom or evalscript):
            raise ViewerInputError("Choose the bands of the custom layer")
        if evalscript and provider != "sentinelhub":
            raise ViewerInputError("Your own evalscript needs the Copernicus Sentinel Hub account")
        script = evalscript or (custom_script(custom["mode"], custom["bands"]) if layer_id == "CUSTOM" else layer["script"])
        if provider == "open":
            if e - w > OPEN_MAX_SPAN_DEG or n - s > OPEN_MAX_SPAN_DEG:
                raise ViewerInputError("Zoom in: the open archive draws views up to about 60 km across")
            k = min(1.0, OPEN_MAX_PX / max(width, height))
            width, height = max(16, round(width * k)), max(16, round(height * k))
        key_src = json.dumps([provider, mission, layer_id, [round(v, 5) for v in bbox], width, height,
                              day or f"latest:{datetime.now(timezone.utc).date()}", max_cloud, custom,
                              hashlib.sha256((script or "").encode()).hexdigest()], sort_keys=True)
        path = self.cache_dir() / (hashlib.sha256(key_src.encode()).hexdigest()[:40] + ".cache")
        meta = {"provider": provider, "mission": mission, "layer": layer_id, "date": day}
        hit = self._cache_get(path)
        if hit:
            return hit[0], {**meta, **hit[1], "cached": True}
        pu = processing_units(width, height, script) if provider == "sentinelhub" else 0.0
        if pu:
            self._check_budget(company, pu)
        slots = self._open_slots if provider == "open" else self._sh_slots
        if not slots.acquire(timeout=SLOT_WAIT_S):
            raise Busy("The satellite image service is busy; the image follows in a moment")
        try:
            if provider == "sentinelhub":
                data, extra = self._render_sentinelhub(mission, script, bbox, width, height, day, max_cloud)
            else:
                data, extra = self._render_open(layer_id, bbox, width, height, day, max_cloud, custom)
        except (ViewerInputError, NoImagery, RuntimeError, OSError):
            raise
        except Exception as exc:          # unreadable answers: JSON, TIFF tiles, DEFLATE data, a connection cut short
            log.warning("Satellite image %s/%s failed: %r", mission, layer_id, exc)
            raise RuntimeError(f"The image service sent data that could not be read ({type(exc).__name__})") from exc
        finally:
            slots.release()
        if pu:
            self._charge(company, pu)
        self._cache_put(path, data, extra)
        return data, {**meta, **extra, "cached": False}

    def _render_sentinelhub(self, mission, script, bbox, width, height, day, max_cloud):
        w, s, e, n = bbox
        x0, y0 = to_mercator(w, s)
        x1, y1 = to_mercator(e, n)
        today = datetime.now(timezone.utc).date()
        if day:
            t0, t1 = f"{day}T00:00:00Z", f"{day}T23:59:59Z"
        else:
            t0, t1 = f"{today - timedelta(days=30)}T00:00:00Z", f"{today}T23:59:59Z"
        info = MISSIONS[mission]
        dfilter: dict = {"timeRange": {"from": t0, "to": t1},
                         "mosaickingOrder": "leastCC" if info["cloud"] and not day else "mostRecent"}
        if info["cloud"]:
            dfilter["maxCloudCoverage"] = max_cloud if not day else 100
        source: dict = {"type": info["type"], "dataFilter": dfilter}
        if mission == "S1GRD":
            dfilter.update(acquisitionMode="IW", polarization="DV")
            source["processing"] = {"backCoeff": "GAMMA0_TERRAIN", "orthorectify": True}
        payload = {"input": {"bounds": {"bbox": [x0, y0, x1, y1], "properties": {"crs": "http://www.opengis.net/def/crs/EPSG/0/3857"}},
                             "data": [source]},
                   "output": {"width": width, "height": height, "responses": [{"identifier": "default", "format": {"type": "image/png"}}]},
                   "evalscript": script}
        status, body = self.sat._sh("/api/v1/process", payload, accept="image/png")
        if status != 200:
            msg = body.decode("utf-8", "replace") if isinstance(body, bytes) else str(body)
            try:
                msg = json.loads(msg)["error"]["message"]
            except (ValueError, KeyError, TypeError):
                msg = msg[:200]
            raise RuntimeError(f"Sentinel Hub: {msg} (HTTP {status})")
        if not isinstance(body, bytes) or not body.startswith(b"\x89PNG"):
            raise RuntimeError("Sentinel Hub did not send a PNG image")
        return body, {"from": t0[:10], "to": t1[:10], "mosaic": dfilter["mosaickingOrder"]}

    def _render_open(self, layer_id, bbox, width, height, day, max_cloud, custom):
        import numpy as np
        from PIL import Image
        w, s, e, n = bbox
        s2 = OpenSentinel2(self.settings, self.sat.http)
        today = datetime.now(timezone.utc).date()
        start, end = (date.fromisoformat(day),) * 2 if day else (today - timedelta(days=30), today)
        cx, cy = (w + e) / 2, (s + n) / 2
        scenes = [sc for sc in s2.search([w, s, e, n], start, end, None if day else max_cloud) if covers(sc, cx, cy)]
        if not scenes:
            raise NoImagery("No Sentinel-2 pass over this view in the open archive for this date")
        if day:
            scene = min(scenes, key=lambda sc: sc["cloud"] or 0)
        else:
            latest_day = max(sc["date"] for sc in scenes)
            scene = min((sc for sc in scenes if sc["date"] == latest_day), key=lambda sc: sc["cloud"] or 0)
        # output pixel centres, evenly spaced in Web Mercator like the dashboard map
        x0, y0 = to_mercator(w, s)
        x1, y1 = to_mercator(e, n)
        xs = x0 + (np.arange(width) + 0.5) * (x1 - x0) / width
        ys = y1 - (np.arange(height) + 0.5) * (y1 - y0) / height
        mx, my = np.meshgrid(xs, ys)
        lon, lat = from_mercator_np(mx, my)
        del mx, my
        zone, south = utm_zone(scene["epsg"])
        ux, uy = utm_forward_np(lat, lon, zone, south)
        del lon, lat
        pixel_m = (x1 - x0) / width * math.cos(math.radians(cy))      # ground size of one output pixel
        need = bands_needed(layer_id, custom)
        missing = [b for b in need + ["SCL"] if not scene["bands"].get(b)]
        if missing:
            raise NoImagery(f"Band {', '.join(missing)} is missing in the open archive for this pass")

        def read(band):                                       # each band is its own file: read them in parallel
            cog = Cog(scene["bands"][band], self.sat.http)
            return band, cog.sample(ux, uy, cog.level_for(pixel_m))

        refl: dict = {}
        with ThreadPoolExecutor(max_workers=4) as pool:
            for band, raw in pool.map(read, need + ["SCL"]):
                refl[band] = raw if band == "SCL" else np.where(raw > 0, (raw.astype(np.float32) - scene["offset"]) / 10000.0, np.nan)
        refl["SCL"] = refl["SCL"].astype(np.int64)
        valid = refl["SCL"] > 0
        for band in need:
            valid &= np.isfinite(refl[band])
            refl[band] = np.nan_to_num(refl[band])
        img = render_numpy(layer_id, refl, custom)
        rgba = np.dstack([np.clip(img, 0, 1) * 255, valid * 255]).astype(np.uint8)
        buf = io.BytesIO()
        Image.fromarray(rgba, "RGBA").save(buf, format="PNG", optimize=False)
        return buf.getvalue(), {"from": scene["date"], "to": scene["date"], "scene": scene["id"], "cloud": scene["cloud"],
                                "mosaic": "single pass"}

    # ------------------------------------------------------------------ availability
    def availability(self, bbox: list[float], days: int, company_rows: dict) -> dict:
        if days not in AVAIL_DAYS:
            raise ViewerInputError(f"Period must be one of {', '.join(map(str, AVAIL_DAYS))} days")
        key = (tuple(round(v, 4) for v in bbox), days)
        with self._avail_guard:
            lock = self._avail_locks.setdefault(key, threading.Lock())
        with lock:                         # one query per farm and period at a time; callers waiting reuse its answer
            hit = self._avail.get(key)
            if hit and time.time() < hit[0]:
                return {**hit[1], **company_rows, "cached": True}
            result, failed = self._query_availability(bbox, days)
            with self._avail_guard:
                now = time.time()
                for k in [k for k, (expires, _) in self._avail.items() if expires <= now]:
                    del self._avail[k]
                while len(self._avail) >= AVAIL_MAX_ENTRIES:
                    del self._avail[min(self._avail, key=lambda k: self._avail[k][0])]
                self._avail[key] = (now + (AVAIL_TTL_FAILED if failed else AVAIL_TTL_OK), result)
        return {**result, **company_rows, "cached": False}

    def _query_availability(self, bbox: list[float], days: int) -> tuple[dict, bool]:
        end = datetime.now(timezone.utc).date()
        start = end - timedelta(days=days)
        jobs = {m: (lambda m=m: self._cdse_items(MISSIONS[m]["stac"], bbox, start, end))
                for m in ("S2L2A", "S1GRD", "S3OLCI", "S3SLSTR")}
        jobs["LANDSAT"] = lambda: self._landsat_items(bbox, start, end)
        for cid, _title in EUMETSAT_ROWS:
            jobs[cid] = (lambda cid=cid: self._eumetsat_count(cid, bbox, start, end))
        out: dict = {}
        pool = ThreadPoolExecutor(max_workers=8)
        try:
            futures = {k: pool.submit(fn) for k, fn in jobs.items()}
            wait_futures(list(futures.values()), timeout=AVAIL_DEADLINE_S)      # one deadline for all catalogues
            for k, fut in futures.items():
                if not fut.done():
                    out[k] = {"ok": False, "error": f"no answer within {AVAIL_DEADLINE_S} s", "items": []}
                    continue
                try:
                    out[k] = {"ok": True, **fut.result()}
                except Exception as exc:                     # one catalogue down must not hide the others
                    out[k] = {"ok": False, "error": (str(exc) or type(exc).__name__)[:160], "items": []}
        finally:
            pool.shutdown(wait=False, cancel_futures=True)   # a hanging catalogue does not hold the request
        missions = []
        for k, title, src in (("S2L2A", "Sentinel-2 L2A", "Copernicus Data Space"), ("S1GRD", "Sentinel-1 GRD (radar)", "Copernicus Data Space"),
                              ("S3OLCI", "Sentinel-3 OLCI (land)", "Copernicus Data Space"), ("S3SLSTR", "Sentinel-3 SLSTR (land temperature)", "Copernicus Data Space"),
                              ("LANDSAT", "Landsat 8 / 9 (USGS)", "Earth Search on AWS")):
            missions.append({"id": k, "title": title, "source": src, "viewer": k in MISSIONS, **out[k]})
        eum = [{"id": cid, "title": title, **out[cid]} for cid, title in EUMETSAT_ROWS]
        failed = any(not v["ok"] for v in out.values())
        return {"bbox": bbox, "from": start.isoformat(), "to": end.isoformat(), "missions": missions, "eumetsat": eum}, failed

    def _stac_pages(self, url: str, body: dict, max_items: int | None = None) -> tuple[list[dict], int | None, bool]:
        """All features of a STAC search (following "next" links on the same host, up to ``max_items``).

        Returns the features, the catalogue's total count when it gives one, and whether the list was cut short."""
        cap = max_items or STAC_MAX_ITEMS
        feats: list[dict] = []
        matched: int | None = None
        host = urllib.parse.urlsplit(url).netloc
        req: tuple[str, str, dict | None] = ("POST", url, body)
        while True:
            method, href, payload = req
            status, raw = self.sat.http(method, href, {"Content-Type": "application/json", "Accept": "application/geo+json"},
                                        json.dumps(payload).encode() if payload is not None else None)
            if status != 200:
                raise RuntimeError(f"catalogue HTTP {status}")
            try:
                data = json.loads(raw)
            except ValueError as exc:
                raise RuntimeError("the catalogue's answer is not JSON") from exc
            if matched is None:
                n = data.get("numberMatched", (data.get("context") or {}).get("matched"))
                matched = n if isinstance(n, int) else None
            page = data.get("features") or []
            feats += page
            nxt = next((lk for lk in data.get("links") or [] if lk.get("rel") == "next" and lk.get("href")), None)
            if not nxt or not page or urllib.parse.urlsplit(nxt["href"]).netloc != host:
                return feats, matched, False
            if len(feats) >= cap:
                return feats, matched, True
            m = (nxt.get("method") or "GET").upper()
            nbody = nxt.get("body") if m == "POST" else None
            if m == "POST" and nxt.get("merge"):
                nbody = {**body, **(nbody or {})}
            req = (m, nxt["href"], nbody)

    @staticmethod
    def _counted(items: list[dict], matched: int | None, truncated: bool) -> dict:
        """count = the catalogue's total when known; exact = count is not a lower bound; partial = older items not listed."""
        count = max(matched or 0, len(items))
        return {"items": items, "count": count, "exact": matched is not None or not truncated,
                "partial": truncated or count > len(items)}

    def _cdse_items(self, collection: str, bbox, start: date, end: date) -> dict:
        feats, matched, truncated = self._stac_pages(self.settings.cdse_stac_url.rstrip("/") + "/search",
                                                     {"collections": [collection], "bbox": bbox,
                                                      "datetime": f"{start}T00:00:00Z/{end}T23:59:59Z", "limit": 100,
                                                      "sortby": [{"field": "properties.datetime", "direction": "desc"}]})
        items = []
        for f in feats:
            p = f.get("properties") or {}
            items.append({"date": str(p.get("datetime", ""))[:10], "time": str(p.get("datetime", ""))[11:16],
                          "cloud": p.get("eo:cloud_cover"), "platform": p.get("platform", ""),
                          "orbit": p.get("sat:relative_orbit"), "orbit_state": p.get("sat:orbit_state"), "id": f.get("id")})
        return self._counted(items, matched, truncated)

    def _landsat_items(self, bbox, start: date, end: date) -> dict:
        feats, matched, truncated = self._stac_pages(self.settings.earthsearch_url.rstrip("/") + "/search",
                                                     {"collections": ["landsat-c2-l2"], "bbox": bbox,
                                                      "datetime": f"{start}T00:00:00Z/{end}T23:59:59Z", "limit": 100},
                                                     max_items=1000)
        items = [{"date": str((f.get("properties") or {}).get("datetime", ""))[:10],
                  "time": str((f.get("properties") or {}).get("datetime", ""))[11:16],
                  "cloud": (f.get("properties") or {}).get("eo:cloud_cover"),
                  "platform": (f.get("properties") or {}).get("platform", ""), "id": f.get("id")} for f in feats]
        items.sort(key=lambda i: i["date"], reverse=True)
        return self._counted(items, matched, truncated)

    def _eumetsat_count(self, collection: str, bbox, start: date, end: date) -> dict:
        res = self.cat.eumetsat_search(collection, bbox, datetime.combine(start, datetime.min.time(), timezone.utc),
                                       datetime.combine(end, datetime.max.time().replace(microsecond=0), timezone.utc), 1)
        latest = res["products"][0]["start"] if res["products"] else None
        return {"count": res.get("total") or 0, "latest": latest, "items": []}


EUMETSAT_ROWS = [("EO:EUM:DAT:1088", "Land surface temperature, MTG (every 10 min)"),
                 ("EO:EUM:DAT:0394", "Land surface temperature, MSG (every 15 min)"),
                 ("EO:EUM:DAT:METOP:LSA-002", "Daily land surface temperature, Metop"),
                 ("EO:EUM:DAT:1087", "Accumulated precipitation, MTG"),
                 ("EO:EUM:DAT:METOP:OAS025", "ASCAT soil moisture and winds")]


def browser_url(mission: str, lat: float, lon: float, zoom: int, day: str | None) -> str:
    q = {"zoom": zoom, "lat": round(lat, 5), "lng": round(lon, 5), "themeId": "DEFAULT-THEME"}
    ds = {"S2L2A": "S2_L2A_CDAS", "S2L1C": "S2L1C_CDAS", "S1GRD": "S1_CDAS_IW_VVVH", "S3OLCI": "S3OLCI_CDAS", "S3SLSTR": "S3SLSTR_CDAS"}.get(mission)
    if ds:
        q["datasetId"] = ds
    if day:
        q.update(fromTime=f"{day}T00:00:00.000Z", toTime=f"{day}T23:59:59.999Z")
    return "https://browser.dataspace.copernicus.eu/?" + urllib.parse.urlencode(q)
