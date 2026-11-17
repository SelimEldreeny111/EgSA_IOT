"""Greenhouse layout editor (Track G, point 58): houses, zones, benches and attached sensors."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from ..security import Principal
from ..services.greenhouse import GreenhouseLayout, VersionConflict, layout_json, summary, warnings
from ..services.runtime import Runtime
from .deps import authenticate, get_runtime, resolve_company

router = APIRouter(prefix="/greenhouses", tags=["greenhouses"])
LAYOUT_PATH = "/api/v2/greenhouses/layout"     # allowed a larger body (app.py)


class LayoutBody(BaseModel):
    layout: GreenhouseLayout
    version: int = Field(ge=0)


@router.get("/layout")
def get_layout(company: str | None = None, principal: Principal = Depends(authenticate),
               runtime: Runtime = Depends(get_runtime)):
    tenant = resolve_company(principal, company, runtime)
    saved = runtime.greenhouses.store.get(tenant)
    layout = saved["layout"]
    return {"company": tenant, "layout": layout_json(layout), "version": saved["version"],
            "updated_at": saved["updated_at"], "updated_by": saved["updated_by"],
            "summary": summary(layout), "warnings": saved["warnings"],
            "map": runtime.farm.map_config(), "view": runtime.greenhouses.center(tenant, layout),
            "can_edit": principal.can_write(tenant)}


@router.put("/layout")
def put_layout(body: LayoutBody, request: Request, company: str | None = None,
               principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    tenant = resolve_company(principal, company, runtime)
    if not principal.can_write(tenant):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Administrator privileges for this company required")
    try:
        version = runtime.greenhouses.store.put(tenant, body.layout, body.version, principal.username)
    except VersionConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    s = summary(body.layout)
    # open editors of this company reload (or warn, when they have unsaved edits) instead of meeting a 409 later
    runtime.hub.publish("greenhouse_layout", {"version": version, "updated_by": principal.username}, company=tenant)
    runtime.main.audit(principal.username, "greenhouse_layout_saved", company=tenant,
                       ip=request.client.host if request.client else None,
                       details={"version": version, "houses": s["houses"], "zones": s["zones"], "benches": s["benches"]})
    return {"saved": True, "version": version, "summary": s, "warnings": warnings(body.layout)}


@router.get("/live")
def live(company: str | None = None, principal: Principal = Depends(authenticate),
         runtime: Runtime = Depends(get_runtime)):
    tenant = resolve_company(principal, company, runtime)
    return {"company": tenant, **runtime.greenhouses.live(tenant)}


@router.get("/attachables")
def attachables(company: str | None = None, principal: Principal = Depends(authenticate),
                runtime: Runtime = Depends(get_runtime)):
    tenant = resolve_company(principal, company, runtime)
    return {"company": tenant, **runtime.greenhouses.attachables(tenant)}
