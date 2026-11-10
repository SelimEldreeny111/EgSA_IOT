"""Broker control, flash archive, analytics, logs and health endpoints."""
from __future__ import annotations

import csv
import io
import json
import platform
import sqlite3
import time
from contextlib import closing

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, Field

from .. import __version__
from ..domain.flash_analysis import analyse as analyse_flash
from ..security import Principal
from ..services.broker import BrokerParams
from ..services.metrics import REGISTRY, WS_CONNECTIONS
from ..services.runtime import Runtime
from .deps import (
    authenticate,
    get_runtime,
    require_supervisor,
    resolve_company,
    resolve_region,
)

router = APIRouter()
health_router = APIRouter(tags=["health"])


# ------------------------------------------------------------------ broker
class BrokerIn(BaseModel):
    host: str | None = Field(default=None, max_length=253)
    port: int | None = Field(default=None, ge=1, le=65535)
    client_id: str | None = Field(default=None, max_length=80)
    aes_key: str | None = Field(default=None, max_length=64)
    username: str | None = Field(default=None, max_length=128)
    password: str | None = Field(default=None, max_length=256)


@router.get("/broker", tags=["broker"])
def broker_status(principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    return runtime.broker.status(public=not principal.is_supervisor)


@router.post("/broker/connect", tags=["broker"], status_code=202)
def broker_connect(body: BrokerIn, principal: Principal = Depends(require_supervisor),
                   runtime: Runtime = Depends(get_runtime)):
    s = runtime.settings
    key_hex = (body.aes_key or (s.mqtt_aes_key_hex.get_secret_value() if s.mqtt_aes_key_hex else "")).strip()
    if not key_hex:
        raise HTTPException(400, "AES key (32 hex characters) is required")
    try:
        key = bytes.fromhex(key_hex)
    except ValueError as exc:
        raise HTTPException(400, "AES key must be hexadecimal") from exc
    params = BrokerParams(
        host=(body.host or s.mqtt_host).strip(), port=body.port or s.mqtt_port,
        client_id=(body.client_id or s.mqtt_client_id).strip(), aes_key=key,
        username=body.username or s.mqtt_username,
        password=body.password or (s.mqtt_password.get_secret_value() if s.mqtt_password else None))
    try:
        runtime.broker.connect(params)
    except OSError as exc:
        raise HTTPException(502, f"Broker unreachable: {exc}") from exc
    runtime.main.audit(principal.username, "broker_connect", target=f"{params.host}:{params.port}")
    return runtime.broker.status()


@router.post("/broker/disconnect", tags=["broker"])
def broker_disconnect(principal: Principal = Depends(require_supervisor),
                      runtime: Runtime = Depends(get_runtime)):
    runtime.broker.disconnect()
    runtime.main.audit(principal.username, "broker_disconnect")
    return runtime.broker.status()


# ------------------------------------------------------------------- flash
@router.get("/flash/status", tags=["flash"])
def flash_status(node_id: int = Query(1, ge=1, le=65535), company: str | None = None,
                 region: str | None = None, principal: Principal = Depends(authenticate),
                 runtime: Runtime = Depends(get_runtime)):
    tenant = resolve_company(principal, company, runtime)
    return runtime.ingest.flash.summary(tenant, resolve_region(region), node_id)


@router.get("/flash/nodes", tags=["flash"])
def flash_nodes(company: str | None = None, region: str | None = None,
                principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    """Nodes that have flash status, transfers or archived samples in this region."""
    tenant = resolve_company(principal, company, runtime)
    return {"nodes": runtime.ingest.flash.nodes(tenant, resolve_region(region))}


@router.get("/flash/analysis", tags=["flash"])
def flash_analysis(node_id: int = Query(1, ge=1, le=65535), company: str | None = None,
                   region: str | None = None, principal: Principal = Depends(authenticate),
                   runtime: Runtime = Depends(get_runtime)):
    """Memory health, retention projection, coverage, statistics and live-gap recovery."""
    tenant = resolve_company(principal, company, runtime)
    reg = resolve_region(region)
    archive = runtime.ingest.flash
    records = archive.all_records(tenant, reg, node_id)
    live: list[int] = []
    if records:
        pad = 3600
        live = runtime.telemetry.receive_times(tenant, reg, node_id, records[0]["epoch"] - pad, records[-1]["epoch"] + pad)
    now = int(time.time())
    result = analyse_flash(archive.summary(tenant, reg, node_id), records, live, now)
    return {"company": tenant, "region": reg, "node_id": node_id, **result,
            "lock": runtime.commands.flash_lock(tenant, reg, node_id, now)}


@router.get("/flash/lock", tags=["flash"])
def flash_lock(node_id: int = Query(1, ge=1, le=65535), company: str | None = None,
               region: str | None = None, principal: Principal = Depends(authenticate),
               runtime: Runtime = Depends(get_runtime)):
    """Whether a new flash command for this node would be refused now, and why.

    Only one flash conversation runs per node: a running history download or a flash
    command still waiting for the node's reply blocks every flash command except Cancel.
    """
    tenant = resolve_company(principal, company, runtime)
    reg = resolve_region(region)
    return {"company": tenant, "region": reg, "node_id": node_id,
            "lock": runtime.commands.flash_lock(tenant, reg, node_id)}


@router.get("/flash/records", tags=["flash"])
def flash_records(node_id: int = Query(1, ge=1, le=65535), company: str | None = None,
                  region: str | None = None, offset: int = Query(0, ge=0, le=10_000_000),
                  format: str = Query("json", pattern="^(json|csv)$"),
                  principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    tenant = resolve_company(principal, company, runtime)
    reg = resolve_region(region)
    archive = runtime.ingest.flash
    if format == "json":
        return {"records": archive.records(tenant, reg, node_id, 200, offset)}

    def generate():
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(["generation", "sequence", "sample_epoch", "node_calendar_day", "telemetry_json"])
        yield out.getvalue()
        page = 0
        while True:
            rows = archive.records(tenant, reg, node_id, 200, page)
            if not rows:
                break
            out.seek(0)
            out.truncate(0)
            for row in rows:
                writer.writerow([row["generation"], row["sequence"], row["epoch"], row["day"],
                                 json.dumps(row["data"])])
            yield out.getvalue()
            page += len(rows)

    return StreamingResponse(generate(), media_type="text/csv", headers={
        "Content-Disposition": f'attachment; filename="flash_{tenant}_{reg}_node{node_id}.csv"'})


# --------------------------------------------------------------- analytics
class PredictIn(BaseModel):
    features: dict


@router.get("/analytics", tags=["analytics"])
def analytics_index(_: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    return {"artifacts": runtime.analytics.available(), "job": runtime.analytics.job}


@router.get("/analytics/live", tags=["analytics"])
def analytics_live(company: str | None = None, principal: Principal = Depends(authenticate),
                   runtime: Runtime = Depends(get_runtime)):
    tenant = resolve_company(principal, company, runtime, allow_all=True)
    return runtime.analytics.live_kpis(tenant)


@router.get("/analytics/model/schema", tags=["analytics"])
def model_schema(_: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    return {"features": runtime.analytics.feature_schema()}


@router.post("/analytics/predict", tags=["analytics"])
def predict(body: PredictIn, _: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    """What-if scoring: edit the model inputs and see delivery probability + SHAP drivers."""
    return runtime.analytics.predict_features(body.features)


@router.post("/analytics/retrain", tags=["analytics"], status_code=202)
def retrain(principal: Principal = Depends(require_supervisor), runtime: Runtime = Depends(get_runtime)):
    runtime.main.audit(principal.username, "analytics_retrain")
    return runtime.analytics.start_retrain()


@router.get("/analytics/report", tags=["analytics"])
def analytics_report(_: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    path = runtime.analytics.directory / "REPORT.md"
    if not path.exists():
        raise HTTPException(404, "Report not generated yet")
    return PlainTextResponse(path.read_text(encoding="utf-8"), media_type="text/markdown")


@router.get("/analytics/figures/{name}", tags=["analytics"])
def analytics_figure(name: str, _: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    if not name.endswith(".png") or "/" in name or "\\" in name or ".." in name:
        raise HTTPException(400, "Invalid figure name")
    path = runtime.analytics.directory / "figures" / name
    if not path.is_file():
        raise HTTPException(404, "Figure not found")
    return FileResponse(path, media_type="image/png")


@router.get("/analytics/{name}", tags=["analytics"])
def analytics_artifact(name: str, _: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    return runtime.analytics.artifact(name)


# ------------------------------------------------------------------ system
@router.get("/system/info", tags=["system"])
def system_info(principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    info = {"version": __version__, "uptime_s": int(time.time() - runtime.started_at),
            "python": platform.python_version(), "websockets": runtime.hub.connections,
            "broker": runtime.broker.status(public=True)}
    if principal.is_supervisor:
        info["config"] = runtime.settings.public_summary()
    return info


@router.get("/system/logs", tags=["system"])
def system_logs(limit: int = Query(300, ge=1, le=2000), principal: Principal = Depends(authenticate),
                runtime: Runtime = Depends(get_runtime)):
    return {"lines": runtime.logs.recent(principal, limit)}


@router.get("/system/logs/download", tags=["system"])
def download_logs(_: Principal = Depends(require_supervisor), runtime: Runtime = Depends(get_runtime)):
    path = runtime.settings.log_dir / "wiot-server.log"
    if not path.exists():
        raise HTTPException(404, "Log file not found")
    return FileResponse(path, filename="wiot-server.log", media_type="text/plain")


@health_router.get("/healthz")
def healthz():
    return {"status": "ok", "version": __version__}


@health_router.get("/readyz")
def readyz(request: Request):
    runtime: Runtime = request.app.state.runtime
    checks = {}
    try:
        with closing(sqlite3.connect(runtime.settings.main_db, timeout=2)) as db:
            db.execute("SELECT 1 FROM users LIMIT 1").fetchone()
        checks["database"] = "ok"
    except sqlite3.Error as exc:
        checks["database"] = f"error: {type(exc).__name__}"
    checks["broker"] = runtime.broker.status(public=True)["state"]
    healthy = checks["database"] == "ok"
    return PlainTextResponse(json.dumps({"ready": healthy, "checks": checks}),
                             status_code=200 if healthy else 503, media_type="application/json")


@health_router.get("/metrics", include_in_schema=False)
def metrics(request: Request):
    runtime: Runtime = request.app.state.runtime
    if not runtime.settings.metrics_public:
        client = request.client.host if request.client else ""
        if client not in ("127.0.0.1", "::1"):
            raise HTTPException(403, "Metrics are restricted to localhost")
    WS_CONNECTIONS.set(runtime.hub.connections)
    return PlainTextResponse(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)

