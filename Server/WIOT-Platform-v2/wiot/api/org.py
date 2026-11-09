"""Organization API: companies, regions, nodes, gateways, API tokens, webhooks, world view.

Permissions
* create / archive a company ............ supervisor
* edit a company profile ................ supervisor, or that company's admin
* regions, nodes, gateways, tokens, hooks  supervisor, or that company's admin (``can_write``)
* read .................................. anyone who may read the company
API tokens can never manage tokens or webhooks (no privilege escalation from a leaked token).
"""
from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ..protocol.topics import region_id
from ..storage.org_store import sensors_from_mask
from ..security import Principal
from ..services.runtime import Runtime
from .deps import authenticate, get_runtime, require_supervisor, resolve_company

router = APIRouter(prefix="/org", tags=["organization"])


def _ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _writable(principal: Principal, company: str | None, runtime: Runtime) -> str:
    tenant = resolve_company(principal, company, runtime)
    if not principal.can_write(tenant):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Administrator privileges for this company required")
    return tenant


def _human_only(principal: Principal) -> None:
    if principal.token:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "API tokens cannot manage tokens or webhooks")


def _live(runtime: Runtime, company: str) -> tuple[list[str], dict]:
    """Regions with data or registration, and live state per (region, node)."""
    regions = sorted(set(runtime.telemetry.regions(company)) | set(runtime.org.region_ids(company)))
    live = {}
    for region in regions:
        for n in runtime.telemetry.fleet(company, region):
            live[(region, n["node_id"])] = {"link_state": n.get("link_state"), "last_seen": n.get("timestamp"),
                                            "battery_v": n.get("battery_voltage"), "uplinks_24h": n.get("uplinks_24h", 0),
                                            "first_seen": n.get("first_seen"),
                                            "sensors_detected": sensors_from_mask(n.get("sensor_mask"))}
    return regions, live


# ================================================================ companies
class CompanyBody(BaseModel):
    name: str | None = Field(None, max_length=80)
    display_name: str | None = Field(None, max_length=120)
    country: str | None = Field(None, max_length=2)
    timezone: str | None = Field(None, max_length=64)
    units: str | None = Field(None, pattern="^(metric|imperial)$")
    language: str | None = Field(None, pattern="^(en|ar)$")
    lat: float | None = None
    lon: float | None = None
    notes: str | None = Field(None, max_length=500)
    active: bool | None = None
    strict_nodes: bool | None = None


@router.get("/companies")
def list_companies(principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    rows = runtime.org.list_companies(include_archived=principal.is_supervisor)
    if not principal.global_read:
        rows = [r for r in rows if r["name"] == principal.company]
    return {"companies": rows}


@router.post("/companies", status_code=201)
def create_company(body: CompanyBody, request: Request, principal: Principal = Depends(require_supervisor),
                   runtime: Runtime = Depends(get_runtime)):
    if not body.name:
        raise ValueError("Company name is required")
    profile = body.model_dump(exclude_none=True, exclude={"name", "active"})
    row = runtime.org.create_company(body.name.strip(), profile)
    runtime.telemetry.ensure(row["name"])
    runtime.main.audit(principal.username, "company_created", company=row["name"], ip=_ip(request), details=profile)
    runtime.logs.emit(f"[ORG] Company {row['name']} created by {principal.username}")
    return row


@router.patch("/companies/{name}")
def update_company(name: str, body: CompanyBody, request: Request, principal: Principal = Depends(authenticate),
                   runtime: Runtime = Depends(get_runtime)):
    changes = body.model_dump(exclude_unset=True, exclude={"name"})
    if "active" in changes and not principal.is_supervisor:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the supervisor can archive or restore a company")
    if not (principal.is_supervisor or (principal.can_write(name) and runtime.org.get_company(name) is not None)):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Administrator privileges for this company required")
    row = runtime.org.update_company(name, changes)
    if changes.get("active") is True:
        runtime.telemetry.ensure(name)
    runtime.webhooks.refresh()
    action = {True: "company_restored", False: "company_archived"}.get(changes.get("active"), "company_updated")
    runtime.main.audit(principal.username, action, company=name, ip=_ip(request), details=changes)
    return row


# ================================================================== regions
class RegionBody(BaseModel):
    region: str | None = Field(None, max_length=40)
    display_name: str | None = Field(None, max_length=80)
    country: str | None = Field(None, max_length=2)
    timezone: str | None = Field(None, max_length=64)
    lat: float | None = None
    lon: float | None = None
    notes: str | None = Field(None, max_length=500)


@router.get("/regions")
def list_regions(company: str | None = None, principal: Principal = Depends(authenticate),
                 runtime: Runtime = Depends(get_runtime)):
    tenant = resolve_company(principal, company, runtime)
    registered = runtime.org.list_regions(tenant)
    regions, live = _live(runtime, tenant)
    for r in registered:
        nodes = [v for (reg, _), v in live.items() if reg == r["region"]]
        r.update(seen_nodes=len(nodes), online=sum(v["link_state"] == "online" for v in nodes))
    known = {r["region"] for r in registered}
    discovered = []
    for reg in regions:
        if reg in known:
            continue
        nodes = [v for (rr, _), v in live.items() if rr == reg]
        if nodes:
            discovered.append({"region": reg, "seen_nodes": len(nodes),
                               "online": sum(v["link_state"] == "online" for v in nodes)})
    return {"company": tenant, "regions": registered, "discovered": discovered}


@router.post("/regions", status_code=201)
def create_region(body: RegionBody, request: Request, company: str | None = None,
                  principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    tenant = _writable(principal, company, runtime)
    row = runtime.org.upsert_region(tenant, body.region or "", body.model_dump(), create=True)
    runtime.main.audit(principal.username, "region_created", company=tenant, target=row["region"], ip=_ip(request))
    return row


@router.patch("/regions/{region}")
def update_region(region: str, body: RegionBody, request: Request, company: str | None = None,
                  principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    tenant = _writable(principal, company, runtime)
    row = runtime.org.upsert_region(tenant, region, body.model_dump(), create=False)
    runtime.main.audit(principal.username, "region_updated", company=tenant, target=region, ip=_ip(request))
    return row


@router.delete("/regions/{region}")
def delete_region(region: str, request: Request, company: str | None = None,
                  principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    tenant = _writable(principal, company, runtime)
    runtime.org.delete_region(tenant, region_id(region))
    runtime.main.audit(principal.username, "region_deleted", company=tenant, target=region, ip=_ip(request))
    return {"deleted": region}


# ==================================================================== nodes
class NodeBody(BaseModel):
    region: str | None = Field(None, max_length=40)
    node_id: int | None = Field(None, ge=1, le=65535)
    name: str | None = Field(None, max_length=80)
    kind: str | None = Field(None, max_length=20)  # legacy; use node_type
    node_type: str | None = Field(None, pattern="^(monitoring|control)$")
    sensors: list[str] | None = None
    lat: float | None = None
    lon: float | None = None
    gateway: str | None = Field(None, max_length=32)
    install_date: str | None = Field(None, max_length=10)
    report_interval_s: int | None = None
    notes: str | None = Field(None, max_length=500)
    new_region: str | None = Field(None, max_length=40)


class CsvBody(BaseModel):
    csv: str = Field(max_length=2_000_000)


@router.get("/nodes")
def list_nodes(company: str | None = None, principal: Principal = Depends(authenticate),
               runtime: Runtime = Depends(get_runtime)):
    tenant = resolve_company(principal, company, runtime)
    _, live = _live(runtime, tenant)
    registered = runtime.org.list_nodes(tenant)
    keys = set()
    for n in registered:
        keys.add((n["region"], n["node_id"]))
        n.update(live.get((n["region"], n["node_id"])) or {"link_state": "pending", "last_seen": None})
    discovered = [{"region": reg, "node_id": nid, **v} for (reg, nid), v in sorted(live.items()) if (reg, nid) not in keys]
    profile = runtime.org.get_company(tenant) or {}
    return {"company": tenant, "strict_nodes": profile.get("strict_nodes", False), "nodes": registered,
            "discovered": discovered}


@router.post("/nodes", status_code=201)
def create_node(body: NodeBody, request: Request, company: str | None = None,
                principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    tenant = _writable(principal, company, runtime)
    row, _ = runtime.org.upsert_node(tenant, body.model_dump(), create=True)
    runtime.main.audit(principal.username, "node_registered", company=tenant,
                       target=f"{row['region']}/{row['node_id']}", ip=_ip(request))
    return row


@router.patch("/nodes/{region}/{node_id}")
def update_node(region: str, node_id: int, body: NodeBody, request: Request, company: str | None = None,
                principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    tenant = _writable(principal, company, runtime)
    data = body.model_dump()
    data.update(region=region_id(region), node_id=node_id)
    row, _ = runtime.org.upsert_node(tenant, data, create=False)
    if body.new_region and body.new_region != region:
        runtime.org.move_node(tenant, region, node_id, body.new_region)
        row = {**row, "region": body.new_region}
    runtime.main.audit(principal.username, "node_updated", company=tenant, target=f"{region}/{node_id}",
                       ip=_ip(request), details={"moved_to": body.new_region} if body.new_region else None)
    return row


@router.delete("/nodes/{region}/{node_id}")
def delete_node(region: str, node_id: int, request: Request, company: str | None = None,
                principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    tenant = _writable(principal, company, runtime)
    runtime.org.delete_node(tenant, region_id(region), node_id)
    runtime.main.audit(principal.username, "node_unregistered", company=tenant, target=f"{region}/{node_id}",
                       ip=_ip(request))
    return {"deleted": f"{region}/{node_id}"}


@router.post("/nodes/import")
def import_nodes(body: CsvBody, request: Request, company: str | None = None,
                 principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    tenant = _writable(principal, company, runtime)
    result = runtime.org.import_nodes_csv(tenant, body.csv)
    runtime.main.audit(principal.username, "nodes_imported", company=tenant, ip=_ip(request),
                       details={"created": result["created"], "updated": result["updated"], "errors": len(result["errors"])})
    return result


@router.get("/nodes/export.csv")
def export_nodes(company: str | None = None, principal: Principal = Depends(authenticate),
                 runtime: Runtime = Depends(get_runtime)):
    tenant = resolve_company(principal, company, runtime)
    return Response(runtime.org.export_nodes_csv(tenant), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{tenant}_nodes.csv"'})


# ================================================================= gateways
class GatewayBody(BaseModel):
    gw_id: str | None = Field(None, max_length=32)
    name: str | None = Field(None, max_length=80)
    region: str | None = Field(None, max_length=40)
    lat: float | None = None
    lon: float | None = None
    backhaul: list[str] | None = None
    primary: str | None = Field(None, max_length=12)
    notes: str | None = Field(None, max_length=500)


@router.get("/gateways")
def list_gateways(company: str | None = None, principal: Principal = Depends(authenticate),
                  runtime: Runtime = Depends(get_runtime)):
    tenant = resolve_company(principal, company, runtime)
    return {"company": tenant, "gateways": runtime.org.list_gateways(tenant)}


@router.post("/gateways", status_code=201)
def create_gateway(body: GatewayBody, request: Request, company: str | None = None,
                   principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    tenant = _writable(principal, company, runtime)
    row = runtime.org.upsert_gateway(tenant, body.model_dump(), create=True)
    runtime.main.audit(principal.username, "gateway_created", company=tenant, target=row["gw_id"], ip=_ip(request))
    return row


@router.patch("/gateways/{gw_id}")
def update_gateway(gw_id: str, body: GatewayBody, request: Request, company: str | None = None,
                   principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    tenant = _writable(principal, company, runtime)
    row = runtime.org.upsert_gateway(tenant, {**body.model_dump(), "gw_id": gw_id}, create=False)
    runtime.main.audit(principal.username, "gateway_updated", company=tenant, target=gw_id, ip=_ip(request))
    return row


@router.delete("/gateways/{gw_id}")
def delete_gateway(gw_id: str, request: Request, company: str | None = None,
                   principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    tenant = _writable(principal, company, runtime)
    runtime.org.delete_gateway(tenant, gw_id)
    runtime.main.audit(principal.username, "gateway_deleted", company=tenant, target=gw_id, ip=_ip(request))
    return {"deleted": gw_id}


# =============================================================== API tokens
class TokenBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    scope: str = Field("read", pattern="^(read|write)$")
    expires_days: int | None = Field(None, ge=1, le=3650)


@router.get("/tokens")
def list_tokens(company: str | None = None, principal: Principal = Depends(authenticate),
                runtime: Runtime = Depends(get_runtime)):
    _human_only(principal)
    tenant = _writable(principal, company, runtime)
    return {"company": tenant, "tokens": runtime.org.list_tokens(tenant)}


@router.post("/tokens", status_code=201)
def create_token(body: TokenBody, request: Request, company: str | None = None,
                 principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    _human_only(principal)
    tenant = _writable(principal, company, runtime)
    row = runtime.org.create_token(tenant, body.name, body.scope, principal.username, body.expires_days)
    runtime.main.audit(principal.username, "api_token_created", company=tenant, target=row["prefix"], ip=_ip(request),
                       details={"name": body.name, "scope": body.scope, "expires_days": body.expires_days})
    return row  # the only time the full token is returned


@router.delete("/tokens/{token_id}")
def revoke_token(token_id: int, request: Request, company: str | None = None,
                 principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    _human_only(principal)
    tenant = _writable(principal, company, runtime)
    runtime.org.revoke_token(tenant, token_id)
    runtime.main.audit(principal.username, "api_token_revoked", company=tenant, target=str(token_id), ip=_ip(request))
    return {"revoked": token_id}


# ================================================================= webhooks
class WebhookBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    url: str = Field(min_length=8, max_length=2000)
    events: list[str] = Field(min_length=1)
    active: bool = True


def _public_hook(h: dict, *, reveal: bool = False) -> dict:
    out = {k: v for k, v in h.items() if k != "secret"}
    out["secret"] = h["secret"] if reveal else h["secret"][:10] + "…"
    return out


@router.get("/webhooks")
def list_webhooks(company: str | None = None, principal: Principal = Depends(authenticate),
                  runtime: Runtime = Depends(get_runtime)):
    _human_only(principal)
    tenant = _writable(principal, company, runtime)
    return {"company": tenant, "webhooks": [_public_hook(h) for h in runtime.org.list_webhooks(tenant)],
            "events": ["telemetry", "command", "automation", "alert", "flash"]}


@router.post("/webhooks", status_code=201)
def create_webhook(body: WebhookBody, request: Request, company: str | None = None,
                   principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    _human_only(principal)
    tenant = _writable(principal, company, runtime)
    hook = runtime.org.save_webhook(tenant, body.model_dump(), principal.username)
    runtime.webhooks.refresh()
    runtime.main.audit(principal.username, "webhook_created", company=tenant, target=hook["url"][:200], ip=_ip(request),
                       details={"events": hook["events"]})
    return _public_hook(hook, reveal=True)


@router.patch("/webhooks/{hook_id}")
def update_webhook(hook_id: int, body: WebhookBody, request: Request, company: str | None = None,
                   principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    _human_only(principal)
    tenant = _writable(principal, company, runtime)
    hook = runtime.org.save_webhook(tenant, body.model_dump(), principal.username, hook_id)
    runtime.webhooks.refresh()
    runtime.main.audit(principal.username, "webhook_updated", company=tenant, target=str(hook_id), ip=_ip(request))
    return _public_hook(hook)


@router.post("/webhooks/{hook_id}/rotate")
def rotate_webhook(hook_id: int, request: Request, company: str | None = None,
                   principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    _human_only(principal)
    tenant = _writable(principal, company, runtime)
    hook = runtime.org.rotate_webhook_secret(tenant, hook_id)
    runtime.webhooks.refresh()
    runtime.main.audit(principal.username, "webhook_secret_rotated", company=tenant, target=str(hook_id), ip=_ip(request))
    return _public_hook(hook, reveal=True)


@router.delete("/webhooks/{hook_id}")
def delete_webhook(hook_id: int, request: Request, company: str | None = None,
                   principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    _human_only(principal)
    tenant = _writable(principal, company, runtime)
    runtime.org.delete_webhook(tenant, hook_id)
    runtime.webhooks.refresh()
    runtime.main.audit(principal.username, "webhook_deleted", company=tenant, target=str(hook_id), ip=_ip(request))
    return {"deleted": hook_id}


@router.post("/webhooks/{hook_id}/test")
def test_webhook(hook_id: int, company: str | None = None, principal: Principal = Depends(authenticate),
                 runtime: Runtime = Depends(get_runtime)):
    _human_only(principal)
    tenant = _writable(principal, company, runtime)
    hook = runtime.org.get_webhook(tenant, hook_id)
    payload = {"id": f"ping-{int(time.time())}", "event": "ping", "company": tenant, "ts": time.time(),
               "data": {"message": "WIOT webhook test", "by": principal.username}}
    return runtime.webhooks.deliver(hook, payload, retries=(0,))


@router.get("/webhooks/{hook_id}/deliveries")
def webhook_deliveries(hook_id: int, company: str | None = None, principal: Principal = Depends(authenticate),
                       runtime: Runtime = Depends(get_runtime)):
    _human_only(principal)
    tenant = _writable(principal, company, runtime)
    runtime.org.get_webhook(tenant, hook_id)
    return {"deliveries": runtime.webhooks.deliveries(hook_id)}


# ==================================================================== world
@router.get("/world")
def world(principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    """Every readable company with its regions/sites, coordinates and live node counts."""
    out = []
    for c in runtime.org.list_companies(include_archived=False):
        if not principal.can_read(c["name"]):
            continue
        name = c["name"]
        reg_rows = {r["region"]: r for r in runtime.org.list_regions(name)}
        regions, live = _live(runtime, name)
        layout = runtime.farm.store.get(name)
        sites = []
        for reg in regions:
            nodes = [v for (rr, _), v in live.items() if rr == reg]
            if not nodes and reg not in reg_rows:
                continue
            r = reg_rows.get(reg, {})
            lat, lon = r.get("lat"), r.get("lon")
            source = "region"
            if lat is None and layout is not None:
                lat, lon, source = layout.site.center[0], layout.site.center[1], "farm"
            if lat is None and c["lat"] is not None:
                lat, lon, source = c["lat"], c["lon"], "company"
            sites.append({
                "region": reg, "name": r.get("display_name") or (layout.site.name if source == "farm" and layout else reg),
                "lat": lat, "lon": lon, "located_by": source if lat is not None else None,
                "country": r.get("country") or c["country"],
                "nodes": len(nodes), "online": sum(v["link_state"] == "online" for v in nodes),
                "late": sum(v["link_state"] == "late" for v in nodes),
                "offline": sum(v["link_state"] == "offline" for v in nodes),
                "uplinks_24h": sum(v.get("uplinks_24h") or 0 for v in nodes),
                "last_seen": max((v["last_seen"] or 0 for v in nodes), default=None) or None,
                "farm": layout.site.name if layout else None,
            })
        out.append({**c, "sites": sites})
    return {"companies": out, "generated_at": time.time()}
