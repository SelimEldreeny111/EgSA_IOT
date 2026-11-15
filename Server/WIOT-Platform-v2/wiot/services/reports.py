"""Monthly operations report per company (R2.3, point 23): Excel (.xlsx), PDF and JSON.

Contents, for one calendar month in the company's time zone:

* summary — nodes reporting, uplinks, water delivered (meter month totals), alerts and commands;
* one row per node — uplinks, days with data, battery (mean / minimum), water m³, soil moisture
  (mean / min / max), salinity (EC mean), flow (mean), alerts;
* water per day (meter day totals), alerts by kind, commands by outcome.

``python -m wiot`` builds last month's report for every company on the 1st (``WIOT_REPORTS_AUTO``) into
``data/reports/<company>/`` and e-mails it to channels subscribed to *report*.
"""
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from ..tools.pdf import Document
from ..tools.xlsx import Workbook
from .notify import TITLES, node_tag


def month_bounds(month: str, tz: str) -> tuple[int, int]:
    year, mon = (int(x) for x in month.split("-"))
    if not (2000 <= year <= 2100 and 1 <= mon <= 12):
        raise ValueError("Month must be YYYY-MM")
    zone = ZoneInfo(tz)
    start = datetime(year, mon, 1, tzinfo=zone)
    end = datetime(year + (mon == 12), mon % 12 + 1, 1, tzinfo=zone)
    return int(start.timestamp()), int(end.timestamp())


def previous_month(now: float | None = None, tz: str = "Africa/Cairo") -> str:
    local = datetime.fromtimestamp(time.time() if now is None else now, ZoneInfo(tz))
    first = local.replace(day=1)
    return (first - timedelta(days=1)).strftime("%Y-%m")


def _r(v, d=2):
    return None if v is None else round(float(v), d)


class ReportService:
    def __init__(self, settings, telemetry, org, alert_store, commands, branding=None):
        self.settings = settings
        self.telemetry = telemetry
        self.org = org
        self.alert_store = alert_store
        self.commands = commands
        self.branding = branding           # callable(company) -> {"name", "color"}

    # -------------------------------------------------------------- data
    def monthly(self, company: str, month: str) -> dict:
        tz = self.org.timezone(company) if self.org else self.settings.timezone
        start, end = month_bounds(month, tz)
        names = {(n["region"], int(n["node_id"])): n.get("name") for n in self.org.list_nodes(company)} if self.org else {}
        nodes: list[dict] = []
        daily: dict[str, float] = {}
        with self.telemetry.connect(company) as db:
            for r in db.execute(
                    "SELECT region, node_id, COUNT(*) AS uplinks, COUNT(DISTINCT (timestamp+?)/86400) AS days, "
                    "AVG(CASE WHEN battery_voltage>0 THEN battery_voltage END) AS batt_avg, "
                    "MIN(CASE WHEN battery_voltage>0 THEN battery_voltage END) AS batt_min, "
                    "AVG(CASE WHEN COALESCE(soil_moisture_temp_valid,0)=1 THEN soil_moisture END) AS sm_avg, "
                    "MIN(CASE WHEN COALESCE(soil_moisture_temp_valid,0)=1 THEN soil_moisture END) AS sm_min, "
                    "MAX(CASE WHEN COALESCE(soil_moisture_temp_valid,0)=1 THEN soil_moisture END) AS sm_max, "
                    "AVG(CASE WHEN COALESCE(soil_moisture_temp_ec_valid,0)=1 THEN electrical_conductivity END) AS ec_avg, "
                    "AVG(CASE WHEN COALESCE(flow_live_valid,0)=1 THEN flow END) AS flow_avg "
                    "FROM messages WHERE type IN ('Status','Telemetry') AND timestamp>=? AND timestamp<? "
                    "GROUP BY region, node_id ORDER BY region, node_id",
                    (self._utc_offset(tz, start), start, end)):
                nodes.append({"region": r["region"], "node_id": r["node_id"],
                              "name": names.get((r["region"], r["node_id"])) or "", "uplinks": r["uplinks"],
                              "days_with_data": r["days"], "battery_avg_v": _r(r["batt_avg"]),
                              "battery_min_v": _r(r["batt_min"]), "soil_moisture_avg": _r(r["sm_avg"], 1),
                              "soil_moisture_min": _r(r["sm_min"], 1), "soil_moisture_max": _r(r["sm_max"], 1),
                              "ec_avg": _r(r["ec_avg"]), "flow_avg_m3h": _r(r["flow_avg"]), "water_m3": None,
                              "alerts": 0})
            water = {(r[0], r[1]): r[2] / 1000.0 for r in db.execute(
                "SELECT region, node_id, SUM(volume_liters) FROM consumption_periods WHERE period_type='month' "
                "AND period_key=? GROUP BY region, node_id", (month,))} if self._has_region(db) else {
                ("Region_1", r[0]): r[1] / 1000.0 for r in db.execute(
                    "SELECT node_id, SUM(volume_liters) FROM consumption_periods WHERE period_type='month' "
                    "AND period_key=? GROUP BY node_id", (month,))}
            for r in db.execute("SELECT period_key, SUM(volume_liters) FROM consumption_periods WHERE "
                                "period_type='day' AND period_key LIKE ? GROUP BY period_key ORDER BY period_key",
                                (month + "-%",)):
                daily[r[0]] = round(r[1] / 1000.0, 3)
        for n in nodes:
            if (n["region"], n["node_id"]) in water:
                n["water_m3"] = round(water[(n["region"], n["node_id"])], 3)
        alerts_by_kind: dict[str, int] = {}
        with closing(sqlite3.connect(self.alert_store.path, timeout=5)) as adb:
            for region, node_id, kind, sev in adb.execute(
                    "SELECT region, node_id, kind, severity FROM alerts WHERE company=? AND opened_at>=? AND opened_at<?",
                    (company, start, end)):
                alerts_by_kind[kind] = alerts_by_kind.get(kind, 0) + 1
                for n in nodes:
                    if n["region"] == region and n["node_id"] == node_id:
                        n["alerts"] += 1
        commands: dict[str, int] = {}
        try:
            with closing(sqlite3.connect(self.commands.journal.path, timeout=5)) as cdb:
                for state, count in cdb.execute("SELECT state, COUNT(*) FROM pending_commands WHERE company=? "
                                                "AND created_at>=? AND created_at<? GROUP BY state", (company, start, end)):
                    commands[state] = count
        except sqlite3.Error:
            pass
        brand = self.branding(company) if self.branding else {}
        return {"company": company, "display_name": brand.get("name") or company, "month": month, "timezone": tz,
                "start": start, "end": end, "generated_at": int(time.time()),
                "summary": {"nodes_reporting": len(nodes), "uplinks": sum(n["uplinks"] for n in nodes),
                            "water_m3": round(sum(n["water_m3"] or 0 for n in nodes), 3),
                            "alerts": sum(alerts_by_kind.values()), "commands": sum(commands.values()),
                            "commands_acknowledged": commands.get("acknowledged", 0)},
                "nodes": nodes, "water_per_day": daily, "alerts_by_kind": alerts_by_kind, "commands": commands,
                "accent": brand.get("color") or "#1f5fad"}

    @staticmethod
    def _has_region(db) -> bool:
        return "region" in {r[1] for r in db.execute("PRAGMA table_info(consumption_periods)")}

    @staticmethod
    def _utc_offset(tz: str, at: int) -> int:
        off = datetime.fromtimestamp(at, ZoneInfo(tz)).utcoffset()
        return int(off.total_seconds()) if off else 0

    # ------------------------------------------------------------ output
    NODE_COLS = [("Region", "region"), ("Node", "node"), ("Name", "name"), ("Uplinks", "uplinks"),
                 ("Days with data", "days_with_data"), ("Battery mean (V)", "battery_avg_v"),
                 ("Battery min (V)", "battery_min_v"), ("Water (m³)", "water_m3"),
                 ("Soil moisture mean (%)", "soil_moisture_avg"), ("Soil moisture min (%)", "soil_moisture_min"),
                 ("Soil moisture max (%)", "soil_moisture_max"), ("EC mean (µS/cm)", "ec_avg"),
                 ("Flow mean (m³/h)", "flow_avg_m3h"), ("Alerts", "alerts")]

    def to_xlsx(self, rep: dict) -> bytes:
        wb = Workbook(f"WIOT monthly report {rep['company']} {rep['month']}")
        s = rep["summary"]
        sh = wb.sheet("Summary")
        sh.title(f"{rep['display_name']} — monthly report {rep['month']}").blank()
        sh.header(["Item", "Value"])
        for label, value in (("Company", rep["company"]), ("Month", rep["month"]), ("Time zone", rep["timezone"]),
                             ("Nodes reporting", s["nodes_reporting"]), ("Uplinks received", s["uplinks"]),
                             ("Water delivered (m³)", s["water_m3"]), ("Alerts opened", s["alerts"]),
                             ("Commands", s["commands"]), ("Commands acknowledged", s["commands_acknowledged"]),
                             ("Generated (UTC)", time.strftime("%Y-%m-%d %H:%M", time.gmtime(rep["generated_at"])))):
            sh.row([label, value])
        nodes = wb.sheet("Nodes").header([c for c, _ in self.NODE_COLS])
        for n in rep["nodes"]:
            nodes.row([node_tag(n["node_id"]) if k == "node" else n.get(k) for _, k in self.NODE_COLS])
        water = wb.sheet("Water per day").header(["Day", "Water (m³)"])
        for day, v in rep["water_per_day"].items():
            water.row([day, v])
        alerts = wb.sheet("Alerts").header(["Alert", "Count"])
        for kind, count in sorted(rep["alerts_by_kind"].items(), key=lambda kv: -kv[1]):
            alerts.row([TITLES.get(kind, kind), count])
        cmds = wb.sheet("Commands").header(["Outcome", "Count"])
        for state, count in sorted(rep["commands"].items()):
            cmds.row([state.replace("_", " "), count])
        return wb.to_bytes()

    def to_pdf(self, rep: dict) -> bytes:
        doc = Document(f"WIOT monthly report {rep['company']} {rep['month']}", accent=rep.get("accent") or "#1f5fad")
        doc.footer = f"{rep['display_name']} · {rep['month']} · generated by the WIOT Platform"
        s = rep["summary"]
        doc.heading(f"{rep['display_name']} — monthly report", 18)
        doc.paragraph(f"{datetime.strptime(rep['month'], '%Y-%m').strftime('%B %Y')} · time zone {rep['timezone']}")
        doc.kpis([("Nodes reporting", str(s["nodes_reporting"])), ("Uplinks", f"{s['uplinks']:,}"),
                  ("Water delivered", f"{s['water_m3']:,.1f} m³"), ("Alerts", str(s["alerts"])),
                  ("Commands acked", f"{s['commands_acknowledged']}/{s['commands']}")])
        doc.heading("Nodes", 12)
        cols = [("Node", "node", 1.0), ("Name", "name", 1.9), ("Uplinks", "uplinks", 0.8), ("Days", "days_with_data", 0.55),
                ("Batt. min V", "battery_min_v", 0.9), ("Water m³", "water_m3", 0.85),
                ("Soil %", "soil_moisture_avg", 0.7), ("EC µS/cm", "ec_avg", 0.8), ("Alerts", "alerts", 0.6)]
        fmt = {"uplinks": "{:,}", "battery_min_v": "{:.2f}", "water_m3": "{:,.1f}", "soil_moisture_avg": "{:.1f}",
               "ec_avg": "{:,.0f}"}

        def cell(n, k):
            if k == "node":
                return node_tag(n["node_id"])
            v = n.get(k)
            return "" if v is None else fmt[k].format(v) if k in fmt else v
        rows = [[cell(n, k) for _, k, _ in cols] for n in rep["nodes"]]
        doc.table([c for c, _, _ in cols], rows or [["No uplinks this month"] + [""] * (len(cols) - 1)],
                  [w for _, _, w in cols], ["l", "l"] + ["r"] * (len(cols) - 2))
        if rep["water_per_day"]:
            doc.heading("Water per day (m³)", 12)
            items = list(rep["water_per_day"].items())
            half = (len(items) + 1) // 2
            left, right = items[:half], items[half:]
            rows = [[a[0], f"{a[1]:,.2f}", *(b if b else ("", ""))] for a, b in zip(left, right + [None] * (len(left) - len(right)))]
            rows = [[r[0], r[1], r[2], f"{r[3]:,.2f}" if isinstance(r[3], float) else r[3]] for r in rows]
            doc.table(["Day", "m³", "Day", "m³"], rows, [1.4, 1, 1.4, 1], ["l", "r", "l", "r"])
        if rep["alerts_by_kind"]:
            doc.heading("Alerts by kind", 12)
            doc.table(["Alert", "Count"], [[TITLES.get(k, k), v] for k, v in
                                           sorted(rep["alerts_by_kind"].items(), key=lambda kv: -kv[1])], [4, 1])
        doc.paragraph("Water is the sum of the flow meters' month totals as reported by the nodes. Soil moisture and "
                      "salinity are means of valid readings only. Alerts count the alerts opened during the month.")
        return doc.to_bytes()

    # --------------------------------------------------------- automation
    def folder(self, company: str) -> Path:
        return Path(self.settings.data_dir) / "reports" / company

    def build_files(self, company: str, month: str) -> dict:
        rep = self.monthly(company, month)
        folder = self.folder(company)
        folder.mkdir(parents=True, exist_ok=True)
        xlsx, pdf = self.to_xlsx(rep), self.to_pdf(rep)
        (folder / f"WIOT_{company}_{month}.xlsx").write_bytes(xlsx)
        (folder / f"WIOT_{company}_{month}.pdf").write_bytes(pdf)
        (folder / f"WIOT_{company}_{month}.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
        return {"report": rep, "xlsx": xlsx, "pdf": pdf}

    def auto_monthly(self, companies: list[str], notifier=None, now: float | None = None) -> list[str]:
        """On or after the 1st: build last month's report once per company and send it to report channels."""
        built = []
        for company in companies:
            tz = self.org.timezone(company) if self.org else self.settings.timezone
            month = previous_month(now, tz)
            if (self.folder(company) / f"WIOT_{company}_{month}.pdf").exists():
                continue
            out = self.build_files(company, month)
            built.append(f"{company}/{month}")
            if notifier is not None:
                s = out["report"]["summary"]
                body = (f"Monthly report for {out['report']['display_name']}, {month}.\n"
                        f"Nodes reporting: {s['nodes_reporting']} · uplinks: {s['uplinks']} · water: {s['water_m3']} m³ · "
                        f"alerts: {s['alerts']}.\nThe Excel and PDF files are attached.")
                notifier.send_report(company, f"[WIOT] Monthly report {month} — {out['report']['display_name']}", body, [
                    (f"WIOT_{company}_{month}.pdf", out["pdf"], "application/pdf"),
                    (f"WIOT_{company}_{month}.xlsx", out["xlsx"],
                     "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")])
        return built

    def list_files(self, company: str) -> list[dict]:
        folder = self.folder(company)
        if not folder.exists():
            return []
        months = sorted({p.stem.rsplit("_", 1)[-1] for p in folder.glob("WIOT_*.pdf")}, reverse=True)
        return [{"month": m, "generated_at": int((folder / f"WIOT_{company}_{m}.pdf").stat().st_mtime)} for m in months]
