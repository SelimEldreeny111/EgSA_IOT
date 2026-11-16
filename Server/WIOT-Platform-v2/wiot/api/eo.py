"""Earth observation (R2.7): Copernicus catalogue, EUMETSAT Data Store and the open Sentinel-2 archive."""
from __future__ import annotations

import http.client
import json
import logging
import ssl
import threading
import time
import urllib.error
from collections import deque
from contextlib import contextmanager
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field

from ..security import Principal
from ..services.eo import CDSE_COLLECTIONS, EUMETSAT_SUGGESTED, OPEN_SOURCE, days_ago, farm_bbox, utc_now
from ..services.eo_layers import public_catalogue
from ..services.eo_render import AVAIL_DAYS, Busy, QuotaExceeded, browser_url
from ..services.runtime import Runtime
from ..services.satellite import zone_geometry
from .deps import authenticate, get_runtime, resolve_company

router = APIRouter(prefix="/eo", tags=["earth observation"])
log = logging.getLogger(__name__)
NETWORK_ERRORS = (urllib.error.URLError, TimeoutError, ConnectionError, http.client.HTTPException, ssl.SSLError)


def _upstream(fn, *args, **kwargs):
    """Call a remote service. Its failures become 502 with its message; local storage errors become 502 without
    details (no server paths); a busy viewer becomes 503 with Retry-After; a used-up allowance becomes 429."""
    try:
        return fn(*args, **kwargs)
    except Busy as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc), headers={"Retry-After": "2"}) from exc
    except QuotaExceeded as exc:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc) or type(exc).__name__) from exc
    except NETWORK_ERRORS as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY,
                            f"The remote service could not be reached ({str(exc)[:160] or type(exc).__name__})") from exc
    except OSError as exc:                                   # disk full, permissions: log it, tell no paths
        log.warning("Earth observation request failed on this server: %r", exc)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Storage error on the server while handling the data") from exc


def _bbox(runtime: Runtime, company: str) -> list[float]:
    bbox = farm_bbox(runtime.farm.store.get(company), zone_geometry)
    if bbox is None:
        raise LookupError("This company has no farm fields yet (Smart farm page)")
    return bbox


@router.get("/status")
def eo_status(_: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    sat = runtime.satellite
    return {"ndvi_provider": sat.ndvi_provider, "provider_setting": runtime.settings.satellite_provider,
            "sentinelhub": sat.sentinel_ready, "eumetsat_download": sat.catalogue.eumetsat_ready,
            "collections": CDSE_COLLECTIONS, "eumetsat_suggested": [{"id": i, "title": t} for i, t in EUMETSAT_SUGGESTED],
            "job": sat.job}


@router.get("/scenes")
def scenes(company: str | None = None, collection: str = Query("sentinel-2-l2a", max_length=40),
           days: int = Query(45, ge=1, le=400), max_cloud: float | None = Query(None, ge=0, le=100),
           limit: int = Query(40, ge=1, le=100), principal: Principal = Depends(authenticate),
           runtime: Runtime = Depends(get_runtime)):
    """Copernicus Data Space products over the farm (public STAC catalogue), newest first."""
    tenant = resolve_company(principal, company, runtime)
    bbox = _bbox(runtime, tenant)
    items = _upstream(runtime.satellite.catalogue.cdse_search, collection, bbox, days_ago(days), utc_now().date(),
                      limit, max_cloud)
    return {"company": tenant, "collection": collection, "bbox": bbox, "scenes": items,
            "read": runtime.satellite.open_scenes(tenant)}


@router.get("/eumetsat/collections")
def eum_collections(q: str = Query("", max_length=60), _: Principal = Depends(authenticate),
                    runtime: Runtime = Depends(get_runtime)):
    rows = _upstream(runtime.satellite.catalogue.eumetsat_collections, q)
    return {"collections": rows[:200], "total": len(rows)}


@router.get("/eumetsat/products")
def eum_products(collection: str = Query(..., max_length=48), company: str | None = None,
                 hours: int = Query(24, ge=1, le=24 * 60), limit: int = Query(20, ge=1, le=100),
                 principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    """Products of a Data Store collection over the farm in the last ``hours`` (search is public)."""
    tenant = resolve_company(principal, company, runtime)
    farm = runtime.farm.store.get(tenant)
    bbox = farm_bbox(farm, zone_geometry)
    end = utc_now()
    out = _upstream(runtime.satellite.catalogue.eumetsat_search, collection, bbox, end - timedelta(hours=hours), end, limit)
    return {"collection": collection, "download": runtime.satellite.catalogue.eumetsat_ready, **out}


class DownloadIn(BaseModel):
    collection: str = Field(max_length=48)
    product: str = Field(max_length=200)


@router.post("/eumetsat/download")
def eum_download(body: DownloadIn, request: Request, principal: Principal = Depends(authenticate),
                 runtime: Runtime = Depends(get_runtime)):
    """Download one product into data/eo/eumetsat (EUMETSAT API key on the server; administrators)."""
    if not principal.can_command:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Administrator privileges required")
    cat = runtime.satellite.catalogue
    if not cat.eumetsat_ready:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "EUMETSAT downloads need WIOT_EUMETSAT_KEY and WIOT_EUMETSAT_SECRET (api.eumetsat.int/api-key)")
    out = _upstream(cat.eumetsat_download, body.collection, body.product)
    runtime.main.audit(principal.username, "eumetsat_download", ip=request.client.host if request.client else "unknown",
                       details={"collection": body.collection, "product": body.product, "bytes": out["bytes"]})
    return out


# ------------------------------------------------------------------ satellite viewer
RENDER_LIMIT, RENDER_WINDOW = 150, 600          # images per user per 10 minutes
AVAIL_LIMIT = 30                                 # availability look-ups per user per 10 minutes
INFLIGHT_PER_USER = 2                            # images of one user being drawn at the same time
_renders: dict[str, deque] = {}
_inflight: dict[str, int] = {}
_renders_lock = threading.Lock()


def _quota(bucket: str, limit: int, what: str) -> None:
    now = time.monotonic()
    with _renders_lock:
        q = _renders.setdefault(bucket, deque())
        while q and now - q[0] > RENDER_WINDOW:
            q.popleft()
        if len(q) >= limit:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, f"Too many {what} in 10 minutes; wait a moment")
        q.append(now)


def _render_quota(user: str) -> None:
    _quota(user, RENDER_LIMIT, "satellite images")


def _refund(bucket: str) -> None:
    """A request the server turned away as busy does not count against the user's images."""
    with _renders_lock:
        q = _renders.get(bucket)
        if q:
            q.pop()


def _render_for(user: str, fn, *args):
    with _drawing(user):
        _render_quota(user)
        try:
            return _upstream(fn, *args)
        except HTTPException as exc:
            if exc.status_code == status.HTTP_503_SERVICE_UNAVAILABLE:
                _refund(user)
            raise


@contextmanager
def _drawing(user: str):
    """At most INFLIGHT_PER_USER images of one user at a time, so one account cannot occupy the server."""
    with _renders_lock:
        if _inflight.get(user, 0) >= INFLIGHT_PER_USER:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                                "Your previous images are still being drawn; this one follows in a moment",
                                headers={"Retry-After": "2"})
        _inflight[user] = _inflight.get(user, 0) + 1
    try:
        yield
    finally:
        with _renders_lock:
            _inflight[user] -= 1
            if not _inflight[user]:
                del _inflight[user]


@router.get("/layers")
def layers(company: str | None = None, principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    """Missions and layers of the satellite viewer, which renderer draws them, and the farm's bounds."""
    tenant = resolve_company(principal, company, runtime)
    viewer = runtime.satellite.viewer
    sh = viewer.sh_enabled
    farm = runtime.farm.store.get(tenant)
    fields = [{"id": z.id, "name": z.name, "geometry": zone_geometry(z)} for z in (farm.zones if farm else [])]
    return {"company": tenant, "bbox": farm_bbox(farm, zone_geometry), "fields": fields, "map": runtime.farm.map_config(),
            "sentinelhub": sh, "open": viewer.open_available, "own_evalscript": sh and principal.is_supervisor,
            **public_catalogue(viewer.open_available, sh)}


class RenderIn(BaseModel):
    mission: str = Field("S2L2A", max_length=12)
    layer: str = Field("CUSTOM", max_length=24)
    west: float = Field(ge=-180, le=180)
    south: float = Field(ge=-85, le=85)
    east: float = Field(ge=-180, le=180)
    north: float = Field(ge=-85, le=85)
    width: int = Field(1024, ge=16, le=1600)
    height: int = Field(768, ge=16, le=1600)
    date: str | None = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    cloud: float = Field(30, ge=0, le=100)
    evalscript: str | None = Field(None, max_length=12000)


def _png(data: bytes, meta: dict) -> Response:
    headers = {"Cache-Control": "private, max-age=3600", "X-Imagery": json.dumps({k: meta.get(k) for k in (
        "provider", "mission", "layer", "from", "to", "mosaic", "scene", "cloud", "cached")})}
    return Response(data, media_type="image/png", headers=headers)


@router.get("/render.png")
def render(mission: str = Query("S2L2A", max_length=12), layer: str = Query("TRUE_COLOR", max_length=24),
           west: float = Query(..., ge=-180, le=180), south: float = Query(..., ge=-85, le=85),
           east: float = Query(..., ge=-180, le=180), north: float = Query(..., ge=-85, le=85),
           width: int = Query(1024, ge=16, le=1600), height: int = Query(768, ge=16, le=1600),
           date: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"), cloud: float = Query(30, ge=0, le=100),
           mode: str | None = Query(None, pattern="^(composite|index)$"), bands: str | None = Query(None, max_length=20),
           principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    """One picture of a layer for the current map view (PNG with transparency outside the data)."""
    custom = {"mode": mode, "bands": [b.strip().upper() for b in (bands or "").split(",") if b.strip()]} if mode else None
    data, meta = _render_for(principal.username, runtime.satellite.viewer.render, mission, layer,
                             (west, south, east, north), width, height, date, cloud, custom, None, principal.company)
    return _png(data, meta)


@router.post("/render.png")
def render_script(body: RenderIn, principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    """Custom layer with your own Sentinel Hub evalscript (the supervisor only: it runs at Sentinel Hub on the
    Copernicus account that every company shares, and its cost cannot be estimated beforehand)."""
    if not principal.is_supervisor:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the supervisor can run an own evalscript (shared Copernicus account)")
    if not body.evalscript or "evaluatePixel" not in body.evalscript:
        raise ValueError("The evalscript needs a setup() and an evaluatePixel() function")
    data, meta = _render_for(principal.username, runtime.satellite.viewer.render, body.mission, "CUSTOM",
                             (body.west, body.south, body.east, body.north), body.width, body.height, body.date,
                             body.cloud, None, body.evalscript, principal.company)
    return _png(data, meta)


@router.get("/availability")
def availability(company: str | None = None, days: int = Query(90), principal: Principal = Depends(authenticate),
                 runtime: Runtime = Depends(get_runtime)):
    """Every satellite pass and product over the farm in the last ``days`` (30, 90, 180 or 365), plus what this
    server holds."""
    if days not in AVAIL_DAYS:
        raise ValueError(f"days must be one of {', '.join(map(str, AVAIL_DAYS))}")
    tenant = resolve_company(principal, company, runtime)
    bbox = _bbox(runtime, tenant)
    _quota(f"availability:{principal.username}", AVAIL_LIMIT, "look-ups of the satellite data")
    with runtime.main.connect() as db:
        ndvi = db.execute("SELECT date, source, COUNT(*) FROM sat_ndvi WHERE company=? AND date>=? GROUP BY date, source "
                          "ORDER BY date DESC", (tenant, days_ago(days).isoformat())).fetchall()
    server = {"ndvi": [{"date": r[0], "source": "Copernicus Sentinel Hub" if r[1] == "sentinel-2" else
                        "open archive" if r[1] == OPEN_SOURCE else r[1], "fields": r[2]} for r in ndvi],
              "wiot_sat": runtime.satellite.products(tenant, 200)}
    out = _upstream(runtime.satellite.viewer.availability, bbox, days, {"server": server})
    lat, lon = (bbox[1] + bbox[3]) / 2, (bbox[0] + bbox[2]) / 2
    out["browser"] = {m: browser_url(m, lat, lon, 13, None) for m in ("S2L2A", "S1GRD", "S3OLCI", "S3SLSTR")}
    return out


@router.get("/downloads")
def downloads(_: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    return {"downloads": runtime.satellite.catalogue.downloads()}
