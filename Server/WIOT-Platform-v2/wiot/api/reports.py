"""Monthly reports, usage metering, integrations, data feeds and company logos (R2.3, points 23, 27-29)."""
from __future__ import annotations

import csv
import io
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field

from ..security import Principal
from ..services.reports import previous_month
from ..services.runtime import Runtime
from ..storage.telemetry_store import SERIES_METRICS
from .deps import authenticate, get_runtime, require_admin, resolve_company

router = APIRouter()

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


# ------------------------------------------------------------------ reports
@router.get("/reports/monthly", tags=["reports"])
def monthly_report(company: str | None = None, month: str | None = Query(None, pattern=r"^\d{4}-\d{2}$"),
                   format: str = Query("json", pattern="^(json|xlsx|pdf)$"),
                   principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    tenant = resolve_company(principal, company, runtime)
    month = month or previous_month(tz=runtime.org.timezone(tenant))
    rep = runtime.reports.monthly(tenant, month)
    if format == "json":
        return rep
    runtime.usage.count(tenant, "exports")
    data, mime = (runtime.reports.to_xlsx(rep), XLSX) if format == "xlsx" else (runtime.reports.to_pdf(rep), "application/pdf")
    return Response(data, media_type=mime, headers={
        "Content-Disposition": f'attachment; filename="WIOT_{tenant}_{month}.{format}"'})


@router.get("/reports", tags=["reports"])
def report_archive(company: str | None = None, principal: Principal = Depends(authenticate),
                   runtime: Runtime = Depends(get_runtime)):
    tenant = resolve_company(principal, company, runtime)
    return {"company": tenant, "archive": runtime.reports.list_files(tenant), "auto": runtime.settings.reports_auto,
            "default_month": previous_month(tz=runtime.org.timezone(tenant))}


@router.post("/reports/monthly/send", tags=["reports"])
def send_report(request: Request, company: str | None = None, month: str | None = Query(None, pattern=r"^\d{4}-\d{2}$"),
                principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    """Build the report files now and send them to the company's report channels."""
    tenant = resolve_company(principal, company, runtime)
    if not principal.can_write(tenant):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Administrator privileges for this company required")
    month = month or previous_month(tz=runtime.org.timezone(tenant))
    out = runtime.reports.build_files(tenant, month)
    s = out["report"]["summary"]
    n = runtime.notifier.send_report(
        tenant, f"[WIOT] Monthly report {month} - {out['report']['display_name']}",
        f"Monthly report for {out['report']['display_name']}, {month}. Nodes: {s['nodes_reporting']}, "
        f"uplinks: {s['uplinks']}, water: {s['water_m3']} m3, alerts: {s['alerts']}.",
        [(f"WIOT_{tenant}_{month}.pdf", out["pdf"], "application/pdf"), (f"WIOT_{tenant}_{month}.xlsx", out["xlsx"], XLSX)])
    runtime.main.audit(principal.username, "report_sent", company=tenant, target=month, ip=_ip(request),
                       details={"channels": n})
    return {"month": month, "channels": n}


# -------------------------------------------------------------------- usage
@router.get("/usage", tags=["usage"])
def usage(company: str | None = None, days: int = Query(90, ge=1, le=800),
          format: str = Query("json", pattern="^(json|csv)$"),
          principal: Principal = Depends(require_admin), runtime: Runtime = Depends(get_runtime)):
    """Daily and monthly usage per company: uplinks, bytes, commands, API calls, exports, active nodes, storage."""
    tenant = resolve_company(principal, company, runtime, allow_all=True) if principal.is_supervisor else principal.company
    data = runtime.usage.report(tenant, days)
    if format == "csv":
        out = io.StringIO()
        w = csv.writer(out)
        cols = ["company", "day", "messages", "bytes", "commands", "api_calls", "exports", "nodes_active", "storage_bytes"]
        w.writerow(cols)
        for r in data["days"]:
            w.writerow([r[c] for c in cols])
        return Response(out.getvalue(), media_type="text/csv",
                        headers={"Content-Disposition": 'attachment; filename="wiot_usage.csv"'})
    return {"company": tenant, **data}


# ------------------------------------------------------------- integrations
class IntegrationIn(BaseModel):
    name: str | None = Field(None, max_length=80)
    kind: str | None = Field(None, pattern="^(thingsboard|azure_iot|http_json)$")
    config: dict | None = None
    secrets: dict | None = None
    enabled: bool | None = None


def _int_admin(principal: Principal, company: str | None, runtime: Runtime) -> str:
    tenant = resolve_company(principal, company, runtime)
    if not principal.can_write(tenant) or principal.token:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Administrator privileges for this company required")
    return tenant


@router.get("/integrations", tags=["integrations"])
def list_integrations(company: str | None = None, principal: Principal = Depends(authenticate),
                      runtime: Runtime = Depends(get_runtime)):
    tenant = _int_admin(principal, company, runtime)
    return {"integrations": runtime.integrations.list(tenant)}


@router.post("/integrations", status_code=201, tags=["integrations"])
def create_integration(body: IntegrationIn, request: Request, company: str | None = None,
                       principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    tenant = _int_admin(principal, company, runtime)
    item = runtime.integrations.save(tenant, body.model_dump(exclude_unset=True))
    runtime.main.audit(principal.username, "integration_created", company=tenant, target=item["name"],
                       ip=_ip(request), details={"kind": item["kind"]})
    return item


@router.patch("/integrations/{integration_id}", tags=["integrations"])
def update_integration(integration_id: int, body: IntegrationIn, request: Request, company: str | None = None,
                       principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    tenant = _int_admin(principal, company, runtime)
    item = runtime.integrations.save(tenant, body.model_dump(exclude_unset=True), integration_id)
    runtime.main.audit(principal.username, "integration_updated", company=tenant, target=item["name"], ip=_ip(request))
    return item


@router.delete("/integrations/{integration_id}", status_code=204, tags=["integrations"])
def delete_integration(integration_id: int, request: Request, company: str | None = None,
                       principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    tenant = _int_admin(principal, company, runtime)
    runtime.integrations.delete(tenant, integration_id)
    runtime.main.audit(principal.username, "integration_deleted", company=tenant, target=str(integration_id),
                       ip=_ip(request))


@router.post("/integrations/{integration_id}/test", tags=["integrations"])
def test_integration(integration_id: int, company: str | None = None, principal: Principal = Depends(authenticate),
                     runtime: Runtime = Depends(get_runtime)):
    tenant = _int_admin(principal, company, runtime)
    return runtime.integrations.test(tenant, integration_id)


# -------------------------------------------------------------------- feeds
FEED_METRICS = ("flow", "battery_voltage", "soil_moisture", "soil_temperature", "electrical_conductivity")


@router.get("/feeds/daily.csv", tags=["integrations"])
def daily_feed(company: str | None = None, days: int = Query(90, ge=1, le=800),
               principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    """One row per node and day (mean / min / max of each metric) from the summaries — for Power BI, Excel or
    a data warehouse. Authenticate with an API token: ``Authorization: Bearer wiot_...``."""
    tenant = resolve_company(principal, company, runtime)
    since = int(time.time()) - days * 86400
    from ..storage import rollups
    rows: dict[tuple, dict] = {}
    with runtime.telemetry.connect(tenant, write=True) as db:
        rollups.ensure_schema(db)
        for region, node, metric, t, n, avg, lo, hi in db.execute(
                "SELECT region, node_id, metric, t, n, avg, lo, hi FROM rollups WHERE grain='day' AND t>=? "
                "AND metric IN (%s) ORDER BY t, region, node_id" % ",".join("?" * len(FEED_METRICS)),
                (since, *FEED_METRICS)):
            r = rows.setdefault((t, region, node), {})
            r[metric] = (n, avg, lo, hi)
    out = io.StringIO()
    w = csv.writer(out)
    header = ["day", "company", "region", "node_id"]
    for m in FEED_METRICS:
        header += [f"{m}_n", f"{m}_mean", f"{m}_min", f"{m}_max"]
    w.writerow(header)
    for (t, region, node), r in sorted(rows.items()):
        line = [datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d"), tenant, region, node]
        for m in FEED_METRICS:
            n, avg, lo, hi = r.get(m, (0, None, None, None))
            line += [n, "" if avg is None else round(avg, 4), "" if lo is None else lo, "" if hi is None else hi]
        w.writerow(line)
    runtime.usage.count(tenant, "exports")
    return Response(out.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="wiot_{tenant}_daily.csv"'})


@router.get("/feeds/metrics", tags=["integrations"])
def feed_metrics(_: Principal = Depends(authenticate)):
    return {"daily_csv_metrics": FEED_METRICS, "series_metrics": list(SERIES_METRICS)}


# -------------------------------------------------------------------- logos
@router.get("/org/companies/{name}/logo", tags=["organization"])
def company_logo(name: str, principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    if not principal.can_read(name):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Cannot read another company")
    logo = runtime.org.company_logo(name)
    if logo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No logo")
    data, mime = logo
    return Response(data, media_type=mime, headers={"Cache-Control": "private, max-age=300"})
