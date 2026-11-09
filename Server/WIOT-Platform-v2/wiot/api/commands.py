"""Command submission, lifecycle timeline and pre-send delivery risk."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from ..security import Principal
from ..services.commands import CATALOG, CMD_IDS, CommandRequest
from ..services.runtime import Runtime
from .deps import authenticate, get_runtime, resolve_company, resolve_region

router = APIRouter(prefix="/commands", tags=["commands"])


class CommandIn(BaseModel):
    company: str | None = Field(default=None, max_length=80)
    region: str | None = Field(default=None, max_length=40)
    node_id: int = Field(ge=1, le=65535)
    cmd_type: str = Field(max_length=32)
    cmd_data: int | str | None = None
    delivery: str = Field("now", pattern="^(now|next_wake)$")
    broadcast: bool = False
    ttl_seconds: int = Field(86400, ge=60, le=604800)


class RiskIn(BaseModel):
    company: str | None = Field(default=None, max_length=80)
    region: str | None = Field(default=None, max_length=40)
    node_id: int = Field(ge=1, le=65535)
    cmd_type: str = Field(max_length=32)


@router.get("/catalog")
def catalog(_: Principal = Depends(authenticate)):
    return {"commands": [{**c, "cmd_id": CMD_IDS[c["type"]]} for c in CATALOG]}


@router.get("")
def list_commands(company: str | None = None, region: str | None = None, node_id: int | None = None,
                  limit: int = Query(50, ge=1, le=200), principal: Principal = Depends(authenticate),
                  runtime: Runtime = Depends(get_runtime)):
    tenant = resolve_company(principal, company, runtime)
    return {"company": tenant,
            "commands": runtime.commands.list(tenant, resolve_region(region), node_id, limit)}


@router.get("/{request_id}")
def get_command(request_id: int, node_id: int = Query(..., ge=0, le=65535), company: str | None = None,
                region: str | None = None, principal: Principal = Depends(authenticate),
                runtime: Runtime = Depends(get_runtime)):
    tenant = resolve_company(principal, company, runtime)
    item = runtime.commands.get(request_id, tenant, resolve_region(region), node_id)
    if item is None:
        raise HTTPException(404, "Command not found")
    return item


@router.post("", status_code=202)
def submit(body: CommandIn, request: Request, principal: Principal = Depends(authenticate),
           runtime: Runtime = Depends(get_runtime)):
    tenant = resolve_company(principal, body.company, runtime)
    if not principal.can_write(tenant):
        raise HTTPException(403, "Command privileges required for this company")
    req = CommandRequest(company=tenant, region=resolve_region(body.region), node_id=body.node_id,
                         cmd_type=body.cmd_type, cmd_data=body.cmd_data, delivery=body.delivery,
                         broadcast=body.broadcast, ttl_seconds=body.ttl_seconds)
    result = runtime.commands.submit(req, actor=principal.username)
    runtime.main.audit(principal.username, "command_submitted", company=tenant,
                       target=f"{req.region}/{'broadcast' if req.broadcast else req.node_id}",
                       ip=request.client.host if request.client else None,
                       details={"cmd_type": req.cmd_type, "delivery": req.delivery,
                                "request_id": result.get("request_id")})
    return result


@router.post("/risk")
def delivery_risk(body: RiskIn, principal: Principal = Depends(authenticate),
                  runtime: Runtime = Depends(get_runtime)):
    """Predict, before sending, whether the node will acknowledge this command."""
    tenant = resolve_company(principal, body.company, runtime)
    if body.cmd_type not in CMD_IDS:
        raise HTTPException(400, "Unknown command type")
    return runtime.analytics.predict_live(tenant, resolve_region(body.region), body.node_id, body.cmd_type)
