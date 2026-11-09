"""Pure-Python MQTT broker for local development and demos (not for production).

Production deployments use Mosquitto (see docker-compose.yml) or the
organisation's managed broker.  With ``--bridge`` the development broker also
relays the real fleet's topics from the upstream broker the field gateways use
(see ``wiot.sim.bridge``), so real hardware and the simulator can run together.
"""
from __future__ import annotations

import asyncio
import logging


async def _serve(host: str, port: int, bridge: str | None, bridge_topics: list[str] | None) -> None:
    from amqtt.broker import Broker

    config = {
        "listeners": {"default": {"type": "tcp", "bind": f"{host}:{port}"}},
        "plugins": {
            "amqtt.plugins.authentication.AnonymousAuthPlugin": {"allow_anonymous": True},
        },
    }
    broker = Broker(config)
    await broker.start()
    logging.getLogger("wiot.devbroker").info("Development MQTT broker on %s:%s", host, port)
    link = None
    if bridge:
        from .bridge import MqttBridge, parse_endpoint
        local_host = "127.0.0.1" if host in ("0.0.0.0", "::", "") else host
        link = MqttBridge((local_host, port), parse_endpoint(bridge), list(bridge_topics or []))
        link.start()
    try:
        await asyncio.Event().wait()
    finally:
        if link is not None:
            link.stop()
        await broker.shutdown()


def main(host: str = "127.0.0.1", port: int = 1883, bridge: str | None = None,
         bridge_topics: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s devbroker %(message)s")
    for noisy in ("amqtt", "transitions"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    try:
        asyncio.run(_serve(host, port, bridge, bridge_topics))
    except KeyboardInterrupt:
        pass
