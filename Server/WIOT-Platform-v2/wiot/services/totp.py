"""Time-based one-time passwords (RFC 6238 over RFC 4226 HOTP), standard library only.

Compatible with Google Authenticator, Microsoft Authenticator, Authy, 1Password and similar apps:
SHA-1, 6 digits, 30-second steps, base32 secret of 160 bits.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import struct
import time
from urllib.parse import quote, urlencode

STEP = 30
DIGITS = 6


def new_secret() -> str:
    return base64.b32encode(os.urandom(20)).decode().rstrip("=")


def _key(secret: str) -> bytes:
    s = secret.strip().replace(" ", "").upper()
    return base64.b32decode(s + "=" * (-len(s) % 8))


def hotp(secret: str, counter: int, digits: int = DIGITS) -> str:
    digest = hmac.new(_key(secret), struct.pack(">Q", int(counter)), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(code).zfill(digits)


def now_step(t: float | None = None) -> int:
    return int((time.time() if t is None else t) // STEP)


def totp(secret: str, t: float | None = None) -> str:
    return hotp(secret, now_step(t))


def verify(secret: str, code: str, t: float | None = None, window: int = 1, last_step: int | None = None) -> int | None:
    """Return the matching time step, or None. Accepts +/- ``window`` steps of clock skew and refuses a
    step at or before ``last_step`` (a code cannot be used twice)."""
    code = (code or "").strip().replace(" ", "")
    if not code.isdigit() or len(code) != DIGITS:
        return None
    step = now_step(t)
    for s in range(step - window, step + window + 1):
        if last_step is not None and s <= last_step:
            continue
        if hmac.compare_digest(hotp(secret, s), code):
            return s
    return None


def provisioning_uri(secret: str, account: str, issuer: str = "WIOT") -> str:
    label = quote(f"{issuer}:{account}", safe=":@")
    return f"otpauth://totp/{label}?" + urlencode({"secret": secret, "issuer": issuer, "algorithm": "SHA1",
                                                    "digits": DIGITS, "period": STEP})
