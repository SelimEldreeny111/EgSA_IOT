"""Third-party devices (Track G, point 53): registry, readings and LoRaWAN webhooks.

Permissions
* read devices and readings ...................... anyone who may read the company
* register / edit / delete devices ............... supervisor, or that company's admin
* device secrets and network-server keys ......... the same, signed in (never an API token);
  secrets and keys are shown once, in the response that creates them
* ``POST /ingest/ttn`` and ``/ingest/chirpstack`` .. a network-server key (``wiotsrc_...``) in
  ``Authorization: Bearer`` or ``X-WIOT-Key``; no session, no CSRF
"""
from __future__ import annotations

import ipaddress
import json
import time
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from ..domain.ext_metrics import GROUPS, catalog
from ..security import Principal
from ..services.devices import RateLimited
from ..services.runtime import Runtime
from ..storage.device_store import AUTH_MODES, PROTOCOLS, SOURCE_KINDS, DeviceStore
from .deps import authenticate, get_runtime, resolve_company

router = APIRouter(prefix="/devices", tags=["third-party devices"])
ingest_router = APIRouter(prefix="/ingest", tags=["third-party devices"])


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _writable(principal: Principal, company: str | None, runtime: Runtime) -> str:
    tenant = resolve_company(principal, company, runtime)
    if not principal.can_write(tenant):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Administrator privileges for this company required")
    return tenant


def _human_only(principal: Principal) -> None:
    if principal.token:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "API tokens cannot handle device secrets or connection keys")


class MappingItem(BaseModel):
    field: str = Field(max_length=330)
    metric: str = Field(max_length=40)
    scale: float | None = None
    offset: float | None = None


class DeviceBody(BaseModel):
    device_id: str | None = Field(None, max_length=40)
    name: str | None = Field(None, max_length=80)
    protocol: str | None = Field(None, max_length=10)
    auth: str | None = Field(None, max_length=10)
    dev_eui: str | None = Field(None, max_length=32)
    region: str | None = Field(None, max_length=40)
    model: str | None = Field(None, max_length=80)
    lat: float | None = None
    lon: float | None = None
    mapping: list[MappingItem] | None = Field(None, max_length=32)
    interval_s: int | None = Field(None, ge=10, le=86400)
    enabled: bool | None = None
    notes: str | None = Field(None, max_length=500)


class SourceBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kind: str = Field(max_length=20)


RESERVED_IDS = {"catalog", "sources"}          # path segments of this router


def _payload(body: DeviceBody) -> dict:
    return body.model_dump(exclude_unset=True)


def _with_location(runtime: Runtime, company: str, devices: list[dict]) -> list[dict]:
    where = runtime.greenhouses.locations(company)
    for d in devices:
        d["locations"] = where.get(("device", d["device_id"]), [])
    return devices


# ================================================================ catalog
def _public_host(host: str | None) -> bool:
    """False for loopback, private, link-local and single-label names: a device or cloud server cannot reach them."""
    host = (host or "").strip("[]").lower()
    if not host or host == "localhost" or "." not in host and ":" not in host:
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return not host.endswith((".local", ".lan", ".internal", ".localhost"))
    return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved)


@router.get("/catalog")
def device_catalog(request: Request, company: str | None = None, principal: Principal = Depends(authenticate),
                   runtime: Runtime = Depends(get_runtime)):
    tenant = resolve_company(principal, company, runtime)
    s = runtime.settings
    base = (s.public_url or str(request.base_url)).rstrip("/")   # what the network server must call
    host, port = s.device_mqtt_host or s.mqtt_host, s.device_mqtt_port or (s.mqtt_port if not s.device_mqtt_host else 1883)
    parts = urlsplit(base)
    return {"metrics": catalog(), "groups": GROUPS, "protocols": list(PROTOCOLS), "auth_modes": list(AUTH_MODES),
            "source_kinds": list(SOURCE_KINDS),
            "mqtt": {"host": host, "port": port, "topic": f"wiotx/{tenant}/<device_id>/up",
                     "connected": runtime.broker.is_ready(), "public": _public_host(host)},
            "webhooks": {"ttn": f"{base}/api/v2/ingest/ttn", "chirpstack": f"{base}/api/v2/ingest/chirpstack",
                         "public": parts.scheme == "https" and _public_host(parts.hostname)}}


# ================================================================ devices
@router.get("")
def list_devices(company: str | None = None, principal: Principal = Depends(authenticate),
                 runtime: Runtime = Depends(get_runtime)):
    tenant = resolve_company(principal, company, runtime)
    devices = _with_location(runtime, tenant, runtime.devices.overview(tenant))
    return {"company": tenant, "devices": devices, "unknown": runtime.devices.unknown_for(tenant),
            "can_edit": principal.can_write(tenant) and not principal.token}


@router.post("", status_code=201)
def create_device(body: DeviceBody, request: Request, company: str | None = None,
                  principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    _human_only(principal)
    tenant = _writable(principal, company, runtime)
    if (body.device_id or "").lower() in RESERVED_IDS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This device ID is reserved; choose another")
    device, secret = runtime.devices.store.create(tenant, _payload(body), principal.username)
    runtime.main.audit(principal.username, "device_registered", company=tenant, target=device["device_id"], ip=_ip(request),
                       details={"protocol": device["protocol"], "auth": device["auth"], "dev_eui": device["dev_eui"]})
    return {**DeviceStore.public(device), "secret": secret}


@router.patch("/{device_id}")
def update_device(device_id: str, body: DeviceBody, request: Request, company: str | None = None,
                  principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    _human_only(principal)
    tenant = _writable(principal, company, runtime)
    data = _payload(body)
    data.pop("device_id", None)
    before = runtime.devices.store.get(tenant, device_id)
    device, secret = runtime.devices.store.update(tenant, device_id, data)
    if before and ((before.get("region") or None) != (device.get("region") or None) or not device["enabled"]):
        runtime.devices.close_alerts(tenant, device_id, before.get("region"))
    runtime.main.audit(principal.username, "device_updated", company=tenant, target=device_id, ip=_ip(request),
                       details=sorted(data))
    return {**DeviceStore.public(device), "secret": secret}


@router.post("/{device_id}/secret")
def rotate_secret(device_id: str, request: Request, company: str | None = None,
                  principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    _human_only(principal)
    tenant = _writable(principal, company, runtime)
    secret = runtime.devices.store.rotate(tenant, device_id)
    runtime.main.audit(principal.username, "device_secret_rotated", company=tenant, target=device_id, ip=_ip(request))
    return {"device_id": device_id, "secret": secret}


@router.delete("/{device_id}")
def delete_device(device_id: str, request: Request, company: str | None = None,
                  principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    _human_only(principal)
    tenant = _writable(principal, company, runtime)
    readings = runtime.devices.delete(tenant, device_id)
    runtime.main.audit(principal.username, "device_deleted", company=tenant, target=device_id, ip=_ip(request),
                       details={"readings_deleted": readings})
    return {"deleted": device_id, "readings_deleted": readings}


@router.get("/{device_id}/series")
def device_series(device_id: str, metric: str = Query(max_length=40), company: str | None = None,
                  hours: float = Query(24, gt=0, le=24 * 400), principal: Principal = Depends(authenticate),
                  runtime: Runtime = Depends(get_runtime)):
    tenant = resolve_company(principal, company, runtime)
    if runtime.devices.store.get(tenant, device_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown device")
    until = int(time.time())
    since = until - int(hours * 3600)
    return {"device_id": device_id, "metric": metric, "since": since, "until": until,
            **runtime.devices.store.series(tenant, device_id, metric, since, until)}


# ======================================================= network-server keys
@router.get("/sources")
def list_sources(company: str | None = None, principal: Principal = Depends(authenticate),
                 runtime: Runtime = Depends(get_runtime)):
    _human_only(principal)
    tenant = _writable(principal, company, runtime)
    return {"company": tenant, "sources": runtime.devices.store.list_sources(tenant)}


@router.post("/sources", status_code=201)
def create_source(body: SourceBody, request: Request, company: str | None = None,
                  principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    _human_only(principal)
    tenant = _writable(principal, company, runtime)
    src = runtime.devices.store.create_source(tenant, body.name, body.kind, principal.username)
    runtime.main.audit(principal.username, "device_source_created", company=tenant, target=src["prefix"], ip=_ip(request),
                       details={"name": src["name"], "kind": src["kind"]})
    return src


@router.delete("/sources/{source_id}")
def revoke_source(source_id: int, request: Request, company: str | None = None,
                  principal: Principal = Depends(authenticate), runtime: Runtime = Depends(get_runtime)):
    _human_only(principal)
    tenant = _writable(principal, company, runtime)
    runtime.devices.store.revoke_source(tenant, source_id)
    runtime.main.audit(principal.username, "device_source_revoked", company=tenant, target=str(source_id), ip=_ip(request))
    return {"revoked": source_id}


# ============================================================ LoRaWAN webhooks
MAX_WEBHOOK_BODY = 64 * 1024


def _source(request: Request, runtime: Runtime, kind: str) -> dict:
    header = request.headers.get("authorization", "")
    key = header[7:].strip() if header.lower().startswith("bearer ") else request.headers.get("x-wiot-key", "").strip()
    src = runtime.devices.store.resolve_source(key)
    if src is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing, unknown or revoked connection key")
    if src["kind"] != kind:
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"This key is for {src['kind']}, not {kind}")
    return src


async def _json(request: Request) -> dict:
    ctype = request.headers.get("content-type", "")
    if "json" not in ctype.lower():
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Send JSON (ChirpStack: set the encoding to JSON)")
    raw = b""
    async for chunk in request.stream():
        raw += chunk
        if len(raw) > MAX_WEBHOOK_BODY:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Request body too large")
    try:
        body = json.loads(raw)
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Body is not valid JSON") from exc
    if not isinstance(body, dict):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Body must be a JSON object")
    return body


def _ingest(runtime: Runtime, src: dict, body: dict, event: str | None) -> dict:
    try:
        return runtime.devices.ingest_webhook(src, body, event)
    except RateLimited as exc:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(exc), headers={"Retry-After": "5"}) from exc


async def _webhook(request: Request, runtime: Runtime, kind: str, event: str | None) -> dict:
    src = await run_in_threadpool(_source, request, runtime, kind)     # the key first: no parsing for strangers
    body = await _json(request)
    return await run_in_threadpool(_ingest, runtime, src, body, event)


@ingest_router.post("/ttn", status_code=202)
async def ingest_ttn(request: Request, runtime: Runtime = Depends(get_runtime)):
    """The Things Stack v3 webhook (enable *Uplink message*; add the key as a header)."""
    return await _webhook(request, runtime, "ttn", None)


@ingest_router.post("/chirpstack", status_code=202)
async def ingest_chirpstack(request: Request, event: str = Query("up", max_length=20),
                            runtime: Runtime = Depends(get_runtime)):
    """ChirpStack v4 HTTP integration, JSON encoding (``?event=up``; ``status`` adds battery level)."""
    return await _webhook(request, runtime, "chirpstack", event)
