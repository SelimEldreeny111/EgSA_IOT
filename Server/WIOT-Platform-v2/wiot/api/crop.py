"""Crop care, farm diary, yields, WaPOR, the farmer view and regional dashboards (R2.5)."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ..security import Principal
from ..services.runtime import Runtime
from ..tools.pdf import Document
from ..tools.xlsx import Workbook
from .deps import authenticate, get_runtime, resolve_company, resolve_region

router = APIRouter(tags=["crop"])
public_router = APIRouter(tags=["crop"])
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
TYPE_LABEL = {"sowing": "Sowing / planting", "irrigation": "Irrigation", "fertiliser": "Fertiliser",
              "plant_protection": "Plant protection", "harvest": "Harvest", "maintenance": "Maintenance", "other": "Other"}


def _ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _writer(principal: Principal, company: str) -> None:
    if not principal.can_write(company):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Administrator privileges for this company required")


@router.get("/crop/status")
def crop_status(company: str | None = None, principal: Principal = Depends(authenticate),
                runtime: Runtime = Depends(get_runtime)):
    """Growing degree days since planting and disease / pest risk from the forecast, per field."""
    tenant = resolve_company(principal, company, runtime)
    return {"company": tenant, "fields": runtime.cropcare.field_status(tenant)}


class DiaryIn(BaseModel):
    zone_id: str = Field(max_length=32)
    date: str = Field(max_length=10)
    type: str = Field(max_length=20)
    operator: str | None = Field(None, max_length=80)
    product: str | None = Field(None, max_length=120)
    active_ingredient: str | None = Field(None, max_length=120)
    dose: float | None = Field(None, ge=0)
    unit: str | None = Field(None, max_length=20)
    phi_days: int | None = Field(None, ge=0, le=365)
    quantity_kg: float | None = Field(None, ge=0)
    water_m3: float | None = Field(None, ge=0)
    method: str | None = Field(None, max_length=80)
    target: str | None = Field(None, max_length=120)
    lot: str | None = Field(None, max_length=60)
    notes: str | None = Field(None, max_length=1000)


@router.get("/crop/diary")
def diary(company: str | None = None, zone_id: str | None = None, start: str | None = None, end: str | None = None,
          principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    tenant = resolve_company(principal, company, runtime)
    return {"entries": runtime.cropcare.entries(tenant, zone_id, start, end)}


@router.post("/crop/diary", status_code=201)
def add_diary(body: DiaryIn, request: Request, company: str | None = None, principal: Principal = Depends(authenticate),
              runtime: Runtime = Depends(get_runtime)):
    tenant = resolve_company(principal, company, runtime)
    _writer(principal, tenant)
    entry = runtime.cropcare.add_entry(tenant, body.model_dump(exclude_none=True), principal.username)
    runtime.main.audit(principal.username, "diary_entry_added", company=tenant, target=body.zone_id, ip=_ip(request),
                       details={"type": body.type, "date": body.date})
    return entry


@router.delete("/crop/diary/{entry_id}", status_code=204)
def delete_diary(entry_id: int, request: Request, company: str | None = None, principal: Principal = Depends(authenticate),
                 runtime: Runtime = Depends(get_runtime)):
    tenant = resolve_company(principal, company, runtime)
    _writer(principal, tenant)
    runtime.cropcare.delete_entry(tenant, entry_id)
    runtime.main.audit(principal.username, "diary_entry_deleted", company=tenant, target=str(entry_id), ip=_ip(request))


@router.get("/crop/traceability")
def traceability(zone_id: str, start: str, end: str, company: str | None = None,
                 format: str = Query("json", pattern="^(json|xlsx|pdf)$"),
                 principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    """GlobalG.A.P.-style traceability record of one field and season (operations, sprays, PHI check)."""
    tenant = resolve_company(principal, company, runtime)
    date.fromisoformat(start), date.fromisoformat(end)
    rec = runtime.cropcare.traceability(tenant, zone_id, start, end)
    if format == "json":
        return rec
    runtime.usage.count(tenant, "exports")
    name = f"WIOT_traceability_{tenant}_{zone_id}_{start}_{end}"
    cols = [("Date", "date"), ("Operation", "type"), ("Product", "product"), ("Active ingredient", "active_ingredient"),
            ("Dose", "dose"), ("Unit", "unit"), ("PHI (days)", "phi_days"), ("Quantity (kg)", "quantity_kg"),
            ("Operator", "operator"), ("Notes", "notes")]
    if format == "xlsx":
        wb = Workbook(name)
        sh = wb.sheet("Field record").title(f"{rec['field']} — traceability {start} to {end}").blank()
        sh.header(["Item", "Value"])
        for label, value in (("Company", tenant), ("Field", rec["field"]), ("Area (ha)", rec["area_ha"]),
                             ("Water applied (m³)", rec["water_m3"]), ("Harvested (kg)", rec["harvest_kg"]),
                             ("Pre-harvest intervals respected", "yes" if rec["phi_ok"] else "NO")):
            sh.row([label, value])
        ops = wb.sheet("Operations").header([c for c, _ in cols])
        for o in rec["operations"]:
            ops.row([TYPE_LABEL.get(o.get(k), o.get(k)) if k == "type" else o.get(k) for _, k in cols])
        ph = wb.sheet("PHI check").header(["Harvest", "Spray", "Product", "PHI (days)", "Safe from", "OK"])
        for c in rec["phi_checks"]:
            ph.row([c["harvest"], c["spray"], c["product"], c["phi_days"], c["safe_from"], "yes" if c["ok"] else "NO"])
        return Response(wb.to_bytes(), media_type=XLSX, headers={"Content-Disposition": f'attachment; filename="{name}.xlsx"'})
    doc = Document(name)
    doc.footer = f"{tenant} · {rec['field']} · traceability record generated by the WIOT Platform"
    doc.heading(f"{rec['field']} - traceability record", 16)
    doc.paragraph(f"Season {start} to {end} · {rec['area_ha']} ha · company {tenant}")
    doc.kpis([("Operations", str(len(rec["operations"]))), ("Water applied", f"{rec['water_m3']:,.0f} m³"),
              ("Harvested", f"{rec['harvest_kg']:,.0f} kg"), ("PHI respected", "yes" if rec["phi_ok"] else "NO")])
    doc.heading("Operations", 12)
    doc.table(["Date", "Operation", "Product", "Dose", "PHI", "Qty kg", "Operator"],
              [[o["date"], TYPE_LABEL.get(o["type"], o["type"]), o.get("product") or "",
                f"{o['dose']} {o.get('unit') or ''}".strip() if o.get("dose") is not None else "", o.get("phi_days") or "",
                o.get("quantity_kg") or "", o.get("operator") or ""] for o in rec["operations"]] or [["No operations recorded"] + [""] * 6],
              [1.1, 1.4, 1.8, 0.9, 0.6, 0.8, 1.2], ["l", "l", "l", "r", "r", "r", "l"])
    if rec["phi_checks"]:
        doc.heading("Pre-harvest interval check", 12)
        doc.table(["Harvest", "Spray", "Product", "PHI days", "Safe from", "Result"],
                  [[c["harvest"], c["spray"], c["product"], c["phi_days"], c["safe_from"], "OK" if c["ok"] else "VIOLATION"]
                   for c in rec["phi_checks"]], [1, 1, 2, 0.8, 1, 1], ["l", "l", "l", "r", "l", "l"])
    return Response(doc.to_bytes(), media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{name}.pdf"'})


@router.get("/crop/productivity")
def productivity(company: str | None = None, principal: Principal = Depends(authenticate),
                 runtime: Runtime = Depends(get_runtime)):
    tenant = resolve_company(principal, company, runtime)
    return {"fields": runtime.cropcare.productivity(tenant)}


@router.get("/crop/wapor")
def wapor(company: str | None = None, principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    tenant = resolve_company(principal, company, runtime)
    return {"rows": runtime.cropcare.wapor_comparison(tenant)}


@router.post("/crop/wapor/import")
async def wapor_import(request: Request, company: str | None = None, principal: Principal = Depends(authenticate),
                       runtime: Runtime = Depends(get_runtime)):
    """CSV body: field,month,aeti_mm (monthly AETI exported from the FAO WaPOR portal)."""
    tenant = resolve_company(principal, company, runtime)
    _writer(principal, tenant)
    text = (await request.body()).decode("utf-8-sig", errors="replace")
    n = runtime.cropcare.import_wapor_csv(tenant, text)
    runtime.main.audit(principal.username, "wapor_imported", company=tenant, ip=_ip(request), details={"rows": n})
    return {"imported": n}


# ------------------------------------------------------------- farmer view
@router.get("/farmer/today")
def farmer_today(company: str | None = None, region: str | None = None, principal: Principal = Depends(authenticate),
                 runtime: Runtime = Depends(get_runtime)):
    tenant = resolve_company(principal, company, runtime)
    return {"company": tenant, **runtime.cropcare.farmer_today(tenant, resolve_region(region))}


@public_router.get("/farmer", include_in_schema=False)
def farmer_page(request: Request):
    runtime: Runtime = request.app.state.runtime
    return FileResponse(runtime.settings.web_dir / "farmer.html", headers={"Cache-Control": "no-store"})


# ---------------------------------------------------------- regional view
@router.get("/regional")
def regional(principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    """Aggregated water use and crop health per area; no farm-level data (global readers only)."""
    if not principal.global_read:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Regional dashboards need a national (global) account")
    return runtime.regional.overview()
