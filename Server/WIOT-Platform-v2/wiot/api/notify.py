"""Custom alert rules and notification channels (R2.3, point 22)."""
from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from ..security import Principal
from ..storage.notify_store import CHANNEL_KINDS, PROVIDERS, RULE_METRICS, RULE_OPS, RULE_SEVERITIES
from ..services.runtime import Runtime
from .deps import authenticate, get_runtime, resolve_company, resolve_region

router = APIRouter(tags=["alerts"])


def _ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _writer(principal: Principal, company: str) -> None:
    if not principal.can_write(company):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Administrator privileges for this company required")


class RuleIn(BaseModel):
    name: str | None = Field(None, max_length=80)
    region: str | None = Field(None, max_length=40)
    nodes: list[int] | None = None
    metric: str | None = Field(None, max_length=40)
    op: str | None = Field(None, max_length=2)
    value: float | None = None
    duration_s: int | None = Field(None, ge=0, le=7 * 86400)
    severity: str | None = Field(None, pattern="^(warning|critical)$")
    enabled: bool | None = None


@router.get("/alert-rules/catalog")
def rule_catalog(_: Principal = Depends(authenticate)):
    return {"metrics": RULE_METRICS, "ops": RULE_OPS, "severities": RULE_SEVERITIES,
            "channel_kinds": CHANNEL_KINDS, "providers": PROVIDERS}


@router.get("/alert-rules")
def list_rules(company: str | None = None, principal: Principal = Depends(authenticate),
               runtime: Runtime = Depends(get_runtime)):
    tenant = resolve_company(principal, company, runtime)
    return {"rules": runtime.notify_store.list_rules(tenant)}


@router.post("/alert-rules", status_code=201)
def create_rule(body: RuleIn, request: Request, company: str | None = None, principal: Principal = Depends(authenticate),
                runtime: Runtime = Depends(get_runtime)):
    tenant = resolve_company(principal, company, runtime)
    _writer(principal, tenant)
    rule = runtime.notify_store.save_rule(tenant, body.model_dump(exclude_unset=True), principal.username)
    runtime.rules.invalidate(tenant)
    runtime.main.audit(principal.username, "alert_rule_created", company=tenant, target=rule["name"], ip=_ip(request),
                       details={k: rule[k] for k in ("metric", "op", "value", "duration_s", "severity")})
    return rule


@router.patch("/alert-rules/{rule_id}")
def update_rule(rule_id: int, body: RuleIn, request: Request, company: str | None = None,
                principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    tenant = resolve_company(principal, company, runtime)
    _writer(principal, tenant)
    rule = runtime.notify_store.save_rule(tenant, body.model_dump(exclude_unset=True), principal.username, rule_id)
    runtime.rules.invalidate(tenant)
    runtime.main.audit(principal.username, "alert_rule_updated", company=tenant, target=rule["name"], ip=_ip(request),
                       details=body.model_dump(exclude_unset=True))
    return rule


@router.delete("/alert-rules/{rule_id}", status_code=204)
def delete_rule(rule_id: int, request: Request, company: str | None = None, principal: Principal = Depends(authenticate),
                runtime: Runtime = Depends(get_runtime)):
    tenant = resolve_company(principal, company, runtime)
    _writer(principal, tenant)
    runtime.notify_store.delete_rule(tenant, rule_id)
    runtime.rules.invalidate(tenant)
    runtime.main.audit(principal.username, "alert_rule_deleted", company=tenant, target=str(rule_id), ip=_ip(request))


@router.post("/alert-rules/preview")
def preview_rule(body: RuleIn, company: str | None = None, region: str | None = None,
                 principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    """Which nodes would breach this rule with their latest readings (nothing is saved)."""
    tenant = resolve_company(principal, company, runtime)
    rule = body.model_dump()
    if rule["metric"] not in RULE_METRICS or rule["op"] not in RULE_OPS or rule["value"] is None:
        raise ValueError("Metric, operator and threshold are required")
    fleet = runtime.telemetry.fleet(tenant, resolve_region(rule.get("region") or region))
    return {"nodes": runtime.rules.preview(rule, fleet, int(time.time()))}


# ---------------------------------------------------------------- channels
class ChannelIn(BaseModel):
    name: str | None = Field(None, max_length=80)
    kind: str | None = Field(None, max_length=20)
    config: dict | None = None
    secrets: dict | None = None
    min_severity: str | None = Field(None, pattern="^(info|warning|critical)$")
    events: list[str] | None = None
    enabled: bool | None = None


@router.get("/notify/channels")
def list_channels(company: str | None = None, principal: Principal = Depends(authenticate),
                  runtime: Runtime = Depends(get_runtime)):
    tenant = resolve_company(principal, company, runtime)
    _writer(principal, tenant)
    return {"channels": runtime.notify_store.list_channels(tenant), "email_enabled": runtime.notifier.smtp_ready()}


@router.post("/notify/channels", status_code=201)
def create_channel(body: ChannelIn, request: Request, company: str | None = None,
                   principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    tenant = resolve_company(principal, company, runtime)
    _writer(principal, tenant)
    ch = runtime.notify_store.save_channel(tenant, body.model_dump(exclude_unset=True))
    runtime.main.audit(principal.username, "notify_channel_created", company=tenant, target=ch["name"],
                       ip=_ip(request), details={"kind": ch["kind"]})
    return ch


@router.patch("/notify/channels/{channel_id}")
def update_channel(channel_id: int, body: ChannelIn, request: Request, company: str | None = None,
                   principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    tenant = resolve_company(principal, company, runtime)
    _writer(principal, tenant)
    ch = runtime.notify_store.save_channel(tenant, body.model_dump(exclude_unset=True), channel_id)
    runtime.main.audit(principal.username, "notify_channel_updated", company=tenant, target=ch["name"],
                       ip=_ip(request), details={k: v for k, v in body.model_dump(exclude_unset=True).items()
                                                 if k != "secrets"})
    return ch


@router.delete("/notify/channels/{channel_id}", status_code=204)
def delete_channel(channel_id: int, request: Request, company: str | None = None,
                   principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    tenant = resolve_company(principal, company, runtime)
    _writer(principal, tenant)
    runtime.notify_store.delete_channel(tenant, channel_id)
    runtime.main.audit(principal.username, "notify_channel_deleted", company=tenant, target=str(channel_id),
                       ip=_ip(request))


@router.post("/notify/channels/{channel_id}/test")
def test_channel(channel_id: int, company: str | None = None, principal: Principal = Depends(authenticate),
                 runtime: Runtime = Depends(get_runtime)):
    tenant = resolve_company(principal, company, runtime)
    _writer(principal, tenant)
    ch = runtime.notify_store.get_channel(channel_id, with_secrets=True)
    if ch is None or ch["company"] != tenant:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Channel not found")
    ok, detail = runtime.notifier.deliver(ch, "test", "[WIOT] Test notification",
                                          f"This is a test message from the WIOT Control Center for {tenant}, "
                                          f"sent by {principal.username}.", retries=(0,))
    return {"ok": ok, "detail": detail}


@router.get("/notify/channels/{channel_id}/log")
def channel_log(channel_id: int, company: str | None = None, principal: Principal = Depends(authenticate),
                runtime: Runtime = Depends(get_runtime)):
    tenant = resolve_company(principal, company, runtime)
    _writer(principal, tenant)
    ch = runtime.notify_store.get_channel(channel_id)
    if ch is None or ch["company"] != tenant:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Channel not found")
    return {"log": runtime.notify_store.channel_log(channel_id)}
