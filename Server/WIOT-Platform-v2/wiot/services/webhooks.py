"""Outbound webhooks.

:class:`WebhookService` listens to the realtime hub and POSTs matching events to each
company's webhooks. Bodies are JSON and signed: ``X-WIOT-Signature: sha256=<hex HMAC of the
raw body with the webhook secret>``. Deliveries run on worker threads with retries, so
MQTT ingestion is never blocked by a slow receiver. Fleet alerts (``alert`` events) come
from :mod:`wiot.services.alerts`.
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import logging
import queue
import socket
import threading
import time
import urllib.error
import urllib.request
import uuid
from collections import deque
from urllib.parse import urlsplit

from ..storage.org_store import OrgStore

log = logging.getLogger(__name__)
HUB_TO_WEBHOOK = {"telemetry": "telemetry", "command": "command", "automation": "automation",
                  "alert": "alert", "flash": "flash"}
RETRY_DELAYS = (0, 2, 8)


def sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def check_destination(url: str, allow_private: bool) -> None:
    """Refuse to deliver into the server's own network unless explicitly allowed (SSRF guard)."""
    host = urlsplit(url).hostname
    if not host:
        raise ValueError("URL has no host")
    if allow_private:
        return
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise ValueError(f"Cannot resolve {host}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise ValueError(f"{host} resolves to a private address ({ip}); not allowed in production")


class WebhookService:
    def __init__(self, org: OrgStore, *, allow_private: bool, workers: int = 2, timeout: float = 5.0):
        self.org = org
        self.allow_private = allow_private
        self.timeout = timeout
        self.queue: queue.Queue = queue.Queue(maxsize=2000)
        self.recent: dict[int, deque] = {}
        self._hooks: dict[str, list[dict]] = {}
        self._hooks_at = 0.0
        self._lock = threading.Lock()
        self.dropped = 0
        self._workers = [threading.Thread(target=self._run, name=f"webhook-{i}", daemon=True) for i in range(workers)]
        for t in self._workers:
            t.start()

    # ------------------------------------------------------------- dispatch
    def refresh(self) -> None:
        with self._lock:
            self._hooks_at = 0.0

    def _active(self, company: str) -> list[dict]:
        with self._lock:
            if time.time() - self._hooks_at > 30:
                hooks: dict[str, list[dict]] = {}
                for h in self.org.list_webhooks(active_only=True):
                    hooks.setdefault(h["company"], []).append(h)
                self._hooks, self._hooks_at = hooks, time.time()
            return self._hooks.get(company, [])

    def on_event(self, event: str, data: dict, company: str | None) -> None:
        """Hub listener (any thread): enqueue deliveries, never block."""
        kind = HUB_TO_WEBHOOK.get(event)
        if not kind or not company:
            return
        for hook in self._active(company):
            if kind in hook["events"]:
                self._enqueue(hook, kind, company, data)

    def _enqueue(self, hook: dict, kind: str, company: str, data: dict) -> None:
        payload = {"id": str(uuid.uuid4()), "event": kind, "company": company, "ts": time.time(), "data": data}
        try:
            self.queue.put_nowait((hook, payload))
        except queue.Full:
            self.dropped += 1

    def _run(self) -> None:
        while True:
            hook, payload = self.queue.get()
            try:
                self.deliver(hook, payload)
            except Exception:  # pragma: no cover - a worker must never die
                log.exception("Webhook worker error")

    def deliver(self, hook: dict, payload: dict, *, retries: tuple = RETRY_DELAYS) -> dict:
        body = json.dumps(payload, default=str, separators=(",", ":")).encode()
        result: dict = {"status": None, "error": None}
        for delay in retries:
            if delay:
                time.sleep(delay)
            started = time.perf_counter()
            try:
                check_destination(hook["url"], self.allow_private)
                req = urllib.request.Request(hook["url"], data=body, method="POST", headers={
                    "Content-Type": "application/json", "User-Agent": "WIOT-Platform-Webhooks/2",
                    "X-WIOT-Event": payload["event"], "X-WIOT-Delivery": payload["id"],
                    "X-WIOT-Signature": sign(hook["secret"], body)})
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310 - scheme validated
                    result = {"status": resp.status, "error": None}
            except urllib.error.HTTPError as exc:
                result = {"status": exc.code, "error": f"HTTP {exc.code}"}
            except ValueError as exc:  # destination refused: retrying will not help
                result = {"status": None, "error": str(exc)}
                break
            except (urllib.error.URLError, OSError, TimeoutError) as exc:
                result = {"status": None, "error": str(getattr(exc, "reason", exc))[:200]}
            result["ms"] = round((time.perf_counter() - started) * 1000)
            if result["error"] is None or (result["status"] and 400 <= result["status"] < 500 and result["status"] != 429):
                break
        self.org.record_delivery(hook["id"], result["status"], result["error"])
        entry = {"ts": time.time(), "event": payload["event"], "delivery": payload["id"], **result}
        with self._lock:
            self.recent.setdefault(hook["id"], deque(maxlen=50)).appendleft(entry)
        return entry

    def deliveries(self, hook_id: int) -> list[dict]:
        with self._lock:
            return list(self.recent.get(hook_id, ()))

