"""Maintenance module (R2.6, point 26): assets, work orders, photos and calibration history.

* **Assets**: nodes (created automatically when a node is commissioned or a work order names it) and other
  equipment (pumps, valves, meters, probes, gateways, solar panels) with serial number and install date.
* **Work orders**: from an alert ("Create work order") or by hand; priority, assignee, due date, status
  (open -> assigned -> in progress -> done / cancelled), a timeline of notes and status changes, and photos
  (JPEG / PNG up to 2 MB each, stored under ``data/maintenance/``). Closing needs a closure note.
* **Records and calibrations**: commissioning certificates, inspections and calibrations per asset; a
  calibration stores the reference and measured values, the deviation and the next due date. Overdue
  calibrations open an alert through the alert monitor.
"""
from __future__ import annotations

import json
import secrets
import time
from datetime import date
from pathlib import Path

ASSET_KINDS = ("node", "pump", "valve", "flow_meter", "soil_probe", "ec_probe", "gateway", "solar", "other")
STATUSES = ("open", "assigned", "in_progress", "done", "cancelled")
PRIORITIES = ("low", "normal", "high", "urgent")
PHOTO_MAX = 2 * 1024 * 1024
PNG = bytes.fromhex("89504e470d0a1a0a")
JPEG = bytes.fromhex("ffd8ff")


def _now() -> int:
    return int(time.time())


class MaintenanceModule:
    def __init__(self, settings, main, audit=None):
        self.settings = settings
        self.main = main
        self.audit = audit

    @property
    def folder(self) -> Path:
        return Path(self.settings.data_dir) / "maintenance"

    def init_schema(self) -> None:
        with self.main.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS mnt_assets (id INTEGER PRIMARY KEY AUTOINCREMENT, company TEXT NOT NULL,
                    kind TEXT NOT NULL, name TEXT NOT NULL, region TEXT, node_id INTEGER, serial TEXT, model TEXT,
                    installed TEXT, notes TEXT, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL);
                CREATE UNIQUE INDEX IF NOT EXISTS mnt_assets_node ON mnt_assets(company, region, node_id) WHERE node_id IS NOT NULL;
                CREATE TABLE IF NOT EXISTS mnt_orders (id INTEGER PRIMARY KEY AUTOINCREMENT, company TEXT NOT NULL,
                    asset_id INTEGER, alert_id INTEGER, title TEXT NOT NULL, description TEXT, priority TEXT NOT NULL,
                    status TEXT NOT NULL, assignee TEXT, due TEXT, created_by TEXT NOT NULL, created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL, closed_at INTEGER, closure TEXT);
                CREATE INDEX IF NOT EXISTS mnt_orders_by_status ON mnt_orders(company, status);
                CREATE TABLE IF NOT EXISTS mnt_events (id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL,
                    ts INTEGER NOT NULL, actor TEXT NOT NULL, kind TEXT NOT NULL, text TEXT, photo TEXT);
                CREATE TABLE IF NOT EXISTS mnt_records (id INTEGER PRIMARY KEY AUTOINCREMENT, company TEXT NOT NULL,
                    asset_id INTEGER NOT NULL, kind TEXT NOT NULL, date TEXT NOT NULL, data TEXT NOT NULL,
                    next_due TEXT, created_by TEXT NOT NULL, created_at INTEGER NOT NULL);
                CREATE INDEX IF NOT EXISTS mnt_records_by_asset ON mnt_records(company, asset_id, date);
            """)

    # ---------------------------------------------------------------- assets
    def list_assets(self, company: str) -> list[dict]:
        with self.main.connect() as db:
            rows = [dict(r) for r in db.execute("SELECT * FROM mnt_assets WHERE company=? ORDER BY kind, name", (company,))]
            due = {r[0]: r[1] for r in db.execute("SELECT asset_id, MIN(next_due) FROM mnt_records WHERE company=? AND "
                                                  "next_due IS NOT NULL GROUP BY asset_id", (company,))}
            open_ = {r[0]: r[1] for r in db.execute("SELECT asset_id, COUNT(*) FROM mnt_orders WHERE company=? AND status NOT IN "
                                                    "('done','cancelled') GROUP BY asset_id", (company,))}
        for r in rows:
            r["next_calibration"] = due.get(r["id"])
            r["open_orders"] = open_.get(r["id"], 0)
        return rows

    def get_asset(self, company: str, asset_id: int) -> dict:
        with self.main.connect() as db:
            r = db.execute("SELECT * FROM mnt_assets WHERE id=? AND company=?", (asset_id, company)).fetchone()
        if r is None:
            raise LookupError("Asset not found")
        return dict(r)

    def save_asset(self, company: str, data: dict, asset_id: int | None = None) -> dict:
        kind = data.get("kind") or "other"
        if kind not in ASSET_KINDS:
            raise ValueError("Unknown asset kind")
        name = str(data.get("name") or "").strip()[:80]
        if not name:
            raise ValueError("Asset name is required")
        node = data.get("node_id")
        node = int(node) if node not in (None, "") else None
        vals = (kind, name, data.get("region") or ("Region_1" if node else None), node, str(data.get("serial") or "")[:60] or None,
                str(data.get("model") or "")[:80] or None, data.get("installed") or None, str(data.get("notes") or "")[:500] or None)
        with self.main.connect() as db:
            if asset_id:
                if not db.execute("UPDATE mnt_assets SET kind=?, name=?, region=?, node_id=?, serial=?, model=?, installed=?, "
                                  "notes=?, updated_at=? WHERE id=? AND company=?", (*vals, _now(), asset_id, company)).rowcount:
                    raise LookupError("Asset not found")
            else:
                asset_id = db.execute("INSERT INTO mnt_assets(kind, name, region, node_id, serial, model, installed, notes, "
                                      "company, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                                      (*vals, company, _now(), _now())).lastrowid
        return self.get_asset(company, asset_id)

    def asset_for_node(self, company: str, region: str, node_id: int, actor: str) -> dict:
        with self.main.connect() as db:
            r = db.execute("SELECT * FROM mnt_assets WHERE company=? AND region=? AND node_id=?", (company, region, node_id)).fetchone()
        if r:
            return dict(r)
        return self.save_asset(company, {"kind": "node", "name": f"NODE-{node_id:03d}", "region": region, "node_id": node_id,
                                         "installed": date.today().isoformat(), "notes": f"Created by {actor}"})

    # --------------------------------------------------------------- records
    def add_record(self, company: str, asset_id: int, kind: str, data: dict, actor: str, day: str | None = None,
                   next_due: str | None = None) -> dict:
        self.get_asset(company, asset_id)
        if kind not in ("commissioning", "inspection", "calibration", "repair", "replacement"):
            raise ValueError("Unknown record kind")
        with self.main.connect() as db:
            rid = db.execute("INSERT INTO mnt_records(company, asset_id, kind, date, data, next_due, created_by, created_at) "
                             "VALUES(?,?,?,?,?,?,?,?)", (company, asset_id, kind, day or date.today().isoformat(),
                                                         json.dumps(data, default=str), next_due, actor, _now())).lastrowid
        return {"id": rid, "asset_id": asset_id, "kind": kind}

    def add_calibration(self, company: str, asset_id: int, data: dict, actor: str) -> dict:
        try:
            ref, meas = float(data["reference"]), float(data["measured"])
            tol = float(data.get("tolerance_pct") or 5)
            day = date.fromisoformat(str(data.get("date") or date.today().isoformat()))
            next_due = date.fromisoformat(str(data["next_due"])) if data.get("next_due") else None
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Calibration needs numeric reference and measured values and valid dates") from exc
        if ref == 0:
            raise ValueError("Reference value cannot be zero")
        dev = (meas - ref) / ref * 100
        rec = {"method": str(data.get("method") or "")[:120], "reference": ref, "measured": meas, "unit": str(data.get("unit") or "")[:20],
               "deviation_pct": round(dev, 2), "tolerance_pct": tol, "pass": abs(dev) <= tol, "notes": str(data.get("notes") or "")[:500]}
        out = self.add_record(company, asset_id, "calibration", rec, actor, day.isoformat(), next_due.isoformat() if next_due else None)
        return {**out, **rec}

    def records(self, company: str, asset_id: int | None = None) -> list[dict]:
        q, p = "SELECT r.*, a.name AS asset FROM mnt_records r JOIN mnt_assets a ON a.id=r.asset_id WHERE r.company=?", [company]
        if asset_id:
            q += " AND r.asset_id=?"
            p.append(asset_id)
        with self.main.connect() as db:
            rows = [dict(r) for r in db.execute(q + " ORDER BY r.date DESC, r.id DESC LIMIT 500", p)]
        for r in rows:
            r["data"] = json.loads(r["data"] or "{}")
        return rows

    # ------------------------------------------------------------- work orders
    def create_order(self, company: str, data: dict, actor: str) -> dict:
        title = str(data.get("title") or "").strip()[:120]
        if not title:
            raise ValueError("Title is required")
        prio = data.get("priority") or "normal"
        if prio not in PRIORITIES:
            raise ValueError("Unknown priority")
        asset_id = data.get("asset_id")
        if asset_id:
            self.get_asset(company, int(asset_id))
        if data.get("due"):
            date.fromisoformat(str(data["due"]))
        status = "assigned" if data.get("assignee") else "open"
        with self.main.connect() as db:
            oid = db.execute("INSERT INTO mnt_orders(company, asset_id, alert_id, title, description, priority, status, assignee, "
                             "due, created_by, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                             (company, asset_id, data.get("alert_id"), title, str(data.get("description") or "")[:2000], prio,
                              status, (data.get("assignee") or None), data.get("due") or None, actor, _now(), _now())).lastrowid
            db.execute("INSERT INTO mnt_events(order_id, ts, actor, kind, text) VALUES(?,?,?,?,?)",
                       (oid, _now(), actor, "created", title))
        return self.get_order(company, oid)

    def get_order(self, company: str, order_id: int) -> dict:
        with self.main.connect() as db:
            r = db.execute("SELECT o.*, a.name AS asset FROM mnt_orders o LEFT JOIN mnt_assets a ON a.id=o.asset_id "
                           "WHERE o.id=? AND o.company=?", (order_id, company)).fetchone()
            if r is None:
                raise LookupError("Work order not found")
            events = [dict(e) for e in db.execute("SELECT ts, actor, kind, text, photo FROM mnt_events WHERE order_id=? "
                                                  "ORDER BY id", (order_id,))]
        return {**dict(r), "events": events}

    def list_orders(self, company: str, status: str | None = None) -> list[dict]:
        q, p = ("SELECT o.*, a.name AS asset FROM mnt_orders o LEFT JOIN mnt_assets a ON a.id=o.asset_id WHERE o.company=?", [company])
        if status == "active":
            q += " AND o.status NOT IN ('done','cancelled')"
        elif status:
            q += " AND o.status=?"
            p.append(status)
        with self.main.connect() as db:
            return [dict(r) for r in db.execute(q + " ORDER BY CASE o.priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 WHEN "
                                                "'normal' THEN 2 ELSE 3 END, o.id DESC LIMIT 500", p)]

    def update_order(self, company: str, order_id: int, data: dict, actor: str) -> dict:
        cur = self.get_order(company, order_id)
        fields, events = {}, []
        if data.get("status") and data["status"] != cur["status"]:
            if data["status"] not in STATUSES:
                raise ValueError("Unknown status")
            if data["status"] == "done" and not (data.get("closure") or "").strip():
                raise ValueError("Write what was done before closing the work order")
            fields["status"] = data["status"]
            if data["status"] in ("done", "cancelled"):
                fields["closed_at"] = _now()
                fields["closure"] = str(data.get("closure") or "")[:2000]
            events.append(("status", f"{cur['status']} -> {data['status']}" + (f": {data['closure']}" if data.get("closure") else "")))
        for k in ("assignee", "due", "priority"):
            if k in data and data[k] != cur[k]:
                if k == "priority" and data[k] not in PRIORITIES:
                    raise ValueError("Unknown priority")
                fields[k] = data[k] or None
                events.append((k, f"{k}: {data[k] or '-'}"))
        if data.get("note"):
            events.append(("note", str(data["note"])[:2000]))
        if fields:
            fields["updated_at"] = _now()
            with self.main.connect() as db:
                db.execute(f"UPDATE mnt_orders SET {', '.join(f'{k}=?' for k in fields)} WHERE id=?", (*fields.values(), order_id))
        with self.main.connect() as db:
            for kind, text in events:
                db.execute("INSERT INTO mnt_events(order_id, ts, actor, kind, text) VALUES(?,?,?,?,?)", (order_id, _now(), actor, kind, text))
        return self.get_order(company, order_id)

    def add_photo(self, company: str, order_id: int, data: bytes, actor: str, caption: str = "") -> dict:
        self.get_order(company, order_id)
        if len(data) > PHOTO_MAX:
            raise ValueError("Photos must be 2 MB or smaller")
        ext = ".png" if data.startswith(PNG) else ".jpg" if data.startswith(JPEG) else None
        if ext is None:
            raise ValueError("Photos must be JPEG or PNG")
        folder = self.folder / company
        folder.mkdir(parents=True, exist_ok=True)
        name = f"wo{order_id}_{secrets.token_hex(6)}{ext}"
        (folder / name).write_bytes(data)
        with self.main.connect() as db:
            db.execute("INSERT INTO mnt_events(order_id, ts, actor, kind, text, photo) VALUES(?,?,?,?,?,?)",
                       (order_id, _now(), actor, "photo", caption[:200], name))
        return {"photo": name}

    def photo_path(self, company: str, name: str) -> Path:
        if "/" in name or "\\" in name or ".." in name:
            raise LookupError("Photo not found")
        path = self.folder / company / name
        if not path.is_file():
            raise LookupError("Photo not found")
        return path

    # ---------------------------------------------------------- alert hook
    def check_alerts(self, monitor, company: str, now: int) -> list[dict]:
        fired = []
        today = date.today().isoformat()
        with self.main.connect() as db:
            overdue_cal = db.execute("SELECT a.id, a.name, a.region, a.node_id, MIN(r.next_due) FROM mnt_records r JOIN mnt_assets a "
                                     "ON a.id=r.asset_id WHERE r.company=? AND r.next_due IS NOT NULL AND r.id=(SELECT MAX(id) FROM "
                                     "mnt_records x WHERE x.asset_id=r.asset_id AND x.kind='calibration') GROUP BY a.id",
                                     (company,)).fetchall()
        for aid, name, region, node_id, due in overdue_cal:
            node = {"node_id": node_id or 0, "name": name}
            kind = f"calibration_due_{aid}"
            if due and due < today:
                fired += monitor._open(company, region or "Region_1", node, kind, "warning",
                                       {"asset": name, "due": due}, now)
            else:
                fired += monitor._resolve(company, region or "Region_1", node, kind, now)
        return fired
