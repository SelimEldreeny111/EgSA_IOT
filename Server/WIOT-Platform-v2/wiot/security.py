"""Authentication primitives: principals, password hashing, JWT and throttling.

Role model (compatible with the v1.31 ``users`` table):

* ``supervisor`` — the built-in ``EgSA_Supervisor`` account (or role
  ``supervisor``). Global scope; owns MQTT ingestion and tenant management.
* ``admin``      — company administrator: users of its company and commands.
* ``monitor``    — read-only. The built-in ``Super_User`` monitor may read
  every company (v1 behaviour); other monitors are scoped to their company.
* ``user``       — read-only within its company.
"""
from __future__ import annotations

import secrets
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field

import jwt
from werkzeug.security import check_password_hash, generate_password_hash

SUPERVISOR_USERNAME = "EgSA_Supervisor"
GLOBAL_MONITOR_USERNAME = "Super_User"
ROLES = ("supervisor", "admin", "monitor", "user")
JWT_ALG = "HS256"
SESSION_COOKIE = "wiot_session"
CSRF_COOKIE = "wiot_csrf"
CSRF_HEADER = "X-CSRF-Token"


class AuthError(Exception):
    def __init__(self, message: str, status: int = 401):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Principal:
    user_id: int
    username: str
    role: str
    company: str
    token_version: int = 0
    via_cookie: bool = False
    csrf: str | None = field(default=None, compare=False)
    token: bool = False  # authenticated with an API token (machine access), not a user session

    @property
    def is_supervisor(self) -> bool:
        return self.role == "supervisor" or self.username == SUPERVISOR_USERNAME

    @property
    def effective_role(self) -> str:
        return "supervisor" if self.is_supervisor else self.role

    @property
    def global_read(self) -> bool:
        return self.is_supervisor or self.username == GLOBAL_MONITOR_USERNAME

    @property
    def can_command(self) -> bool:
        return self.is_supervisor or self.role == "admin"

    @property
    def can_manage_users(self) -> bool:
        return not self.token and (self.is_supervisor or self.role == "admin")

    def can_read(self, company: str) -> bool:
        return self.global_read or company == self.company

    def can_write(self, company: str) -> bool:
        return self.can_command and (self.is_supervisor or company == self.company)

    def public(self) -> dict:
        return {
            "id": self.user_id,
            "username": self.username,
            "role": self.effective_role,
            "company": self.company,
            "permissions": {
                "global_read": self.global_read,
                "command": self.can_command,
                "manage_users": self.can_manage_users,
                "supervisor": self.is_supervisor,
            },
        }


def hash_password(password: str) -> str:
    return generate_password_hash(password)


def verify_password(stored_hash: str | None, password: str) -> bool:
    if not stored_hash or not password:
        return False
    try:
        return check_password_hash(stored_hash, password)
    except (ValueError, TypeError):
        return False


def validate_new_password(password: str) -> None:
    if not isinstance(password, str) or len(password) < 10:
        raise ValueError("Password must be at least 10 characters")
    if len(password) > 512:
        raise ValueError("Password is too long")
    classes = sum(
        (
            any(c.islower() for c in password),
            any(c.isupper() for c in password),
            any(c.isdigit() for c in password),
            any(not c.isalnum() for c in password),
        )
    )
    if classes < 3:
        raise ValueError("Password needs 3 of: lowercase, uppercase, digit, symbol")


def issue_token(secret: str, principal: Principal, ttl_minutes: int) -> tuple[str, int, str]:
    """Return (jwt, expires_at_epoch, csrf_token)."""
    now = int(time.time())
    exp = now + ttl_minutes * 60
    csrf = secrets.token_urlsafe(24)
    claims = {
        "sub": principal.username,
        "uid": principal.user_id,
        "role": principal.role,
        "company": principal.company,
        "tv": principal.token_version,
        "csrf": csrf,
        "iat": now,
        "exp": exp,
        "jti": secrets.token_hex(8),
        "iss": "wiot-platform",
    }
    return jwt.encode(claims, secret, algorithm=JWT_ALG), exp, csrf


def decode_token(secret: str, token: str) -> dict:
    try:
        return jwt.decode(
            token, secret, algorithms=[JWT_ALG], issuer="wiot-platform",
            options={"require": ["exp", "iat", "sub", "uid"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("Session expired") from exc
    except jwt.PyJWTError as exc:
        raise AuthError("Invalid session") from exc


class LoginThrottle:
    """Sliding-window limiter keyed by client IP and username."""

    def __init__(self, max_attempts: int, window_seconds: int):
        self.max_attempts = max_attempts
        self.window = window_seconds
        self._failures: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> deque[float]:
        bucket = self._failures[key]
        while bucket and now - bucket[0] > self.window:
            bucket.popleft()
        return bucket

    def check(self, *keys: str) -> int:
        """Return seconds to wait (0 when allowed)."""
        now = time.monotonic()
        with self._lock:
            waits = []
            for key in keys:
                bucket = self._prune(key, now)
                if len(bucket) >= self.max_attempts:
                    waits.append(int(self.window - (now - bucket[0])) + 1)
            return max(waits, default=0)

    def failure(self, *keys: str) -> None:
        now = time.monotonic()
        with self._lock:
            for key in keys:
                self._prune(key, now).append(now)

    def success(self, *keys: str) -> None:
        with self._lock:
            for key in keys:
                self._failures.pop(key, None)
