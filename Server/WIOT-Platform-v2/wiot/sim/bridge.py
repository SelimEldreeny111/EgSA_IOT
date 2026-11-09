"""Two-way MQTT bridge between the local development broker and an upstream broker.

Field gateways publish to the organisation's broker (``broker.hivemq.com`` in the
current firmware), while a development PC usually runs the server against the local
``devbroker`` together with the fleet simulator.  The bridge copies the real fleet's
topics between the two so live hardware and simulated demo tenants appear side by
side, and server commands still reach the gateway:

* upstream -> local: everything under each bridged filter (status, data, command acks);
* local -> upstream: everything the server publishes under the same filters (commands).

Payloads are forwarded byte-for-byte (still AES-encrypted).  Every forwarded frame is
fingerprinted so its echo from the other side is dropped instead of looping.  Only the
listed filters cross the bridge; simulated tenants stay on the local broker.

Production deployments bridge with Mosquitto (``connection`` / ``topic ... both``) or
point ``WIOT_MQTT_HOST`` at the managed broker directly.
"""
from __future__ import annotations

import hashlib
import logging
import threading
import time
import uuid

from ..protocol.transport import _make_paho_client

log = logging.getLogger("wiot.bridge")
ECHO_TTL_S = 60.0


class _Echo:
    """Fingerprints of frames recently forwarded *to* one side, so their echo is dropped."""

    def __init__(self) -> None:
        self._seen: dict[bytes, float] = {}
        self._lock = threading.Lock()

    @staticmethod
    def key(topic: str, payload: bytes) -> bytes:
        return hashlib.blake2b(topic.encode() + b"\0" + payload, digest_size=16).digest()

    def add(self, topic: str, payload: bytes) -> None:
        now = time.monotonic()
        with self._lock:
            self._seen[self.key(topic, payload)] = now
            if len(self._seen) > 4096:
                self._seen = {k: t for k, t in self._seen.items() if now - t < ECHO_TTL_S}

    def take(self, topic: str, payload: bytes) -> bool:
        """True (and forget it) when this frame is the echo of one we forwarded."""
        with self._lock:
            t = self._seen.pop(self.key(topic, payload), None)
        return t is not None and time.monotonic() - t < ECHO_TTL_S


class MqttBridge:
    def __init__(self, local: tuple[str, int], upstream: tuple[str, int], filters: list[str]) -> None:
        if not filters:
            raise ValueError("bridge needs at least one topic filter")
        self.filters = filters
        self.counts = {"up": 0, "down": 0}
        tag = uuid.uuid4().hex[:6]
        self._sides = {
            "local": (_make_paho_client(f"wiot-bridge-local-{tag}"), local),
            "upstream": (_make_paho_client(f"wiot-bridge-up-{tag}"), upstream),
        }
        self._to = {"local": _Echo(), "upstream": _Echo()}
        for name, (client, _) in self._sides.items():
            other = "upstream" if name == "local" else "local"
            client.on_connect = self._on_connect(name)
            client.on_disconnect = self._on_disconnect(name)
            client.on_message = self._on_message(name, other)
            client.reconnect_delay_set(min_delay=1, max_delay=30)

    # ------------------------------------------------------------- callbacks
    def _on_connect(self, name: str):
        def handler(client, userdata, flags, rc, *args):
            if rc != 0:
                log.warning("bridge %s connection refused (rc=%s)", name, rc)
                return
            host, port = self._sides[name][1]
            client.subscribe([(f, 1) for f in self.filters])
            log.info("bridge %s connected to %s:%s; filters %s", name, host, port, ", ".join(self.filters))
        return handler

    def _on_disconnect(self, name: str):
        def handler(client, userdata, rc, *args):
            if rc != 0:
                log.warning("bridge %s link lost (rc=%s); reconnecting", name, rc)
        return handler

    def _on_message(self, source: str, target: str):
        direction = "down" if source == "upstream" else "up"

        def handler(client, userdata, msg):
            if self._to[source].take(msg.topic, msg.payload):
                return  # echo of a frame we just delivered to this side
            self._to[target].add(msg.topic, msg.payload)
            self._sides[target][0].publish(msg.topic, msg.payload, qos=1, retain=bool(msg.retain))
            self.counts[direction] += 1
            arrow = "upstream -> local" if direction == "down" else "local -> upstream"
            log.info("bridge %s %s (%d bytes)", arrow, msg.topic, len(msg.payload))
        return handler

    # -------------------------------------------------------------- lifecycle
    def start(self) -> None:
        for name, (client, (host, port)) in self._sides.items():
            client.connect_async(host, port, keepalive=30)
            client.loop_start()

    def stop(self) -> None:
        for client, _ in self._sides.values():
            client.disconnect()
            client.loop_stop()


def parse_endpoint(value: str, default_port: int = 1883) -> tuple[str, int]:
    host, _, port = value.rpartition(":") if ":" in value else (value, "", "")
    return (host or value), int(port) if port else default_port
