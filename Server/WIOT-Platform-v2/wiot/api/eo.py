"""Earth observation (R2.7): Copernicus catalogue, EUMETSAT Data Store and the open Sentinel-2 archive."""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from ..security import Principal
from ..services.eo import CDSE_COLLECTIONS, EUMETSAT_SUGGESTED, days_ago, farm_bbox, utc_now
from ..services.runtime import Runtime
from ..services.satellite import zone_geometry
from .deps import authenticate, get_runtime, resolve_company

router = APIRouter(prefix="/eo", tags=["earth observation"])


def _upstream(fn, *args, **kwargs):
    """Call a catalogue; failures of the remote service become 502 with its message."""
    try:
        return fn(*args, **kwargs)
    except (RuntimeError, OSError) as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc) or type(exc).__name__) from exc


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


@router.get("/downloads")
def downloads(_: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    return {"downloads": runtime.satellite.catalogue.downloads()}
