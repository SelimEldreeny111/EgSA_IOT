"""Tenant administration: users, companies, audit trail."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from ..security import Principal
from ..services.runtime import Runtime
from .deps import authenticate, get_runtime, require_admin, require_supervisor

router = APIRouter(tags=["administration"])


class UserIn(BaseModel):
    username: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=10, max_length=512)
    role: str = Field(pattern="^(admin|monitor|user)$")
    company: str | None = Field(default=None, max_length=80)


class CompanyIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)


def _ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.get("/users")
def list_users(principal: Principal = Depends(require_admin), runtime: Runtime = Depends(get_runtime)):
    scope = None if principal.is_supervisor else principal.company
    return {"users": runtime.main.list_users(scope)}


@router.post("/users", status_code=201)
def create_user(body: UserIn, request: Request, principal: Principal = Depends(require_admin),
                runtime: Runtime = Depends(get_runtime)):
    company = (body.company or "").strip() if principal.is_supervisor else principal.company
    company = company or principal.company
    if not company:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Company is required")
    user_id = runtime.main.create_user(body.username, body.password, body.role, company)
    runtime.main.audit(principal.username, "user_created", company=company, target=body.username,
                       ip=_ip(request), details={"role": body.role})
    return {"id": user_id}


@router.delete("/users/{user_id}", status_code=204)
def delete_user(user_id: int, request: Request, principal: Principal = Depends(require_admin),
                runtime: Runtime = Depends(get_runtime)):
    target = runtime.main.get_user_by_id(user_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    if target["id"] == principal.user_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You cannot delete your own account")
    if not principal.is_supervisor and target["company"] != principal.company:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Cannot manage another company's users")
    removed = runtime.main.delete_user(user_id)
    runtime.main.audit(principal.username, "user_deleted", company=removed["company"],
                       target=removed["username"], ip=_ip(request))


@router.get("/companies")
def list_companies(principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    rows = runtime.org.list_companies(include_archived=False)  # includes country / time zone / units / language
    if not principal.global_read:
        rows = [r for r in rows if r["name"] == principal.company]
    return {"companies": rows}


@router.post("/companies", status_code=201)
def add_company(body: CompanyIn, request: Request, principal: Principal = Depends(require_supervisor),
                runtime: Runtime = Depends(get_runtime)):
    name = body.name.strip()
    runtime.main.add_company(name)
    runtime.telemetry.ensure(name)
    runtime.main.audit(principal.username, "company_created", company=name, ip=_ip(request))
    return {"name": name}


@router.get("/audit")
def audit(limit: int = Query(200, ge=1, le=1000), principal: Principal = Depends(require_admin),
          runtime: Runtime = Depends(get_runtime)):
    scope = None if principal.is_supervisor else principal.company
    return {"entries": runtime.main.list_audit(scope, limit)}
