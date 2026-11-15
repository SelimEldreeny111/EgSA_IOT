"""Forward readings to other platforms (R2.3, point 29).

Per company, any number of outbound integrations receive every stored node reading:

* **ThingsBoard** — HTTP device API ``POST {host}/api/v1/{access token}/telemetry`` (one ThingsBoard device per
  company, keys prefixed with the node, or ``device_per_node`` with a token map);
* **Azure IoT Hub** — device-to-cloud messages over HTTPS with a SAS token computed from the device key
  (``POST https://{hub}.azure-devices.net/devices/{device}/messages/events``); no SDK needed;
* **HTTP JSON** — any HTTPS endpoint (Power Automate, Node-RED, a data lake ingest URL) with optional headers.

A bounded queue and two worker threads deliver with retries (0, 2, 10 s); every integration keeps sent / failed
counters and its last error. Reading forwarding never blocks ingestion: when the queue is full the reading is
counted as dropped for that integration.

**Power BI / Excel** pull data instead: ``GET /api/v2/feeds/daily.csv`` (API token) returns one row per node and
day from the summaries; see ``docs/integrations/``.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import queue
import threading
import time
import urllib.parse

from ..protocol.validation import company_id
from ..security import seal, unseal
from .notify import http_request

log = logging.getLogger(__name__)

KINDS = ("thingsboard", "azure_iot", "http_json")
RETRIES = (0, 2, 10)
FIELDS = ("flow", "velocity", "flow_day", "battery_voltage", "soil_moisture", "soil_temperature",
          "electrical_conductivity", "ec_moisture", "ec_temperature", "node_status", "power_mode",
          "forward_total_liters", "net_total_liters")


def reading(row: dict) -> dict:
    out = {"company": row.get("company"), "region": row.get("region"), "node_id": row.get("node_id"),
           "ts": row.get("measured_at") or row.get("timestamp"), "received_at": row.get("timestamp"),
           "type": row.get("type")}
    for f in FIELDS:
        v = row.get(f)
        if v is not None:
            out[f] = v
    return out


def azure_sas(resource_uri: str, key_b64: str, ttl_s: int = 3600, now: float | None = None) -> str:
    expiry = int((time.time() if now is None else now) + ttl_s)
    uri = urllib.parse.quote(resource_uri, safe="").lower()
    sig = base64.b64encode(hmac.new(base64.b64decode(key_b64), f"{uri}\n{expiry}".encode(), hashlib.sha256).digest())
    return f"SharedAccessSignature sr={uri}&sig={urllib.parse.quote(sig.decode(), safe='')}&se={expiry}"


class IntegrationService:
    def __init__(self, main, secret_key: str, *, allow_private: bool = False, http=http_request,
                 queue_max: int = 5000, workers: int = 2):
        self.main = main
        self.secret_key = secret_key
        self.allow_private = allow_private
        self.http = http
        self.queue: queue.Queue = queue.Queue(maxsize=queue_max)
        self._active: dict[str, list[dict]] = {}
        self._active_at = 0.0
        self._stats: dict[int, dict] = {}
        self._lock = threading.Lock()
        self._workers = [threading.Thread(target=self._run, name=f"forward-{i}", daemon=True) for i in range(workers)]

    def start(self) -> None:
        for t in self._workers:
            t.start()

    def init_schema(self) -> None:
        with self.main.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS integrations (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                       "company TEXT NOT NULL, kind TEXT NOT NULL, name TEXT NOT NULL, config TEXT NOT NULL DEFAULT '{}', "
                       "secrets TEXT, enabled INTEGER NOT NULL DEFAULT 1, created_at INTEGER NOT NULL, "
                       "updated_at INTEGER NOT NULL, sent INTEGER NOT NULL DEFAULT 0, failed INTEGER NOT NULL DEFAULT 0, "
                       "dropped INTEGER NOT NULL DEFAULT 0, last_ok_at INTEGER, last_error TEXT, last_error_at INTEGER)")

    # -------------------------------------------------------------- store
    def _public(self, row) -> dict:
        r = dict(row)
        secrets = self._secrets(r)
        r["config"] = json.loads(r["config"] or "{}")
        r["secrets_set"] = sorted(k for k, v in secrets.items() if v)
        r["enabled"] = bool(r["enabled"])
        live = self._stats.get(r["id"], {})
        for k in ("sent", "failed", "dropped"):
            r[k] = r[k] + live.get(k, 0)
        r.pop("secrets", None)
        return r

    def _secrets(self, row: dict) -> dict:
        try:
            return json.loads(unseal(self.secret_key, row["secrets"])) if row.get("secrets") else {}
        except (ValueError, json.JSONDecodeError):
            return {}

    def list(self, company: str | None) -> list[dict]:
        q, p = "SELECT * FROM integrations", ()
        if company:
            q, p = q + " WHERE company=?", (company,)
        with self.main.connect() as db:
            return [self._public(r) for r in db.execute(q + " ORDER BY id", p)]

    def get(self, integration_id: int, with_secrets: bool = False) -> dict | None:
        with self.main.connect() as db:
            row = db.execute("SELECT * FROM integrations WHERE id=?", (integration_id,)).fetchone()
        if not row:
            return None
        out = self._public(row)
        if with_secrets:
            out["secret_values"] = self._secrets(dict(row))
        return out

    def _validate(self, kind: str, cfg: dict, sec: dict) -> None:
        from .webhooks import check_destination
        if kind not in KINDS:
            raise ValueError(f"Kind must be one of {', '.join(KINDS)}")
        if kind == "thingsboard":
            host = str(cfg.get("host", ""))
            if not host.startswith(("https://", "http://")):
                raise ValueError("ThingsBoard host must be a URL, e.g. https://thingsboard.cloud")
            check_destination(host, self.allow_private)
            if not sec.get("access_token"):
                raise ValueError("ThingsBoard device access token is required")
        elif kind == "azure_iot":
            if not str(cfg.get("hub", "")).replace("-", "").isalnum() or not cfg.get("device_id"):
                raise ValueError("Azure IoT Hub needs the hub name (without .azure-devices.net) and the device id")
            if not sec.get("device_key"):
                raise ValueError("Azure device primary key is required")
            try:
                base64.b64decode(sec["device_key"], validate=True)
            except ValueError as exc:
                raise ValueError("Azure device key must be base64") from exc
        else:
            url = str(cfg.get("url", ""))
            if not url.startswith("https://") and not self.allow_private:
                raise ValueError("Endpoint must use https://")
            check_destination(url, self.allow_private)

    def save(self, company: str, data: dict, integration_id: int | None = None) -> dict:
        company_id(company)
        current = self.get(integration_id, with_secrets=True) if integration_id else None
        if integration_id and (current is None or current["company"] != company):
            raise LookupError("Integration not found")
        kind = data.get("kind") or (current or {}).get("kind")
        cfg = {**((current or {}).get("config") or {}), **(data.get("config") or {})}
        sec = {**((current or {}).get("secret_values") or {}),
               **{k: v for k, v in (data.get("secrets") or {}).items() if v not in (None, "")}}
        self._validate(kind, cfg, sec)
        name = str(data.get("name") or (current or {}).get("name") or kind)[:80]
        enabled = int(bool(data.get("enabled", (current or {}).get("enabled", True))))
        now = int(time.time())
        sealed = seal(self.secret_key, json.dumps(sec)) if sec else None
        with self.main.connect() as db:
            if integration_id:
                db.execute("UPDATE integrations SET kind=?, name=?, config=?, secrets=?, enabled=?, updated_at=? WHERE id=?",
                           (kind, name, json.dumps(cfg), sealed, enabled, now, integration_id))
            else:
                integration_id = db.execute(
                    "INSERT INTO integrations(company, kind, name, config, secrets, enabled, created_at, updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?)", (company, kind, name, json.dumps(cfg), sealed, enabled, now, now)).lastrowid
        self.refresh()
        return self.get(integration_id)

    def delete(self, company: str, integration_id: int) -> None:
        with self.main.connect() as db:
            if not db.execute("DELETE FROM integrations WHERE id=? AND company=?", (integration_id, company)).rowcount:
                raise LookupError("Integration not found")
        self.refresh()

    def refresh(self) -> None:
        with self._lock:
            self._active_at = 0.0

    def _for(self, company: str) -> list[dict]:
        with self._lock:
            if time.time() - self._active_at > 30:
                active: dict[str, list[dict]] = {}
                with self.main.connect() as db:
                    for row in db.execute("SELECT * FROM integrations WHERE enabled=1"):
                        item = self._public(row)
                        item["secret_values"] = self._secrets(dict(row))
                        active.setdefault(item["company"], []).append(item)
                self._active, self._active_at = active, time.time()
            return self._active.get(company, [])

    # ------------------------------------------------------------ forward
    def on_event(self, event: str, data: dict, company: str | None) -> None:
        if event != "telemetry" or not company or data.get("type") not in ("Status", "Telemetry"):
            return
        for integ in self._for(company):
            try:
                self.queue.put_nowait((integ, reading({**data, "company": company})))
            except queue.Full:
                self._bump(integ["id"], "dropped")

    def _bump(self, integration_id: int, key: str, error: str | None = None) -> None:
        with self._lock:
            s = self._stats.setdefault(integration_id, {"sent": 0, "failed": 0, "dropped": 0})
            s[key] += 1
            if error:
                s["error"], s["error_at"] = error, int(time.time())
            elif key == "sent":
                s["ok_at"] = int(time.time())

    def flush_stats(self) -> None:
        """Persist the live counters (maintenance cycle)."""
        with self._lock:
            stats, self._stats = self._stats, {}
        with self.main.connect() as db:
            for iid, s in stats.items():
                db.execute("UPDATE integrations SET sent=sent+?, failed=failed+?, dropped=dropped+?, "
                           "last_ok_at=COALESCE(?, last_ok_at), last_error=COALESCE(?, last_error), "
                           "last_error_at=COALESCE(?, last_error_at) WHERE id=?",
                           (s["sent"], s["failed"], s["dropped"], s.get("ok_at"), s.get("error"), s.get("error_at"), iid))

    def _run(self) -> None:
        while True:
            integ, item = self.queue.get()
            self.deliver(integ, item)

    def deliver(self, integ: dict, item: dict, retries=RETRIES) -> tuple[bool, str]:
        err = ""
        for delay in retries:
            if delay:
                time.sleep(delay)
            try:
                status, body = self.send(integ, item)
                if 200 <= status < 300:
                    self._bump(integ["id"], "sent")
                    return True, f"HTTP {status}"
                err = f"HTTP {status}: {body[:200]}"
                if 400 <= status < 500 and status != 429:
                    break                                   # configuration error: retrying will not help
            except Exception as exc:
                err = f"{type(exc).__name__}: {exc}"
        self._bump(integ["id"], "failed", err)
        return False, err

    def send(self, integ: dict, item: dict) -> tuple[int, str]:
        cfg, sec = integ["config"], integ.get("secret_values", {})
        if integ["kind"] == "thingsboard":
            token = sec["access_token"]
            if cfg.get("device_per_node"):
                token = json.loads(sec.get("node_tokens") or "{}").get(str(item["node_id"]), token)
                values = {k: v for k, v in item.items() if k not in ("company", "region", "type")}
            else:
                prefix = f"n{item['node_id']}_"
                values = {prefix + k: v for k, v in item.items() if k not in ("company", "region", "node_id", "ts", "type")}
            body = json.dumps({"ts": int(item["ts"] or time.time()) * 1000, "values": values}).encode()
            return self.http("POST", f"{cfg['host'].rstrip('/')}/api/v1/{token}/telemetry",
                             {"Content-Type": "application/json"}, body)
        if integ["kind"] == "azure_iot":
            resource = f"{cfg['hub']}.azure-devices.net/devices/{cfg['device_id']}"
            headers = {"Authorization": azure_sas(resource, sec["device_key"]), "Content-Type": "application/json",
                       "iothub-contenttype": "application/json", "iothub-contentencoding": "utf-8"}
            return self.http("POST", f"https://{resource}/messages/events?api-version=2020-03-13", headers,
                             json.dumps(item).encode())
        headers = {"Content-Type": "application/json", **json.loads(sec.get("headers") or "{}")}
        return self.http("POST", cfg["url"], headers, json.dumps(item).encode())

    def test(self, company: str, integration_id: int) -> dict:
        integ = self.get(integration_id, with_secrets=True)
        if not integ or integ["company"] != company:
            raise LookupError("Integration not found")
        ok, detail = self.deliver(integ, {"company": company, "region": "Region_1", "node_id": 0,
                                          "ts": int(time.time()), "received_at": int(time.time()), "type": "Test",
                                          "test": True}, retries=(0,))
        return {"ok": ok, "detail": detail}
