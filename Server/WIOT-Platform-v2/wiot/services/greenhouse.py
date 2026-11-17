"""Greenhouse layout (Track G, point 58): houses, zones and benches on the map.

A company has one layout: a list of *houses* (glasshouse, plastic house, net house, tunnel...),
each split into *zones* that hold *benches* (or rows/gutters). Every level is a polygon in
WGS84 and can carry *attachments*: registered third-party devices (point 53) or WIOT nodes,
so readings can be shown and later evaluated per house, zone or bench.

This is deliberately separate from the Smart-farm layout (``FarmLayout``): its zones are
irrigated fields used by irrigation advice, water accounts and reports; greenhouse zones are
not, and must not leak into those calculations.

Saving is optimistic: the client sends the version it loaded; a stale version is refused
(HTTP 409) instead of silently overwriting someone else's edits.
"""
from __future__ import annotations

import json
import math
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from ..domain.ext_metrics import DEVICE_ID_RE, METRICS
from ..protocol.validation import company_id

ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,23}$"
HOUSE_KINDS = ("glass", "poly", "net", "tunnel", "shade", "other")
MAX_HOUSES, MAX_ZONES, MAX_BENCHES_PER_ZONE, MAX_BENCHES = 200, 50, 1000, 5000
MAX_POINTS = 200
MAX_LAYOUT_POINTS = 50000          # corners in the whole layout (bounds the cost of the containment checks)
FRESH_S = 3 * 3600                 # readings older than this are not shown on the layout
EDGE_TOLERANCE_M = 0.5             # a vertex this close outside its parent still counts as inside


class VersionConflict(Exception):
    def __init__(self, current: int):
        super().__init__("The layout was changed by someone else; reload it and apply your edits again")
        self.current = current


def _polygon(v: list) -> list[tuple[float, float]]:
    if not isinstance(v, list) or not 3 <= len(v) <= MAX_POINTS:
        raise ValueError(f"A shape needs 3..{MAX_POINTS} corner points")
    out = []
    for p in v:
        try:
            if not isinstance(p, (list, tuple)):
                raise TypeError
            lat, lon = float(p[0]), float(p[1])
        except (TypeError, ValueError, IndexError, KeyError, OverflowError) as exc:
            raise ValueError("Each corner is [latitude, longitude]") from exc
        if not (-90 <= lat <= 90 and -180 <= lon <= 180) or not (math.isfinite(lat) and math.isfinite(lon)):
            raise ValueError("Corner outside the valid latitude/longitude range")
        out.append((round(lat, 7), round(lon, 7)))
    if area_m2(out) < 0.05:
        raise ValueError("A shape must have an area (its corners are on one line)")
    return out


class Attachment(BaseModel):
    kind: Literal["device", "node"]
    device_id: str | None = None
    region: str | None = Field(None, pattern=r"^[A-Za-z0-9_-]{1,40}$")
    node_id: int | None = Field(None, ge=1, le=65535)

    @model_validator(mode="after")
    def _target(self) -> "Attachment":
        if self.kind == "device":
            if not self.device_id or not DEVICE_ID_RE.fullmatch(self.device_id):
                raise ValueError("A device attachment needs a valid device_id")
            self.region = self.node_id = None
        else:
            if not self.region or self.node_id is None:
                raise ValueError("A node attachment needs region and node_id")
            self.device_id = None
        return self

    def key(self) -> tuple:
        return ("device", self.device_id) if self.kind == "device" else ("node", self.region, self.node_id)


class _Shape(BaseModel):
    id: str = Field(pattern=ID_PATTERN)
    name: str = Field(min_length=1, max_length=80)
    polygon: list[tuple[float, float]]
    attach: list[Attachment] = Field(default_factory=list, max_length=20)

    @field_validator("polygon", mode="before")
    @classmethod
    def _poly(cls, v):
        return _polygon(v)

    @model_validator(mode="after")
    def _unique_attach(self):
        keys = [a.key() for a in self.attach]
        if len(keys) != len(set(keys)):
            raise ValueError(f"{self.id}: the same sensor is attached twice")
        return self


class Bench(_Shape):
    name: str = Field(min_length=1, max_length=60)
    attach: list[Attachment] = Field(default_factory=list, max_length=10)


class GZone(_Shape):
    crop: str = Field("", max_length=40)
    benches: list[Bench] = Field(default_factory=list, max_length=MAX_BENCHES_PER_ZONE)


class House(_Shape):
    kind: Literal["glass", "poly", "net", "tunnel", "shade", "other"] = "poly"
    crop: str = Field("", max_length=40)
    notes: str = Field("", max_length=300)
    zones: list[GZone] = Field(default_factory=list, max_length=MAX_ZONES)


class GreenhouseLayout(BaseModel):
    houses: list[House] = Field(default_factory=list, max_length=MAX_HOUSES)

    @model_validator(mode="after")
    def _ids(self) -> "GreenhouseLayout":
        seen, benches, points = set(), 0, 0
        for item in self.walk():
            if item[1].id in seen:
                raise ValueError(f"ID {item[1].id} is used twice; house, zone and bench IDs must be unique")
            seen.add(item[1].id)
            benches += item[0] == "bench"
            points += len(item[1].polygon)
        if benches > MAX_BENCHES:
            raise ValueError(f"At most {MAX_BENCHES} benches per company")
        if points > MAX_LAYOUT_POINTS:
            raise ValueError(f"At most {MAX_LAYOUT_POINTS} corners per company")
        return self

    def walk(self):
        """(level, element, parent) for every house, zone and bench."""
        for h in self.houses:
            yield "house", h, None
            for z in h.zones:
                yield "zone", z, h
                for b in z.benches:
                    yield "bench", b, z


# --------------------------------------------------------------------- geometry
def _local(points, origin=None):
    lat0, lon0 = origin or (sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points))
    k = math.cos(math.radians(lat0))
    return [((p[1] - lon0) * 111320.0 * k, (p[0] - lat0) * 110540.0) for p in points], (lat0, lon0)


def area_m2(points) -> float:
    xy, _ = _local(points)
    return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(xy, xy[1:] + xy[:1]))) / 2


def _inside(pt, poly) -> bool:
    x, y, inside = pt[0], pt[1], False
    for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def _dist_to_edges(pt, poly) -> float:
    best = math.inf
    for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]):
        dx, dy = x2 - x1, y2 - y1
        t = 0.0 if dx == dy == 0 else max(0.0, min(1.0, ((pt[0] - x1) * dx + (pt[1] - y1) * dy) / (dx * dx + dy * dy)))
        best = min(best, math.hypot(pt[0] - (x1 + t * dx), pt[1] - (y1 + t * dy)))
    return best


def contained(child, parent, tolerance_m: float = EDGE_TOLERANCE_M) -> bool:
    pxy, origin = _local(parent)
    cxy, _ = _local(child, origin)
    return all(_inside(p, pxy) or _dist_to_edges(p, pxy) <= tolerance_m for p in cxy)


def warnings(layout: GreenhouseLayout) -> list[str]:
    """Shapes that stick out of their parent (saved anyway; shown so they can be fixed)."""
    out = []
    for level, el, parent in layout.walk():
        if parent is not None and not contained(el.polygon, parent.polygon):
            out.append(f"{'Zone' if level == 'zone' else 'Bench'} {el.id} extends outside {parent.id}")
            if len(out) >= 50:
                break
    return out


def summary(layout: GreenhouseLayout) -> dict:
    houses = [{"id": h.id, "name": h.name, "kind": h.kind, "area_m2": round(area_m2(h.polygon), 1),
               "zones": len(h.zones), "benches": sum(len(z.benches) for z in h.zones),
               "bench_area_m2": round(sum(area_m2(b.polygon) for z in h.zones for b in z.benches), 1)}
              for h in layout.houses]
    return {"houses": len(houses), "zones": sum(h["zones"] for h in houses), "benches": sum(h["benches"] for h in houses),
            "area_m2": round(sum(h["area_m2"] for h in houses), 1), "per_house": houses,
            "attachments": sum(len(el.attach) for _, el, _ in layout.walk())}


# ------------------------------------------------------------------------ store
class GreenhouseStore:
    def __init__(self, main_db: Path):
        self.path = Path(main_db)
        self._parsed: dict[str, tuple[int, GreenhouseLayout]] = {}     # company -> (version, layout): parse once

    def init_schema(self) -> None:
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS greenhouse_layouts (
                company TEXT PRIMARY KEY, layout TEXT NOT NULL, version INTEGER NOT NULL,
                updated_at INTEGER NOT NULL, updated_by TEXT NOT NULL)""")
            cols = {r[1] for r in db.execute("PRAGMA table_info(greenhouse_layouts)")}
            if "warnings" not in cols:                 # computed once per save, not on every read
                db.execute("ALTER TABLE greenhouse_layouts ADD COLUMN warnings TEXT")
            db.commit()

    def get(self, company: str) -> dict:
        with closing(sqlite3.connect(self.path)) as db:
            row = db.execute("SELECT version, updated_at, updated_by, warnings FROM greenhouse_layouts WHERE company=?",
                             (company,)).fetchone()
            if row is None:
                return {"layout": GreenhouseLayout(), "version": 0, "updated_at": None, "updated_by": None, "warnings": []}
            hit = self._parsed.get(company)
            if hit is not None and hit[0] == row[0]:
                layout = hit[1]
            else:
                text = db.execute("SELECT layout FROM greenhouse_layouts WHERE company=?", (company,)).fetchone()[0]
                layout = GreenhouseLayout.model_validate_json(text)
                self._parsed[company] = (row[0], layout)
        stored = json.loads(row[3]) if row[3] else None
        return {"layout": layout, "version": row[0], "updated_at": row[1], "updated_by": row[2],
                "warnings": stored if stored is not None else warnings(layout)}

    def put(self, company: str, layout: GreenhouseLayout, version: int, actor: str) -> int:
        company_id(company)
        now = int(time.time())
        with closing(sqlite3.connect(self.path, timeout=10)) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT version FROM greenhouse_layouts WHERE company=?", (company,)).fetchone()
            current = row[0] if row else 0
            if int(version) != current:
                db.rollback()
                raise VersionConflict(current)
            text, warn = layout.model_dump_json(), json.dumps(warnings(layout))
            if row is None:
                db.execute("INSERT INTO greenhouse_layouts(company,layout,version,updated_at,updated_by,warnings) "
                           "VALUES(?,?,1,?,?,?)", (company, text, now, actor, warn))
            else:
                db.execute("UPDATE greenhouse_layouts SET layout=?, version=version+1, updated_at=?, updated_by=?, "
                           "warnings=? WHERE company=?", (text, now, actor, warn, company))
            db.commit()
            self._parsed[company] = (current + 1, layout)
            return current + 1


# ---------------------------------------------------------------------- service
# WIOT node fields shown on the layout (device health such as battery stays on the Fleet pages): the HNDA probe,
# else the Sondas probe (moisture, temperature and EC in µS/cm), each behind its own validity flag.
HNDA_FIELDS = (("soil_moisture", "soil_moisture_pct", 1.0), ("soil_temperature", "soil_temp_c", 1.0))
SONDAS_FIELDS = (("ec_moisture", "soil_moisture_pct", 1.0), ("ec_temperature", "soil_temp_c", 1.0),
                 ("electrical_conductivity", "soil_ec_ds_m", 0.001))


class GreenhouseService:
    def __init__(self, settings, store: GreenhouseStore, telemetry, devices, farm, org):
        self.settings, self.store, self.telemetry, self.devices, self.farm, self.org = (
            settings, store, telemetry, devices, farm, org)

    def init_schema(self) -> None:
        self.store.init_schema()

    def seed_demo(self, companies: list[str]) -> bool:
        """Two demo greenhouses on Demo_AgriFarm (once, when it has no layout)."""
        from ..sim.demo_greenhouses import DEMO_COMPANY, layout
        if DEMO_COMPANY not in companies or self.store.get(DEMO_COMPANY)["version"]:
            return False
        self.store.put(DEMO_COMPANY, GreenhouseLayout.model_validate(layout()), 0, "seed")
        return True

    def center(self, company: str, layout: GreenhouseLayout) -> dict:
        """Where the editor opens: the layout, else the farm site, else registered nodes, else the backdrop."""
        pts = [p for h in layout.houses for p in h.polygon]
        if pts:
            return {"bounds": [[min(p[0] for p in pts), min(p[1] for p in pts)],
                               [max(p[0] for p in pts), max(p[1] for p in pts)]]}
        farm = self.farm.store.get(company) if self.farm is not None else None
        if farm is not None:
            return {"center": list(farm.site.center), "zoom": max(farm.site.zoom, 16)}
        nodes = [n for n in self.org.list_nodes(company) if n.get("lat") is not None and n.get("lon") is not None]
        devs = [d for d in self.devices.store.list(company) if d.get("lat") is not None]
        located = [(n["lat"], n["lon"]) for n in nodes] + [(d["lat"], d["lon"]) for d in devs]
        if located:
            return {"center": [sum(p[0] for p in located) / len(located), sum(p[1] for p in located) / len(located)],
                    "zoom": 17}
        try:
            lat, lon, zoom = (float(v) for v in self.settings.map_backdrop.split(","))
        except (ValueError, AttributeError):
            lat, lon, zoom = 26.8, 30.8, 6
        return {"center": [lat, lon], "zoom": int(zoom)}

    def attachables(self, company: str) -> dict:
        devices = [{"device_id": d["device_id"], "name": d["name"], "protocol": d["protocol"], "model": d["model"],
                    "enabled": d["enabled"]} for d in self.devices.store.list(company)]
        nodes = {(n["region"], int(n["node_id"])): {"region": n["region"], "node_id": int(n["node_id"]),
                                                     "name": n.get("name") or ""} for n in self.org.list_nodes(company)}
        for region in self.telemetry.regions(company):
            for n in self.telemetry.fleet(company, region):
                nodes.setdefault((region, int(n["node_id"])), {"region": region, "node_id": int(n["node_id"]), "name": ""})
        return {"devices": devices, "nodes": sorted(nodes.values(), key=lambda n: (n["region"], n["node_id"]))}

    def _sources(self, company: str, now: int) -> dict[tuple, dict]:
        """Fresh values per attachable source: {("device", id) | ("node", region, n): {metric: (value, ts)}}."""
        out: dict[tuple, dict] = {}
        for device_id, live in self.devices.store.latest(company).items():
            vals = {m: (v["value"], v["ts"], bool(v["trusted"])) for m, v in live["values"].items()
                    if m in METRICS and METRICS[m][5] != "device" and now - v["ts"] <= FRESH_S}
            out[("device", device_id)] = vals
        for region in self.telemetry.regions(company):
            for n in self.telemetry.fleet(company, region):
                ts = n.get("measured_at") or n.get("timestamp") or 0
                if now - ts > FRESH_S:
                    continue
                vals = {}
                hnda = n.get("soil_moisture_temp_valid") and (n.get("soil_moisture") or 0) > 0
                sondas = n.get("soil_moisture_temp_ec_valid") and (n.get("ec_moisture") or 0) > 0
                for field, metric, scale in (HNDA_FIELDS if hnda else ()) + (SONDAS_FIELDS if sondas else ()):
                    v = n.get(field)
                    if metric in vals or not isinstance(v, (int, float)) or isinstance(v, bool):
                        continue
                    v = float(v) * scale
                    if METRICS[metric][2] <= v <= METRICS[metric][3]:
                        vals[metric] = (v, ts, True)          # node frames are AES-encrypted: trusted
                out[("node", region, int(n["node_id"]))] = vals
        return out

    def live(self, company: str, now: int | None = None) -> dict:
        """Mean of fresh readings per house, zone and bench, each over its whole subtree."""
        now = int(time.time() if now is None else now)
        layout = self.store.get(company)["layout"]
        sources = self._sources(company, now)

        def roll(attachments: list[Attachment]) -> dict:
            acc: dict[str, list] = {}
            seen = set()
            for a in attachments:
                if a.key() in seen:                   # attached at two levels of one subtree: count it once
                    continue
                seen.add(a.key())
                for metric, (v, ts, trusted) in (sources.get(a.key()) or {}).items():
                    acc.setdefault(metric, []).append((v, ts, trusted))
            return {m: {"value": round(sum(x[0] for x in xs) / len(xs), 3), "n": len(xs), "ts": max(x[1] for x in xs),
                        "untrusted": sum(1 for x in xs if not x[2])}
                    for m, xs in acc.items()}

        out = {}
        for h in layout.houses:
            h_all = list(h.attach)
            for z in h.zones:
                z_all = list(z.attach)
                for b in z.benches:
                    if b.attach:
                        out[b.id] = roll(b.attach)
                    z_all += b.attach
                out[z.id] = roll(z_all)
                h_all += z_all
            out[h.id] = roll(h_all)
        return {"at": now, "fresh_s": FRESH_S, "values": {k: v for k, v in out.items() if v}}

    def locations(self, company: str) -> dict[tuple, list[str]]:
        """Where each source is attached: {key: ["GH-1 Tomato house › A › B-3", ...]}."""
        layout = self.store.get(company)["layout"]
        out: dict[tuple, list[str]] = {}
        for h in layout.houses:
            for a in h.attach:
                out.setdefault(a.key(), []).append(h.name)
            for z in h.zones:
                for a in z.attach:
                    out.setdefault(a.key(), []).append(f"{h.name} › {z.name}")
                for b in z.benches:
                    for a in b.attach:
                        out.setdefault(a.key(), []).append(f"{h.name} › {z.name} › {b.name}")
        return out


def layout_json(layout: GreenhouseLayout) -> dict:
    return json.loads(layout.model_dump_json())
