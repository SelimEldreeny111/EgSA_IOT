"""Request-scoped dependencies: runtime, authentication, tenant scoping."""
from __future__ import annotations

import hmac

from fastapi import Depends, HTTPException, Request, WebSocket, status

from ..protocol.topics import DEFAULT_REGION, region_id
from ..protocol.validation import company_id
from ..security import (
    CSRF_HEADER,
    SESSION_COOKIE,
    AuthError,
    Principal,
    decode_token,
)
from ..services.runtime import Runtime

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def get_runtime(request: Request) -> Runtime:
    return request.app.state.runtime


def _principal_from_token(runtime: Runtime, token: str, via_cookie: bool) -> Principal:
    claims = decode_token(runtime.settings.secret_key.get_secret_value(), token)
    user = runtime.main.get_user_by_id(int(claims["uid"]))
    if user is None or user["username"] != claims["sub"] or user.get("disabled"):
        raise AuthError("Account no longer exists")
    if int(user.get("token_version") or 0) != int(claims.get("tv", 0)):
        raise AuthError("Session revoked")
    return Principal(user_id=user["id"], username=user["username"], role=user["role"],
                     company=user["company"] or "", token_version=int(user.get("token_version") or 0),
                     via_cookie=via_cookie, csrf=claims.get("csrf"))


def _principal_from_api_token(runtime: Runtime, token: str) -> Principal:
    row = runtime.org.resolve_token(token)
    if row is None:
        raise AuthError("Invalid, expired or revoked API token")
    if row["company"] not in runtime.main.company_names():
        raise AuthError("API token's company is archived")
    return Principal(user_id=0, username=f"token:{row['prefix']}", role="admin" if row["scope"] == "write" else "user",
                     company=row["company"], token=True)


def authenticate(request: Request) -> Principal:
    runtime = get_runtime(request)
    header = request.headers.get("authorization", "")
    try:
        if header.lower().startswith("bearer "):
            bearer = header[7:].strip()
            principal = (_principal_from_api_token(runtime, bearer) if bearer.startswith("wiot_")
                         else _principal_from_token(runtime, bearer, via_cookie=False))
            request.state.principal = principal
            return principal
        token = request.cookies.get(SESSION_COOKIE)
        if not token:
            raise AuthError("Not authenticated")
        principal = _principal_from_token(runtime, token, via_cookie=True)
    except AuthError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc
    if request.method in UNSAFE_METHODS:
        sent = request.headers.get(CSRF_HEADER, "")
        if not principal.csrf or not hmac.compare_digest(sent, principal.csrf):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "CSRF token missing or invalid")
    request.state.principal = principal
    return principal


def ws_authenticate(websocket: WebSocket) -> Principal:
    runtime: Runtime = websocket.app.state.runtime
    token = websocket.cookies.get(SESSION_COOKIE) or websocket.query_params.get("token")
    if not token:
        raise AuthError("Not authenticated")
    return _principal_from_token(runtime, token, via_cookie=True)


def require_supervisor(principal: Principal = Depends(authenticate)) -> Principal:
    if not principal.is_supervisor:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Supervisor privileges required")
    return principal


def require_admin(principal: Principal = Depends(authenticate)) -> Principal:
    if not principal.can_manage_users:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Administrator privileges required")
    return principal


def resolve_company(principal: Principal, company: str | None, runtime: Runtime,
                    *, allow_all: bool = False) -> str | None:
    """Return the tenant this request may read. ``None`` means "all" (global readers only)."""
    if company:
        company_id(company)
        if not principal.can_read(company):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Cannot read another company")
        if company not in runtime.main.company_names():
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown company")
        return company
    if principal.global_read:
        if allow_all:
            return None
        names = runtime.main.company_names()
        if principal.company in names:
            return principal.company
        if not names:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No companies registered")
        return names[0]
    return principal.company


def resolve_region(region: str | None) -> str:
    return region_id(region or DEFAULT_REGION)
