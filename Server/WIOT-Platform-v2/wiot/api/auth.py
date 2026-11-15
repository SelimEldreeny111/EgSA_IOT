"""Login (password, two-factor, SSO), logout, sessions, invitations and password change."""
from __future__ import annotations

import secrets
import time

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from ..security import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    Principal,
    issue_token,
    verify_password,
)
from ..services.oidc import OidcError, username_for
from ..services.runtime import Runtime
from .deps import authenticate, get_runtime

router = APIRouter(prefix="/auth", tags=["auth"])
OIDC_COOKIE = "wiot_oidc"


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=512)
    otp: str | None = Field(default=None, max_length=32)


class PasswordIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=512)
    new_password: str = Field(min_length=10, max_length=512)


class CodeIn(BaseModel):
    code: str = Field(min_length=6, max_length=32)


class DisableIn(BaseModel):
    password: str = Field(min_length=1, max_length=512)


class AcceptIn(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    username: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=10, max_length=512)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _principal(user: dict) -> Principal:
    return Principal(user_id=user["id"], username=user["username"], role=user["role"],
                     company=user["company"] or "", token_version=int(user.get("token_version") or 0))


def _set_session(response: Response, runtime: Runtime, principal: Principal, request: Request | None = None,
                 method: str = "password") -> dict:
    s = runtime.settings
    token, expires_at, csrf = issue_token(s.secret_key.get_secret_value(), principal, s.token_ttl_minutes)
    jti = jwt.decode(token, options={"verify_signature": False}).get("jti")
    runtime.security.record_session(jti, {"id": principal.user_id, "username": principal.username}, expires_at,
                                    _client_ip(request) if request else None,
                                    request.headers.get("user-agent") if request else None, method)
    max_age = s.token_ttl_minutes * 60
    response.set_cookie(SESSION_COOKIE, token, max_age=max_age, httponly=True,
                        secure=s.cookie_secure, samesite="lax", path="/")
    response.set_cookie(CSRF_COOKIE, csrf, max_age=max_age, httponly=False,
                        secure=s.cookie_secure, samesite="lax", path="/")
    return {"user": principal.public(), "csrf": csrf, "expires_at": expires_at, "token": token}


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response,
          runtime: Runtime = Depends(get_runtime)):
    ip = _client_ip(request)
    keys = (f"ip:{ip}", f"user:{body.username.lower()}")
    wait = runtime.throttle.check(*keys)
    if wait:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            f"Too many failed attempts; retry in {wait} s",
                            headers={"Retry-After": str(wait)})
    user = runtime.main.get_user(body.username)
    if not user or user.get("disabled") or not verify_password(user["password"], body.password):
        runtime.throttle.failure(*keys)
        runtime.main.audit(body.username, "login_failed", ip=ip)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password")
    method = "password"
    if user.get("totp_enabled"):
        if not body.otp:
            return JSONResponse({"detail": "Enter the 6-digit code from your authenticator app", "otp_required": True},
                                status_code=401)
        used = runtime.security.check_second_factor(user, body.otp)
        if used is None:
            runtime.throttle.failure(*keys)
            runtime.main.audit(user["username"], "login_failed", company=user["company"], ip=ip,
                               details={"reason": "second factor"})
            return JSONResponse({"detail": "The code is not valid", "otp_required": True}, status_code=401)
        method = used
        if used == "recovery":
            runtime.main.audit(user["username"], "recovery_code_used", company=user["company"], ip=ip)
    runtime.throttle.success(*keys)
    runtime.main.touch_login(user["id"])
    principal = _principal(user)
    runtime.main.audit(user["username"], "login", company=principal.company or None, ip=ip,
                       details={"method": method})
    return _set_session(response, runtime, principal, request, method)


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, runtime: Runtime = Depends(get_runtime)):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        try:
            jti = jwt.decode(token, runtime.settings.secret_key.get_secret_value(), algorithms=["HS256"],
                             issuer="wiot-platform").get("jti")
            if jti:
                runtime.security.revoke_session(jti, "logout")
        except jwt.PyJWTError:
            pass
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    response.status_code = 204
    return response


@router.get("/me")
def me(principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    user = runtime.main.get_user_by_id(principal.user_id) or {} if not principal.token else {}
    return {"user": {**principal.public(), "pages": runtime.security.pages_of(user) if user else None,
                     "email": user.get("email"), "two_factor": bool(user.get("totp_enabled"))},
            "csrf": principal.csrf}


@router.post("/password")
def change_password(body: PasswordIn, request: Request, response: Response,
                    principal: Principal = Depends(authenticate),
                    runtime: Runtime = Depends(get_runtime)):
    user = runtime.main.get_user_by_id(principal.user_id)
    if not user or not verify_password(user["password"], body.current_password):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect")
    runtime.main.set_password(principal.user_id, body.new_password)
    runtime.main.audit(principal.username, "password_changed", company=principal.company or None,
                       ip=_client_ip(request))
    fresh = runtime.main.get_user_by_id(principal.user_id)
    return _set_session(response, runtime, _principal(fresh), request)


# ------------------------------------------------------------ two-factor
def _own_user(principal: Principal, runtime: Runtime) -> dict:
    if principal.token:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not available to API tokens")
    user = runtime.main.get_user_by_id(principal.user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return user


@router.get("/totp")
def totp_status(principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    return runtime.security.totp_status(_own_user(principal, runtime)["id"])


@router.post("/totp/setup")
def totp_setup(principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    """Start enrolment: returns the secret (for manual entry) and the otpauth:// URI (for a QR code)."""
    return runtime.security.totp_begin(_own_user(principal, runtime), issuer="WIOT")


@router.post("/totp/enable")
def totp_enable(body: CodeIn, request: Request, response: Response, principal: Principal = Depends(authenticate),
                runtime: Runtime = Depends(get_runtime)):
    user = _own_user(principal, runtime)
    codes = runtime.security.totp_enable(user, body.code)
    runtime.main.audit(principal.username, "two_factor_enabled", company=principal.company or None,
                       ip=_client_ip(request))
    fresh = runtime.main.get_user_by_id(user["id"])            # other sessions were signed out
    session = _set_session(response, runtime, _principal(fresh), request, "totp")
    return {"recovery_codes": codes, "csrf": session["csrf"]}


@router.post("/totp/disable")
def totp_disable(body: DisableIn, request: Request, principal: Principal = Depends(authenticate),
                 runtime: Runtime = Depends(get_runtime)):
    user = _own_user(principal, runtime)
    if not verify_password(user["password"], body.password):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Password is incorrect")
    runtime.security.totp_disable(user["id"])
    runtime.main.audit(principal.username, "two_factor_disabled", company=principal.company or None,
                       ip=_client_ip(request))
    return runtime.security.totp_status(user["id"])


# -------------------------------------------------------------- sessions
@router.get("/sessions")
def my_sessions(principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    rows = runtime.security.list_sessions(user_id=_own_user(principal, runtime)["id"])
    for r in rows:
        r["current"] = r["jti"] == principal.session_id
    return {"sessions": rows}


@router.delete("/sessions/{jti}", status_code=204)
def revoke_my_session(jti: str, request: Request, principal: Principal = Depends(authenticate),
                      runtime: Runtime = Depends(get_runtime)):
    row = runtime.security.get_session(jti)
    if row is None or row["user_id"] != principal.user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")
    runtime.security.revoke_session(jti, principal.username)
    runtime.main.audit(principal.username, "session_revoked", company=principal.company or None,
                       ip=_client_ip(request), target=jti[:6])


@router.post("/sessions/revoke-others")
def revoke_other_sessions(request: Request, principal: Principal = Depends(authenticate),
                          runtime: Runtime = Depends(get_runtime)):
    n = 0
    for r in runtime.security.list_sessions(user_id=principal.user_id):
        if r["jti"] != principal.session_id and runtime.security.revoke_session(r["jti"], principal.username):
            n += 1
    runtime.main.audit(principal.username, "sessions_revoked", company=principal.company or None,
                       ip=_client_ip(request), details={"count": n})
    return {"revoked": n}


# ------------------------------------------------------------ invitations
@router.get("/invitations/{token}")
def invitation_info(token: str, runtime: Runtime = Depends(get_runtime)):
    try:
        inv = runtime.security.lookup_invitation(token)
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    company = runtime.org.get_company(inv["company"]) or {}
    return {"email": inv["email"], "role": inv["role"], "company": company.get("display_name") or inv["company"],
            "expires_at": inv["expires_at"]}


@router.post("/invitations/accept")
def accept_invitation(body: AcceptIn, request: Request, response: Response, runtime: Runtime = Depends(get_runtime)):
    user = runtime.security.accept_invitation(body.token, body.username.strip(), body.password)
    runtime.main.audit(user["username"], "invitation_accepted", company=user["company"], ip=_client_ip(request))
    return _set_session(response, runtime, _principal(user), request)


# -------------------------------------------------------------------- SSO
def _redirect_uri(request: Request, runtime: Runtime) -> str:
    base = (runtime.settings.public_url or str(request.base_url)).rstrip("/")
    return f"{base}/api/v2/auth/oidc/callback"


@router.get("/oidc")
def oidc_info(runtime: Runtime = Depends(get_runtime)):
    return runtime.oidc.public_info()


@router.get("/oidc/login")
def oidc_login(request: Request, runtime: Runtime = Depends(get_runtime)):
    if not runtime.oidc.enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Single sign-on is not configured")
    try:
        url, cookie = runtime.oidc.begin(_redirect_uri(request, runtime))
    except Exception as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Identity provider unreachable: {exc}") from exc
    resp = RedirectResponse(url, status_code=302)
    resp.set_cookie(OIDC_COOKIE, cookie, max_age=600, httponly=True, secure=runtime.settings.cookie_secure,
                    samesite="lax", path="/api/v2/auth/oidc")
    return resp


def _login_error(message: str) -> RedirectResponse:
    from urllib.parse import quote
    return RedirectResponse(f"/login?sso_error={quote(message)}", status_code=302)


@router.get("/oidc/callback")
def oidc_callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None,
                  error_description: str | None = None, runtime: Runtime = Depends(get_runtime)):
    if error:
        return _login_error(error_description or error)
    if not runtime.oidc.enabled or not code:
        return _login_error("Single sign-on is not available")
    ip = _client_ip(request)
    try:
        claims = runtime.oidc.finish(code, state or "", request.cookies.get(OIDC_COOKIE))
        ident = runtime.oidc.identity(claims)
    except OidcError as exc:
        runtime.main.audit("sso", "login_failed", ip=ip, details={"reason": str(exc)})
        return _login_error(str(exc))
    except Exception as exc:
        return _login_error(f"Identity provider error: {type(exc).__name__}")
    user = _sso_user(runtime, ident)
    if user is None:
        runtime.main.audit(ident["email"] or "sso", "login_failed", ip=ip, details={"reason": "no matching account"})
        return _login_error("No WIOT account is linked to this identity; ask an administrator for an invitation")
    if user.get("disabled"):
        return _login_error("This account is disabled")
    runtime.main.touch_login(user["id"])
    runtime.main.audit(user["username"], "login", company=user["company"], ip=ip, details={"method": "sso"})
    resp = RedirectResponse("/", status_code=302)
    _set_session(resp, runtime, _principal(user), request, "sso")
    resp.delete_cookie(OIDC_COOKIE, path="/api/v2/auth/oidc")
    return resp


def _sso_user(runtime: Runtime, ident: dict) -> dict | None:
    s = runtime.settings
    with runtime.main.connect() as db:
        row = db.execute("SELECT * FROM users WHERE sso_subject=?", (ident["subject"],)).fetchone()
        if row is None and ident["email"]:
            row = db.execute("SELECT * FROM users WHERE lower(email)=? AND sso_subject IS NULL",
                             (ident["email"],)).fetchone()
            if row is not None:
                db.execute("UPDATE users SET sso_subject=? WHERE id=?", (ident["subject"], row["id"]))
    if row is not None:
        return dict(row)
    if not s.oidc_auto_create or not ident["email"]:
        return None
    company = ident["company"] if ident["company"] in runtime.main.company_names() else s.oidc_default_company
    if company not in runtime.main.company_names():
        return None
    username = username_for(ident["email"])
    if runtime.main.get_user(username):
        username = f"{username[:60]}.{secrets.token_hex(2)}"
    password = f"Sso-{secrets.token_urlsafe(24)}-9a"           # never used: sign-in is through the provider
    user_id = runtime.main.create_user(username, password, ident["role"] or s.oidc_default_role, company)
    with runtime.main.connect() as db:
        db.execute("UPDATE users SET email=?, sso_subject=? WHERE id=?", (ident["email"], ident["subject"], user_id))
    runtime.main.audit("sso", "user_created", company=company, target=username,
                       details={"email": ident["email"], "at": int(time.time())})
    return runtime.main.get_user_by_id(user_id)
