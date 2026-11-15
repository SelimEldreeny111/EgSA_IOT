"""Optional AI assistant (R2.6, point 31): answers fleet questions and writes a daily summary with Claude.

Off by default. To turn it on, install the extra (``pip install -e ".[assistant]"``, which adds the official
``anthropic`` SDK), set ``WIOT_ASSISTANT_ENABLED=true`` and provide a key (``WIOT_ASSISTANT_API_KEY``, or the
SDK's usual ``ANTHROPIC_API_KEY`` / ``ant auth login`` profile). Model: ``WIOT_ASSISTANT_MODEL`` (default
``claude-opus-5-5``), with server-side refusal fallbacks enabled.

Data-handling rules (approve them before enabling; they are also shown on the Assistant page):
* Questions and the data the assistant looks up leave the server and are processed by Anthropic under the
  organisation's API agreement. Nothing is sent unless a user asks a question or the daily summary runs.
* The assistant only has **read-only** tools, scoped to the asking user's company: fleet status, open alerts,
  node health, the farm overview and water use. It cannot send commands or change anything.
* Tool results carry no personal data: no user names, e-mail addresses, IP addresses or secrets.
* Every question is recorded in the audit trail and in the assistant log (question, answer, tools used).
* Rate limit: ``WIOT_ASSISTANT_MAX_PER_HOUR`` questions per user per hour.
"""
from __future__ import annotations

import json
import logging
import time
from collections import defaultdict, deque

log = logging.getLogger(__name__)
MAX_TOOL_ROUNDS = 8
MAX_TOOL_CHARS = 20000

SYSTEM = (
    "You are the operations assistant of the WIOT Control Center, a platform that monitors water-IoT nodes "
    "(soil moisture, salinity, flow meters, valves, batteries) on farms and water networks in Egypt and the region. "
    "Answer the user's question about their own company using the tools; look data up rather than guessing, and say "
    "plainly when the data does not answer the question. Be brief and practical: lead with the answer, then the "
    "few facts behind it, and name nodes as NODE-xxx and fields by name. Use metric units. You can only read data: "
    "if the user asks you to change something (send a command, open a valve, edit settings), explain where in the "
    "dashboard they can do it. Answer in the language of the question (Arabic or English)."
)

TOOLS = [
    {"name": "get_fleet_status", "description": "Latest state of every node in a region of the user's company: link state "
     "(online / late / offline), seconds since the last report, battery voltage, soil moisture, salinity (EC, uS/cm), flow "
     "(m3/h), valve state and power mode.",
     "input_schema": {"type": "object", "properties": {"region": {"type": "string", "description": "Region id, e.g. Region_1; empty for the default region"}}}},
    {"name": "get_open_alerts", "description": "Alerts that are open now (or in the last 7 days with include_resolved), with "
     "kind, severity, node, region, when they opened and their details.",
     "input_schema": {"type": "object", "properties": {"include_resolved": {"type": "boolean"}}}},
    {"name": "get_node_health", "description": "Health score (0-100) per node with battery trend, days until the battery "
     "reaches 3.3 V, resets, missed reports, clock and command success, and the findings in words.",
     "input_schema": {"type": "object", "properties": {"region": {"type": "string"}}}},
    {"name": "get_farm_overview", "description": "Fields of the farm with crop, soil-moisture status (dry / optimal / wet), "
     "irrigation advice, whether it is irrigating, today's water, and the weather forecast summary.",
     "input_schema": {"type": "object", "properties": {"region": {"type": "string"}}}},
    {"name": "get_water_use", "description": "Water applied per field (m3, from the flow meters) over the last N days.",
     "input_schema": {"type": "object", "properties": {"days": {"type": "integer", "minimum": 1, "maximum": 90}}}},
]

FLEET_KEYS = ("node_id", "name", "link_state", "last_seen_age_s", "battery_voltage", "soil_moisture", "soil_temperature",
              "electrical_conductivity", "flow", "node_status", "power_mode_name", "uplinks_24h")


class AssistantUnavailable(Exception):
    pass


class Assistant:
    def __init__(self, settings, runtime, client_factory=None):
        self.settings = settings
        self.rt = runtime
        self.client_factory = client_factory
        self._client = None
        self._recent: dict[int, deque] = defaultdict(deque)

    # ----------------------------------------------------------- availability
    def status(self) -> dict:
        s = self.settings
        sdk = True
        try:
            import anthropic  # noqa: F401
        except ImportError:
            sdk = self.client_factory is not None
        return {"enabled": bool(s.assistant_enabled), "sdk_installed": sdk, "model": s.assistant_model,
                "ready": bool(s.assistant_enabled) and sdk, "max_per_hour": s.assistant_max_per_hour}

    def _get_client(self):
        if not self.settings.assistant_enabled:
            raise AssistantUnavailable("The assistant is turned off on this server (WIOT_ASSISTANT_ENABLED)")
        if self._client is None:
            if self.client_factory is not None:
                self._client = self.client_factory()
            else:
                try:
                    import anthropic
                except ImportError as exc:
                    raise AssistantUnavailable("Install the assistant extra: pip install -e \".[assistant]\"") from exc
                key = self.settings.assistant_api_key
                self._client = anthropic.Anthropic(api_key=key.get_secret_value()) if key else anthropic.Anthropic()
        return self._client

    def init_schema(self) -> None:
        with self.rt.main.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS assistant_log (id INTEGER PRIMARY KEY AUTOINCREMENT, company TEXT NOT NULL, "
                       "kind TEXT NOT NULL, user_id INTEGER, question TEXT NOT NULL, answer TEXT, tools TEXT, "
                       "input_tokens INTEGER, output_tokens INTEGER, ts INTEGER NOT NULL)")

    # ------------------------------------------------------------------ tools
    def run_tool(self, company: str, name: str, args: dict) -> dict:
        from ..protocol.topics import region_id
        region = region_id(args.get("region") or "Region_1") if name != "get_open_alerts" else None
        if name == "get_fleet_status":
            nodes = self.rt.telemetry.fleet(company, region)
            return {"region": region, "nodes": [{k: n.get(k) for k in FLEET_KEYS} for n in nodes]}
        if name == "get_open_alerts":
            inc = bool(args.get("include_resolved"))
            items = self.rt.alert_store.list(company, status="all" if inc else "open",
                                             since=int(time.time()) - 7 * 86400 if inc else None)
            return {"alerts": [{"kind": a["kind"], "severity": a["severity"], "state": a["state"], "region": a["region"],
                                "node_id": a["node_id"], "opened_at": a["opened_at"], "resolved_at": a.get("resolved_at"),
                                "details": {k: v for k, v in (a.get("details") or {}).items() if k not in ("acknowledged_by",)}}
                               for a in items[:100]]}
        if name == "get_node_health":
            return {"region": region, "nodes": self.rt.node_health.fleet(company, region)}
        if name == "get_farm_overview":
            ov = self.rt.farm.overview(company, region)
            if not ov.get("configured"):
                return {"configured": False}
            keep = ("id", "name", "crop", "status", "advice", "moisture", "irrigating", "water_today_m3", "area_ha", "deficit_mm",
                    "runtime_min", "node_id", "stage")
            wx = ov.get("weather") or {}
            return {"site": ov["site"]["name"], "kpis": ov["kpis"], "fields": [{k: z.get(k) for k in keep} for z in ov["zones"]],
                    "weather": {"current": wx.get("current"), "rain_next_24h_mm": wx.get("rain_next_24h_mm"),
                                "days": [{k: d.get(k) for k in ("date", "tmax", "tmin", "rain_mm", "et0_mm", "label")}
                                         for d in (wx.get("daily") or [])[:4]]}}
        if name == "get_water_use":
            from datetime import timedelta
            days = max(1, min(90, int(args.get("days") or 7)))
            layout = self.rt.farm.store.get(company)
            if layout is None:
                return {"fields": []}
            today = self.rt.water._today(company)
            start = today - timedelta(days=days - 1)
            return {"from": start.isoformat(), "to": today.isoformat(), "fields": [
                {"field": z.name, "m3": round(self.rt.water._zone_volume(company, z, start, today + timedelta(days=1)), 1)}
                for z in layout.zones]}
        raise ValueError(f"Unknown tool {name}")

    # ------------------------------------------------------------------- loop
    def ask(self, company: str, question: str, user_id: int | None = None, kind: str = "question") -> dict:
        question = (question or "").strip()
        if not question or len(question) > 2000:
            raise ValueError("Ask a question of 1 to 2000 characters")
        client = self._get_client()                 # unavailable assistant: no question is counted
        if user_id is not None:
            recent = self._recent[user_id]
            while recent and time.time() - recent[0] > 3600:
                recent.popleft()
            if len(recent) >= self.settings.assistant_max_per_hour:
                raise PermissionError("Question limit reached for this hour")
            recent.append(time.time())
        messages = [{"role": "user", "content": f"Company: {company}\n\n{question}"}]
        used, tokens_in, tokens_out, answer = [], 0, 0, ""
        for _ in range(MAX_TOOL_ROUNDS):
            response = client.beta.messages.create(
                model=self.settings.assistant_model, max_tokens=16000, system=SYSTEM, tools=TOOLS, messages=messages,
                output_config={"effort": "medium"},
                betas=["server-side-fallback-2026-07-01"], fallbacks="default")
            usage = getattr(response, "usage", None)
            tokens_in += getattr(usage, "input_tokens", 0) or 0
            tokens_out += getattr(usage, "output_tokens", 0) or 0
            if response.stop_reason == "refusal":
                answer = "The assistant declined to answer this question."
                break
            messages.append({"role": "assistant", "content": response.content})
            calls = [b for b in response.content if b.type == "tool_use"]
            if response.stop_reason != "tool_use" or not calls:
                answer = "\n".join(b.text for b in response.content if b.type == "text").strip()
                if response.stop_reason == "max_tokens":
                    answer += "\n\n(The answer was cut short.)"
                break
            results = []
            for call in calls:
                used.append(call.name)
                try:
                    data = self.run_tool(company, call.name, dict(call.input or {}))
                    text = json.dumps(data, default=str, separators=(",", ":"))[:MAX_TOOL_CHARS]
                    results.append({"type": "tool_result", "tool_use_id": call.id, "content": text})
                except Exception as exc:
                    results.append({"type": "tool_result", "tool_use_id": call.id, "content": f"Error: {exc}", "is_error": True})
            messages.append({"role": "user", "content": results})
        else:
            answer = answer or "The assistant needed too many look-ups; ask a narrower question."
        with self.rt.main.connect() as db:
            db.execute("INSERT INTO assistant_log(company, kind, user_id, question, answer, tools, input_tokens, output_tokens, ts) "
                       "VALUES(?,?,?,?,?,?,?,?,?)", (company, kind, user_id, question[:2000], answer[:20000], json.dumps(used),
                                                     tokens_in, tokens_out, int(time.time())))
        return {"answer": answer, "tools": used, "input_tokens": tokens_in, "output_tokens": tokens_out}

    def daily_summary(self, company: str) -> dict:
        return self.ask(company, "Write today's operations summary for this company in at most 10 short lines: nodes that "
                                 "need a visit and why, open alerts that matter, fields that need water today, water use in the "
                                 "last 7 days, and anything unusual. Use the tools.", kind="daily_summary")

    def history(self, company: str, user_id: int | None = None, limit: int = 30) -> list[dict]:
        q, p = "SELECT id, kind, user_id, question, answer, tools, ts FROM assistant_log WHERE company=?", [company]
        if user_id is not None:
            q += " AND (user_id=? OR kind='daily_summary')"
            p.append(user_id)
        with self.rt.main.connect() as db:
            rows = [dict(r) for r in db.execute(q + " ORDER BY id DESC LIMIT ?", (*p, limit))]
        for r in rows:
            r["tools"] = json.loads(r["tools"] or "[]")
        return rows

    def run_daily(self) -> list[str]:
        if not (self.settings.assistant_enabled and self.settings.assistant_daily_summary):
            return []
        done = []
        today = time.strftime("%Y-%m-%d")
        for company in self.rt.main.company_names():
            with self.rt.main.connect() as db:
                last = db.execute("SELECT MAX(ts) FROM assistant_log WHERE company=? AND kind='daily_summary'", (company,)).fetchone()[0]
            if last and time.strftime("%Y-%m-%d", time.localtime(last)) == today:
                continue
            if self.rt.farm.store.get(company) is None and not self.rt.telemetry.fleet(company, "Region_1"):
                continue
            try:
                self.daily_summary(company)
                done.append(company)
            except Exception:
                log.exception("Daily summary failed for %s", company)
        return done
