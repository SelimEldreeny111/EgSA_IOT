"""Phone app and push alerts, commissioning, maintenance and the optional assistant (R2.6)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from ..security import Principal
from ..services.assistant import AssistantUnavailable
from ..services.commissioning import parse_qr
from ..services.runtime import Runtime
from ..tools.pdf import Document
from .deps import authenticate, get_runtime, resolve_company, resolve_region

router = APIRouter(tags=["field"])
public_router = APIRouter(include_in_schema=False)


def _ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _writer(principal: Principal, company: str) -> None:
    if not principal.can_write(company):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Administrator privileges for this company required")


# ===================================================================== PWA
@public_router.get("/manifest.webmanifest")
def manifest(request: Request):
    return FileResponse(request.app.state.runtime.settings.web_dir / "manifest.webmanifest",
                        media_type="application/manifest+json", headers={"Cache-Control": "no-cache"})


@public_router.get("/sw.js")
def service_worker(request: Request):
    return FileResponse(request.app.state.runtime.settings.web_dir / "sw.js", media_type="text/javascript",
                        headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"})


class SubscriptionIn(BaseModel):
    endpoint: str = Field(max_length=1000)
    keys: dict


@router.get("/push/key")
def push_key(principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    if not runtime.settings.web_push:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Push alerts are turned off on this server")
    return {"public_key": runtime.push.public_key, "subscriptions": runtime.push.count(principal.user_id)}


@router.post("/push/subscribe", status_code=201)
def push_subscribe(body: SubscriptionIn, request: Request, principal: Principal = Depends(authenticate),
                   runtime: Runtime = Depends(get_runtime)):
    if principal.token:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not available to API tokens")
    runtime.push.subscribe(principal.user_id, body.model_dump(), request.headers.get("user-agent"))
    runtime.main.audit(principal.username, "push_subscribed", company=principal.company or None, ip=_ip(request))
    return {"subscriptions": runtime.push.count(principal.user_id)}


@router.post("/push/unsubscribe")
def push_unsubscribe(body: SubscriptionIn, principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    runtime.push.unsubscribe(principal.user_id, body.endpoint)
    return {"subscriptions": runtime.push.count(principal.user_id)}


@router.post("/push/test")
def push_test(principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    with runtime.main.connect() as db:
        subs = [dict(r) for r in db.execute("SELECT * FROM push_subscriptions WHERE user_id=?", (principal.user_id,))]
    results = [runtime.push.send(s, {"title": "WIOT test alert", "body": "Push alerts work on this device.", "url": "/#/alerts"})
               for s in subs]
    return {"sent": len(results), "statuses": results}


# ============================================================ commissioning
class QrIn(BaseModel):
    code: str = Field(max_length=500)


class RegisterIn(BaseModel):
    region: str | None = Field(None, max_length=40)
    node_id: int = Field(ge=1, le=65535)
    name: str | None = Field(None, max_length=80)
    type: str = Field("monitoring", pattern="^(monitoring|control)$")
    sensors: list[str] = []
    lat: float | None = Field(None, ge=-90, le=90)
    lon: float | None = Field(None, ge=-180, le=180)
    notes: str | None = Field(None, max_length=500)


@router.post("/commission/parse")
def commission_parse(body: QrIn, _: Principal = Depends(authenticate)):
    return parse_qr(body.code)


@router.post("/commission/register")
def commission_register(body: RegisterIn, request: Request, company: str | None = None,
                        principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    tenant = resolve_company(principal, company, runtime)
    _writer(principal, tenant)
    out = runtime.commissioning.register(tenant, {**body.model_dump(), "region": resolve_region(body.region)}, principal.username)
    runtime.main.audit(principal.username, "node_registered", company=tenant, target=f"{out['node']['region']}/{body.node_id}",
                       ip=_ip(request), details={"type": body.type, "sensors": body.sensors})
    return out


@router.get("/commission/check")
def commission_check(node_id: int = Query(ge=1, le=65535), region: str | None = None, company: str | None = None,
                     principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    tenant = resolve_company(principal, company, runtime)
    return runtime.commissioning.checks(tenant, resolve_region(region), node_id)


@router.post("/commission/clock")
def commission_clock(node_id: int = Query(ge=1, le=65535), region: str | None = None, company: str | None = None,
                     principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    tenant = resolve_company(principal, company, runtime)
    _writer(principal, tenant)
    return runtime.commissioning.send_clock(tenant, resolve_region(region), node_id, principal.username)


class CompleteIn(BaseModel):
    node_id: int = Field(ge=1, le=65535)
    region: str | None = Field(None, max_length=40)
    notes: str = Field("", max_length=500)


@router.post("/commission/complete")
def commission_complete(body: CompleteIn, company: str | None = None, format: str = Query("json", pattern="^(json|pdf)$"),
                        principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    tenant = resolve_company(principal, company, runtime)
    _writer(principal, tenant)
    rec = runtime.commissioning.complete(tenant, resolve_region(body.region), body.node_id, principal.username, body.notes)
    if format == "json":
        return rec
    import time as _t
    doc = Document(f"Commissioning certificate NODE-{body.node_id:03d}")
    doc.footer = f"{tenant} · NODE-{body.node_id:03d} · commissioning certificate"
    doc.heading(f"Commissioning certificate - NODE-{body.node_id:03d}", 16)
    doc.paragraph(f"Company {tenant} · region {rec['region']} · {_t.strftime('%Y-%m-%d %H:%M', _t.localtime(rec['at']))} · by {rec['by']}")
    doc.table(["Check", "Result", "Detail"], [[i["label"], "PASS" if i["ok"] else ("INFO" if not i["blocking"] else "FAIL"), i["detail"]]
                                              for i in rec["checks"]], [2.4, 0.7, 2.4], ["l", "l", "l"])
    if rec["notes"]:
        doc.paragraph(f"Notes: {rec['notes']}")
    return Response(doc.to_bytes(), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="WIOT_commissioning_NODE-{body.node_id:03d}.pdf"'})


# ============================================================== maintenance
@router.get("/maintenance/assets")
def assets(company: str | None = None, principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    tenant = resolve_company(principal, company, runtime)
    return {"assets": runtime.maint.list_assets(tenant)}


@router.post("/maintenance/assets", status_code=201)
def create_asset(body: dict, company: str | None = None, principal: Principal = Depends(authenticate),
                 runtime: Runtime = Depends(get_runtime)):
    tenant = resolve_company(principal, company, runtime)
    _writer(principal, tenant)
    return runtime.maint.save_asset(tenant, body)


@router.patch("/maintenance/assets/{asset_id}")
def update_asset(asset_id: int, body: dict, company: str | None = None, principal: Principal = Depends(authenticate),
                 runtime: Runtime = Depends(get_runtime)):
    tenant = resolve_company(principal, company, runtime)
    _writer(principal, tenant)
    return runtime.maint.save_asset(tenant, {**runtime.maint.get_asset(tenant, asset_id), **body}, asset_id)


@router.get("/maintenance/records")
def records(company: str | None = None, asset_id: int | None = None, principal: Principal = Depends(authenticate),
            runtime: Runtime = Depends(get_runtime)):
    tenant = resolve_company(principal, company, runtime)
    return {"records": runtime.maint.records(tenant, asset_id)}


@router.post("/maintenance/assets/{asset_id}/calibrations", status_code=201)
def add_calibration(asset_id: int, body: dict, request: Request, company: str | None = None,
                    principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    tenant = resolve_company(principal, company, runtime)
    _writer(principal, tenant)
    out = runtime.maint.add_calibration(tenant, asset_id, body, principal.username)
    runtime.main.audit(principal.username, "calibration_recorded", company=tenant, target=str(asset_id), ip=_ip(request),
                       details={"deviation_pct": out["deviation_pct"], "pass": out["pass"]})
    return out


@router.get("/maintenance/orders")
def orders(company: str | None = None, status_: str | None = Query(None, alias="status"),
           principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    tenant = resolve_company(principal, company, runtime)
    return {"orders": runtime.maint.list_orders(tenant, status_)}


@router.get("/maintenance/orders/{order_id}")
def order(order_id: int, company: str | None = None, principal: Principal = Depends(authenticate),
          runtime: Runtime = Depends(get_runtime)):
    return runtime.maint.get_order(resolve_company(principal, company, runtime), order_id)


class OrderIn(BaseModel):
    title: str = Field(max_length=120)
    description: str | None = Field(None, max_length=2000)
    priority: str = Field("normal", pattern="^(low|normal|high|urgent)$")
    asset_id: int | None = None
    alert_id: int | None = None
    node_id: int | None = Field(None, ge=1, le=65535)
    region: str | None = Field(None, max_length=40)
    assignee: str | None = Field(None, max_length=80)
    due: str | None = Field(None, max_length=10)


@router.post("/maintenance/orders", status_code=201)
def create_order(body: OrderIn, request: Request, company: str | None = None, principal: Principal = Depends(authenticate),
                 runtime: Runtime = Depends(get_runtime)):
    tenant = resolve_company(principal, company, runtime)
    _writer(principal, tenant)
    data = body.model_dump()
    if data.get("node_id") and not data.get("asset_id"):
        data["asset_id"] = runtime.maint.asset_for_node(tenant, resolve_region(data.get("region")), data["node_id"],
                                                         principal.username)["id"]
    out = runtime.maint.create_order(tenant, data, principal.username)
    runtime.main.audit(principal.username, "work_order_created", company=tenant, target=str(out["id"]), ip=_ip(request),
                       details={"title": out["title"], "priority": out["priority"]})
    return out


class OrderPatch(BaseModel):
    status: str | None = Field(None, pattern="^(open|assigned|in_progress|done|cancelled)$")
    assignee: str | None = Field(None, max_length=80)
    due: str | None = Field(None, max_length=10)
    priority: str | None = Field(None, pattern="^(low|normal|high|urgent)$")
    note: str | None = Field(None, max_length=2000)
    closure: str | None = Field(None, max_length=2000)


@router.patch("/maintenance/orders/{order_id}")
def update_order(order_id: int, body: OrderPatch, request: Request, company: str | None = None,
                 principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    tenant = resolve_company(principal, company, runtime)
    _writer(principal, tenant)
    out = runtime.maint.update_order(tenant, order_id, body.model_dump(exclude_unset=True), principal.username)
    runtime.main.audit(principal.username, "work_order_updated", company=tenant, target=str(order_id), ip=_ip(request),
                       details=body.model_dump(exclude_unset=True, exclude={"note", "closure"}))
    return out


@router.post("/maintenance/orders/{order_id}/photos", status_code=201)
async def add_photo(order_id: int, request: Request, company: str | None = None, caption: str = Query("", max_length=200),
                    principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    tenant = resolve_company(principal, company, runtime)
    _writer(principal, tenant)
    return runtime.maint.add_photo(tenant, order_id, await request.body(), principal.username, caption)


@router.get("/maintenance/photos/{name}")
def photo(name: str, company: str | None = None, principal: Principal = Depends(authenticate),
          runtime: Runtime = Depends(get_runtime)):
    tenant = resolve_company(principal, company, runtime)
    path = runtime.maint.photo_path(tenant, name)
    return FileResponse(path, media_type="image/png" if path.suffix == ".png" else "image/jpeg",
                        headers={"Cache-Control": "private, max-age=86400"})


# ================================================================ assistant
class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


@router.get("/assistant")
def assistant_status(company: str | None = None, principal: Principal = Depends(authenticate),
                     runtime: Runtime = Depends(get_runtime)):
    tenant = resolve_company(principal, company, runtime)
    return {**runtime.assistant.status(), "history": runtime.assistant.history(tenant, None if principal.can_command
                                                                               else principal.user_id)}


@router.post("/assistant/ask")
def assistant_ask(body: AskIn, request: Request, company: str | None = None, principal: Principal = Depends(authenticate),
                  runtime: Runtime = Depends(get_runtime)):
    tenant = resolve_company(principal, company, runtime)
    try:
        out = runtime.assistant.ask(tenant, body.question, principal.user_id)
    except AssistantUnavailable as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    runtime.main.audit(principal.username, "assistant_question", company=tenant, ip=_ip(request),
                       details={"chars": len(body.question), "tools": out["tools"], "tokens": out["input_tokens"] + out["output_tokens"]})
    return out
