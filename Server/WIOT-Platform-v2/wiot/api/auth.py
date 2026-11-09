"""Login, logout, session introspection and password change."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from ..security import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    Principal,
    issue_token,
    verify_password,
)
from ..services.runtime import Runtime
from .deps import authenticate, get_runtime

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=512)


class PasswordIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=512)
    new_password: str = Field(min_length=10, max_length=512)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _set_session(response: Response, runtime: Runtime, principal: Principal) -> dict:
    s = runtime.settings
    token, expires_at, csrf = issue_token(s.secret_key.get_secret_value(), principal, s.token_ttl_minutes)
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
    runtime.throttle.success(*keys)
    runtime.main.touch_login(user["id"])
    principal = Principal(user_id=user["id"], username=user["username"], role=user["role"],
                          company=user["company"] or "", token_version=int(user.get("token_version") or 0))
    runtime.main.audit(user["username"], "login", company=principal.company or None, ip=ip)
    return _set_session(response, runtime, principal)


@router.post("/logout", status_code=204)
def logout(response: Response):
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    response.status_code = 204
    return response


@router.get("/me")
def me(principal: Principal = Depends(authenticate)):
    return {"user": principal.public(), "csrf": principal.csrf}


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
    updated = Principal(user_id=fresh["id"], username=fresh["username"], role=fresh["role"],
                        company=fresh["company"] or "", token_version=int(fresh["token_version"]))
    return _set_session(response, runtime, updated)
