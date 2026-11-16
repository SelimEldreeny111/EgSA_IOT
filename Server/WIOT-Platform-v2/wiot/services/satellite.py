"""Satellite data (R2.5, points 49, 51 and 52).

**Crop health from Sentinel-2** (point 49; MisrSat-2 later through the same interface). With a Copernicus Data
Space Ecosystem account (free) set ``WIOT_SENTINEL_CLIENT_ID`` / ``WIOT_SENTINEL_CLIENT_SECRET``. Once a day the
server asks the Sentinel Hub Statistical API for the NDVI of every field (L2A, cloud-masked) over the last 30
days and stores one value per satellite pass; the Process API renders the latest NDVI image of a field on
request (cached on disk). Nothing is fetched without the account.

**Open Sentinel-2** (R2.7): with ``WIOT_SATELLITE_PROVIDER=open`` the same NDVI table is filled without an account
from the open Earth Search archive on AWS: the farm's pixels of red, NIR and the scene classification are read
from the cloud-optimised GeoTIFFs of each clear pass (see ``wiot.services.eo``). Field images come from the same
files. The Copernicus catalogue and the EUMETSAT Data Store are searched through ``eo.Catalogue``.

**Pivot detection** (point 51): finds centre-pivot circles in an image of a new farm (an uploaded PNG / JPEG with
its corner coordinates, or the Sentinel-2 true-colour image of an area). Vegetation is separated from the desert
with the excess-green index and Otsu's threshold; the Euclidean distance transform of that mask peaks at the
centre of every disc with the disc radius as its value, so touching pivots are still separated. Candidates are
kept when they are round and filled; an administrator reviews them and adds them to the farm as fields.
Needs numpy, scipy and Pillow (the server's ``analytics`` extra).

**WIOT-SAT** (point 52): the ground tool hands over *products* — node readings received through the satellite
pass — as JSON; they are stored like radio uplinks but marked ``time_source = "satellite"``. The pass schedule
(AOS / LOS per station) is imported from the ground tool and shown with the products of each pass. Real
satellite data needs the satellite option in the node firmware.
"""
from __future__ import annotations

import base64
import io
import json
import logging
import math
import threading
import time
import urllib.parse
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .eo import OPEN_SOURCE, Catalogue, OpenSentinel2, farm_bbox

log = logging.getLogger(__name__)
MAX_DOWNLOAD = 20 * 1024 * 1024


def http_raw(method: str, url: str, headers: dict, body: bytes | None, timeout: float = 60.0) -> tuple[int, bytes]:
    """HTTP call returning the whole body as bytes (statistics JSON, PNG images)."""
    import urllib.error
    import urllib.request
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:      # noqa: S310 - configured provider URLs
            return resp.status, resp.read(MAX_DOWNLOAD)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(2000)

NDVI_EVALSCRIPT = """//VERSION=3
function setup() { return { input: [{ bands: ["B04", "B08", "SCL", "dataMask"] }],
  output: [{ id: "ndvi", bands: 1, sampleType: "FLOAT32" }, { id: "dataMask", bands: 1 }] }; }
function evaluatePixel(s) {
  var clear = s.dataMask == 1 && [3, 8, 9, 10].indexOf(s.SCL) < 0;   // drop cloud shadow, clouds, cirrus
  return { ndvi: [(s.B08 - s.B04) / (s.B08 + s.B04 + 1e-6)], dataMask: [clear ? 1 : 0] };
}"""
NDVI_IMAGE_EVALSCRIPT = """//VERSION=3
function setup() { return { input: ["B04", "B08", "dataMask"], output: { bands: 4 } }; }
const ramp = [[-0.2, 0xa50026], [0.1, 0xd73027], [0.2, 0xfdae61], [0.35, 0xfee08b], [0.5, 0xa6d96a], [0.7, 0x1a9850], [0.9, 0x006837]];
const viz = new ColorRampVisualizer(ramp);
function evaluatePixel(s) { var v = (s.B08 - s.B04) / (s.B08 + s.B04 + 1e-6); return [...viz.process(v), s.dataMask]; }"""
TRUECOLOR_EVALSCRIPT = """//VERSION=3
function setup() { return { input: ["B02", "B03", "B04"], output: { bands: 3 } }; }
function evaluatePixel(s) { return [2.5 * s.B04, 2.5 * s.B03, 2.5 * s.B02]; }"""


def zone_geometry(zone) -> dict:
    """GeoJSON polygon of a field (circles as 48-gon), lon/lat order."""
    if zone.shape == "polygon":
        ring = [[p[1], p[0]] for p in zone.polygon] + [[zone.polygon[0][1], zone.polygon[0][0]]]
    else:
        lat, lon = zone.center
        dlat = zone.radius_m / 110574
        dlon = zone.radius_m / (111320 * math.cos(math.radians(lat)))
        ring = [[lon + dlon * math.cos(a), lat + dlat * math.sin(a)] for a in (2 * math.pi * i / 48 for i in range(48))]
        ring.append(ring[0])
    return {"type": "Polygon", "coordinates": [ring]}


SH_RES_DEG = 0.0001                 # grid of the Statistical API requests (about 10 m)


def field_share_of_bbox(geom: dict, res: float = SH_RES_DEG) -> float:
    """Share of the cells of the bounding-box grid whose centres lie inside the field polygon.

    The Statistical API counts every cell of the request's bounding box in ``sampleCount`` and the cells outside
    the polygon in ``noDataCount``, so for a round pivot about 22 % of the cells are "no data" even on a clear day.
    Dividing by this share measures the clear part against the field itself. Small grids are counted cell by cell
    (as the API sees them); large ones use the exact area ratio."""
    ring = geom["coordinates"][0]
    xs, ys = [q[0] for q in ring], [q[1] for q in ring]
    x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
    nx, ny = max(1, math.ceil((x1 - x0) / res)), max(1, math.ceil((y1 - y0) / res))
    if nx * ny <= 40000:
        inside = 0
        n = len(ring)
        for j in range(ny):
            py = y0 + (j + 0.5) * res
            for i in range(nx):
                px, hit = x0 + (i + 0.5) * res, False
                for k in range(n - 1):
                    (ax, ay), (bx, by) = ring[k], ring[k + 1]
                    if (ay > py) != (by > py) and px < ax + (py - ay) * (bx - ax) / (by - ay):
                        hit = not hit
                inside += hit
        if inside:
            return inside / (nx * ny)
    area = abs(sum(ring[k][0] * ring[k + 1][1] - ring[k + 1][0] * ring[k][1] for k in range(len(ring) - 1))) / 2
    box = max((x1 - x0) * (y1 - y0), 1e-12)
    return min(1.0, max(area / box, 1e-6))


def bbox_of(geom: dict) -> list[float]:
    xs = [p[0] for p in geom["coordinates"][0]]
    ys = [p[1] for p in geom["coordinates"][0]]
    return [min(xs), min(ys), max(xs), max(ys)]


# ======================================================================= pivots
def detect_pivots(image_bytes: bytes, bounds: tuple[float, float, float, float], min_radius_m: float = 100,
                  max_radius_m: float = 800) -> list[dict]:
    """Centre pivots in an RGB image covering ``bounds`` = (south, west, north, east)."""
    import numpy as np
    from PIL import Image
    from scipy import ndimage

    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    scale = min(1.0, 900 / max(img.size))
    if scale < 1:
        img = img.resize((int(img.width * scale), int(img.height * scale)))
    a = np.asarray(img, dtype=np.float32) / 255.0
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    total = r + g + b + 1e-6
    exg = 2 * g / total - r / total - b / total                 # excess green on chromatic coordinates
    hist, edges = np.histogram(exg, bins=128)
    p = hist / hist.sum()
    omega, mu = np.cumsum(p), np.cumsum(p * (edges[:-1] + edges[1:]) / 2)
    sigma_b = (mu[-1] * omega - mu) ** 2 / (omega * (1 - omega) + 1e-12)
    thr = max(edges[int(np.argmax(sigma_b))], 0.02)               # Otsu, but never below "barely green"
    mask = ndimage.binary_opening(exg > thr, iterations=2)
    mask = ndimage.binary_fill_holes(mask)
    south, west, north, east = bounds
    h, w = mask.shape
    m_per_px_x = (east - west) * 111320 * math.cos(math.radians((north + south) / 2)) / w
    m_per_px_y = (north - south) * 110574 / h
    m_per_px = (m_per_px_x + m_per_px_y) / 2
    rmin, rmax = min_radius_m / m_per_px, max_radius_m / m_per_px
    dist = ndimage.distance_transform_edt(mask)
    peaks = (dist == ndimage.maximum_filter(dist, size=max(3, int(rmin)))) & (dist >= rmin) & (dist <= rmax)
    cand = sorted(((float(dist[y, x]), y, x) for y, x in zip(*np.nonzero(peaks))), reverse=True)
    yy, xx = np.mgrid[0:h, 0:w]
    found: list[tuple[float, float, float, float]] = []
    for rad, y, x in cand:
        if any(math.hypot(x - fx, y - fy) < 0.8 * max(rad, fr) for fr, fy, fx, _ in found):
            continue
        rad_out = rad * 1.04                                       # EDT is measured to the first background pixel
        disc = (xx - x) ** 2 + (yy - y) ** 2 <= rad_out ** 2
        fill = float(mask[disc].mean()) if disc.any() else 0.0
        if fill < 0.85:
            continue
        found.append((rad_out, y, x, fill))
    out = []
    for rad, y, x, fill in found:
        lat = north - (y + 0.5) / h * (north - south)
        lon = west + (x + 0.5) / w * (east - west)
        out.append({"lat": round(lat, 6), "lon": round(lon, 6), "radius_m": round(rad * m_per_px, 1),
                    "area_ha": round(math.pi * (rad * m_per_px) ** 2 / 1e4, 1), "fill": round(fill, 3)})
    return sorted(out, key=lambda c: (-c["lat"], c["lon"]))


class SatelliteService:
    def __init__(self, settings, main, telemetry, farm, http=http_raw):
        self.settings = settings
        self.main = main
        self.telemetry = telemetry
        self.farm = farm
        self.http = http
        self._token: tuple[float, str] | None = None
        self.catalogue = Catalogue(settings, lambda *a, **k: self.http(*a, **k))
        from .eo_render import SatelliteViewer
        self.viewer = SatelliteViewer(settings, self, self.catalogue)
        self._job_lock = threading.Lock()
        self.job: dict = {"running": False}

    def init_schema(self) -> None:
        with self.main.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS sat_ndvi (company TEXT NOT NULL, zone_id TEXT NOT NULL, date TEXT NOT NULL,
                    mean REAL, min REAL, max REAL, clear_share REAL, source TEXT NOT NULL,
                    PRIMARY KEY (company, zone_id, date, source));
                CREATE TABLE IF NOT EXISTS sat_passes (id INTEGER PRIMARY KEY AUTOINCREMENT, satellite TEXT NOT NULL,
                    station TEXT, aos INTEGER NOT NULL, los INTEGER NOT NULL, max_elevation REAL,
                    UNIQUE (satellite, station, aos));
                CREATE TABLE IF NOT EXISTS sat_products (pass_id TEXT PRIMARY KEY, satellite TEXT NOT NULL,
                    received_at INTEGER NOT NULL, imported_at INTEGER NOT NULL, records INTEGER NOT NULL,
                    stored INTEGER NOT NULL, rejected INTEGER NOT NULL, companies TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS sat_open_scenes (company TEXT NOT NULL, scene_id TEXT NOT NULL,
                    date TEXT NOT NULL, cloud REAL, fields INTEGER NOT NULL, meta TEXT NOT NULL, read_at INTEGER NOT NULL,
                    PRIMARY KEY (company, scene_id));
            """)

    # ------------------------------------------------------- Sentinel Hub
    @property
    def sentinel_ready(self) -> bool:
        s = self.settings
        return bool(s.sentinel_client_id and s.sentinel_client_secret)

    def _sh_token(self) -> str:
        if self._token and time.time() < self._token[0]:
            return self._token[1]
        s = self.settings
        body = urllib.parse.urlencode({"grant_type": "client_credentials", "client_id": s.sentinel_client_id,
                                       "client_secret": s.sentinel_client_secret.get_secret_value()}).encode()
        status, text = self.http("POST", s.sentinel_token_url, {"Content-Type": "application/x-www-form-urlencoded"}, body)
        if status != 200:
            raise RuntimeError(f"Copernicus sign-in failed (HTTP {status})")
        data = json.loads(text)
        self._token = (time.time() + int(data.get("expires_in", 600)) - 60, data["access_token"])
        return self._token[1]

    def _sh(self, path: str, payload: dict, accept: str = "application/json") -> tuple[int, str]:
        headers = {"Authorization": f"Bearer {self._sh_token()}", "Content-Type": "application/json", "Accept": accept}
        return self.http("POST", self.settings.sentinel_base_url.rstrip("/") + path, headers, json.dumps(payload).encode())

    @property
    def ndvi_provider(self) -> str | None:
        """"sentinelhub", "open" or None, from WIOT_SATELLITE_PROVIDER and what is configured / installed."""
        choice = self.settings.satellite_provider
        if choice in ("auto", "sentinelhub") and self.sentinel_ready:
            return "sentinelhub"
        if choice == "open":
            try:
                import numpy  # noqa: F401
            except ImportError:
                return None
            return "open"
        return None

    def fetch_ndvi(self, company: str, days: int = 30, today: date | None = None) -> int:
        """NDVI per field and clear pass from the configured provider; returns the number of values stored."""
        provider = self.ndvi_provider
        if provider == "sentinelhub":
            return self._fetch_ndvi_sentinelhub(company, days, today)
        if provider == "open":
            return self._fetch_ndvi_open(company, days, today)
        return 0

    def _fetch_ndvi_sentinelhub(self, company: str, days: int = 30, today: date | None = None) -> int:
        """Statistical API: NDVI mean / min / max per field and clear acquisition; stored per pass date."""
        if not self.sentinel_ready:
            return 0
        layout = self.farm.store.get(company)
        if layout is None:
            return 0
        today = today or datetime.now(timezone.utc).date()
        stored = 0
        for zone in layout.zones:
            geom = zone_geometry(zone)
            share = field_share_of_bbox(geom)                             # cells of the box inside the field
            payload = {"input": {"bounds": {"geometry": geom, "properties": {"crs": "http://www.opengis.net/def/crs/EPSG/0/4326"}},
                                 "data": [{"type": "sentinel-2-l2a", "dataFilter": {"maxCloudCoverage": 60}}]},
                       "aggregation": {"timeRange": {"from": f"{today - timedelta(days=days)}T00:00:00Z", "to": f"{today}T23:59:59Z"},
                                       "aggregationInterval": {"of": "P1D"}, "evalscript": NDVI_EVALSCRIPT,
                                       "resx": SH_RES_DEG, "resy": SH_RES_DEG}}
            status, text = self._sh("/api/v1/statistics", payload)
            if status != 200:
                log.warning("Sentinel statistics for %s/%s failed: HTTP %s", company, zone.id, status)
                continue
            rows = []
            for item in json.loads(text).get("data", []):
                st = (((item.get("outputs") or {}).get("ndvi") or {}).get("bands") or {}).get("B0", {}).get("stats", {})
                if not st or st.get("sampleCount", 0) == 0 or st.get("mean") in (None, "NaN"):
                    continue
                samples = max(1, st.get("sampleCount", 1))                # every cell of the bounding box
                clear = min(1.0, (samples - st.get("noDataCount", 0)) / (samples * share))
                if clear < 0.5:
                    continue
                rows.append((company, zone.id, item["interval"]["from"][:10], float(st["mean"]), float(st["min"]),
                             float(st["max"]), round(clear, 3), "sentinel-2"))
            with self.main.connect() as db:
                db.executemany("INSERT OR REPLACE INTO sat_ndvi(company, zone_id, date, mean, min, max, clear_share, source) "
                               "VALUES(?,?,?,?,?,?,?,?)", rows)
            stored += len(rows)
        return stored

    def _fetch_ndvi_open(self, company: str, days: int = 30, today: date | None = None) -> int:
        """Open archive: read the farm's pixels of each new clear pass (at most satellite_open_max_scenes a run)."""
        layout = self.farm.store.get(company)
        bbox = farm_bbox(layout, zone_geometry)
        if bbox is None:
            return 0
        today = today or datetime.now(timezone.utc).date()
        zones = [(z.id, zone_geometry(z)["coordinates"][0]) for z in layout.zones]
        s2 = OpenSentinel2(self.settings, self.http)
        scenes = s2.best_per_day(s2.search(bbox, today - timedelta(days=days), today, self.settings.satellite_max_cloud),
                                 bbox)
        with self.main.connect() as db:
            done = {r[0] for r in db.execute("SELECT scene_id FROM sat_open_scenes WHERE company=?", (company,))}
        todo = [sc for sc in scenes if sc["id"] not in done][-self.settings.satellite_open_max_scenes:]
        stored = 0
        for sc in todo:
            try:
                stats = s2.field_stats(sc, zones)
            except Exception as exc:                                  # one bad pass must not stop the others
                log.warning("Open Sentinel-2 %s for %s failed: %s", sc["id"], company, exc)
                continue
            rows = [(company, st["zone_id"], sc["date"], st["mean"], st["min"], st["max"], st["clear_share"], OPEN_SOURCE)
                    for st in stats if st["mean"] is not None and st["clear_share"] >= 0.5]
            meta = {k: sc[k] for k in ("date", "datetime", "tile", "epsg", "offset", "platform", "hrefs", "cloud")}
            with self.main.connect() as db:
                db.executemany("INSERT OR REPLACE INTO sat_ndvi(company, zone_id, date, mean, min, max, clear_share, source) "
                               "VALUES(?,?,?,?,?,?,?,?)", rows)
                db.execute("INSERT OR REPLACE INTO sat_open_scenes(company, scene_id, date, cloud, fields, meta, read_at) "
                           "VALUES(?,?,?,?,?,?,?)", (company, sc["id"], sc["date"], sc["cloud"], len(rows),
                                                     json.dumps(meta), int(time.time())))
            stored += len(rows)
        return stored

    def start_refresh(self, company: str, days: int = 30) -> dict:
        """Run fetch_ndvi in the background (the open archive can take minutes on a slow link)."""
        with self._job_lock:
            if self.job.get("running"):
                return {"started": False, **self.job}
            self.job = {"running": True, "company": company, "since": int(time.time())}

        def work():
            try:
                n = self.fetch_ndvi(company, days)
                self.job.update(running=False, finished=int(time.time()), stored=n)
            except Exception as exc:
                log.exception("NDVI refresh for %s failed", company)
                self.job.update(running=False, finished=int(time.time()), error=str(exc)[:200])

        threading.Thread(target=work, name="ndvi-refresh", daemon=True).start()
        return {"started": True, **self.job}

    def open_scenes(self, company: str, limit: int = 60) -> list[dict]:
        with self.main.connect() as db:
            rows = db.execute("SELECT scene_id, date, cloud, fields, read_at FROM sat_open_scenes WHERE company=? "
                              "ORDER BY date DESC LIMIT ?", (company, limit)).fetchall()
        return [{"id": r[0], "date": r[1], "cloud": r[2], "fields": r[3], "read_at": r[4]} for r in rows]

    def ndvi_history(self, company: str, zone_id: str | None = None, days: int = 365) -> list[dict]:
        since = (datetime.now(timezone.utc).date() - timedelta(days=days)).isoformat()
        q, p = "SELECT zone_id, date, mean, min, max, clear_share, source FROM sat_ndvi WHERE company=? AND date>=?", [company, since]
        if zone_id:
            q += " AND zone_id=?"
            p.append(zone_id)
        with self.main.connect() as db:
            return [dict(r) for r in db.execute(q + " ORDER BY date", p)]

    def latest_ndvi(self, company: str) -> dict[str, dict]:
        with self.main.connect() as db:
            rows = db.execute("SELECT zone_id, date, mean FROM sat_ndvi n WHERE company=? AND date=(SELECT MAX(date) FROM "
                              "sat_ndvi m WHERE m.company=n.company AND m.zone_id=n.zone_id)", (company,)).fetchall()
        return {r[0]: {"date": r[1], "mean": r[2]} for r in rows}

    def image(self, company: str, zone_id: str, kind: str = "ndvi") -> bytes:
        """PNG of the field from the most recent clear acquisition (Process API or open archive, cached a day)."""
        provider = self.ndvi_provider
        if provider is None:
            raise LookupError("Sentinel-2 is not configured on this server")
        layout = self.farm.store.get(company)
        zone = next((z for z in (layout.zones if layout else []) if z.id == zone_id), None)
        if zone is None:
            raise LookupError("Unknown field")
        folder = Path(self.settings.data_dir) / "satellite" / company
        folder.mkdir(parents=True, exist_ok=True)
        cache = folder / f"{zone_id}_{kind}_{date.today().isoformat()}.png"
        if cache.exists():
            return cache.read_bytes()
        geom = zone_geometry(zone)
        if provider == "open":
            with self.main.connect() as db:
                row = db.execute("SELECT o.meta FROM sat_open_scenes o JOIN sat_ndvi n ON n.company=o.company AND "
                                 "n.date=o.date AND n.source=? AND n.zone_id=? WHERE o.company=? ORDER BY o.date DESC "
                                 "LIMIT 1", (OPEN_SOURCE, zone_id, company)).fetchone()
            if row is None:
                raise LookupError("No clear pass read yet for this field; press Update now")
            scene = json.loads(row[0])
            body = OpenSentinel2(self.settings, self.http).field_png(scene, geom["coordinates"][0], kind)
            cache.write_bytes(body)
            return body
        today = datetime.now(timezone.utc).date()
        payload = {"input": {"bounds": {"bbox": bbox_of(geom), "properties": {"crs": "http://www.opengis.net/def/crs/EPSG/0/4326"}},
                             "data": [{"type": "sentinel-2-l2a", "dataFilter": {"timeRange": {
                                 "from": f"{today - timedelta(days=30)}T00:00:00Z", "to": f"{today}T23:59:59Z"},
                                 "maxCloudCoverage": 30, "mosaickingOrder": "leastCC"}}]},
                   "output": {"width": 512, "height": 512, "responses": [{"identifier": "default", "format": {"type": "image/png"}}]},
                   "evalscript": NDVI_IMAGE_EVALSCRIPT if kind == "ndvi" else TRUECOLOR_EVALSCRIPT}
        status, body = self._sh("/api/v1/process", payload, accept="image/png")
        if status != 200:
            raise RuntimeError(f"Sentinel image failed (HTTP {status})")
        cache.write_bytes(body)
        return body

    def area_image(self, bounds: tuple[float, float, float, float]) -> bytes:
        """True-colour Sentinel-2 image of an area (south, west, north, east) for pivot detection."""
        if not self.sentinel_ready:
            raise LookupError("Sentinel-2 is not configured on this server; upload an image instead")
        south, west, north, east = bounds
        today = datetime.now(timezone.utc).date()
        payload = {"input": {"bounds": {"bbox": [west, south, east, north]},
                             "data": [{"type": "sentinel-2-l2a", "dataFilter": {"timeRange": {
                                 "from": f"{today - timedelta(days=60)}T00:00:00Z", "to": f"{today}T23:59:59Z"},
                                 "maxCloudCoverage": 20, "mosaickingOrder": "leastCC"}}]},
                   "output": {"width": 900, "height": 900, "responses": [{"identifier": "default", "format": {"type": "image/png"}}]},
                   "evalscript": TRUECOLOR_EVALSCRIPT}
        status, body = self._sh("/api/v1/process", payload, accept="image/png")
        if status != 200:
            raise RuntimeError(f"Sentinel image failed (HTTP {status})")
        return body

    def add_pivots(self, company: str, circles: list[dict], actor: str, crop: str = "") -> int:
        """Append reviewed pivot circles to the company's farm layout as new fields."""
        from .farm import FarmLayout, Zone
        layout = self.farm.store.get(company)
        if layout is None:
            raise LookupError("Create the farm (site) first on the Smart farm page")
        existing = {z.id for z in layout.zones}
        zones = list(layout.zones)
        n = 1
        for c in circles:
            while f"AUTO-{n:02d}" in existing:
                n += 1
            zid = f"AUTO-{n:02d}"
            existing.add(zid)
            zones.append(Zone(id=zid, name=f"Pivot {zid}", crop=crop, center=(float(c["lat"]), float(c["lon"])),
                              radius_m=float(c["radius_m"]), region=zones[0].region if zones else "Region_1"))
        self.farm.store.put(company, FarmLayout.model_validate({**layout.model_dump(), "zones": [z.model_dump() for z in zones]}), actor)
        return len(circles)

    # ------------------------------------------------------------ WIOT-SAT
    def import_passes(self, items: list[dict]) -> int:
        rows = []
        for i, p in enumerate(items, start=1):
            try:
                aos, los = int(p["aos"]), int(p["los"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"Pass {i}: aos and los must be epoch seconds") from exc
            if los <= aos or los - aos > 3600:
                raise ValueError(f"Pass {i}: LOS must follow AOS within an hour")
            rows.append((str(p.get("satellite") or "WIOT-SAT")[:40], str(p.get("station") or "")[:60], aos, los,
                         float(p["max_elevation"]) if p.get("max_elevation") is not None else None))
        with self.main.connect() as db:
            db.executemany("INSERT OR REPLACE INTO sat_passes(satellite, station, aos, los, max_elevation) VALUES(?,?,?,?,?)", rows)
        return len(rows)

    def passes(self, since: int | None = None, until: int | None = None) -> list[dict]:
        since = since if since is not None else int(time.time()) - 86400
        until = until if until is not None else int(time.time()) + 7 * 86400
        with self.main.connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM sat_passes WHERE los>=? AND aos<=? ORDER BY aos", (since, until))]

    def import_product(self, product: dict, allowed_companies, writer) -> dict:
        """Store the node readings of one satellite pass. ``writer`` is IngestService.store_satellite_record."""
        pass_id = str(product.get("pass_id") or "").strip()
        if not pass_id or len(pass_id) > 80:
            raise ValueError("pass_id is required")
        with self.main.connect() as db:
            if db.execute("SELECT 1 FROM sat_products WHERE pass_id=?", (pass_id,)).fetchone():
                raise ValueError("This pass was already imported")
        records = product.get("records") or []
        if not isinstance(records, list) or len(records) > 20000:
            raise ValueError("records must be a list of at most 20000 readings")
        stored = rejected = 0
        companies = set()
        for rec in records:
            try:
                if rec.get("company") not in allowed_companies:
                    raise PermissionError("company")
                writer(rec, pass_id)
                stored += 1
                companies.add(rec["company"])
            except Exception:
                rejected += 1
        with self.main.connect() as db:
            db.execute("INSERT INTO sat_products(pass_id, satellite, received_at, imported_at, records, stored, rejected, "
                       "companies) VALUES(?,?,?,?,?,?,?,?)",
                       (pass_id, str(product.get("satellite") or "WIOT-SAT")[:40], int(product.get("received_at") or time.time()),
                        int(time.time()), len(records), stored, rejected, json.dumps(sorted(companies))))
        return {"pass_id": pass_id, "records": len(records), "stored": stored, "rejected": rejected}

    def products(self, company: str | None, limit: int = 50) -> list[dict]:
        with self.main.connect() as db:
            rows = [dict(r) for r in db.execute("SELECT * FROM sat_products ORDER BY imported_at DESC LIMIT ?", (limit * 4,))]
        out = []
        for r in rows:
            r["companies"] = json.loads(r["companies"])
            if company is None or company in r["companies"]:
                out.append(r)
        return out[:limit]


def b64png(data: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(data).decode()
