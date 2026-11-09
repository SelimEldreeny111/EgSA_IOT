"""Organization registry: company profiles, regions, nodes, gateways, API tokens, webhooks.

Lives in ``iot_data.db`` next to users/companies. Everything is additive (new tables and new
nullable columns on ``companies``), so a v1.31 server can still open the file.

Nodes and regions keep working without registration — telemetry is still accepted for any
valid region/node — unless a company switches on *strict provisioning*, in which case only
registered nodes are ingested.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import secrets
import sqlite3
import threading
import time
from datetime import date
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..protocol.topics import region_id
from ..protocol.validation import company_id
from .main_store import MainStore

UNITS = ("metric", "imperial")
LANGUAGES = ("en", "ar")
NODE_KINDS = ("soil", "flow", "valve", "soil_flow", "weather", "gateway_bridge", "other")  # legacy "kind" values
# Two node types: monitoring nodes only report sensors; control nodes also drive a valve.
NODE_TYPES = ("monitoring", "control")
CONTROL_KINDS = ("valve", "soil_flow")
# Sensors the WIOT firmware reports, with their sensor_mask bit.
SENSORS = {"tuf": 0x01, "hnda": 0x02, "sondas": 0x04, "supmea": 0x08}


def sensors_from_mask(mask) -> list[str]:
    try:
        mask = int(mask or 0)
    except (TypeError, ValueError):
        return []
    return [k for k, bit in SENSORS.items() if mask & bit]


def parse_sensors(value) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, str):
        value = [v for v in re.split(r"[|;, ]+", value) if v]
    out = sorted({str(v).strip().lower() for v in value})
    bad = [v for v in out if v not in SENSORS]
    if bad:
        raise ValueError(f"Unknown sensor(s) {', '.join(bad)}; choose from: {', '.join(SENSORS)}")
    return out
BACKHAULS = ("lora", "wifi", "cellular", "satellite", "ethernet")
WEBHOOK_EVENTS = ("telemetry", "command", "automation", "alert", "flash")
TOKEN_SCOPES = ("read", "write")
_GW = re.compile(r"[A-Za-z0-9._-]{1,32}")
NODE_COLUMNS = ("region", "node_id", "name", "type", "sensors", "lat", "lon", "gateway", "install_date", "report_interval_s", "notes")


# ---------------------------------------------------------------- validators
def check_timezone(tz: str | None) -> str | None:
    if tz in (None, ""):
        return None
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"Unknown time zone '{tz}' (use an IANA name such as Africa/Cairo)") from exc
    return tz


def check_country(code: str | None) -> str | None:
    if code in (None, ""):
        return None
    code = code.strip().upper()
    if not re.fullmatch(r"[A-Z]{2}", code):
        raise ValueError("Country must be an ISO 3166-1 alpha-2 code such as EG")
    return code


def check_point(lat, lon) -> tuple[float | None, float | None]:
    if lat in (None, "") and lon in (None, ""):
        return None, None
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError) as exc:
        raise ValueError("Latitude and longitude must both be numbers") from exc
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("Latitude must be -90..90 and longitude -180..180")
    return round(lat, 6), round(lon, 6)


def _text(value, limit: int, what: str) -> str:
    value = (value or "").strip()
    if len(value) > limit:
        raise ValueError(f"{what} is limited to {limit} characters")
    return value


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class OrgStore:
    def __init__(self, main: MainStore):
        self.main = main
        self._lock = threading.Lock()
        self._cache: dict[str, dict] = {}   # company -> {"tz", "strict", "nodes"}

    # ------------------------------------------------------------------ schema
    def init_schema(self) -> None:
        with self.main.connect() as db:
            cols = {r["name"] for r in db.execute("PRAGMA table_info(companies)")}
            for name, ddl in {
                "display_name": "TEXT", "country": "TEXT", "timezone": "TEXT", "units": "TEXT",
                "language": "TEXT", "lat": "REAL", "lon": "REAL", "notes": "TEXT",
                "active": "INTEGER NOT NULL DEFAULT 1", "strict_nodes": "INTEGER NOT NULL DEFAULT 0",
                "updated_at": "INTEGER",
            }.items():
                if name not in cols:
                    db.execute(f"ALTER TABLE companies ADD COLUMN {name} {ddl}")
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS org_regions (
                    company TEXT NOT NULL, region TEXT NOT NULL, display_name TEXT, country TEXT,
                    timezone TEXT, lat REAL, lon REAL, notes TEXT,
                    created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
                    PRIMARY KEY (company, region));
                CREATE TABLE IF NOT EXISTS org_nodes (
                    company TEXT NOT NULL, region TEXT NOT NULL, node_id INTEGER NOT NULL,
                    name TEXT, kind TEXT, lat REAL, lon REAL, gateway TEXT, install_date TEXT,
                    report_interval_s INTEGER, notes TEXT,
                    created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
                    PRIMARY KEY (company, region, node_id));
                CREATE TABLE IF NOT EXISTS org_gateways (
                    company TEXT NOT NULL, gw_id TEXT NOT NULL, name TEXT, region TEXT,
                    lat REAL, lon REAL, backhaul TEXT, primary_link TEXT, notes TEXT,
                    created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
                    PRIMARY KEY (company, gw_id));
                CREATE TABLE IF NOT EXISTS api_tokens (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, company TEXT NOT NULL, name TEXT NOT NULL,
                    token_hash TEXT NOT NULL UNIQUE, prefix TEXT NOT NULL, scope TEXT NOT NULL,
                    created_by TEXT NOT NULL, created_at INTEGER NOT NULL, expires_at INTEGER,
                    last_used_at INTEGER, revoked_at INTEGER);
                CREATE TABLE IF NOT EXISTS webhooks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, company TEXT NOT NULL, name TEXT NOT NULL,
                    url TEXT NOT NULL, secret TEXT NOT NULL, events TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1, created_by TEXT NOT NULL, created_at INTEGER NOT NULL,
                    last_delivery_at INTEGER, last_status INTEGER, last_error TEXT,
                    deliveries INTEGER NOT NULL DEFAULT 0, failures INTEGER NOT NULL DEFAULT 0);
                """
            )
            node_cols = {r["name"] for r in db.execute("PRAGMA table_info(org_nodes)")}
            for name in ("node_type", "sensors"):
                if name not in node_cols:
                    db.execute(f"ALTER TABLE org_nodes ADD COLUMN {name} TEXT")
            db.execute("UPDATE org_nodes SET node_type = CASE WHEN kind IN ('valve', 'soil_flow') THEN 'control' "
                       "ELSE 'monitoring' END WHERE node_type IS NULL")
        self.invalidate()

    def invalidate(self, company: str | None = None) -> None:
        with self._lock:
            if company is None:
                self._cache.clear()
            else:
                self._cache.pop(company, None)

    # --------------------------------------------------------------- companies
    def list_companies(self, *, include_archived: bool = True) -> list[dict]:
        with self.main.connect() as db:
            rows = [dict(r) for r in db.execute("SELECT * FROM companies ORDER BY id")]
            regions = dict(db.execute("SELECT company, COUNT(*) FROM org_regions GROUP BY company").fetchall())
            nodes = dict(db.execute("SELECT company, COUNT(*) FROM org_nodes GROUP BY company").fetchall())
            gws = dict(db.execute("SELECT company, COUNT(*) FROM org_gateways GROUP BY company").fetchall())
        out = []
        for r in rows:
            r = self._company_public(r)
            if not include_archived and not r["active"]:
                continue
            r.update(registered_regions=regions.get(r["name"], 0), registered_nodes=nodes.get(r["name"], 0),
                     gateways=gws.get(r["name"], 0))
            out.append(r)
        return out

    def get_company(self, name: str) -> dict | None:
        with self.main.connect() as db:
            row = db.execute("SELECT * FROM companies WHERE name=?", (name,)).fetchone()
        return self._company_public(dict(row)) if row else None

    @staticmethod
    def _company_public(r: dict) -> dict:
        return {
            "id": r["id"], "name": r["name"], "display_name": r.get("display_name") or r["name"],
            "country": r.get("country"), "timezone": r.get("timezone") or "Africa/Cairo",
            "units": r.get("units") or "metric", "language": r.get("language") or "en",
            "lat": r.get("lat"), "lon": r.get("lon"), "notes": r.get("notes") or "",
            "active": bool(r.get("active", 1) if r.get("active") is not None else 1),
            "strict_nodes": bool(r.get("strict_nodes") or 0), "created_at": r.get("created_at"),
        }

    def create_company(self, name: str, profile: dict) -> dict:
        name = (name or "").strip()
        company_id(name)
        self.main.add_company(name)
        return self.update_company(name, profile)

    def update_company(self, name: str, changes: dict) -> dict:
        current = self.get_company(name)
        if current is None:
            raise LookupError("Unknown company")
        fields: dict = {}
        if "display_name" in changes:
            fields["display_name"] = _text(changes["display_name"], 120, "Display name") or None
        if "country" in changes:
            fields["country"] = check_country(changes["country"])
        if "timezone" in changes:
            fields["timezone"] = check_timezone(changes["timezone"])
        if "units" in changes:
            if changes["units"] not in UNITS:
                raise ValueError("Units must be metric or imperial")
            fields["units"] = changes["units"]
        if "language" in changes:
            if changes["language"] not in LANGUAGES:
                raise ValueError("Language must be en or ar")
            fields["language"] = changes["language"]
        if "lat" in changes or "lon" in changes:
            fields["lat"], fields["lon"] = check_point(changes.get("lat", current["lat"]), changes.get("lon", current["lon"]))
        if "notes" in changes:
            fields["notes"] = _text(changes["notes"], 500, "Notes")
        if "active" in changes:
            fields["active"] = 1 if changes["active"] else 0
        if "strict_nodes" in changes:
            fields["strict_nodes"] = 1 if changes["strict_nodes"] else 0
        if fields:
            fields["updated_at"] = int(time.time())
            with self.main.connect() as db:
                db.execute(f"UPDATE companies SET {', '.join(f'{k}=?' for k in fields)} WHERE name=?",
                           (*fields.values(), name))
        self.invalidate(name)
        return self.get_company(name)

    # ----------------------------------------------------------------- regions
    def list_regions(self, company: str) -> list[dict]:
        with self.main.connect() as db:
            rows = [dict(r) for r in db.execute(
                "SELECT * FROM org_regions WHERE company=? ORDER BY region", (company,))]
            counts = dict(db.execute("SELECT region, COUNT(*) FROM org_nodes WHERE company=? GROUP BY region",
                                     (company,)).fetchall())
        for r in rows:
            r["registered_nodes"] = counts.get(r["region"], 0)
        return rows

    def region_ids(self, company: str) -> list[str]:
        with self.main.connect() as db:
            return [r[0] for r in db.execute("SELECT region FROM org_regions WHERE company=?", (company,))]

    def upsert_region(self, company: str, region: str, data: dict, *, create: bool) -> dict:
        region = region_id((region or "").strip())
        lat, lon = check_point(data.get("lat"), data.get("lon"))
        values = (_text(data.get("display_name"), 80, "Display name") or None, check_country(data.get("country")),
                  check_timezone(data.get("timezone")), lat, lon, _text(data.get("notes"), 500, "Notes"))
        now = int(time.time())
        with self.main.connect() as db:
            exists = db.execute("SELECT 1 FROM org_regions WHERE company=? AND region=?", (company, region)).fetchone()
            if create and exists:
                raise ValueError(f"Region {region} already exists")
            if not create and not exists:
                raise LookupError("Unknown region")
            if exists:
                db.execute("UPDATE org_regions SET display_name=?, country=?, timezone=?, lat=?, lon=?, notes=?, "
                           "updated_at=? WHERE company=? AND region=?", (*values, now, company, region))
            else:
                db.execute("INSERT INTO org_regions VALUES (?,?,?,?,?,?,?,?,?,?)", (company, region, *values, now, now))
        self.invalidate(company)
        return next(r for r in self.list_regions(company) if r["region"] == region)

    def delete_region(self, company: str, region: str) -> None:
        with self.main.connect() as db:
            n = db.execute("SELECT COUNT(*) FROM org_nodes WHERE company=? AND region=?", (company, region)).fetchone()[0]
            if n:
                raise ValueError(f"Region {region} still has {n} registered node(s); move or remove them first")
            if not db.execute("DELETE FROM org_regions WHERE company=? AND region=?", (company, region)).rowcount:
                raise LookupError("Unknown region")
        self.invalidate(company)

    # ------------------------------------------------------------------- nodes
    def list_nodes(self, company: str, region: str | None = None) -> list[dict]:
        query, params = "SELECT * FROM org_nodes WHERE company=?", [company]
        if region:
            query += " AND region=?"
            params.append(region)
        with self.main.connect() as db:
            rows = [dict(r) for r in db.execute(query + " ORDER BY region, node_id", params)]
        for r in rows:
            r["node_type"] = r.get("node_type") or ("control" if r.get("kind") in CONTROL_KINDS else "monitoring")
            try:
                r["sensors"] = json.loads(r.get("sensors") or "[]")
            except json.JSONDecodeError:
                r["sensors"] = []
        return rows

    def _node_values(self, company: str, data: dict) -> tuple:
        region = region_id(str(data.get("region") or "Region_1").strip())
        try:
            node_id = int(data.get("node_id"))
        except (TypeError, ValueError) as exc:
            raise ValueError("Node ID must be a number 1..65535") from exc
        if not 1 <= node_id <= 65535:
            raise ValueError("Node ID must be 1..65535")
        node_type = (data.get("node_type") or data.get("type") or "").strip().lower()
        if not node_type:  # legacy "kind" (API clients / old CSV files)
            kind = (data.get("kind") or "other").strip()
            if kind not in NODE_KINDS:
                raise ValueError(f"Kind must be one of: {', '.join(NODE_KINDS)}")
            node_type = "control" if kind in CONTROL_KINDS else "monitoring"
        if node_type not in NODE_TYPES:
            raise ValueError("Node type must be monitoring (sensors only) or control (sensors + valve)")
        sensors = parse_sensors(data.get("sensors"))
        lat, lon = check_point(data.get("lat"), data.get("lon"))
        gateway = (data.get("gateway") or "").strip() or None
        if gateway and not _GW.fullmatch(gateway):
            raise ValueError("Gateway ID must be 1..32 letters, digits, '.', '_' or '-'")
        install = (data.get("install_date") or "").strip() or None
        if install:
            try:
                date.fromisoformat(install)
            except ValueError as exc:
                raise ValueError("Install date must be YYYY-MM-DD") from exc
        interval = data.get("report_interval_s")
        if interval in (None, ""):
            interval = None
        else:
            interval = int(interval)
            if not 5 <= interval <= 7 * 86400:
                raise ValueError("Report interval must be 5 s .. 7 days")
        return (region, node_id, _text(data.get("name"), 80, "Name") or f"Node {node_id}", node_type, lat, lon,
                gateway, install, interval, _text(data.get("notes"), 500, "Notes"), node_type, json.dumps(sensors))

    def upsert_node(self, company: str, data: dict, *, create: bool | None) -> tuple[dict, bool]:
        """create=True: must be new; False: must exist; None: insert or update. Returns (row, created)."""
        v = self._node_values(company, data)
        now = int(time.time())
        with self.main.connect() as db:
            exists = db.execute("SELECT 1 FROM org_nodes WHERE company=? AND region=? AND node_id=?",
                                (company, v[0], v[1])).fetchone()
            if create is True and exists:
                raise ValueError(f"Node {v[1]} is already registered in {v[0]}")
            if create is False and not exists:
                raise LookupError("Unknown node")
            if exists:
                db.execute("UPDATE org_nodes SET name=?, kind=?, lat=?, lon=?, gateway=?, install_date=?, "
                           "report_interval_s=?, notes=?, node_type=?, sensors=?, updated_at=? "
                           "WHERE company=? AND region=? AND node_id=?", (*v[2:], now, company, v[0], v[1]))
            else:
                db.execute("INSERT INTO org_nodes(company, region, node_id, name, kind, lat, lon, gateway, install_date, "
                           "report_interval_s, notes, node_type, sensors, created_at, updated_at) "
                           "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (company, *v, now, now))
        self.invalidate(company)
        row = next(n for n in self.list_nodes(company, v[0]) if n["node_id"] == v[1])
        return row, not exists

    def move_node(self, company: str, region: str, node_id: int, new_region: str) -> None:
        new_region = region_id(new_region)
        with self.main.connect() as db:
            if db.execute("SELECT 1 FROM org_nodes WHERE company=? AND region=? AND node_id=?",
                          (company, new_region, node_id)).fetchone():
                raise ValueError(f"Node {node_id} is already registered in {new_region}")
            if not db.execute("UPDATE org_nodes SET region=?, updated_at=? WHERE company=? AND region=? AND node_id=?",
                              (new_region, int(time.time()), company, region, node_id)).rowcount:
                raise LookupError("Unknown node")
        self.invalidate(company)

    def delete_node(self, company: str, region: str, node_id: int) -> None:
        with self.main.connect() as db:
            if not db.execute("DELETE FROM org_nodes WHERE company=? AND region=? AND node_id=?",
                              (company, region, node_id)).rowcount:
                raise LookupError("Unknown node")
        self.invalidate(company)

    def import_nodes_csv(self, company: str, text: str, limit: int = 5000) -> dict:
        reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
        if not reader.fieldnames or not {"region", "node_id"} <= {f.strip() for f in reader.fieldnames}:
            raise ValueError(f"CSV header must include region and node_id (columns: {', '.join(NODE_COLUMNS)})")
        created = updated = 0
        errors = []
        for line, row in enumerate(reader, start=2):
            if line - 1 > limit:
                errors.append({"line": line, "error": f"Stopped after {limit} rows"})
                break
            row = {(k or "").strip(): (v or "").strip() for k, v in row.items()}
            if not any(row.values()):
                continue
            try:
                _, was_new = self.upsert_node(company, row, create=None)
                created += was_new
                updated += not was_new
            except (ValueError, LookupError) as exc:
                errors.append({"line": line, "error": str(exc)})
        return {"created": created, "updated": updated, "errors": errors[:200]}

    def export_nodes_csv(self, company: str) -> str:
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(NODE_COLUMNS)
        for n in self.list_nodes(company):
            row = {**n, "type": n["node_type"], "sensors": "|".join(n["sensors"])}
            w.writerow([row.get(c) if row.get(c) is not None else "" for c in NODE_COLUMNS])
        return buf.getvalue()

    # ---------------------------------------------------------------- gateways
    def list_gateways(self, company: str) -> list[dict]:
        with self.main.connect() as db:
            rows = [dict(r) for r in db.execute("SELECT * FROM org_gateways WHERE company=? ORDER BY gw_id", (company,))]
            counts = dict(db.execute("SELECT gateway, COUNT(*) FROM org_nodes WHERE company=? AND gateway IS NOT NULL "
                                     "GROUP BY gateway", (company,)).fetchall())
        for r in rows:
            r["backhaul"] = json.loads(r["backhaul"] or "[]")
            r["primary"] = r.pop("primary_link")
            r["nodes"] = counts.get(r["gw_id"], 0)
        return rows

    def upsert_gateway(self, company: str, data: dict, *, create: bool) -> dict:
        gw_id = (data.get("gw_id") or "").strip()
        if not _GW.fullmatch(gw_id):
            raise ValueError("Gateway ID must be 1..32 letters, digits, '.', '_' or '-'")
        region = (data.get("region") or "").strip() or None
        if region:
            region_id(region)
        backhaul = [b for b in data.get("backhaul") or ["lora", "cellular"] if b]
        if not backhaul or any(b not in BACKHAULS for b in backhaul):
            raise ValueError(f"Backhaul must be chosen from: {', '.join(BACKHAULS)}")
        primary = data.get("primary") or next((b for b in backhaul if b != "lora"), "cellular")
        if primary not in BACKHAULS or primary == "lora":
            raise ValueError("Primary backhaul must be wifi, cellular, satellite or ethernet")
        lat, lon = check_point(data.get("lat"), data.get("lon"))
        values = (_text(data.get("name"), 80, "Name") or gw_id, region, lat, lon, json.dumps(sorted(set(backhaul))),
                  primary, _text(data.get("notes"), 500, "Notes"))
        now = int(time.time())
        with self.main.connect() as db:
            exists = db.execute("SELECT 1 FROM org_gateways WHERE company=? AND gw_id=?", (company, gw_id)).fetchone()
            if create and exists:
                raise ValueError(f"Gateway {gw_id} already exists")
            if not create and not exists:
                raise LookupError("Unknown gateway")
            if exists:
                db.execute("UPDATE org_gateways SET name=?, region=?, lat=?, lon=?, backhaul=?, primary_link=?, notes=?, "
                           "updated_at=? WHERE company=? AND gw_id=?", (*values, now, company, gw_id))
            else:
                db.execute("INSERT INTO org_gateways VALUES (?,?,?,?,?,?,?,?,?,?,?)", (company, gw_id, *values, now, now))
        return next(g for g in self.list_gateways(company) if g["gw_id"] == gw_id)

    def delete_gateway(self, company: str, gw_id: str) -> None:
        with self.main.connect() as db:
            if not db.execute("DELETE FROM org_gateways WHERE company=? AND gw_id=?", (company, gw_id)).rowcount:
                raise LookupError("Unknown gateway")
            db.execute("UPDATE org_nodes SET gateway=NULL WHERE company=? AND gateway=?", (company, gw_id))

    # ------------------------------------------------------- ingest fast path
    def _profile(self, company: str) -> dict:
        with self._lock:
            hit = self._cache.get(company)
        if hit is not None:
            return hit
        c = self.get_company(company) or {}
        with self.main.connect() as db:
            nodes = {(r[0], r[1]): r[2] or ("control" if r[3] in CONTROL_KINDS else "monitoring")
                     for r in db.execute("SELECT region, node_id, node_type, kind FROM org_nodes WHERE company=?", (company,))}
        prof = {"tz": c.get("timezone") or "Africa/Cairo", "strict": bool(c.get("strict_nodes")), "nodes": nodes}
        with self._lock:
            self._cache[company] = prof
        return prof

    def timezone(self, company: str) -> str:
        return self._profile(company)["tz"]

    def node_type(self, company: str, region: str, node_id) -> str | None:
        """'monitoring' / 'control' for a registered node, None when the node is not registered."""
        try:
            return self._profile(company)["nodes"].get((region, int(node_id)))
        except (TypeError, ValueError):
            return None

    def accepts(self, company: str, region: str, node_id: int) -> bool:
        prof = self._profile(company)
        return not prof["strict"] or (region, int(node_id)) in prof["nodes"] or not node_id

    # -------------------------------------------------------------- API tokens
    def create_token(self, company: str, name: str, scope: str, actor: str, expires_days: int | None) -> dict:
        if scope not in TOKEN_SCOPES:
            raise ValueError("Scope must be read or write")
        name = _text(name, 80, "Token name")
        if not name:
            raise ValueError("Give the token a name")
        token = "wiot_" + secrets.token_urlsafe(32)
        now = int(time.time())
        expires = now + int(expires_days) * 86400 if expires_days else None
        with self.main.connect() as db:
            cur = db.execute("INSERT INTO api_tokens(company,name,token_hash,prefix,scope,created_by,created_at,expires_at) "
                             "VALUES(?,?,?,?,?,?,?,?)", (company, name, _hash(token), token[:12], scope, actor, now, expires))
        return {"id": cur.lastrowid, "token": token, "prefix": token[:12], "name": name, "scope": scope,
                "company": company, "expires_at": expires}

    def list_tokens(self, company: str) -> list[dict]:
        with self.main.connect() as db:
            return [dict(r) for r in db.execute(
                "SELECT id, company, name, prefix, scope, created_by, created_at, expires_at, last_used_at, revoked_at "
                "FROM api_tokens WHERE company=? ORDER BY id DESC", (company,))]

    def revoke_token(self, company: str, token_id: int) -> None:
        with self.main.connect() as db:
            if not db.execute("UPDATE api_tokens SET revoked_at=? WHERE id=? AND company=? AND revoked_at IS NULL",
                              (int(time.time()), token_id, company)).rowcount:
                raise LookupError("Unknown or already revoked token")

    def resolve_token(self, token: str) -> dict | None:
        with self.main.connect() as db:
            row = db.execute("SELECT * FROM api_tokens WHERE token_hash=?", (_hash(token),)).fetchone()
            if row is None or row["revoked_at"] or (row["expires_at"] and row["expires_at"] < time.time()):
                return None
            if not row["last_used_at"] or time.time() - row["last_used_at"] > 60:
                db.execute("UPDATE api_tokens SET last_used_at=? WHERE id=?", (int(time.time()), row["id"]))
            return dict(row)

    # ---------------------------------------------------------------- webhooks
    def list_webhooks(self, company: str | None = None, *, active_only: bool = False) -> list[dict]:
        query, params = "SELECT * FROM webhooks", []
        where = []
        if company is not None:
            where.append("company=?")
            params.append(company)
        if active_only:
            where.append("active=1")
        if where:
            query += " WHERE " + " AND ".join(where)
        with self.main.connect() as db:
            rows = [dict(r) for r in db.execute(query + " ORDER BY id", params)]
        for r in rows:
            r["events"] = json.loads(r["events"] or "[]")
            r["active"] = bool(r["active"])
        return rows

    def get_webhook(self, company: str, hook_id: int) -> dict:
        hook = next((h for h in self.list_webhooks(company) if h["id"] == hook_id), None)
        if hook is None:
            raise LookupError("Unknown webhook")
        return hook

    def save_webhook(self, company: str, data: dict, actor: str, hook_id: int | None = None) -> dict:
        name = _text(data.get("name"), 80, "Name")
        url = (data.get("url") or "").strip()
        if not name:
            raise ValueError("Give the webhook a name")
        if not re.fullmatch(r"https?://[^\s/$.?#].[^\s]{0,2000}", url):
            raise ValueError("URL must start with http:// or https://")
        events = sorted({e for e in data.get("events") or [] if e})
        if not events or any(e not in WEBHOOK_EVENTS for e in events):
            raise ValueError(f"Choose events from: {', '.join(WEBHOOK_EVENTS)}")
        active = 1 if data.get("active", True) else 0
        with self.main.connect() as db:
            if hook_id is None:
                secret = "whsec_" + secrets.token_urlsafe(24)
                cur = db.execute("INSERT INTO webhooks(company,name,url,secret,events,active,created_by,created_at) "
                                 "VALUES(?,?,?,?,?,?,?,?)", (company, name, url, secret, json.dumps(events), active,
                                                            actor, int(time.time())))
                hook_id = cur.lastrowid
            elif not db.execute("UPDATE webhooks SET name=?, url=?, events=?, active=? WHERE id=? AND company=?",
                                (name, url, json.dumps(events), active, hook_id, company)).rowcount:
                raise LookupError("Unknown webhook")
        return self.get_webhook(company, hook_id)

    def rotate_webhook_secret(self, company: str, hook_id: int) -> dict:
        with self.main.connect() as db:
            if not db.execute("UPDATE webhooks SET secret=? WHERE id=? AND company=?",
                              ("whsec_" + secrets.token_urlsafe(24), hook_id, company)).rowcount:
                raise LookupError("Unknown webhook")
        return self.get_webhook(company, hook_id)

    def delete_webhook(self, company: str, hook_id: int) -> None:
        with self.main.connect() as db:
            if not db.execute("DELETE FROM webhooks WHERE id=? AND company=?", (hook_id, company)).rowcount:
                raise LookupError("Unknown webhook")

    def record_delivery(self, hook_id: int, status: int | None, error: str | None) -> None:
        with self.main.connect() as db:
            db.execute("UPDATE webhooks SET last_delivery_at=?, last_status=?, last_error=?, deliveries=deliveries+1, "
                       "failures=failures+? WHERE id=?",
                       (int(time.time()), status, (error or "")[:300] or None, 0 if error is None else 1, hook_id))
