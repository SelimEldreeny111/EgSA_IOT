"""Fleet, node, message history, consumption and CSV export endpoints."""
from __future__ import annotations

import csv
import io
import time
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from ..security import Principal
from ..services.runtime import Runtime
from ..storage.telemetry_store import SERIES_METRICS
from .deps import authenticate, get_runtime, resolve_company, resolve_region

router = APIRouter(tags=["telemetry"])


@router.get("/fleet")
def fleet(company: str | None = None, region: str | None = None,
          principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    tenant = resolve_company(principal, company, runtime)
    reg = resolve_region(region)
    nodes = runtime.telemetry.fleet(tenant, reg)
    names = {n["node_id"]: n for n in runtime.org.list_nodes(tenant, reg)}
    for n in nodes:  # registered display name / kind, when the node is in the Organization registry
        meta = names.get(n["node_id"])
        n["name"], n["kind"] = (meta["name"], meta["kind"]) if meta else (None, None)
        n["node_type"], n["sensors"] = (meta["node_type"], meta["sensors"]) if meta else (None, None)
    summary = {
        "nodes": len(nodes),
        "online": sum(n["link_state"] == "online" for n in nodes),
        "late": sum(n["link_state"] == "late" for n in nodes),
        "offline": sum(n["link_state"] == "offline" for n in nodes),
        "uplinks_24h": sum(n.get("uplinks_24h", 0) for n in nodes),
    }
    return {"company": tenant, "region": reg, "summary": summary, "nodes": nodes,
            "regions": _regions(runtime, tenant)}


def _regions(runtime: Runtime, tenant: str) -> list[str]:
    """Regions seen in telemetry plus regions registered on the Organization page."""
    return sorted(set(runtime.telemetry.regions(tenant)) | set(runtime.org.region_ids(tenant)))


@router.get("/nodes/{node_id}")
def node_detail(node_id: int, company: str | None = None, region: str | None = None,
                limit: int = Query(120, ge=1, le=1000),
                principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    tenant = resolve_company(principal, company, runtime)
    reg = resolve_region(region)
    fleet = {n["node_id"]: n for n in runtime.telemetry.fleet(tenant, reg)}
    if node_id not in fleet:
        raise HTTPException(404, "Node has no uplinks in this region")
    history = runtime.telemetry.node_history(tenant, reg, node_id, limit)
    return {"company": tenant, "region": reg, "latest": fleet[node_id], "history": history}


@router.get("/nodes/{node_id}/series")
def node_series(node_id: int, metric: str = Query(..., description=", ".join(SERIES_METRICS)),
                company: str | None = None, region: str | None = None,
                hours: float = Query(24, gt=0, le=24 * 90), points: int = Query(240, ge=10, le=2000),
                end: int | None = None,
                principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    tenant = resolve_company(principal, company, runtime)
    stop = int(end or time.time())
    start = stop - int(hours * 3600)
    bucket = max(1, int(hours * 3600 / points))
    rows = runtime.telemetry.series(tenant, resolve_region(region), node_id, metric, start, stop, bucket)
    return {"metric": metric, "bucket_s": bucket, "start": start, "end": stop,
            "columns": ["t", "avg", "min", "max", "n"], "points": rows}


@router.get("/messages")
def messages(company: str | None = None, region: str | None = None, type: str | None = None,
             node_id: int | None = None, start: str | None = None, end: str | None = None,
             page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=1000),
             principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    tenant = resolve_company(principal, company, runtime, allow_all=True)
    if type and type not in ("Status", "Telemetry", "Command"):
        raise HTTPException(400, "type must be Status, Telemetry or Command")
    rows, total = runtime.telemetry.query_messages(
        tenant, resolve_region(region), start=start, end=end, msg_type=type, node_id=node_id,
        limit=page_size, offset=(page - 1) * page_size)
    return {"rows": rows, "total": total, "page": page, "page_size": page_size,
            "total_pages": max(1, -(-total // page_size))}


@router.get("/regions")
def regions(company: str | None = None, principal: Principal = Depends(authenticate),
            runtime: Runtime = Depends(get_runtime)):
    tenant = resolve_company(principal, company, runtime)
    return {"company": tenant, "regions": _regions(runtime, tenant)}


@router.get("/consumption")
def consumption(company: str | None = None, region: str | None = None,
                period: str | None = Query(None, pattern="^(day|month|year)$"),
                node_id: int | None = None, flow_meter_type: int | None = Query(None, ge=1, le=2),
                principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    tenant = resolve_company(principal, company, runtime)
    rows = runtime.telemetry.consumption(tenant, resolve_region(region), period=period,
                                         node_id=node_id, flow_meter_type=flow_meter_type)
    return {"company": tenant, "rows": rows}


EXPORT_COLUMNS = [
    ("Received At", lambda r: datetime.fromtimestamp(r["timestamp"]).strftime("%Y-%m-%d %H:%M:%S")),
    ("Measured At", lambda r: r.get("measured_at")), ("Time Source", lambda r: r.get("time_source")),
    ("Type", lambda r: r["type"]), ("Company", lambda r: r.get("company")),
    ("Region", lambda r: r.get("region")), ("Node ID", lambda r: r["node_id"]),
    ("Sensor ID", lambda r: r["sensor_id"]), ("Node Status", lambda r: r.get("node_status")),
    ("Battery Voltage", lambda r: r.get("battery_voltage")),
    ("WDT Resets", lambda r: r.get("wdt_reset_count")), ("Power Resets", lambda r: r.get("power_reset_count")),
    ("Power Mode", lambda r: r.get("power_mode")), ("Power State", lambda r: r.get("power_state")),
    ("Flow (m3/h)", lambda r: r["flow"]), ("Velocity (m/s)", lambda r: r["velocity"]),
    ("Consumption Today (m3)", lambda r: r["flow_day"]), ("Consumption Month (m3)", lambda r: r["flow_month"]),
    ("Consumption Year (m3)", lambda r: r["flow_year"]), ("Flow Meter Type", lambda r: r.get("flow_meter_type")),
    ("Period Source", lambda r: r.get("flow_period_source")), ("Flow Valid", lambda r: r.get("flow_live_valid")),
    ("Period Valid", lambda r: r.get("flow_period_totals_valid")),
    ("Cumulative Valid", lambda r: r.get("flow_cumulative_totals_valid")), ("RTC Valid", lambda r: r.get("rtc_valid")),
    ("Forward Total (L)", lambda r: r.get("forward_total_liters")),
    ("Reverse Total (L)", lambda r: r.get("reverse_total_liters")), ("Net Total (L)", lambda r: r.get("net_total_liters")),
    ("Period Quality", lambda r: r.get("flow_period_quality")), ("Alarm Flags", lambda r: r.get("flow_meter_alarm_flags")),
    ("HNDA Temp", lambda r: r.get("soil_temperature")), ("HNDA Moisture", lambda r: r.get("soil_moisture")),
    ("HNDA Valid", lambda r: r.get("soil_moisture_temp_valid")), ("Sondas Temp", lambda r: r.get("ec_temperature")),
    ("Sondas Moisture", lambda r: r.get("ec_moisture")), ("Sondas EC", lambda r: r.get("electrical_conductivity")),
    ("Sondas Valid", lambda r: r.get("soil_moisture_temp_ec_valid")),
    ("Active Sensors", lambda r: r.get("active_sensor_count")), ("Sensor Mask", lambda r: r.get("sensor_mask")),
    ("Details", lambda r: r.get("details")),
]


def _csv_safe(value):
    """Neutralise spreadsheet formula injection in free-text cells."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return "" if value is None else value


@router.get("/export.csv")
def export_csv(company: str | None = None, region: str | None = None, start: str | None = None,
               end: str | None = None, principal: Principal = Depends(authenticate),
               runtime: Runtime = Depends(get_runtime)):
    tenant = resolve_company(principal, company, runtime, allow_all=True)
    reg = resolve_region(region)
    rows = runtime.telemetry.iter_export(tenant, reg, start, end)

    def generate():
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow([name for name, _ in EXPORT_COLUMNS])
        yield buffer.getvalue()
        for row in rows:
            buffer.seek(0)
            buffer.truncate(0)
            writer.writerow([_csv_safe(fn(row)) for _, fn in EXPORT_COLUMNS])
            yield buffer.getvalue()

    name = f"wiot_{tenant or 'all'}_{reg}_{datetime.now():%Y%m%d_%H%M}.csv"
    return StreamingResponse(generate(), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{name}"'})
