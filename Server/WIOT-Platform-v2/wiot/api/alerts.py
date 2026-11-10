"""Fleet alerts: silent nodes, low batteries and unstable flow readings."""
from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ..protocol.topics import region_id
from ..security import Principal
from ..services.runtime import Runtime
from .deps import authenticate, get_runtime, resolve_company

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("")
def list_alerts(company: str | None = None, region: str | None = None,
                status: str = Query("open", pattern="^(open|all)$"),
                days: int = Query(7, ge=1, le=90), limit: int = Query(200, ge=1, le=500),
                principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    """Open alerts, or (``status=all``) everything open or changed in the last ``days``.

    Company-wide unless ``region`` is given; the summary always covers the whole company.
    """
    tenant = resolve_company(principal, company, runtime)
    now = int(time.time())
    store = runtime.alert_store
    return {"company": tenant, "status": status,
            "alerts": store.list(tenant, status=status, region=region_id(region) if region else None,
                                 since=now - days * 86400, limit=limit),
            "summary": store.summary(tenant, now)}


@router.post("/{alert_id}/acknowledge")
def acknowledge(alert_id: int, request: Request, company: str | None = None,
                principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    """Mark an open alert as seen. It stays open until its condition clears."""
    tenant = resolve_company(principal, company, runtime)
    if not principal.can_write(tenant):
        raise HTTPException(403, "Operator privileges required to acknowledge alerts")
    alert = runtime.alert_store.acknowledge(tenant, alert_id, principal.username)
    runtime.main.audit(principal.username, "alert_acknowledged", company=tenant,
                       target=f"{alert['region']}/{alert['node_id']}",
                       ip=request.client.host if request.client else None,
                       details={"alert_id": alert_id, "kind": alert["kind"]})
    runtime.hub.publish("alert", {"kind": "acknowledged", "alert_id": alert_id, "alert_kind": alert["kind"],
                                  "region": alert["region"], "node_id": alert["node_id"],
                                  "severity": alert["severity"], "state": alert["state"]}, company=tenant)
    return alert
