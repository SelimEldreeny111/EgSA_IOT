"""System health, maintenance, node health and the public status page (R2.2)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse

from ..security import Principal
from ..services.runtime import Runtime
from .deps import authenticate, get_runtime, require_supervisor, resolve_company, resolve_region

router = APIRouter(tags=["system"])
public_router = APIRouter(tags=["status"])


@router.get("/system/health")
def system_health(_: Principal = Depends(require_supervisor), runtime: Runtime = Depends(get_runtime)):
    """Supervisor view: broker, ingestion per company, disk, backups, databases and background threads."""
    snap = runtime.system.snapshot()
    snap["maintenance"] = runtime.maintenance.last_run
    return snap


@router.get("/system/status-history")
def status_history(days: int = Query(30, ge=1, le=365), _: Principal = Depends(require_supervisor),
                   runtime: Runtime = Depends(get_runtime)):
    return {"samples": runtime.system.history(days), **runtime.system.public_status(min(days, 90))}


@router.post("/system/maintenance/run")
def run_maintenance(principal: Principal = Depends(require_supervisor), runtime: Runtime = Depends(get_runtime)):
    """Fold new readings into the summaries now (retention runs on the daily cycle only)."""
    report = runtime.maintenance.run_once(daily=False)
    runtime.main.audit(principal.username, "maintenance_run",
                       details={"messages": sum(r["messages"] for r in report["rollups"]),
                                "errors": len(report["errors"])})
    return report


@router.get("/fleet/health", tags=["telemetry"])
def nodes_health(company: str | None = None, region: str | None = None,
                 principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    """Health score per node: battery trend, resets, regularity, store-and-forward, clock, commands, config."""
    tenant = resolve_company(principal, company, runtime)
    reg = resolve_region(region)
    nodes = runtime.node_health.fleet(tenant, reg)
    grades = {g: sum(1 for n in nodes if n["grade"] == g) for g in ("good", "fair", "poor")}
    return {"company": tenant, "region": reg, "nodes": nodes, "grades": grades}


# ----------------------------------------------------------------- public
def _public_enabled(request: Request) -> Runtime:
    runtime: Runtime = request.app.state.runtime
    if not runtime.settings.status_public:
        raise HTTPException(404, "Not found")
    return runtime


@public_router.get("/api/v2/public/status")
def public_status(days: int = Query(30, ge=1, le=90), runtime: Runtime = Depends(_public_enabled)):
    """Service availability only — no company names, node data or counts."""
    return runtime.system.public_status(days)


@public_router.get("/status", include_in_schema=False)
def status_page(runtime: Runtime = Depends(_public_enabled)):
    return FileResponse(runtime.settings.web_dir / "status.html", headers={"Cache-Control": "no-cache"})
