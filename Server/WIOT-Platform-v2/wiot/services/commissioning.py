"""Commissioning wizard (R2.6, point 25): QR scan -> register -> first uplink -> clock -> checks -> certificate.

The node's QR label carries ``WIOT:<company>/<region>/<node_id>?type=control&sensors=tuf,hnda&name=P-12``
(plain node numbers and JSON are accepted too). The wizard registers the node in the Organization registry with
the technician's GPS position, waits for its first uplink, queues a clock set when the node's clock is not
trusted, and runs the acceptance checks. "Mark commissioned" stores the record as an asset in the maintenance
module and produces a PDF certificate.
"""
from __future__ import annotations

import json
import re
import time
from urllib.parse import parse_qs, urlsplit

from ..storage.org_store import SENSORS, sensors_from_mask

QR = re.compile(r"^WIOT:(?P<company>[^/]+)/(?P<region>[^/]+)/(?P<node>\d{1,5})(?:\?(?P<q>.*))?$", re.I)
MIN_BATTERY_V = 3.6


def parse_qr(text: str) -> dict:
    text = (text or "").strip()
    if not text:
        raise ValueError("Empty code")
    if text.isdigit():
        return {"node_id": int(text)}
    m = QR.match(text)
    if m:
        q = {k: v[0] for k, v in parse_qs(m.group("q") or "").items()}
        out = {"company": m.group("company"), "region": m.group("region"), "node_id": int(m.group("node"))}
        if q.get("type") in ("monitoring", "control"):
            out["type"] = q["type"]
        if q.get("sensors"):
            out["sensors"] = [s for s in q["sensors"].split(",") if s in SENSORS]
        if q.get("name"):
            out["name"] = q["name"][:80]
        return out
    if text.startswith("{"):
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError("Unreadable code") from exc
        if isinstance(data, dict) and str(data.get("node_id", "")).isdigit():
            return {k: data[k] for k in ("company", "region", "node_id", "type", "sensors", "name") if k in data}
    if urlsplit(text).scheme in ("http", "https"):
        raise ValueError("This QR code is a web link, not a WIOT node label")
    raise ValueError("Not a WIOT node label")


class Commissioning:
    def __init__(self, telemetry, org, commands, maintenance=None, audit=None):
        self.telemetry = telemetry
        self.org = org
        self.commands = commands
        self.maintenance = maintenance
        self.audit = audit

    def register(self, company: str, data: dict, actor: str) -> dict:
        node_id = int(data["node_id"])
        row, created = self.org.upsert_node(company, {
            "region": data.get("region") or "Region_1", "node_id": node_id, "name": data.get("name") or f"Node {node_id}",
            "type": data.get("type") or "monitoring", "sensors": ",".join(data.get("sensors") or []),
            "lat": data.get("lat"), "lon": data.get("lon"), "install_date": time.strftime("%Y-%m-%d"),
            "notes": data.get("notes") or f"Commissioned by {actor}"}, create=None)
        return {"node": row, "created": created}

    def checks(self, company: str, region: str, node_id: int, now: int | None = None) -> dict:
        now = int(time.time() if now is None else now)
        reg = next((n for n in self.org.list_nodes(company, region) if int(n["node_id"]) == node_id), None)
        latest = self.telemetry.latest.get((company, region, node_id))
        if latest is None:
            fleet = {n["node_id"]: n for n in self.telemetry.fleet(company, region)}
            latest = fleet.get(node_id)
        items = []

        def add(key, label, ok, detail, blocking=True):
            items.append({"key": key, "label": label, "ok": ok, "detail": detail, "blocking": blocking})

        add("registered", "Registered in the organization", reg is not None, "in the registry" if reg else "not registered")
        if latest is None:
            add("uplink", "First uplink received", False, "waiting for the node's first report")
            return {"node_id": node_id, "region": region, "ready": False, "items": items, "last_seen": None}
        age = now - int(latest.get("timestamp") or 0)
        add("uplink", "First uplink received", age < 3600, f"{age // 60} min ago" if age >= 60 else f"{age} s ago")
        batt = latest.get("battery_voltage")
        add("battery", f"Battery at least {MIN_BATTERY_V} V", bool(batt and batt >= MIN_BATTERY_V),
            f"{batt:.2f} V" if batt else "no battery reading")
        add("clock", "Node clock trusted", bool(latest.get("rtc_valid")),
            "trusted" if latest.get("rtc_valid") else "not set - send the clock", blocking=False)
        detected = sensors_from_mask(latest.get("sensor_mask") or 0)
        wanted = [s for s in str((reg or {}).get("sensors") or "").split(",") if s] if reg else []
        if isinstance((reg or {}).get("sensors"), list):
            wanted = reg["sensors"]
        missing = [s for s in wanted if s not in detected]
        add("sensors", "Fitted sensors detected", not missing,
            f"detected {', '.join(detected) or 'none'}" + (f"; missing {', '.join(missing)}" if missing else ""))
        if "hnda" in detected or "sondas" in detected:
            ok = bool(latest.get("soil_moisture_temp_valid") or latest.get("soil_moisture_temp_ec_valid"))
            add("soil", "Soil probe reading valid", ok, "valid" if ok else "probe reports invalid values")
        if "tuf" in detected or "supmea" in detected:
            add("flow", "Flow meter reading valid", bool(latest.get("flow_live_valid")),
                "valid" if latest.get("flow_live_valid") else "meter not answering")
        add("power_mode", "Power mode reported", bool(latest.get("power_mode")),
            str(latest.get("power_mode_name") or latest.get("power_mode") or "not reported"), blocking=False)
        ready = all(i["ok"] for i in items if i["blocking"])
        return {"node_id": node_id, "region": region, "ready": ready, "items": items, "last_seen": latest.get("timestamp"),
                "battery_v": batt, "sensors_detected": detected}

    def send_clock(self, company: str, region: str, node_id: int, actor: str) -> dict:
        from .commands import CommandRequest
        return self.commands.submit(CommandRequest(company=company, region=region, node_id=node_id, cmd_type="STIME",
                                                   delivery="auto", ttl_seconds=3600), actor=actor)

    def complete(self, company: str, region: str, node_id: int, actor: str, notes: str = "") -> dict:
        result = self.checks(company, region, node_id)
        if not result["ready"]:
            raise ValueError("Not all required checks have passed")
        record = {"company": company, "region": region, "node_id": node_id, "by": actor, "at": int(time.time()),
                  "notes": notes[:500], "checks": result["items"], "battery_v": result.get("battery_v"),
                  "sensors": result.get("sensors_detected")}
        if self.maintenance is not None:
            asset = self.maintenance.asset_for_node(company, region, node_id, actor)
            self.maintenance.add_record(company, asset["id"], "commissioning", record, actor)
            record["asset_id"] = asset["id"]
        if self.audit is not None:
            self.audit(actor, "node_commissioned", company=company, target=f"{region}/{node_id}",
                       details={"battery_v": record["battery_v"], "sensors": record["sensors"]})
        return record
