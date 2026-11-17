"""Third-party device integration (Track G, point 53): MQTT JSON and LoRaWAN network servers.

Two ways in
-----------
* **MQTT JSON** on the same broker session as the WIOT nodes, topic
  ``wiotx/{company}/{device_id}/up``. The field broker is public, so a device registered as
  *signed* (the default) publishes ``{"p": "<JSON text>", "sig": "<hex>"}`` where ``sig`` is
  HMAC-SHA256(device secret, topic + "\\n" + p) and ``p`` carries ``ts`` (Unix seconds) and the
  readings. Messages must be newer than the last one stored (no replays). *Unsigned* devices
  publish plain JSON; their readings are stored but marked untrusted.
* **LoRaWAN** through The Things Stack (v3 webhook) or ChirpStack (v4 HTTP integration,
  JSON). The network server sends a per-company connection key; devices are matched by DevEUI.

Every accepted uplink is mapped to catalog metrics (``domain.ext_metrics``), stored in the
company's database, published on the hub as ``device_reading`` and counted as a message.
Devices that stop reporting raise a ``device_silent_<id>`` warning (node 0, the site).
"""
from __future__ import annotations

import json
import logging
import threading
import time
from collections import OrderedDict

from ..domain.ext_metrics import (apply_mapping, auto_mapping, flatten, parse_chirpstack, parse_time, parse_ttn,
                                  verify_signature)
from ..protocol.topics import DEFAULT_REGION
from ..protocol.validation import company_id
from ..storage.device_store import DeviceStore

log = logging.getLogger(__name__)

TOPIC_ROOT = "wiotx"
MAX_PAYLOAD = 8192
PAST_WINDOW_S = 7 * 86400          # devices may deliver buffered readings up to a week late
FUTURE_SKEW_S = 600
SILENT_FACTOR = 3                  # silent after 3 missed reports ...
SILENT_MIN_S = 900                 # ... and never sooner than 15 minutes
DEVICE_BURST, DEVICE_REFILL_S = 20, 3.0       # unsigned device: 20 messages, then one every 3 s
SIGNED_BURST, SIGNED_REFILL_S = 500, 1.0      # signed device, counted after verification: room for a backlog
COMPANIES_TTL_S = 5.0
SOURCE_BURST, SOURCE_REFILL_S = 600, 0.05     # per network-server key: 600, then 20 per second
UNKNOWN_KEEP = 20


class RateLimited(Exception):
    """A network-server key sent more requests than allowed."""


class _Bucket:
    __slots__ = ("tokens", "at")

    def __init__(self, burst: int):
        self.tokens, self.at = float(burst), time.monotonic()

    def take(self, burst: int, refill_s: float) -> bool:
        now = time.monotonic()
        self.tokens = min(burst, self.tokens + (now - self.at) / refill_s)
        self.at = now
        if self.tokens < 1:
            return False
        self.tokens -= 1
        return True


class DeviceService:
    def __init__(self, main, telemetry, hub, logs, secret_key: str, companies, alert_store=None):
        self.store = DeviceStore(main, telemetry, secret_key)
        self.hub, self.logs, self.companies, self.alert_store = hub, logs, companies, alert_store
        self.usage = None                              # UsageMeter, injected by the runtime
        self._lock = threading.Lock()
        self._buckets: dict[tuple, _Bucket] = {}
        self._last: dict[tuple[str, str], tuple[int, str]] = {}      # (company, device) -> (ts, sig) of last signed msg
        self.unknown: dict[str, OrderedDict] = {}                     # company -> key -> {...} heard but not registered
        self.payloads: dict[tuple[str, str], dict] = {}               # last decoded payload per device (diagnostics)
        self.stats: dict[tuple[str, str], dict] = {}
        self.dropped = {"bad_topic": 0, "unknown_company": 0, "too_large": 0}
        self.monitor = None                            # AlertMonitor, injected by the runtime (resolve events)
        self._companies_at, self._companies_set = 0.0, frozenset()
        # One uplink at a time per server: a device deleted while its message is being stored must not get its
        # readings back (registry lookup and save happen under this lock, and so does delete()).
        self._ingest_lock = threading.Lock()

    def init_schema(self) -> None:
        self.store.init_schema()

    def seed_demo(self, companies: list[str]) -> bool:
        """Register the simulator's unsigned demo devices on Demo_AgriFarm, once: deleting them later is final."""
        from ..sim.demo_greenhouses import DEMO_COMPANY, DEVICES
        if DEMO_COMPANY not in companies or self.store.meta("demo_devices_seeded"):
            return False
        self.store.set_meta("demo_devices_seeded", str(int(time.time())))
        if self.store.list(DEMO_COMPANY):
            return False
        for d in DEVICES:
            self.store.create(DEMO_COMPANY, {**d, "protocol": "mqtt", "auth": "none", "region": "Region_1"}, "seed")
        return True

    def _known_company(self, company: str) -> bool:
        """Company check for every MQTT message without a database query each time."""
        now = time.monotonic()
        if now - self._companies_at > COMPANIES_TTL_S:
            self._companies_set, self._companies_at = frozenset(self.companies()), now
        return company in self._companies_set

    # ------------------------------------------------------------- bookkeeping
    def _stat(self, company: str, device_id: str, key: str, error: str | None = None) -> None:
        with self._lock:
            s = self.stats.setdefault((company, device_id), {"accepted": 0, "rejected": 0, "duplicates": 0})
            s[key] = s.get(key, 0) + 1
            if error:
                s["last_error"], s["last_error_at"] = error, int(time.time())

    def _allow(self, key: tuple, burst: int, refill_s: float) -> bool:
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                if len(self._buckets) > 20000:
                    self._buckets.clear()
                bucket = self._buckets[key] = _Bucket(burst)
            return bucket.take(burst, refill_s)

    def _heard_unknown(self, company: str, via: str, ident: str, extra: dict) -> None:
        with self._lock:
            seen = self.unknown.setdefault(company, OrderedDict())
            key = f"{via}:{ident}"
            item = seen.pop(key, None) or {"via": via, "id": ident, "count": 0, "first_at": int(time.time())}
            item.update(extra, count=item["count"] + 1, last_at=int(time.time()))
            seen[key] = item
            while len(seen) > UNKNOWN_KEEP:
                seen.popitem(last=False)

    def unknown_for(self, company: str) -> list[dict]:
        registered = {d["device_id"] for d in self.store.list(company)}
        euis = {d["dev_eui"] for d in self.store.list(company) if d.get("dev_eui")}
        with self._lock:
            items = list((self.unknown.get(company) or {}).values())
        return [i for i in reversed(items) if i["id"] not in registered and i["id"] not in euis]

    # -------------------------------------------------------------------- MQTT
    def on_mqtt(self, topic: str, payload: bytes) -> None:
        """Broker callback (paho network thread) for ``wiotx/{company}/{device}/up``. Never raises."""
        try:
            self._on_mqtt(topic, payload)
        except Exception:
            log.exception("Third-party MQTT message on %r failed", topic[:120])

    def _on_mqtt(self, topic: str, payload: bytes) -> None:
        parts = topic.split("/")
        if len(parts) != 4 or parts[0] != TOPIC_ROOT or parts[3] != "up":
            self.dropped["bad_topic"] += 1
            return
        company, device_id = parts[1], parts[2]
        try:
            company_id(company)
        except ValueError:
            self.dropped["bad_topic"] += 1
            return
        if len(payload) > MAX_PAYLOAD:
            self.dropped["too_large"] += 1
            return
        if not self._known_company(company):
            self.dropped["unknown_company"] += 1
            return
        with self._ingest_lock:
            self._on_device_message(topic, company, device_id, payload)

    def _on_device_message(self, topic: str, company: str, device_id: str, payload: bytes) -> None:
        device = self.store.get(company, device_id)
        if device is None or device["protocol"] != "mqtt":
            if len(device_id) <= 40 and self._allow(("unknown", company), 60, 1.0):
                self._heard_unknown(company, "mqtt", device_id, {"topic": topic, "fields": self._field_names(payload)})
            return
        if not device["enabled"]:
            self._stat(company, device_id, "rejected", "Device is disabled")
            return
        signed = device["auth"] == "hmac"
        # Signed devices are charged only after verification (a JSON parse and one HMAC over <= 8 KiB are cheap), so
        # junk published to their topic on the public broker cannot use up their allowance.
        if not signed and not self._allow(("dev", company, device_id), DEVICE_BURST, DEVICE_REFILL_S):
            self._stat(company, device_id, "rejected", "Too many messages (rate limit)")
            return
        try:
            body = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, RecursionError):
            self._stat(company, device_id, "rejected", "Payload is not JSON")
            return
        if not isinstance(body, dict):
            self._stat(company, device_id, "rejected", "Payload must be a JSON object")
            return
        now = int(time.time())
        if device["auth"] == "hmac":
            inner, measured, sig = self._verify(company, device, topic, body, now)
            if inner is None:
                return
            if not self._allow(("dev", company, device_id), SIGNED_BURST, SIGNED_REFILL_S):
                self._stat(company, device_id, "rejected", "Too many messages (rate limit)")
                return
        else:
            inner, sig = body, None
            stamp = next((inner[k] for k in ("ts", "time", "timestamp") if k in inner), None)
            measured = now if stamp is None else parse_time(stamp)
            if measured is None or not now - PAST_WINDOW_S <= measured <= now + FUTURE_SKEW_S:
                self._stat(company, device_id, "rejected", "Time stamp missing, invalid or out of range")
                return
            measured = min(measured, now)          # an unsigned clock ahead of ours must not pin "latest"
        fields = flatten({k: v for k, v in inner.items() if k not in ("ts", "time", "timestamp", "p", "sig")})
        self.accept(company, device, measured, fields, trusted=device["auth"] == "hmac", source="mqtt")
        if sig:
            with self._lock:
                self._last[(company, device_id)] = (measured, sig)

    @staticmethod
    def _field_names(payload: bytes) -> list[str]:
        """Numeric field names of an unregistered device's message (signed ones: inside "p"), for the Register form."""
        try:
            body = json.loads(payload.decode("utf-8"))
            if isinstance(body, dict) and isinstance(body.get("p"), str):
                body = json.loads(body["p"])
        except (UnicodeDecodeError, ValueError, RecursionError):
            return []
        if not isinstance(body, dict):
            return []
        return sorted(k for k in flatten(body) if k not in ("ts", "time", "timestamp"))[:30]

    def _verify(self, company: str, device: dict, topic: str, body: dict, now: int):
        device_id = device["device_id"]
        p, sig = body.get("p"), body.get("sig")
        if not isinstance(p, str) or len(p) > MAX_PAYLOAD:
            self._stat(company, device_id, "rejected", "Signed device: expected {\"p\": \"...\", \"sig\": \"...\"}")
            return None, None, None
        secret = self.store.secret_of(device)
        if not secret or not verify_signature(secret, topic, p, sig):
            self._stat(company, device_id, "rejected", "Signature does not match (wrong secret or altered message)")
            return None, None, None
        try:
            inner = json.loads(p)
        except (ValueError, RecursionError):
            self._stat(company, device_id, "rejected", "Signed text is not JSON")
            return None, None, None
        measured = parse_time(inner.get("ts")) if isinstance(inner, dict) else None
        if measured is None or not now - PAST_WINDOW_S <= measured <= now + FUTURE_SKEW_S:
            self._stat(company, device_id, "rejected", "Signed message needs \"ts\" (Unix seconds) within the last 7 days")
            return None, None, None
        with self._lock:
            last = self._last.get((company, device_id))
        if last is None:
            stored = self.store.last_ts(company, device_id)
            last = (stored, "") if stored is not None else None
        if last is not None and (measured < last[0] or (measured == last[0] and sig.lower() == last[1])):
            self._stat(company, device_id, "rejected", "Older than the last message (replay refused)")
            return None, None, None
        return inner, measured, sig.lower()

    # ----------------------------------------------------------------- LoRaWAN
    def ingest_webhook(self, source: dict, body, event: str | None = None) -> dict:
        """One request from a network server; ``source`` is the resolved connection key row."""
        company = source["company"]
        if company not in self.companies():
            raise PermissionError("This connection's company is archived")
        if not self._allow(("src", source["id"]), SOURCE_BURST, SOURCE_REFILL_S):
            raise RateLimited("Too many requests for this connection")
        with self._ingest_lock:
            return self._ingest_webhook(source, company, body, event)

    def _ingest_webhook(self, source: dict, company: str, body, event: str | None) -> dict:
        parsed = parse_ttn(body) if source["kind"] == "ttn" else parse_chirpstack(body, event or "up")
        if parsed is None:
            return {"accepted": False, "reason": "Not an uplink; ignored"}
        device = self.store.by_eui(company, parsed["dev_eui"])
        if device is None or device["protocol"] != "lorawan":
            ident = str(parsed.get("dev_eui") or "")[:32]
            if ident:
                self._heard_unknown(company, source["kind"], ident.upper(),
                                    {"name": parsed.get("external_id"), "fields": sorted(parsed["fields"])[:30]})
            return {"accepted": False, "reason": "Unknown DevEUI; register the device first"}
        if not device["enabled"]:
            self._stat(company, device["device_id"], "rejected", "Device is disabled")
            return {"accepted": False, "reason": "Device is disabled"}
        now = int(time.time())
        measured = parsed["measured_at"] or now
        if not now - PAST_WINDOW_S <= measured <= now + FUTURE_SKEW_S:
            self._stat(company, device["device_id"], "rejected", "Uplink time out of range")
            return {"accepted": False, "reason": "Uplink time out of range"}
        result = self.accept(company, device, measured, parsed["fields"], trusted=True, source=source["kind"],
                             radio=parsed.get("radio"), mapping=parsed.get("mapping"))
        return {"accepted": True, "device_id": device["device_id"], **result}

    # ------------------------------------------------------------------ common
    def accept(self, company: str, device: dict, measured: int, fields: dict, *, trusted: bool, source: str,
               radio: dict | None = None, mapping: list | None = None) -> dict:
        device_id = device["device_id"]
        values, rejected = apply_mapping(fields, mapping if mapping is not None else device["mapping"])
        for metric, v in (radio or {}).items():
            values.setdefault(metric, v)
        now = int(time.time())
        with self._lock:
            self.payloads[(company, device_id)] = {"at": now, "fields": dict(list(fields.items())[:60]),
                                                   "rejected": rejected[:10], "source": source,
                                                   "suggested": {m["field"]: m["metric"] for m in auto_mapping(fields)}}
        if not values:
            self._stat(company, device_id, "rejected",
                       "No mapped values in the payload" if not rejected else "All values outside their valid range")
            return {"stored": 0, "rejected": rejected}
        added = self.store.save(company, device_id, measured, now, values, trusted, source)
        self._stat(company, device_id, "accepted" if added else "duplicates")
        if added:
            if self.usage is not None:
                self.usage.count(company, "messages")
            self.hub.publish("device_reading", {"device_id": device_id, "ts": measured, "received_at": now,
                                                "values": values, "trusted": trusted, "source": source}, company=company)
        return {"stored": added, "rejected": rejected}

    # ------------------------------------------------------------------- views
    def overview(self, company: str, now: int | None = None) -> list[dict]:
        now = int(time.time() if now is None else now)
        latest = self.store.latest(company)
        counts = self.store.counts(company, now - 86400)
        out = []
        for d in self.store.list(company):
            pub = DeviceStore.public(d)
            live = latest.get(d["device_id"]) or {}
            last = live.get("last_seen") or None
            pub.update(last_seen=last, measured_at=live.get("measured_at") or None, values=live.get("values") or {},
                       uplinks_24h=counts.get(d["device_id"], 0), state=self.link_state(d, last, now))
            with self._lock:
                pub["stats"] = dict(self.stats.get((company, d["device_id"]), {}))
                pub["last_payload"] = self.payloads.get((company, d["device_id"]))
            out.append(pub)
        return out

    @staticmethod
    def silent_after(device: dict) -> int:
        return max(SILENT_FACTOR * int(device.get("interval_s") or 900), SILENT_MIN_S)

    def link_state(self, device: dict, last_seen: int | None, now: int) -> str:
        if not device.get("enabled"):
            return "disabled"
        if not last_seen:
            return "waiting"
        return "silent" if now - last_seen > self.silent_after(device) else "online"

    # ------------------------------------------------------------------ alerts
    def check_alerts(self, monitor, company: str, now: int) -> list[dict]:
        """Alert-monitor hook: ``device_silent_<id>`` opens after 3 missed reports, clears on the next one."""
        devices = self.store.list(company)
        if not devices:
            return []
        latest = self.store.latest(company)
        fired = []
        for d in devices:
            kind = f"device_silent_{d['device_id']}"
            region = d.get("region") or DEFAULT_REGION
            last = (latest.get(d["device_id"]) or {}).get("last_seen")
            node = {"node_id": 0, "timestamp": last}
            if d["enabled"] and last and now - last > self.silent_after(d):
                fired += monitor._open(company, region, node, kind, "warning",
                                       {"device_id": d["device_id"], "name": d["name"], "last_seen": last,
                                        "interval_s": d["interval_s"], "protocol": d["protocol"]}, now)
            elif monitor.store.get_open(company, region, 0, kind):
                fired += monitor._resolve(company, region, node, kind, now)
        return fired

    def close_alerts(self, company: str, device_id: str, region: str | None) -> None:
        """Clear a device's open silence alert (device deleted, disabled or moved to another region).

        Through the alert monitor when there is one, so channels, webhooks and open pages get the "resolved" event."""
        kind, region, now = f"device_silent_{device_id}", region or DEFAULT_REGION, int(time.time())
        try:
            if self.monitor is not None:
                self.monitor._resolve(company, region, {"node_id": 0, "timestamp": None}, kind, now)
            elif self.alert_store is not None:
                self.alert_store.resolve(company, region, 0, kind, now)
        except Exception:
            log.exception("Could not clear the silence alert of %s/%s", company, device_id)

    def delete(self, company: str, device_id: str) -> int:
        """Remove a device, its readings and its in-memory state; no uplink can be half-stored meanwhile."""
        with self._ingest_lock:
            before = self.store.get(company, device_id)
            readings = self.store.delete(company, device_id)
            with self._lock:
                for d in (self._last, self.stats, self.payloads):
                    d.pop((company, device_id), None)
                for key in (("dev", company, device_id),):
                    self._buckets.pop(key, None)
        self.close_alerts(company, device_id, (before or {}).get("region"))
        return readings

    # ------------------------------------------------------------- maintenance
    def retention(self, company: str, days: int, now: int | None = None) -> int:
        return self.store.apply_retention(company, days, now)
