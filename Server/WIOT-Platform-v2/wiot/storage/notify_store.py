"""Notification channels, their delivery log and custom alert rules (R2.3, point 22). Main database.

Channel secrets (bot tokens, API keys, passwords) are sealed with the server key; the API never returns them,
only whether they are set.
"""
from __future__ import annotations

import json
import time

from ..protocol.validation import company_id
from ..security import seal, unseal
from .telemetry_store import SERIES_METRICS

CHANNEL_KINDS = ("email", "telegram", "sms", "whatsapp", "teams")
PROVIDERS = {"sms": ("twilio", "generic"), "whatsapp": ("twilio", "meta", "generic")}
SECRET_FIELDS = ("bot_token", "auth_token", "token", "headers", "webhook_url")
SEVERITY_ORDER = {"info": 0, "warning": 1, "critical": 2}
RULE_OPS = ("<", "<=", ">", ">=")
RULE_METRICS = {**{k: k for k in SERIES_METRICS}, "silent_minutes": "minutes since the last uplink"}
RULE_SEVERITIES = ("warning", "critical")


def _now() -> int:
    return int(time.time())


class NotifyStore:
    def __init__(self, main, secret_key: str):
        self.main = main
        self.secret_key = secret_key

    def init_schema(self) -> None:
        with self.main.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS notify_channels (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, company TEXT NOT NULL, name TEXT NOT NULL,
                    kind TEXT NOT NULL, config TEXT NOT NULL DEFAULT '{}', secrets TEXT,
                    min_severity TEXT NOT NULL DEFAULT 'warning', events TEXT NOT NULL DEFAULT '["alert"]',
                    enabled INTEGER NOT NULL DEFAULT 1, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
                    last_ok INTEGER, last_at INTEGER, last_error TEXT);
                CREATE TABLE IF NOT EXISTS notify_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, channel_id INTEGER NOT NULL, ts INTEGER NOT NULL,
                    event TEXT NOT NULL, ok INTEGER NOT NULL, detail TEXT);
                CREATE INDEX IF NOT EXISTS notify_log_by_channel ON notify_log(channel_id, id DESC);
                CREATE TABLE IF NOT EXISTS alert_rules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, company TEXT NOT NULL, name TEXT NOT NULL,
                    region TEXT, nodes TEXT, metric TEXT NOT NULL, op TEXT NOT NULL, value REAL NOT NULL,
                    duration_s INTEGER NOT NULL DEFAULT 0, severity TEXT NOT NULL DEFAULT 'warning',
                    enabled INTEGER NOT NULL DEFAULT 1, created_by TEXT, created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL);
            """)

    # ------------------------------------------------------------- channels
    def _public(self, row) -> dict:
        r = dict(row)
        secrets = self._secrets(r)
        r["config"] = json.loads(r["config"] or "{}")
        r["secrets_set"] = sorted(k for k, v in secrets.items() if v)
        r["events"] = json.loads(r["events"] or "[]")
        r["enabled"] = bool(r["enabled"])
        r.pop("secrets", None)
        return r

    def _secrets(self, row: dict) -> dict:
        if not row.get("secrets"):
            return {}
        try:
            return json.loads(unseal(self.secret_key, row["secrets"]))
        except (ValueError, json.JSONDecodeError):
            return {}

    @staticmethod
    def _validate(kind: str, config: dict, secrets: dict) -> None:
        if kind not in CHANNEL_KINDS:
            raise ValueError(f"Channel kind must be one of {', '.join(CHANNEL_KINDS)}")
        if kind == "email":
            to = config.get("to") or []
            if not to or any("@" not in t or " " in t for t in to) or len(to) > 20:
                raise ValueError("E-mail channel needs 1..20 addresses")
        elif kind == "telegram":
            if not str(config.get("chat_id") or "").lstrip("-").isdigit() and not str(config.get("chat_id", "")).startswith("@"):
                raise ValueError("Telegram channel needs a chat id (number) or @channel name")
        elif kind == "teams":
            pass
        else:
            provider = config.get("provider")
            if provider not in PROVIDERS[kind]:
                raise ValueError(f"{kind} provider must be one of {', '.join(PROVIDERS[kind])}")
            to = config.get("to") or []
            if not to or len(to) > 20 or any(not str(n).lstrip("+").isdigit() for n in to):
                raise ValueError("Give 1..20 phone numbers in international format, e.g. +201001234567")
            if provider == "generic" and not str(config.get("url", "")).startswith("https://"):
                raise ValueError("Generic gateway URL must start with https://")

    def list_channels(self, company: str | None) -> list[dict]:
        q, params = "SELECT * FROM notify_channels", ()
        if company is not None:
            q, params = q + " WHERE company=?", (company,)
        with self.main.connect() as db:
            return [self._public(r) for r in db.execute(q + " ORDER BY id", params)]

    def get_channel(self, channel_id: int, *, with_secrets: bool = False) -> dict | None:
        with self.main.connect() as db:
            row = db.execute("SELECT * FROM notify_channels WHERE id=?", (channel_id,)).fetchone()
        if row is None:
            return None
        out = self._public(row)
        if with_secrets:
            out["secret_values"] = self._secrets(dict(row))
        return out

    def save_channel(self, company: str, data: dict, channel_id: int | None = None) -> dict:
        company_id(company)
        current = self.get_channel(channel_id, with_secrets=True) if channel_id else None
        if channel_id and (current is None or current["company"] != company):
            raise LookupError("Channel not found")
        kind = data.get("kind", current["kind"] if current else None)
        config = {**(current["config"] if current else {}), **(data.get("config") or {})}
        secrets = {**(current["secret_values"] if current else {}),
                   **{k: v for k, v in (data.get("secrets") or {}).items() if v not in (None, "")}}
        self._validate(kind, config, secrets)
        name = (data.get("name") or (current or {}).get("name") or kind).strip()[:80]
        sev = data.get("min_severity", (current or {}).get("min_severity", "warning"))
        if sev not in SEVERITY_ORDER:
            raise ValueError("Minimum severity must be info, warning or critical")
        events = data.get("events", (current or {}).get("events", ["alert"]))
        if not set(events) <= {"alert", "resolved", "report", "daily_digest"}:
            raise ValueError("Events must be among alert, resolved, report, daily_digest")
        enabled = int(bool(data.get("enabled", (current or {}).get("enabled", True))))
        sealed = seal(self.secret_key, json.dumps(secrets)) if secrets else None
        now = _now()
        with self.main.connect() as db:
            if channel_id:
                db.execute("UPDATE notify_channels SET name=?, kind=?, config=?, secrets=?, min_severity=?, events=?, "
                           "enabled=?, updated_at=? WHERE id=?",
                           (name, kind, json.dumps(config), sealed, sev, json.dumps(events), enabled, now, channel_id))
            else:
                channel_id = db.execute(
                    "INSERT INTO notify_channels(company, name, kind, config, secrets, min_severity, events, enabled, "
                    "created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (company, name, kind, json.dumps(config), sealed, sev, json.dumps(events), enabled, now, now)).lastrowid
        return self.get_channel(channel_id)

    def delete_channel(self, company: str, channel_id: int) -> None:
        with self.main.connect() as db:
            if not db.execute("DELETE FROM notify_channels WHERE id=? AND company=?", (channel_id, company)).rowcount:
                raise LookupError("Channel not found")
            db.execute("DELETE FROM notify_log WHERE channel_id=?", (channel_id,))

    def active_channels(self, company: str) -> list[dict]:
        with self.main.connect() as db:
            rows = db.execute("SELECT * FROM notify_channels WHERE company=? AND enabled=1", (company,)).fetchall()
        out = []
        for row in rows:
            ch = self._public(row)
            ch["secret_values"] = self._secrets(dict(row))
            out.append(ch)
        return out

    def log(self, channel_id: int, event: str, ok: bool, detail: str) -> None:
        now = _now()
        with self.main.connect() as db:
            db.execute("INSERT INTO notify_log(channel_id, ts, event, ok, detail) VALUES(?,?,?,?,?)",
                       (channel_id, now, event, int(ok), detail[:500]))
            db.execute("UPDATE notify_channels SET last_ok=?, last_at=?, last_error=? WHERE id=?",
                       (int(ok), now, None if ok else detail[:300], channel_id))
            db.execute("DELETE FROM notify_log WHERE channel_id=? AND id NOT IN (SELECT id FROM notify_log "
                       "WHERE channel_id=? ORDER BY id DESC LIMIT 200)", (channel_id, channel_id))

    def channel_log(self, channel_id: int, limit: int = 50) -> list[dict]:
        with self.main.connect() as db:
            return [dict(r) for r in db.execute("SELECT ts, event, ok, detail FROM notify_log WHERE channel_id=? "
                                                "ORDER BY id DESC LIMIT ?", (channel_id, limit))]

    # ---------------------------------------------------------------- rules
    @staticmethod
    def _rule_public(row) -> dict:
        r = dict(row)
        r["nodes"] = json.loads(r["nodes"]) if r.get("nodes") else None
        r["enabled"] = bool(r["enabled"])
        return r

    def list_rules(self, company: str, enabled_only: bool = False) -> list[dict]:
        q = "SELECT * FROM alert_rules WHERE company=?" + (" AND enabled=1" if enabled_only else "")
        with self.main.connect() as db:
            return [self._rule_public(r) for r in db.execute(q + " ORDER BY id", (company,))]

    def get_rule(self, rule_id: int) -> dict | None:
        with self.main.connect() as db:
            row = db.execute("SELECT * FROM alert_rules WHERE id=?", (rule_id,)).fetchone()
        return self._rule_public(row) if row else None

    def save_rule(self, company: str, data: dict, actor: str, rule_id: int | None = None) -> dict:
        current = self.get_rule(rule_id) if rule_id else None
        if rule_id and (current is None or current["company"] != company):
            raise LookupError("Rule not found")
        merged = {**(current or {}), **{k: v for k, v in data.items() if v is not None or k == "nodes"}}
        name = str(merged.get("name") or "").strip()[:80]
        if not name:
            raise ValueError("Rule name is required")
        if merged.get("metric") not in RULE_METRICS:
            raise ValueError("Unknown metric")
        if merged.get("op") not in RULE_OPS:
            raise ValueError("Operator must be <, <=, > or >=")
        try:
            value = float(merged.get("value"))
        except (TypeError, ValueError) as exc:
            raise ValueError("Threshold must be a number") from exc
        duration = int(merged.get("duration_s") or 0)
        if not 0 <= duration <= 7 * 86400:
            raise ValueError("Duration must be 0..7 days")
        severity = merged.get("severity", "warning")
        if severity not in RULE_SEVERITIES:
            raise ValueError("Severity must be warning or critical")
        nodes = merged.get("nodes")
        if nodes is not None:
            if not isinstance(nodes, list) or not all(isinstance(n, int) and 0 < n < 65536 for n in nodes):
                raise ValueError("Nodes must be a list of node ids, or empty for every node")
            nodes = sorted(set(nodes)) or None
        region = merged.get("region") or None
        enabled = int(bool(merged.get("enabled", True)))
        now = _now()
        values = (name, region, json.dumps(nodes) if nodes else None, merged["metric"], merged["op"], value, duration,
                  severity, enabled, now)
        with self.main.connect() as db:
            if rule_id:
                db.execute("UPDATE alert_rules SET name=?, region=?, nodes=?, metric=?, op=?, value=?, duration_s=?, "
                           "severity=?, enabled=?, updated_at=? WHERE id=?", (*values, rule_id))
            else:
                rule_id = db.execute("INSERT INTO alert_rules(name, region, nodes, metric, op, value, duration_s, "
                                     "severity, enabled, updated_at, company, created_by, created_at) "
                                     "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (*values, company, actor, now)).lastrowid
        return self.get_rule(rule_id)

    def delete_rule(self, company: str, rule_id: int) -> None:
        with self.main.connect() as db:
            if not db.execute("DELETE FROM alert_rules WHERE id=? AND company=?", (rule_id, company)).rowcount:
                raise LookupError("Rule not found")
