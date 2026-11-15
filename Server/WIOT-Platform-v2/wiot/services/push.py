"""Web Push for the installable dashboard (R2.6, point 24), with no third-party push library.

* **VAPID** (RFC 8292): the server's P-256 key pair is created on first use in ``data/vapid_private.pem``; each
  push carries ``Authorization: vapid t=<ES256 JWT for the push service origin>, k=<public key>``.
* **Payload encryption** (RFC 8291, ``aes128gcm`` of RFC 8188): ECDH between a fresh server key and the
  browser's ``p256dh`` key, HKDF with the browser's ``auth`` secret, AES-128-GCM, one record.
* **Subscriptions** are per user and browser (``push_subscriptions``); alerts of the user's company (warning and
  critical) are pushed to every browser of every user who may read that company. A push service answering 404 or
  410 means the subscription is gone and it is deleted.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import queue
import struct
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

import jwt
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .notify import alert_text, http_request

log = logging.getLogger(__name__)
SEVERITY_MIN = {"warning", "critical"}


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def unb64u(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _hkdf(salt: bytes, ikm: bytes, info: bytes, length: int) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=salt, info=info).derive(ikm)


def encrypt(payload: bytes, p256dh_b64: str, auth_b64: str, *, salt: bytes | None = None,
            server_key: ec.EllipticCurvePrivateKey | None = None) -> bytes:
    """RFC 8291 message encryption; returns the aes128gcm body (header + one record)."""
    ua_public = unb64u(p256dh_b64)
    auth = unb64u(auth_b64)
    ua_key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public)
    server_key = server_key or ec.generate_private_key(ec.SECP256R1())
    as_public = server_key.public_key().public_bytes(serialization.Encoding.X962,
                                                     serialization.PublicFormat.UncompressedPoint)
    shared = server_key.exchange(ec.ECDH(), ua_key)
    ikm = _hkdf(auth, shared, b"WebPush: info\x00" + ua_public + as_public, 32)
    salt = salt or os.urandom(16)
    cek = _hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    record = AESGCM(cek).encrypt(nonce, payload + b"\x02", None)          # 0x02 = last record delimiter
    return salt + struct.pack(">I", 4096) + bytes([len(as_public)]) + as_public + record


def decrypt(body: bytes, ua_private: ec.EllipticCurvePrivateKey, auth_b64: str) -> bytes:
    """Inverse of :func:`encrypt` (what a browser does); used by the tests."""
    salt, idlen = body[:16], body[20]
    as_public = body[21:21 + idlen]
    ua_public = ua_private.public_key().public_bytes(serialization.Encoding.X962,
                                                     serialization.PublicFormat.UncompressedPoint)
    shared = ua_private.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), as_public))
    ikm = _hkdf(unb64u(auth_b64), shared, b"WebPush: info\x00" + ua_public + as_public, 32)
    cek = _hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    plain = AESGCM(cek).decrypt(nonce, body[21 + idlen:], None)
    return plain[:plain.rindex(b"\x02")]


class PushService:
    def __init__(self, settings, main, http=http_request):
        self.settings = settings
        self.main = main
        self.http = http
        self._key: ec.EllipticCurvePrivateKey | None = None
        self.queue: queue.Queue = queue.Queue(maxsize=1000)
        self._worker: threading.Thread | None = None

    # ---------------------------------------------------------------- keys
    @property
    def key(self) -> ec.EllipticCurvePrivateKey:
        if self._key is None:
            path = Path(self.settings.data_dir) / "vapid_private.pem"
            if path.exists():
                self._key = serialization.load_pem_private_key(path.read_bytes(), password=None)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                self._key = ec.generate_private_key(ec.SECP256R1())
                path.write_bytes(self._key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                         serialization.NoEncryption()))
                try:
                    os.chmod(path, 0o600)
                except OSError:
                    pass
        return self._key

    @property
    def public_key(self) -> str:
        return b64u(self.key.public_key().public_bytes(serialization.Encoding.X962,
                                                       serialization.PublicFormat.UncompressedPoint))

    def vapid_header(self, endpoint: str) -> str:
        parts = urlsplit(endpoint)
        subject = self.settings.public_url or "https://wiot.invalid"
        token = jwt.encode({"aud": f"{parts.scheme}://{parts.netloc}", "exp": int(time.time()) + 12 * 3600,
                            "sub": subject}, self.key, algorithm="ES256")
        return f"vapid t={token}, k={self.public_key}"

    # -------------------------------------------------------- subscriptions
    def init_schema(self) -> None:
        with self.main.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS push_subscriptions (endpoint TEXT PRIMARY KEY, user_id INTEGER NOT NULL, "
                       "p256dh TEXT NOT NULL, auth TEXT NOT NULL, user_agent TEXT, created_at INTEGER NOT NULL, "
                       "last_ok_at INTEGER, failures INTEGER NOT NULL DEFAULT 0)")

    def subscribe(self, user_id: int, sub: dict, user_agent: str | None) -> None:
        endpoint = str(sub.get("endpoint") or "")
        keys = sub.get("keys") or {}
        if not endpoint.startswith("https://") or len(endpoint) > 1000:
            raise ValueError("Invalid push endpoint")
        try:
            if len(unb64u(keys["p256dh"])) != 65 or len(unb64u(keys["auth"])) < 16:
                raise ValueError
        except (KeyError, ValueError, TypeError) as exc:
            raise ValueError("Invalid push subscription keys") from exc
        with self.main.connect() as db:
            db.execute("INSERT OR REPLACE INTO push_subscriptions(endpoint, user_id, p256dh, auth, user_agent, created_at) "
                       "VALUES(?,?,?,?,?,?)", (endpoint, user_id, keys["p256dh"], keys["auth"], (user_agent or "")[:200],
                                               int(time.time())))

    def unsubscribe(self, user_id: int, endpoint: str) -> None:
        with self.main.connect() as db:
            db.execute("DELETE FROM push_subscriptions WHERE endpoint=? AND user_id=?", (endpoint, user_id))

    def count(self, user_id: int) -> int:
        with self.main.connect() as db:
            return db.execute("SELECT COUNT(*) FROM push_subscriptions WHERE user_id=?", (user_id,)).fetchone()[0]

    def _targets(self, company: str) -> list[dict]:
        from ..security import GLOBAL_MONITOR_USERNAME, SUPERVISOR_USERNAME
        with self.main.connect() as db:
            rows = db.execute("SELECT s.*, u.company, u.role, u.username FROM push_subscriptions s JOIN users u ON "
                              "u.id=s.user_id WHERE COALESCE(u.disabled,0)=0").fetchall()
        out = []
        for r in rows:
            global_read = r["role"] == "supervisor" or r["username"] in (SUPERVISOR_USERNAME, GLOBAL_MONITOR_USERNAME)
            if r["company"] == company or global_read:
                out.append(dict(r))
        return out

    # ------------------------------------------------------------- sending
    def start(self) -> None:
        self._worker = threading.Thread(target=self._run, name="web-push", daemon=True)
        self._worker.start()

    def on_event(self, event: str, data: dict, company: str | None) -> None:
        if event != "alert" or not company or data.get("state") == "resolved" or data.get("severity") not in SEVERITY_MIN:
            return
        subject, body = alert_text(company, data)
        payload = {"title": subject.replace("[WIOT] ", ""), "body": body.split("\n")[1] if "\n" in body else body,
                   "url": "/#/alerts", "tag": f"{company}-{data.get('alert_id')}"}
        for sub in self._targets(company):
            try:
                self.queue.put_nowait((sub, payload))
            except queue.Full:
                return

    def _run(self) -> None:
        while True:
            sub, payload = self.queue.get()
            try:
                self.send(sub, payload)
            except Exception:
                log.exception("Web push failed")

    def send(self, sub: dict, payload: dict, ttl: int = 3600) -> int:
        body = encrypt(json.dumps(payload).encode(), sub["p256dh"], sub["auth"])
        status, _ = self.http("POST", sub["endpoint"], {"Authorization": self.vapid_header(sub["endpoint"]),
                                                         "Content-Encoding": "aes128gcm", "Content-Type": "application/octet-stream",
                                                         "TTL": str(ttl), "Urgency": "high"}, body)
        with self.main.connect() as db:
            if status in (404, 410):
                db.execute("DELETE FROM push_subscriptions WHERE endpoint=?", (sub["endpoint"],))
            elif 200 <= status < 300:
                db.execute("UPDATE push_subscriptions SET last_ok_at=?, failures=0 WHERE endpoint=?", (int(time.time()), sub["endpoint"]))
            else:
                db.execute("UPDATE push_subscriptions SET failures=failures+1 WHERE endpoint=?", (sub["endpoint"],))
        return status
