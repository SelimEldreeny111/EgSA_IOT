"""Tenant-scoped WebSocket fan-out, safe to call from any thread.

MQTT callbacks run on paho's network thread. ``RealtimeHub.publish`` hands
events to the asyncio loop with ``call_soon_threadsafe``; each socket has a
bounded queue so a slow browser can never stall ingestion.
"""
from __future__ import annotations

import asyncio
import collections
import itertools
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime

from fastapi import WebSocket

from ..logging_setup import redact
from ..security import Principal

log = logging.getLogger(__name__)
QUEUE_LIMIT = 500


@dataclass(eq=False)
class Subscriber:
    socket: WebSocket
    principal: Principal
    company: str | None  # None = every company the principal may read
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(QUEUE_LIMIT))
    dropped: int = 0

    def wants(self, company: str | None, infra: bool, everyone: bool = False) -> bool:
        if everyone:
            return True
        if infra:
            return self.principal.is_supervisor
        if company is None:
            return False
        if not self.principal.can_read(company):
            return False
        return self.company is None or self.company == company


class RealtimeHub:
    def __init__(self) -> None:
        self._subs: set[Subscriber] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self.published = 0
        # Synchronous observers (e.g. webhooks): called on the publishing thread; must not block.
        self.listeners: list = []

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    @property
    def connections(self) -> int:
        return len(self._subs)

    def add(self, sub: Subscriber) -> None:
        self._subs.add(sub)

    def remove(self, sub: Subscriber) -> None:
        self._subs.discard(sub)

    def publish(self, event: str, data: dict, *, company: str | None = None, infra: bool = False,
                everyone: bool = False) -> None:
        """Thread-safe: queue one event for every authorised subscriber."""
        for listener in self.listeners:
            try:
                listener(event, data, company)
            except Exception:  # an observer must never break ingestion
                log.exception("Hub listener failed for %s", event)
        if self._loop is None or self._loop.is_closed():
            return
        envelope = {"type": event, "company": company, "ts": time.time(), "data": data}
        try:
            self._loop.call_soon_threadsafe(self._fanout, envelope, company, infra, everyone)
        except RuntimeError:
            pass  # loop shutting down

    def _fanout(self, envelope: dict, company: str | None, infra: bool, everyone: bool) -> None:
        self.published += 1
        text = json.dumps(envelope, default=str)
        for sub in list(self._subs):
            if not sub.wants(company, infra, everyone):
                continue
            if sub.queue.full():
                try:
                    sub.queue.get_nowait()
                    sub.dropped += 1
                except asyncio.QueueEmpty:
                    pass
            sub.queue.put_nowait(text)

    async def pump(self, sub: Subscriber) -> None:
        while True:
            text = await sub.queue.get()
            await sub.socket.send_text(text)


class LogBuffer:
    """Recent operational log lines, tenant-scoped, mirrored to the hub."""

    def __init__(self, hub: RealtimeHub, size: int = 2000):
        self.hub = hub
        self._lines: collections.deque[dict] = collections.deque(maxlen=size)
        self._ids = itertools.count(1)
        self._lock = threading.Lock()

    def emit(self, message: str, *, company: str | None = None, level: str = "info") -> None:
        text = redact(str(message).replace("\r", " ").replace("\n", " "))[:2048]
        entry = {
            "id": next(self._ids),
            "ts": time.time(),
            "time": datetime.now().strftime("%H:%M:%S"),
            "level": level,
            "company": company,
            "message": text,
        }
        with self._lock:
            self._lines.append(entry)
        getattr(log, level if level in ("info", "warning", "error", "debug") else "info")(
            "%s%s", f"[{company}] " if company else "", text)
        self.hub.publish("log", entry, infra=True)
        if company is not None:
            self.hub.publish("log", entry, company=company)

    def recent(self, principal: Principal, limit: int = 300) -> list[dict]:
        with self._lock:
            lines = list(self._lines)
        if not principal.is_supervisor:
            lines = [l for l in lines if l["company"] and principal.can_read(l["company"])]
        return lines[-limit:]
