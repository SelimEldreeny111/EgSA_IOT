"""Live event stream (WebSocket)."""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..security import AuthError
from ..services.metrics import WS_CONNECTIONS
from ..services.realtime import Subscriber
from .deps import ws_authenticate

router = APIRouter()


@router.websocket("/ws")
async def stream(websocket: WebSocket):
    """Events: ``telemetry``, ``command``, ``flash``, ``log``, ``broker``.

    Optional query ``company`` narrows the feed for global readers. Clients may
    send ``{"action":"select","company":"..."}`` to switch tenant live.
    """
    try:
        principal = ws_authenticate(websocket)
    except AuthError:
        await websocket.close(code=4401)
        return
    runtime = websocket.app.state.runtime
    origin = websocket.headers.get("origin")
    host = websocket.headers.get("host")
    if origin and host and origin.split("://", 1)[-1] != host:
        await websocket.close(code=4403)
        return
    requested = websocket.query_params.get("company") or None
    if requested and not principal.can_read(requested):
        await websocket.close(code=4403)
        return
    company = requested or (None if principal.global_read else principal.company)
    await websocket.accept()
    sub = Subscriber(socket=websocket, principal=principal, company=company)
    runtime.hub.add(sub)
    WS_CONNECTIONS.set(runtime.hub.connections)
    await websocket.send_text(json.dumps({"type": "hello", "data": {
        "user": principal.public(), "company": company,
        "broker": runtime.broker.status(public=True)}}))
    pump = asyncio.create_task(runtime.hub.pump(sub))
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(msg, dict) and msg.get("action") == "select":
                target = msg.get("company") or None
                if target is None or principal.can_read(target):
                    sub.company = target if (target or principal.global_read) else principal.company
            elif isinstance(msg, dict) and msg.get("action") == "ping":
                await websocket.send_text('{"type":"pong"}')
    except WebSocketDisconnect:
        pass
    finally:
        pump.cancel()
        runtime.hub.remove(sub)
        WS_CONNECTIONS.set(runtime.hub.connections)
