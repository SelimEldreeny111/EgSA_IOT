"""Alert notifications and custom alert rules (R2.3, point 22).

**Channels** (per company, Rules & notifications page): e-mail (the server's SMTP account), Telegram (bot token +
chat id), SMS and WhatsApp (Twilio, Meta WhatsApp Cloud API, or any HTTPS gateway with a body template) and
Microsoft Teams (incoming-webhook URL). Each channel has a minimum severity and the events it wants: alert opened,
alert resolved, monthly report.

**Delivery**: the notifier listens to the realtime hub, queues a message per matching channel and sends it from
a worker thread with retries (0, 5, 30 s). At most ``BURST`` messages per channel in ``BURST_WINDOW_S``; the rest
are counted and summarised in the next message, so a fleet-wide outage cannot flood a phone. Every attempt is in
the channel's delivery log.

**Rules**: ``RuleEngine.check_node`` runs inside the alert monitor's minute sweep. A rule compares the latest
valid value of one metric with a threshold; when the condition holds for ``duration_s`` it opens an alert
``rule_<id>`` (same lifecycle, webhooks and notifications as built-in alerts) and resolves it when it clears.
"""
from __future__ import annotations

import base64
import json
import logging
import queue
import smtplib
import ssl
import threading
import time
import urllib.parse
import urllib.request
from collections import deque
from email.message import EmailMessage

from ..storage.notify_store import SEVERITY_ORDER
from ..storage.telemetry_store import SERIES_METRICS

log = logging.getLogger(__name__)

RETRIES = (0, 5, 30)
BURST = 20
BURST_WINDOW_S = 600
TITLES = {
    "node_offline": "Node silent", "low_battery": "Low battery", "flow_unstable": "Flow reading unstable",
    "leak_suspected": "Leak suspected", "no_flow": "No flow", "night_flow": "Night flow",
    "frost_risk": "Frost risk", "heat_stress": "Heat stress", "foreign_command": "Command not sent by this server",
    "possible_replay": "Possible replay", "salinity_risk": "Soil salinity above crop tolerance",
    "well_licence": "Well licence nearly used",
}
VALIDITY = {k: v[1] for k, v in SERIES_METRICS.items()}
FLAG_OF = {"COALESCE(flow_live_valid,0)=1": "flow_live_valid",
           "COALESCE(soil_moisture_temp_valid,0)=1": "soil_moisture_temp_valid",
           "COALESCE(soil_moisture_temp_ec_valid,0)=1": "soil_moisture_temp_ec_valid",
           "COALESCE(flow_period_totals_valid,0)=1": "flow_period_totals_valid"}


def http_request(method: str, url: str, headers: dict, body: bytes | None, timeout: float = 10.0) -> tuple[int, str]:
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:     # noqa: S310 - destinations are checked
            return resp.status, resp.read(2000).decode(errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(500).decode(errors="replace")


def node_tag(node_id) -> str:
    return "SITE" if int(node_id or 0) == 0 else f"NODE-{int(node_id):03d}"


def alert_text(company: str, data: dict) -> tuple[str, str]:
    """(subject, body) for an alert hub event."""
    kind = data.get("alert_kind") or data.get("kind", "")
    resolved = data.get("state") == "resolved" or str(data.get("kind", "")).endswith("_resolved")
    d = data.get("details") or {}
    title = (d.get("rule") if kind.startswith("rule_") else f"Water quota {d.get('quota', '')}".strip() if kind.startswith("quota_")
             else f"Calibration overdue: {d.get('asset', '')}".strip(": ") if kind.startswith("calibration_due_")
             else TITLES.get(kind, kind.replace("_", " ").capitalize()))
    where = f"{node_tag(data.get('node_id'))} · {company}/{data.get('region', '')}"
    sev = "Resolved" if resolved else str(data.get("severity", "")).capitalize()
    facts = []
    if kind.startswith("rule_"):
        facts.append(f"{d.get('metric')} {d.get('value')} {d.get('op')} {d.get('threshold')}")
    for key, label in (("battery_v", "battery {} V"), ("flow_m3h", "flow {} m³/h"), ("tmin_c", "minimum {} °C"),
                       ("tmax_c", "maximum {} °C"), ("date", "on {}"), ("cmd", "command {}")):
        if d.get(key) is not None:
            facts.append(label.format(d[key]))
    subject = f"[WIOT] {sev}: {title} — {node_tag(data.get('node_id'))}"
    body = f"{sev}: {title}\n{where}\n" + ("; ".join(facts) + "\n" if facts else "") + \
        time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
    return subject, body


class Notifier:
    def __init__(self, settings, store, *, allow_private: bool = False, http=http_request, smtp_factory=None):
        self.settings = settings
        self.store = store
        self.allow_private = allow_private
        self.http = http
        self.smtp_factory = smtp_factory
        self.queue: queue.Queue = queue.Queue(maxsize=2000)
        self._sent: dict[int, deque] = {}
        self._suppressed: dict[int, int] = {}
        self._worker: threading.Thread | None = None

    def start(self) -> None:
        self._worker = threading.Thread(target=self._run, name="notifier", daemon=True)
        self._worker.start()

    # ----------------------------------------------------------- dispatch
    def on_event(self, event: str, data: dict, company: str | None) -> None:
        if event != "alert" or not company:
            return
        resolved = data.get("state") == "resolved"
        try:
            channels = self.store.active_channels(company)
        except Exception:
            log.exception("Notification channels unavailable")
            return
        for ch in channels:
            if resolved and "resolved" not in ch["events"]:
                continue
            if not resolved and ("alert" not in ch["events"]
                                 or SEVERITY_ORDER.get(data.get("severity"), 0) < SEVERITY_ORDER[ch["min_severity"]]):
                continue
            subject, body = alert_text(company, data)
            self._enqueue(ch, "resolved" if resolved else "alert", subject, body)

    def send_report(self, company: str, subject: str, body: str, attachments: list[tuple[str, bytes, str]]) -> int:
        count = 0
        for ch in self.store.active_channels(company):
            if "report" in ch["events"]:
                self._enqueue(ch, "report", subject, body, attachments)
                count += 1
        return count

    def _enqueue(self, ch, event, subject, body, attachments=None) -> None:
        now = time.time()
        sent = self._sent.setdefault(ch["id"], deque())
        while sent and now - sent[0] > BURST_WINDOW_S:
            sent.popleft()
        if event != "report" and len(sent) >= BURST:
            self._suppressed[ch["id"]] = self._suppressed.get(ch["id"], 0) + 1
            return
        sent.append(now)
        extra = self._suppressed.pop(ch["id"], 0)
        if extra:
            body += f"\n(+{extra} more alert message(s) were held back to avoid flooding this channel)"
        try:
            self.queue.put_nowait((ch, event, subject, body, attachments or []))
        except queue.Full:
            log.warning("Notification queue full; message for channel %s dropped", ch["id"])

    def _run(self) -> None:
        while True:
            ch, event, subject, body, attachments = self.queue.get()
            self.deliver(ch, event, subject, body, attachments)

    def deliver(self, ch, event, subject, body, attachments=(), retries=RETRIES) -> tuple[bool, str]:
        ok, detail = False, ""
        for delay in retries:
            if delay:
                time.sleep(delay)
            try:
                detail = self.send(ch, subject, body, attachments)
                ok = True
                break
            except Exception as exc:                       # adapters raise on any failure
                detail = f"{type(exc).__name__}: {exc}"
        try:
            self.store.log(ch["id"], event, ok, detail)
        except Exception:
            log.exception("Notification log write failed")
        return ok, detail

    # ----------------------------------------------------------- adapters
    def send(self, ch: dict, subject: str, body: str, attachments=()) -> str:
        kind, cfg, sec = ch["kind"], ch["config"], ch.get("secret_values", {})
        if kind == "email":
            return self._email(cfg["to"], subject, body, attachments)
        if kind == "telegram":
            token = sec.get("bot_token")
            if not token:
                raise ValueError("Telegram bot token is not set")
            return self._post_json(f"https://api.telegram.org/bot{token}/sendMessage",
                                   {"chat_id": cfg["chat_id"], "text": f"{subject}\n\n{body}"}, {}, mask=token)
        if kind == "teams":
            url = sec.get("webhook_url")
            if not url:
                raise ValueError("Teams webhook URL is not set")
            return self._post_json(url, {"text": f"**{subject}**\n\n{body}".replace("\n", "  \n")}, {}, mask=url)
        text = f"{subject}\n{body}"[:1500]
        provider = cfg.get("provider")
        results = []
        for to in cfg["to"]:
            if provider == "twilio":
                sid, token = cfg.get("account_sid"), sec.get("auth_token")
                if not sid or not token or not cfg.get("from"):
                    raise ValueError("Twilio needs account SID, auth token and the sender number")
                prefix = "whatsapp:" if kind == "whatsapp" else ""
                form = urllib.parse.urlencode({"To": prefix + str(to), "From": prefix + cfg["from"], "Body": text}).encode()
                auth = base64.b64encode(f"{sid}:{token}".encode()).decode()
                status, resp = self.http("POST", f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
                                         {"Authorization": f"Basic {auth}",
                                          "Content-Type": "application/x-www-form-urlencoded"}, form)
            elif provider == "meta":
                token = sec.get("token")
                if not token or not cfg.get("phone_number_id"):
                    raise ValueError("WhatsApp Cloud API needs the phone number id and an access token")
                status, resp = self.http(
                    "POST", f"https://graph.facebook.com/v20.0/{cfg['phone_number_id']}/messages",
                    {"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                    json.dumps({"messaging_product": "whatsapp", "to": str(to).lstrip("+"), "type": "text",
                                "text": {"body": text}}).encode())
            else:
                from .webhooks import check_destination
                check_destination(cfg["url"], self.allow_private)
                headers = {"Content-Type": cfg.get("content_type", "application/json")}
                headers.update(json.loads(sec.get("headers") or "{}"))
                template = cfg.get("body_template") or '{"to": "{to}", "text": "{text}"}'
                safe = json.dumps(text)[1:-1] if "json" in headers["Content-Type"] else urllib.parse.quote_plus(text)
                payload = template.replace("{to}", str(to)).replace("{text}", safe).encode()
                status, resp = self.http("POST", cfg["url"], headers, payload)
            if not 200 <= status < 300:
                raise RuntimeError(f"HTTP {status}: {resp[:200]}")
            results.append(f"{to}: HTTP {status}")
        return "; ".join(results)

    def _post_json(self, url: str, payload: dict, headers: dict, mask: str = "") -> str:
        status, resp = self.http("POST", url, {"Content-Type": "application/json", **headers},
                                 json.dumps(payload).encode())
        if not 200 <= status < 300:
            raise RuntimeError(f"HTTP {status}: {resp[:200].replace(mask, '***') if mask else resp[:200]}")
        return f"HTTP {status}"

    def smtp_ready(self) -> bool:
        s = self.settings
        return bool(s.smtp_host and (s.smtp_from or s.smtp_username))

    def _email(self, to: list[str], subject: str, body: str, attachments=()) -> str:
        s = self.settings
        if not self.smtp_ready():
            raise ValueError("Outgoing e-mail is not configured (WIOT_SMTP_HOST, WIOT_SMTP_FROM)")
        msg = EmailMessage()
        msg["Subject"], msg["From"], msg["To"] = subject, s.smtp_from or s.smtp_username, ", ".join(to)
        msg.set_content(body)
        for name, data, mime in attachments:
            main, sub = mime.split("/", 1)
            msg.add_attachment(data, maintype=main, subtype=sub, filename=name)
        if self.smtp_factory:
            smtp = self.smtp_factory()
        elif s.smtp_security == "ssl":
            smtp = smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, timeout=15, context=ssl.create_default_context())
        else:
            smtp = smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=15)
        with smtp:
            if s.smtp_security == "starttls" and not self.smtp_factory:
                smtp.starttls(context=ssl.create_default_context())
            if s.smtp_username and s.smtp_password:
                smtp.login(s.smtp_username, s.smtp_password.get_secret_value())
            smtp.send_message(msg)
        return f"sent to {len(to)} recipient(s)"

    def send_email(self, to: list[str], subject: str, body: str) -> str:
        return self._email(to, subject, body)


class RuleEngine:
    """Evaluates a company's custom rules against the latest reading of each node."""

    def __init__(self, store):
        self.store = store
        self._since: dict[tuple, int] = {}
        self._rules: dict[str, tuple[float, list[dict]]] = {}

    def rules(self, company: str) -> list[dict]:
        hit = self._rules.get(company)
        if hit and time.time() - hit[0] < 60:
            return hit[1]
        rules = self.store.list_rules(company, enabled_only=True)
        self._rules[company] = (time.time(), rules)
        return rules

    def invalidate(self, company: str) -> None:
        self._rules.pop(company, None)

    @staticmethod
    def value(rule: dict, node: dict, now: int) -> float | None:
        metric = rule["metric"]
        if metric == "silent_minutes":
            ts = node.get("timestamp")
            return round((now - int(ts)) / 60, 1) if ts else None
        flag = FLAG_OF.get(VALIDITY.get(metric, ""))
        if flag and not node.get(flag):
            return None
        v = node.get(metric)
        if metric == "battery_voltage" and not v:
            return None
        return float(v) if v is not None else None

    @staticmethod
    def breached(op: str, value: float, threshold: float) -> bool:
        return {"<": value < threshold, "<=": value <= threshold, ">": value > threshold, ">=": value >= threshold}[op]

    def check_node(self, monitor, company: str, region: str, node: dict, now: int) -> list[dict]:
        fired = []
        for rule in self.rules(company):
            if rule["region"] and rule["region"] != region:
                continue
            if rule["nodes"] and node["node_id"] not in rule["nodes"]:
                continue
            kind = f"rule_{rule['id']}"
            key = (company, region, node["node_id"], rule["id"])
            value = self.value(rule, node, now)
            if value is not None and self.breached(rule["op"], value, rule["value"]):
                start = self._since.setdefault(key, now)
                if now - start >= rule["duration_s"]:
                    details = {"rule": rule["name"], "rule_id": rule["id"], "metric": rule["metric"], "op": rule["op"],
                               "threshold": rule["value"], "value": round(value, 3), "since": start,
                               "name": node.get("name")}
                    fired += monitor._open(company, region, node, kind, rule["severity"], details, now)
            else:
                self._since.pop(key, None)
                if value is not None:      # resolve only on a valid reading that is back inside the limit
                    fired += monitor._resolve(company, region, node, kind, now)
        return fired

    def preview(self, rule: dict, fleet: list[dict], now: int) -> list[dict]:
        out = []
        for node in fleet:
            if rule.get("nodes") and node["node_id"] not in rule["nodes"]:
                continue
            v = self.value(rule, node, now)
            out.append({"node_id": node["node_id"], "value": v,
                        "breached": v is not None and self.breached(rule["op"], v, float(rule["value"]))})
        return out
