"""Single owner of the shared MQTT ingestion session.

One subscription set covers every tenant (``wiot/+/+/+/...``); tenant scoping
happens at the view layer. paho's threaded loop reconnects automatically and
``MqttNodeClient`` re-subscribes and re-confirms SUBACKs after each reconnect.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass
from typing import Callable

from ..protocol.topics import SUBSCRIPTIONS
from ..protocol.transport import MqttNodeClient
from .metrics import BROKER_READY
from .realtime import LogBuffer, RealtimeHub

log = logging.getLogger(__name__)
_HOST_RE = re.compile(r"[A-Za-z0-9.:-]{1,253}")
_CLIENT_RE = re.compile(r"[A-Za-z0-9_-]{1,80}")


@dataclass
class BrokerParams:
    host: str
    port: int
    aes_key: bytes
    client_id: str
    username: str | None = None
    password: str | None = None

    def validate(self) -> "BrokerParams":
        if not _HOST_RE.fullmatch(self.host or ""):
            raise ValueError("Invalid broker hostname")
        if not 1 <= int(self.port) <= 65535:
            raise ValueError("Port must be 1..65535")
        if not _CLIENT_RE.fullmatch(self.client_id or ""):
            raise ValueError("Client ID must be 1..80 letters, digits, _ or -")
        if len(self.aes_key) != 16:
            raise ValueError("AES key must be 16 bytes (32 hex characters)")
        return self


class BrokerManager:
    def __init__(self, hub: RealtimeHub, logs: LogBuffer,
                 on_plaintext: Callable[[str, bytes], None]):
        self.hub = hub
        self.logs = logs
        self.on_plaintext = on_plaintext
        self.client: MqttNodeClient | None = None
        self.params: BrokerParams | None = None
        self.connected_since: float | None = None
        self.last_rx_at: float | None = None
        self.last_error: str | None = None
        self._lock = threading.RLock()

    # ---------------------------------------------------------------- control
    def connect(self, params: BrokerParams) -> None:
        params.validate()
        with self._lock:
            self.disconnect(quiet=True)
            client_id = f"{params.client_id}_{int(time.time())}"
            client = MqttNodeClient(
                broker_host=params.host, broker_port=params.port, aes_key_16=params.aes_key,
                client_id=client_id, subscribe_topics=list(SUBSCRIPTIONS),
                on_plaintext=self._on_plaintext, on_status=self._on_status,
            )
            if params.username:
                client.client.username_pw_set(params.username, params.password or None)
            client.client.reconnect_delay_set(min_delay=1, max_delay=60)
            self.client, self.params, self.last_error = client, params, None
            self.logs.emit(f"[MQTT] Connecting to {params.host}:{params.port} as {client_id}; "
                           f"topics={', '.join(SUBSCRIPTIONS)}")
            try:
                client.connect()
            except Exception as exc:
                self.client = None
                self.last_error = f"{type(exc).__name__}: {exc}"
                self.logs.emit(f"[MQTT] Connection failed: {self.last_error}", level="error")
                raise

    def disconnect(self, quiet: bool = False) -> None:
        with self._lock:
            if self.client is not None:
                try:
                    self.client.disconnect()
                except Exception:
                    log.exception("MQTT disconnect failed")
                self.client = None
                self.connected_since = None
                if not quiet:
                    self.logs.emit("[MQTT] Disconnected by operator")
            BROKER_READY.set(0)
            self.hub.publish("broker", self.status(public=True), everyone=True)

    # --------------------------------------------------------------- callbacks
    def _on_plaintext(self, topic: str, plaintext: bytes) -> None:
        self.last_rx_at = time.time()
        self.on_plaintext(topic, plaintext)

    def _on_status(self, message: str) -> None:
        if not message or message.startswith(("[RX#", "[TX#", "MQTT frame", "Frame header")):
            if message and "[ERROR]" in message:
                self.logs.emit(message, level="warning")
            return
        self.logs.emit(message)
        if "[MQTT] Ready" in message:
            self.connected_since = time.time()
            BROKER_READY.set(1)
        elif "Disconnected" in message or "FAILED" in message or "Subscription failed" in message:
            self.connected_since = None
            BROKER_READY.set(0)
            if "FAILED" in message or "failed" in message:
                self.last_error = message
        self.hub.publish("broker", self.status(public=True), everyone=True)

    # ----------------------------------------------------------------- status
    def is_ready(self) -> bool:
        client = self.client
        return bool(client and client.is_connected())

    def status(self, public: bool = False) -> dict:
        client = self.client
        ready = self.is_ready()
        state = ("ready" if ready else "connecting" if client and client.connected
                 else "disconnected" if client is None else "reconnecting")
        info = {"state": state, "ready": ready,
                "connected_since": self.connected_since,
                "last_rx_at": self.last_rx_at}
        if public:
            return info
        if self.params is not None:
            info.update(host=self.params.host, port=self.params.port,
                        client_id=client.client._client_id.decode() if client else None)
        if client is not None:
            info.update(rx=client.counters.rx_counter, tx=client.counters.tx_counter,
                        subscriptions=sorted(getattr(client, "_confirmed_subscriptions", set())))
        info["last_error"] = self.last_error
        return info
