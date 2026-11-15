"""OpenID Connect single sign-on (R2.3, point 21): authorization-code flow with PKCE.

Works with any standards-compliant identity provider (Microsoft Entra ID, Google Workspace, Keycloak,
Okta, Auth0). Configure ``WIOT_OIDC_ISSUER``, ``WIOT_OIDC_CLIENT_ID`` (and ``WIOT_OIDC_CLIENT_SECRET`` for a
confidential client) and register ``<public URL>/api/v2/auth/oidc/callback`` as the redirect URI at the provider.

Flow: ``/auth/oidc/login`` stores state, nonce and the PKCE verifier in a short-lived signed cookie and
redirects to the provider; ``/auth/oidc/callback`` exchanges the code (with the verifier), verifies the ID
token's signature against the provider's JWKS, its issuer, audience, expiry and nonce, then maps the person to
a WIOT account:

1. a user already linked to this identity (``users.sso_subject`` = ``issuer|sub``);
2. else a user whose ``email`` matches the verified e-mail (linked on first sign-in);
3. else, when ``WIOT_OIDC_AUTO_CREATE`` is on, a new account with the role and company from the token claims
   (``WIOT_OIDC_ROLE_CLAIM`` / ``WIOT_OIDC_COMPANY_CLAIM``) or the configured defaults.

``WIOT_OIDC_ALLOWED_DOMAINS`` limits sign-in to e-mail domains. Two-factor sign-in is the provider's job for SSO.
"""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
import urllib.parse
import urllib.request

import jwt

STATE_TTL_S = 600
DISCOVERY_TTL_S = 3600


def _fetch_json(url: str, data: dict | None = None, timeout: float = 10.0) -> dict:
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers={"Accept": "application/json", **(
        {"Content-Type": "application/x-www-form-urlencoded"} if body else {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:      # noqa: S310 - provider URLs are configured
        return json.loads(resp.read().decode())


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


class OidcError(Exception):
    pass


class OidcClient:
    def __init__(self, settings, fetch=_fetch_json):
        self.settings = settings
        self.fetch = fetch
        self._discovery: tuple[float, dict] | None = None
        self._jwks: tuple[float, dict] | None = None

    @property
    def enabled(self) -> bool:
        s = self.settings
        return bool(s.oidc_issuer and s.oidc_client_id)

    def public_info(self) -> dict:
        return {"enabled": self.enabled, "label": self.settings.oidc_button_label}

    def discovery(self) -> dict:
        if self._discovery and time.time() - self._discovery[0] < DISCOVERY_TTL_S:
            return self._discovery[1]
        issuer = self.settings.oidc_issuer.rstrip("/")
        doc = self.fetch(f"{issuer}/.well-known/openid-configuration")
        for key in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
            if not doc.get(key):
                raise OidcError(f"Provider discovery document has no {key}")
        self._discovery = (time.time(), doc)
        return doc

    def _secret(self) -> str:
        return self.settings.secret_key.get_secret_value()

    def begin(self, redirect_uri: str) -> tuple[str, str]:
        """Return (provider URL to redirect to, signed state cookie)."""
        doc = self.discovery()
        state, nonce, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(24), secrets.token_urlsafe(48)
        challenge = _b64(hashlib.sha256(verifier.encode()).digest())
        params = {"response_type": "code", "client_id": self.settings.oidc_client_id, "redirect_uri": redirect_uri,
                  "scope": self.settings.oidc_scopes, "state": state, "nonce": nonce,
                  "code_challenge": challenge, "code_challenge_method": "S256"}
        cookie = jwt.encode({"st": state, "n": nonce, "v": verifier, "r": redirect_uri,
                             "exp": int(time.time()) + STATE_TTL_S, "aud": "wiot-oidc"}, self._secret(), "HS256")
        sep = "&" if "?" in doc["authorization_endpoint"] else "?"
        return doc["authorization_endpoint"] + sep + urllib.parse.urlencode(params), cookie

    def _keys(self, force: bool = False) -> jwt.PyJWKSet:
        if force or not self._jwks or time.time() - self._jwks[0] > DISCOVERY_TTL_S:
            self._jwks = (time.time(), self.fetch(self.discovery()["jwks_uri"]))
        return jwt.PyJWKSet.from_dict(self._jwks[1])

    def finish(self, code: str, state: str, cookie: str | None) -> dict:
        """Exchange the code and return the verified ID-token claims."""
        if not cookie:
            raise OidcError("Sign-in session expired; start again")
        try:
            saved = jwt.decode(cookie, self._secret(), algorithms=["HS256"], audience="wiot-oidc")
        except jwt.PyJWTError as exc:
            raise OidcError("Sign-in session expired; start again") from exc
        if not secrets.compare_digest(saved["st"], state or ""):
            raise OidcError("State does not match; start again")
        doc = self.discovery()
        form = {"grant_type": "authorization_code", "code": code, "redirect_uri": saved["r"],
                "client_id": self.settings.oidc_client_id, "code_verifier": saved["v"]}
        if self.settings.oidc_client_secret:
            form["client_secret"] = self.settings.oidc_client_secret.get_secret_value()
        tokens = self.fetch(doc["token_endpoint"], form)
        id_token = tokens.get("id_token")
        if not id_token:
            raise OidcError("Provider returned no ID token")
        kid = jwt.get_unverified_header(id_token).get("kid")
        keyset = self._keys()
        try:
            key = keyset[kid] if kid else keyset.keys[0]
        except KeyError:
            key = self._keys(force=True)[kid]                # provider rotated its keys
        try:
            claims = jwt.decode(id_token, key.key, algorithms=["RS256", "RS384", "RS512", "ES256", "ES384", "PS256"],
                                audience=self.settings.oidc_client_id, issuer=doc.get("issuer", self.settings.oidc_issuer),
                                options={"require": ["exp", "iat", "sub"]}, leeway=60)
        except jwt.PyJWTError as exc:
            raise OidcError(f"ID token rejected: {exc}") from exc
        if not secrets.compare_digest(str(claims.get("nonce", "")), saved["n"]):
            raise OidcError("ID token nonce does not match")
        return claims

    # ------------------------------------------------------------- mapping
    def identity(self, claims: dict) -> dict:
        s = self.settings
        email = (claims.get("email") or claims.get("preferred_username") or claims.get("upn") or "").strip().lower()
        if claims.get("email_verified") is False:
            raise OidcError("The provider has not verified this e-mail address")
        if s.oidc_allowed_domains:
            domain = email.rsplit("@", 1)[-1] if "@" in email else ""
            if domain not in {d.lower() for d in s.oidc_allowed_domains}:
                raise OidcError("This e-mail domain may not sign in here")
        role = claims.get(s.oidc_role_claim) if s.oidc_role_claim else None
        if isinstance(role, list):
            role = next((r for r in role if r in ("admin", "monitor", "user")), None)
        company = claims.get(s.oidc_company_claim) if s.oidc_company_claim else None
        return {"subject": f"{doc_issuer(claims)}|{claims['sub']}", "email": email,
                "name": claims.get("name") or email, "role": role if role in ("admin", "monitor", "user") else None,
                "company": company if isinstance(company, str) else None}


def doc_issuer(claims: dict) -> str:
    return str(claims.get("iss", "")).rstrip("/")


def username_for(email: str) -> str:
    base = "".join(c if c.isalnum() or c in "._-" else "." for c in email.replace("@", ".")).strip(".")
    return (base or "sso.user")[:70]
