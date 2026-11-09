"""Smart-agriculture endpoints: farm map, zones, weather/ET0, satellite readiness."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from ..security import Principal
from ..services.farm import FarmLayout
from ..services.runtime import Runtime
from .deps import authenticate, get_runtime, resolve_company, resolve_region

router = APIRouter(prefix="/farm", tags=["smart agriculture"])
public_router = APIRouter(tags=["smart agriculture"])


class ZonePatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=80)
    crop: str | None = Field(None, max_length=40)
    moisture_min: float | None = Field(None, ge=0, le=100)
    moisture_max: float | None = Field(None, ge=0, le=100)
    auto_irrigation: bool | None = None


def _require_writer(principal: Principal, company: str) -> None:
    if not principal.can_write(company):
        raise HTTPException(403, "Administrator privileges for this company required")


@router.get("/overview")
def overview(company: str | None = None, region: str | None = None,
             principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    tenant = resolve_company(principal, company, runtime)
    return runtime.farm.overview(tenant, resolve_region(region))


@router.get("/layout")
def get_layout(company: str | None = None, principal: Principal = Depends(authenticate),
               runtime: Runtime = Depends(get_runtime)):
    tenant = resolve_company(principal, company, runtime)
    layout = runtime.farm.store.get(tenant)
    return {"company": tenant, "layout": layout.model_dump() if layout else None, "map": runtime.farm.map_config()}


@router.put("/layout")
def put_layout(layout: FarmLayout, request: Request, company: str | None = None,
               principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    tenant = resolve_company(principal, company, runtime)
    _require_writer(principal, tenant)
    runtime.farm.store.put(tenant, layout, principal.username)
    runtime.main.audit(principal.username, "farm_layout_saved", company=tenant,
                       ip=request.client.host if request.client else None,
                       details={"zones": len(layout.zones), "devices": len(layout.devices)})
    return {"saved": True, "zones": len(layout.zones), "devices": len(layout.devices)}


@router.patch("/zones/{zone_id}")
def patch_zone(zone_id: str, body: ZonePatch, request: Request, company: str | None = None,
               principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    tenant = resolve_company(principal, company, runtime)
    _require_writer(principal, tenant)
    zone = runtime.farm.update_zone(tenant, zone_id, body.model_dump(exclude_none=True), principal.username)
    runtime.main.audit(principal.username, "zone_updated", company=tenant, target=zone_id,
                       ip=request.client.host if request.client else None, details=body.model_dump(exclude_none=True))
    return zone


@router.get("/zones/{zone_id}/history")
def zone_history(zone_id: str, company: str | None = None, hours: float = Query(24, gt=0, le=24 * 30),
                 principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    tenant = resolve_company(principal, company, runtime)
    return runtime.farm.zone_history(tenant, zone_id, hours)


@router.get("/weather")
def weather(company: str | None = None, principal: Principal = Depends(authenticate),
            runtime: Runtime = Depends(get_runtime)):
    tenant = resolve_company(principal, company, runtime)
    layout = runtime.farm.store.get(tenant)
    if layout is None:
        raise HTTPException(404, "No farm layout configured for this company")
    return runtime.farm.weather.get(*layout.site.center)


@router.get("/connectivity")
def connectivity(company: str | None = None, region: str | None = None,
                 budget: int | None = Query(None, ge=1, le=10000),
                 principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    tenant = resolve_company(principal, company, runtime)
    return runtime.farm.connectivity(tenant, resolve_region(region), runtime.ingest.frame_stats,
                                     budget or runtime.settings.satellite_msgs_per_day)


@public_router.get("/api/v2/public/map")
def public_map(request: Request):
    """Basemap + backdrop for the sign-in page (no tenant data)."""
    s = request.app.state.runtime.settings
    try:
        lat, lon, zoom = (float(v) for v in s.map_backdrop.split(","))
    except ValueError:
        lat, lon, zoom = 22.2545, 28.7215, 15
    return {"tiles": s.map_tile_url, "attribution": s.map_attribution, "center": [lat, lon], "zoom": int(zoom)}
