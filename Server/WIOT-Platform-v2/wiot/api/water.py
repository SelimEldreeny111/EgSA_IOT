"""Irrigation planning and water accounts (R2.4)."""
from __future__ import annotations

import time
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field

from ..security import Principal
from ..services.runtime import Runtime
from ..tools.xlsx import Workbook
from .deps import authenticate, get_runtime, resolve_company

router = APIRouter(prefix="/water", tags=["water"])
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _writer(principal: Principal, company: str) -> None:
    if not principal.can_write(company):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Administrator privileges for this company required")


@router.get("/catalog")
def catalog(_: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    """Crops (FAO-56 / FAO-29), soil textures and deficit programmes."""
    return runtime.water.catalog()


# ------------------------------------------------------------------ fields
@router.get("/fields")
def fields(company: str | None = None, principal: Principal = Depends(authenticate),
           runtime: Runtime = Depends(get_runtime)):
    tenant = resolve_company(principal, company, runtime)
    layout = runtime.farm.store.get(tenant)
    if layout is None:
        return {"company": tenant, "fields": [], "configured": False}
    out = []
    for z in layout.zones:
        prof = runtime.water.profile(tenant, z.id)
        kc, st = runtime.water.kc(tenant, z)
        out.append({"id": z.id, "name": z.name, "crop": prof.get("crop") or z.crop, "planting_date": prof.get("planting_date"),
                    "soil": (prof.get("soil") or {}).get("texture"), "deficit": prof.get("deficit"), "kc": kc,
                    "stage": st.get("stage"), "area_ha": round(z.area_ha(), 1), "node_id": z.node_id})
    return {"company": tenant, "fields": out, "configured": True}


@router.get("/fields/{zone_id}")
def field_plan(zone_id: str, company: str | None = None, principal: Principal = Depends(authenticate),
               runtime: Runtime = Depends(get_runtime)):
    tenant = resolve_company(principal, company, runtime)
    return runtime.water.field_plan(tenant, zone_id)


class ProfileIn(BaseModel):
    crop: str | None = Field(None, max_length=40)
    planting_date: str | None = Field(None, max_length=10)
    soil: dict | None = None
    salinity: dict | None = None
    deficit: str | None = Field(None, max_length=40)


@router.put("/fields/{zone_id}")
def set_profile(zone_id: str, body: ProfileIn, request: Request, company: str | None = None,
                principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    tenant = resolve_company(principal, company, runtime)
    _writer(principal, tenant)
    prof = runtime.water.set_profile(tenant, zone_id, body.model_dump(exclude_none=True), principal.username)
    runtime.main.audit(principal.username, "field_profile_set", company=tenant, target=zone_id, ip=_ip(request),
                       details=prof)
    return runtime.water.field_plan(tenant, zone_id)


# ------------------------------------------------------------ settings
class TariffIn(BaseModel):
    currency: str | None = Field(None, max_length=8)
    water_price_m3: float | None = Field(None, ge=0)
    energy_price_kwh: float | None = Field(None, ge=0)
    pump_kw: float | None = Field(None, ge=0)


@router.get("/tariffs")
def tariffs(company: str | None = None, principal: Principal = Depends(authenticate),
            runtime: Runtime = Depends(get_runtime)):
    return runtime.water.settings_for(resolve_company(principal, company, runtime))


@router.put("/tariffs")
def set_tariffs(body: TariffIn, request: Request, company: str | None = None,
                principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    tenant = resolve_company(principal, company, runtime)
    _writer(principal, tenant)
    out = runtime.water.set_settings(tenant, body.model_dump(exclude_none=True))
    runtime.main.audit(principal.username, "tariffs_set", company=tenant, ip=_ip(request), details=out)
    return out


@router.get("/costs")
def costs(company: str | None = None, start: str | None = None, end: str | None = None,
          principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    tenant = resolve_company(principal, company, runtime)
    return runtime.water.field_costs(tenant, date.fromisoformat(start) if start else None,
                                     date.fromisoformat(end) if end else None)


# --------------------------------------------- schedules, rotations, quotas, wells, districts
KIND_PATH = {"schedules": "schedule", "rotations": "rotation", "quotas": "quota", "wells": "well", "districts": "dma"}


def _kind(kinds: str) -> str:
    if kinds not in KIND_PATH:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    return KIND_PATH[kinds]


def _decorate(runtime: Runtime, tenant: str, kind: str, item: dict) -> dict:
    if kind == "schedule":
        item["next_runs"] = runtime.water.next_runs(tenant, item)
    elif kind == "rotation":
        tz = runtime.org.timezone(tenant)
        from zoneinfo import ZoneInfo
        item["window"] = runtime.water.rotation_window(item, datetime.now(ZoneInfo(tz)))
    elif kind == "quota":
        item["status"] = runtime.water.quota_status(tenant, item)
    elif kind == "well":
        item["status"] = runtime.water.well_status(tenant, item)
    return item


@router.get("/{kinds}")
def list_items(kinds: str, company: str | None = None, principal: Principal = Depends(authenticate),
               runtime: Runtime = Depends(get_runtime)):
    kind = _kind(kinds)
    tenant = resolve_company(principal, company, runtime)
    return {"items": [_decorate(runtime, tenant, kind, i) for i in runtime.water.list_items(tenant, kind)]}


@router.post("/{kinds}", status_code=201)
def create_item(kinds: str, body: dict, request: Request, company: str | None = None,
                principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    kind = _kind(kinds)
    tenant = resolve_company(principal, company, runtime)
    _writer(principal, tenant)
    item = runtime.water.save_item(tenant, kind, body, principal.username)
    runtime.main.audit(principal.username, f"{kind}_created", company=tenant, target=item["name"], ip=_ip(request))
    return _decorate(runtime, tenant, kind, item)


@router.patch("/{kinds}/{item_id}")
def update_item(kinds: str, item_id: int, body: dict, request: Request, company: str | None = None,
                principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    kind = _kind(kinds)
    tenant = resolve_company(principal, company, runtime)
    _writer(principal, tenant)
    current = runtime.water.get_item(tenant, item_id)
    merged = {**{k: v for k, v in current.items() if k not in ("id", "company", "kind", "state", "updated_at")}, **body}
    item = runtime.water.save_item(tenant, kind, merged, principal.username, item_id)
    runtime.main.audit(principal.username, f"{kind}_updated", company=tenant, target=item["name"], ip=_ip(request))
    return _decorate(runtime, tenant, kind, item)


@router.delete("/{kinds}/{item_id}", status_code=204)
def delete_item(kinds: str, item_id: int, request: Request, company: str | None = None,
                principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    kind = _kind(kinds)
    tenant = resolve_company(principal, company, runtime)
    _writer(principal, tenant)
    runtime.water.delete_item(tenant, item_id)
    runtime.main.audit(principal.username, f"{kind}_deleted", company=tenant, target=str(item_id), ip=_ip(request))


@router.get("/schedules/{item_id}/log")
def schedule_log(item_id: int, company: str | None = None, principal: Principal = Depends(authenticate),
                 runtime: Runtime = Depends(get_runtime)):
    tenant = resolve_company(principal, company, runtime)
    return {"log": runtime.water.item_log(tenant, item_id)}


@router.get("/districts/{item_id}/balance")
def district_balance(item_id: int, company: str | None = None, month: str = Query(..., pattern=r"^\d{4}-\d{2}$"),
                     format: str = Query("json", pattern="^(json|xlsx)$"),
                     principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    """Monthly water balance of a district: system input, billed consumption, non-revenue water and the
    customer statement with meter readings at the start and end of the month."""
    tenant = resolve_company(principal, company, runtime)
    dma = runtime.water.get_item(tenant, item_id)
    if dma["kind"] != "dma":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not a district")
    bal = runtime.water.utility_balance(tenant, dma, month)
    if format == "json":
        return bal
    wb = Workbook(f"WIOT water balance {dma['name']} {month}")
    sh = wb.sheet("Balance").title(f"{dma['name']} — water balance {month}").blank().header(["Item", "m³"])
    for label, key in (("System input volume", "system_input_m3"), ("Billed consumption", "billed_m3"),
                       ("Non-revenue water", "non_revenue_m3")):
        sh.row([label, bal[key]])
    sh.row(["Non-revenue water (%)", bal["non_revenue_pct"]])
    cs = wb.sheet("Customers").header(["Meter (node)", "Customer", "Reading start (m³)", "Reading end (m³)",
                                       "Meter difference (m³)", "Consumption (m³)"])
    for c in bal["customers"]:
        cs.row([c["node_id"], c["customer"], c["reading_start_m3"], c["reading_end_m3"], c["meter_difference_m3"],
                c["consumption_m3"]])
    runtime.usage.count(tenant, "exports")
    return Response(wb.to_bytes(), media_type=XLSX, headers={
        "Content-Disposition": f'attachment; filename="WIOT_{tenant}_{dma["name"].replace(" ", "_")}_{month}.xlsx"'})


@router.post("/schedules/run")
def run_schedules_now(company: str | None = None, principal: Principal = Depends(authenticate),
                      runtime: Runtime = Depends(get_runtime)):
    """Run one scheduler tick now (normally every minute)."""
    tenant = resolve_company(principal, company, runtime)
    _writer(principal, tenant)
    return {"actions": runtime.water.run_schedules(tenant, int(time.time()))}
