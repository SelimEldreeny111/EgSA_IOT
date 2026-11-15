"""Tenant administration: users, companies, audit trail."""
from __future__ import annotations

import csv
import io
import json
import time

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
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
def audit(limit: int = Query(200, ge=1, le=5000), offset: int = Query(0, ge=0, le=1_000_000),
          company: str | None = None, actor: str | None = Query(None, max_length=80),
          action: str | None = Query(None, max_length=60), q: str | None = Query(None, max_length=80),
          since: int | None = None, until: int | None = None,
          format: str = Query("json", pattern="^(json|csv)$"),
          principal: Principal = Depends(require_admin), runtime: Runtime = Depends(get_runtime)):
    """Audit trail with filters (actor, action, free text, time range) and CSV export."""
    scope = (company or None) if principal.is_supervisor else principal.company
    rows = runtime.main.list_audit(scope, limit, actor=actor, action=action, q=q, since=since, until=until,
                                   offset=offset)
    if format == "csv":
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(["time_utc", "actor", "action", "company", "target", "ip", "details"])
        for r in rows:
            w.writerow([time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(r["ts"])), r["actor"], r["action"],
                        r["company"] or "", r["target"] or "", r["ip"] or "", json.dumps(r["details"], default=str)])
        runtime.usage.count(principal.company, "exports")
        return Response(out.getvalue(), media_type="text/csv",
                        headers={"Content-Disposition": 'attachment; filename="wiot_audit.csv"'})
    return {"entries": rows, "actions": runtime.main.audit_actions(scope), "offset": offset, "limit": limit}


# ---------------------------------------------------------------- R2.3 security
def _managed_user(user_id: int, principal: Principal, runtime: Runtime) -> dict:
    target = runtime.main.get_user_by_id(user_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    if not principal.is_supervisor and target["company"] != principal.company:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Cannot manage another company's users")
    return target


class PagesIn(BaseModel):
    pages: list[str] | None = None


@router.put("/users/{user_id}/pages")
def set_user_pages(user_id: int, body: PagesIn, request: Request, principal: Principal = Depends(require_admin),
                   runtime: Runtime = Depends(get_runtime)):
    """Limit which dashboard pages a user sees (null = every page of the role)."""
    target = _managed_user(user_id, principal, runtime)
    runtime.security.set_pages(user_id, body.pages)
    runtime.main.audit(principal.username, "user_pages_set", company=target["company"], target=target["username"],
                       ip=_ip(request), details={"pages": body.pages})
    return {"id": user_id, "pages": body.pages}


@router.post("/users/{user_id}/totp/reset")
def reset_user_totp(user_id: int, request: Request, principal: Principal = Depends(require_admin),
                    runtime: Runtime = Depends(get_runtime)):
    """Turn off a user's two-factor sign-in (lost phone); they can enrol again after signing in."""
    target = _managed_user(user_id, principal, runtime)
    runtime.security.totp_disable(user_id)
    with runtime.main.connect() as db:
        db.execute("UPDATE users SET token_version=token_version+1 WHERE id=?", (user_id,))
    runtime.main.audit(principal.username, "two_factor_reset", company=target["company"], target=target["username"],
                       ip=_ip(request))
    return {"id": user_id, "totp_enabled": False}


@router.get("/sessions")
def list_sessions(principal: Principal = Depends(require_admin), runtime: Runtime = Depends(get_runtime)):
    scope = None if principal.is_supervisor else principal.company
    rows = runtime.security.list_sessions(company=scope)
    for r in rows:
        r["current"] = r["jti"] == principal.session_id
    return {"sessions": rows}


@router.delete("/sessions/{jti}", status_code=204)
def revoke_session(jti: str, request: Request, principal: Principal = Depends(require_admin),
                   runtime: Runtime = Depends(get_runtime)):
    row = runtime.security.get_session(jti)
    if row is None or (not principal.is_supervisor and row["company"] != principal.company):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")
    runtime.security.revoke_session(jti, principal.username)
    runtime.main.audit(principal.username, "session_revoked", company=row["company"], target=row["username"],
                       ip=_ip(request))


class InviteIn(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    role: str = Field(pattern="^(admin|monitor|user)$")
    company: str | None = Field(default=None, max_length=80)
    pages: list[str] | None = None


@router.get("/invitations")
def list_invitations(principal: Principal = Depends(require_admin), runtime: Runtime = Depends(get_runtime)):
    return {"invitations": runtime.security.list_invitations(None if principal.is_supervisor else principal.company),
            "email_enabled": runtime.notifier.smtp_ready()}


INVITE_TEXT = "\n".join((
    "{who} invited you to {company} on the WIOT Control Center as {role}.", "",
    "Open this link within 7 days to choose your username and password:", "{link}", "",
    "If you did not expect this invitation, ignore this e-mail."))


@router.post("/invitations", status_code=201)
def create_invitation(body: InviteIn, request: Request, principal: Principal = Depends(require_admin),
                      runtime: Runtime = Depends(get_runtime)):
    company = (body.company or principal.company) if principal.is_supervisor else principal.company
    inv, token = runtime.security.invite(body.email, body.role, company, principal.username, body.pages)
    base = (runtime.settings.public_url or str(request.base_url)).rstrip("/")
    link = f"{base}/invite#{token}"
    sent, error = False, None
    if runtime.notifier.smtp_ready():
        try:
            display = (runtime.org.get_company(company) or {}).get("display_name") or company
            runtime.notifier.send_email([inv["email"]], f"Invitation to the WIOT Control Center - {display}",
                                        INVITE_TEXT.format(who=principal.username, company=display, role=inv["role"],
                                                           link=link))
            sent = True
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
    runtime.main.audit(principal.username, "invitation_created", company=company, target=inv["email"],
                       ip=_ip(request), details={"role": inv["role"], "emailed": sent})
    return {**inv, "link": link, "emailed": sent, "email_error": error}


@router.delete("/invitations/{inv_id}", status_code=204)
def revoke_invitation(inv_id: int, request: Request, principal: Principal = Depends(require_admin),
                      runtime: Runtime = Depends(get_runtime)):
    inv = runtime.security.get_invitation(inv_id)
    if inv is None or (not principal.is_supervisor and inv["company"] != principal.company):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invitation not found")
    runtime.security.revoke_invitation(inv_id)
    runtime.main.audit(principal.username, "invitation_revoked", company=inv["company"], target=inv["email"],
                       ip=_ip(request))
