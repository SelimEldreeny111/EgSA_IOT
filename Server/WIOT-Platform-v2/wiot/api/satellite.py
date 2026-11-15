"""Satellite data: Sentinel-2 NDVI, pivot detection, WIOT-SAT products and passes (R2.5)."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field

from ..security import Principal
from ..services.runtime import Runtime
from ..services.satellite import detect_pivots
from .deps import authenticate, get_runtime, resolve_company

router = APIRouter(prefix="/satellite", tags=["satellite"])


def _ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _writer(principal: Principal, company: str) -> None:
    if not principal.can_write(company):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Administrator privileges for this company required")


@router.get("/status")
def sat_status(_: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    try:
        import numpy  # noqa: F401
        import PIL  # noqa: F401
        import scipy  # noqa: F401
        pivots = True
    except ImportError:
        pivots = False
    sat = runtime.satellite
    provider = sat.ndvi_provider
    return {"sentinel": provider is not None, "provider": provider, "sentinelhub": sat.sentinel_ready,
            "pivot_detection": pivots, "job": sat.job}


@router.get("/ndvi")
def ndvi(company: str | None = None, zone_id: str | None = None, days: int = Query(365, ge=7, le=1500),
         principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    tenant = resolve_company(principal, company, runtime)
    return {"company": tenant, "sentinel": runtime.satellite.ndvi_provider is not None,
            "history": runtime.satellite.ndvi_history(tenant, zone_id, days), "latest": runtime.satellite.latest_ndvi(tenant)}


@router.post("/ndvi/refresh")
def ndvi_refresh(company: str | None = None, days: int = Query(30, ge=1, le=400), principal: Principal = Depends(authenticate),
                 runtime: Runtime = Depends(get_runtime)):
    tenant = resolve_company(principal, company, runtime)
    _writer(principal, tenant)
    provider = runtime.satellite.ndvi_provider
    if provider is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Sentinel-2 is not configured: set WIOT_SATELLITE_PROVIDER=open "
                            "(open archive, no account) or the Copernicus OAuth client (WIOT_SENTINEL_CLIENT_ID / _SECRET)")
    if provider == "open":                     # reads image files: minutes on a slow link, so in the background
        return runtime.satellite.start_refresh(tenant, days)
    return {"stored": runtime.satellite.fetch_ndvi(tenant, days)}


@router.get("/image/{zone_id}.png")
def field_image(zone_id: str, company: str | None = None, kind: str = Query("ndvi", pattern="^(ndvi|truecolor)$"),
                principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    tenant = resolve_company(principal, company, runtime)
    data = runtime.satellite.image(tenant, zone_id, kind)
    return Response(data, media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})


@router.post("/pivots/detect")
async def pivots_detect(request: Request, south: float = Query(..., ge=-90, le=90), west: float = Query(..., ge=-180, le=180),
                        north: float = Query(..., ge=-90, le=90), east: float = Query(..., ge=-180, le=180),
                        min_radius_m: float = Query(100, ge=20, le=2000), max_radius_m: float = Query(800, ge=50, le=3000),
                        source: str = Query("upload", pattern="^(upload|sentinel)$"),
                        principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    """Find centre pivots in an image (request body: PNG / JPEG covering the bounds) or in the Sentinel-2 image."""
    if not principal.can_command:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Administrator privileges required")
    if not (south < north and west < east) or north - south > 0.5 or east - west > 0.5:
        raise ValueError("Bounds must be south < north, west < east and at most 0.5 degrees wide")
    image = await request.body() if source == "upload" else runtime.satellite.area_image((south, west, north, east))
    if not image:
        raise ValueError("Send the image as the request body")
    try:
        circles = detect_pivots(image, (south, west, north, east), min_radius_m, max_radius_m)
    except ImportError as exc:
        raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "Pivot detection needs the analytics extra (numpy, scipy, Pillow)") from exc
    except OSError as exc:
        raise ValueError(f"Not a readable image: {exc}") from exc
    return {"circles": circles, "count": len(circles)}


class PivotsIn(BaseModel):
    circles: list[dict] = Field(min_length=1, max_length=200)
    crop: str = Field("", max_length=40)


@router.post("/pivots/add")
def pivots_add(body: PivotsIn, request: Request, company: str | None = None, principal: Principal = Depends(authenticate),
               runtime: Runtime = Depends(get_runtime)):
    tenant = resolve_company(principal, company, runtime)
    _writer(principal, tenant)
    n = runtime.satellite.add_pivots(tenant, body.circles, principal.username, body.crop)
    runtime.main.audit(principal.username, "pivots_added", company=tenant, ip=_ip(request), details={"count": n})
    return {"added": n}


# ------------------------------------------------------------- WIOT-SAT
@router.get("/passes")
def passes(_: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    return {"passes": runtime.satellite.passes()}


@router.post("/passes")
def import_passes(body: list[dict], request: Request, principal: Principal = Depends(authenticate),
                  runtime: Runtime = Depends(get_runtime)):
    if not principal.is_supervisor:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Supervisor privileges required")
    n = runtime.satellite.import_passes(body)
    runtime.main.audit(principal.username, "sat_passes_imported", ip=_ip(request), details={"passes": n})
    return {"imported": n}


@router.get("/products")
def products(company: str | None = None, principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    tenant = None if principal.global_read and not company else resolve_company(principal, company, runtime)
    return {"products": runtime.satellite.products(tenant)}


@router.post("/products")
async def import_product(request: Request, principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    """One WIOT-SAT ground-tool product (JSON): node readings received in a satellite pass."""
    if not principal.can_command:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Write access required")
    try:
        product = json.loads(await request.body())
    except json.JSONDecodeError as exc:
        raise ValueError("Body must be JSON") from exc
    allowed = set(runtime.main.company_names()) if principal.is_supervisor else {principal.company}
    out = runtime.satellite.import_product(product, allowed, runtime.store_satellite_record)
    runtime.main.audit(principal.username, "sat_product_imported", ip=_ip(request), details=out)
    return out
