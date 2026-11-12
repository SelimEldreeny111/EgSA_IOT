"""Operator command intents: validation, durable journal, publish and receipts.

Semantics are those of v1.31: the journal (``command_lifecycle.db``) is the
authority; PUBACK proves broker receipt only; a node Telemetry ACK proves
execution. ``next_wake`` intents are released one per Status uplink.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

from ..domain.command_queue import CommandConflict, CommandQueue, ack_timeout_for
from ..domain.flash_archive import FLASH_COMMANDS, TRANSFER_IDLE_S
from ..protocol import messages_pb2
from ..protocol.power import WAKE_COMMAND_ID, validate_wake_seconds
from ..protocol.topics import DEFAULT_REGION, command_topic, region_id
from ..protocol.validation import company_id, integer
from .broker import BrokerManager
from .metrics import COMMANDS_SUBMITTED
from .realtime import LogBuffer, RealtimeHub

log = logging.getLogger(__name__)

CMD_IDS: dict[str, int] = {"SRATE": 1, "STRAN": 2, "STIME": 3, "GOSTM": 4, "VALVE": 5,
                           "WAKE": WAKE_COMMAND_ID, "CLEAR_POWER_RESETS": 7, "CLEAR_WDT_RESETS": 8}
CMD_IDS.update(FLASH_COMMANDS)
CMD_NAMES = {v: k for k, v in CMD_IDS.items()}

CATALOG = [
    {"type": "SRATE", "label": "Sampling interval", "data": "seconds", "min": 10, "max": 86400,
     "default": 60, "group": "configuration", "help": "How often the node samples its sensors."},
    {"type": "STRAN", "label": "Report interval", "data": "seconds", "min": 10, "max": 86400,
     "default": 60, "group": "configuration", "help": "How often the node uplinks a Status message."},
    {"type": "STIME", "label": "Sync node clock", "data": "auto", "group": "configuration",
     "help": "Sends the server epoch at the moment of dispatch."},
    {"type": "GOSTM", "label": "Request status now", "data": "none", "group": "diagnostics",
     "help": "Ask the node for an immediate Status uplink."},
    {"type": "VALVE", "label": "Valve", "data": "enum", "options": [[0, "Close"], [1, "Open"]],
     "default": 0, "group": "actuation", "help": "Latching valve command; never auto-retried."},
    {"type": "WAKE", "label": "Remote wake lease", "data": "seconds", "min": 0, "max": 86400,
     "default": 0, "group": "power", "help": "Keep a low-power node awake (0 = node default)."},
    {"type": "CLEAR_POWER_RESETS", "label": "Clear power-reset counter", "data": "none",
     "group": "diagnostics", "single_node": True},
    {"type": "CLEAR_WDT_RESETS", "label": "Clear watchdog counter", "data": "none",
     "group": "diagnostics", "single_node": True},
    {"type": "FLASH_STATUS", "label": "Flash log status", "data": "none", "group": "flash", "single_node": True},
    {"type": "FLASH_LAST", "label": "Download last sample", "data": "none", "group": "flash", "single_node": True},
    {"type": "FLASH_TODAY", "label": "Download today's history", "data": "cursor", "min": 0,
     "default": 0, "group": "flash", "single_node": True},
    {"type": "FLASH_CANCEL", "label": "Cancel history download", "data": "none", "group": "flash", "single_node": True},
    {"type": "CLEAR_FLASH", "label": "Erase flash log", "data": "none", "group": "flash",
     "single_node": True, "danger": True},
]
ACTUATION = {c["type"] for c in CATALOG if c.get("group") == "actuation"}  # need a control node


class CommandError(Exception):
    def __init__(self, message: str, status: int = 400, **extra):
        super().__init__(message)
        self.status = status
        self.extra = extra


@dataclass
class CommandRequest:
    company: str
    region: str
    node_id: int
    cmd_type: str
    cmd_data: object = None
    delivery: str = "now"
    broadcast: bool = False
    ttl_seconds: int = 86400


class CommandService:
    def __init__(self, journal_path, legacy_path, broker: BrokerManager, hub: RealtimeHub,
                 logs: LogBuffer, history_writer):
        self._journal_path = journal_path
        self._legacy_path = legacy_path
        self._journal: CommandQueue | None = None
        self.broker = broker
        self.hub = hub
        self.logs = logs
        self.history_writer = history_writer
        self.node_type = None  # (company, region, node) -> 'monitoring' | 'control' | None, set by the runtime
        self.flash_transfer = None  # (company, region, node, now) -> running history download | None
        self.power_mode = None  # (company, region, node) -> last reported power mode | None, set by the runtime
        self.risk = None  # (company, region, node, cmd_type) -> delivery-risk dict, set by the runtime
        self._lock = threading.RLock()

    @property
    def journal(self) -> CommandQueue:
        with self._lock:
            if self._journal is None:
                self._journal = CommandQueue(str(self._journal_path), legacy_path=str(self._legacy_path))
            return self._journal

    # ------------------------------------------------------------- validation
    @staticmethod
    def normalise(req: CommandRequest) -> tuple[int, int]:
        """Return (cmd_id, cmd_data) or raise CommandError."""
        company_id(req.company)
        region_id(req.region)
        if req.cmd_type not in CMD_IDS:
            raise CommandError("Unknown command type")
        if req.delivery not in ("now", "next_wake"):
            raise CommandError("delivery must be 'now' or 'next_wake'")
        if not isinstance(req.broadcast, bool):
            raise CommandError("broadcast must be true or false")
        integer(req.node_id, 1, 65535, "Node ID")
        if req.delivery == "next_wake" and req.broadcast:
            raise CommandError("Queued commands must target one node")
        ctype, value = req.cmd_type, req.cmd_data
        if ctype == "STIME":
            data = int(time.time())
        elif ctype == "GOSTM":
            data = 0
        elif ctype in FLASH_COMMANDS:
            if req.broadcast:
                raise CommandError("Flash commands must target one node")
            if ctype == "FLASH_TODAY":
                data = integer(value if value is not None else 0, 0, (1 << 63) - 1, "History resume cursor")
            else:
                data = integer(value if value is not None else 0, 0, 0, "Flash command data")
        elif ctype in ("CLEAR_POWER_RESETS", "CLEAR_WDT_RESETS"):
            if req.broadcast:
                raise CommandError("Counter clear must target one node")
            data = integer(value if value is not None else 0, 0, 0, "Counter clear data")
        elif ctype == "WAKE":
            data = validate_wake_seconds(0 if value is None else value)
        else:
            if isinstance(value, (bool, float)) or value is None:
                raise CommandError(f"Invalid command data: {value!r}")
            try:
                data = int(value)
            except (TypeError, ValueError) as exc:
                raise CommandError(f"Invalid command data: {value!r}") from exc
            if ctype in ("SRATE", "STRAN") and not 10 <= data <= 86400:
                # The node firmware accepts 10..86400 s (AppConfig); a shorter value would be rejected.
                raise CommandError("Interval must be 10..86400 seconds")
            if ctype == "VALVE" and data not in (0, 1):
                raise CommandError("Valve data must be 0 (close) or 1 (open)")
        integer(req.ttl_seconds, 60, 604800, "Command TTL")
        return CMD_IDS[ctype], data

    # --------------------------------------------------------------- dispatch
    def _ack_timeout(self, company: str, region: str, node_id: int) -> int:
        """Reply deadline from the node's last reported power mode (sleeping radios answer later)."""
        try:
            return ack_timeout_for(self.power_mode(company, region, node_id) if self.power_mode else None)
        except Exception:
            return ack_timeout_for(None)

    def _auto_delivery(self, req: CommandRequest) -> tuple[str, dict]:
        """``delivery='auto'``: queue for the next wake when the node is probably asleep."""
        info: dict = {"requested": "auto"}
        if req.broadcast:
            return "now", {**info, "chosen": "now", "reason": "broadcast"}
        if not self.broker.is_ready():
            return "next_wake", {**info, "chosen": "next_wake", "reason": "broker not connected"}
        try:
            risk = self.risk(req.company, req.region, req.node_id, req.cmd_type) if self.risk else None
        except Exception:
            risk = None  # model not trained yet or no data: behave like "now"
        if not risk:
            return "now", {**info, "chosen": "now", "reason": "no delivery-risk estimate"}
        chosen = "next_wake" if risk.get("tier") == "UNLIKELY" else "now"
        return chosen, {**info, "chosen": chosen, "tier": risk.get("tier"),
                        "probability": risk.get("probability"),
                        "reason": "node probably asleep" if chosen == "next_wake" else "node probably listening"}

    def submit(self, req: CommandRequest, actor: str) -> dict:
        auto = None
        if req.delivery == "auto":
            req.delivery, auto = self._auto_delivery(req)
        cmd_id, cmd_data = self.normalise(req)
        if req.cmd_type in ACTUATION and not req.broadcast and self.node_type is not None \
                and self.node_type(req.company, req.region, req.node_id) == "monitoring":
            raise CommandError(f"Node {req.node_id} is a monitoring node (sensors only); {req.cmd_type} commands need a "
                               "control node. Change its type on the Organization page if it has a valve.", status=409)
        if req.delivery == "now" and not self.broker.is_ready():
            raise CommandError("Broker is not connected", status=503)
        with self._lock:
            journal = self.journal
            exclusive = req.cmd_type in FLASH_COMMANDS and req.cmd_type != "FLASH_CANCEL"
            if exclusive:
                # One flash conversation per node: extra downlinks during a download collide
                # with its per-row ACKs on the LoRa link and stall it (OI-04).
                lock = self._transfer_lock(req.company, req.region, req.node_id, int(time.time()))
                if lock:
                    raise CommandError(lock["message"], status=409, lock=lock)
            try:
                result = journal.enqueue(req.company, req.node_id, cmd_id, req.cmd_type, cmd_data,
                                         ttl_seconds=req.ttl_seconds, actor=actor, delivery=req.delivery,
                                         broadcast=req.broadcast, region=req.region)
            except CommandConflict as exc:
                raise CommandError(str(exc), status=409, lock=self._command_lock(exc.blocking)) from exc
            request_id = result["request_id"]
            COMMANDS_SUBMITTED.labels(req.cmd_type, req.delivery).inc()
            if req.delivery == "now":
                item = journal.claim_immediate(request_id, ack_timeout=self._ack_timeout(
                    req.company, req.region, req.node_id))
                if item is None:
                    raise CommandError("Accepted command could not be claimed", status=500)
                try:
                    self._publish(item)
                except Exception as exc:
                    raise CommandError("Publication failed; execution unknown. Inspect the journal.",
                                       status=503, request_id=request_id, outcome_unknown=True) from exc
        self._notify(req.company, request_id)
        extra = {"delivery": req.delivery, **({"auto": auto} if auto else {})}
        if req.delivery == "next_wake":
            self.logs.emit(f"[QUEUE] Accepted {req.cmd_type} request={request_id}; waiting for Status",
                           company=req.company)
            return {**result, **extra, "queued": True, "message": "Queued until the node's next Status uplink"}
        try:
            self.history_writer(req.company, req.region, req.node_id,
                                f"{req.cmd_type} data={cmd_data} request={request_id}", request_id)
        except Exception:
            log.exception("Command submitted; history copy failed (journal retained)")
        return {**result, **extra, "queued": False, "awaiting_node_ack": True,
                "message": "Submitted; waiting for the node's execution reply"}

    def _publish(self, item: dict) -> None:
        client = self.broker.client
        if client is None:
            raise RuntimeError("Broker is not connected")
        msg = messages_pb2.CMD_Message(node_id=item["node_id"], cmd_id=item["cmd_id"],
                                       cmd_data=item["cmd_data"], request_id=item["request_id"])
        company, request_id, attempt = item["company"], item["request_id"], item["attempts"]
        topic = command_topic(company, item["region"], item["node_id"], bool(item["broadcast"]))
        journal = self.journal

        def confirmed() -> None:
            if journal.confirm_publish(request_id, attempt):
                self._notify(company, request_id)

        try:
            frame = client.publish_plaintext(topic, msg.SerializeToString(), on_complete=confirmed)
            if frame and frame.get("mqtt_mid") is not None:
                journal.record_transport_mid(request_id, attempt, frame["mqtt_mid"])
            self.logs.emit(f"[CMD] Submitted {item['cmd_type']} request={request_id} "
                           f"attempt={attempt} -> {topic}", company=company)
        except Exception as exc:
            journal.publish_failed(request_id, attempt, type(exc).__name__)
            raise

    def dispatch_on_status(self, company: str, region: str, node_id: int) -> None:
        """A valid Status proves the node's RX window is open: release one intent."""
        if not self.broker.is_ready():
            return
        try:
            with self._lock:
                item = self.journal.claim_on_status(company, node_id, region=region,
                                                    ack_timeout=self._ack_timeout(company, region, node_id))
                if item is not None:
                    self._publish(item)
                    self._notify(company, item["request_id"])
        except Exception as exc:
            self.logs.emit(f"[QUEUE] Dispatch failed ({type(exc).__name__}); inspect the journal",
                           company=company, level="warning")

    def acknowledge(self, company: str, region: str, node_id: int, request_id: int,
                    cmd_id: int, success: bool) -> bool:
        accepted = self.journal.acknowledge(company, node_id, request_id, cmd_id,
                                            success=success, region=region)
        if accepted:
            self._notify(company, request_id)
        return accepted

    def has_active(self, company: str, region: str, node_id: int, cmd_type: str) -> bool:
        """Is a ``cmd_type`` command for this node still pending, dispatched or waiting to retry?"""
        return any(r["cmd_type"] == cmd_type and r["state"] in ("pending", "dispatched", "waiting_retry")
                   for r in self.journal.list(company, node_id, 50, region=region))

    def _notify(self, company: str, request_id: int) -> None:
        self.hub.publish("command", {"request_id": request_id}, company=company)

    # ------------------------------------------------------------ flash lock
    def flash_lock(self, company: str, region: str, node_id: int, now: int | None = None) -> dict | None:
        """Why a new flash command for this node would be refused right now (Cancel never is)."""
        now = int(time.time() if now is None else now)
        lock = self._transfer_lock(company, region, node_id, now)
        if lock:
            return lock
        busy = self.journal.active_flash(company, node_id, now, region=region)
        return self._command_lock(busy) if busy else None

    def _transfer_lock(self, company: str, region: str, node_id: int, now: int) -> dict | None:
        t = self.flash_transfer(company, region, node_id, now) if self.flash_transfer else None
        if not t:
            return None
        rows = f"{t['received']}/{t['total']} rows" if t.get("total") else "preparing"
        return {"kind": "download", "request_id": t["request"], "cmd_type": "FLASH_TODAY",
                "received": t["received"], "total": t["total"], "since": t["updated"],
                "until": t["updated"] + TRANSFER_IDLE_S,
                "message": f"History download #{t['request']} is still running ({rows}); "
                           "wait for it to finish or cancel it first"}

    @staticmethod
    def _command_lock(busy: dict) -> dict:
        queued = busy["state"] == "pending" and busy["delivery"] == "next_wake"
        waiting = "queued for the next wake" if queued else "waiting for the node's reply"
        return {"kind": "queued" if queued else "command", "request_id": busy["request_id"],
                "cmd_type": busy["cmd_type"], "state": busy["state"],
                "since": busy.get("submitted_at") or busy["created_at"],
                "until": busy["expires_at"] if queued else (busy.get("ack_deadline") or busy["expires_at"]),
                "message": f"{busy['cmd_type']} #{busy['request_id']} is still {waiting}; "
                           "send the next flash command when it finishes (Cancel is always allowed)"}

    # ------------------------------------------------------------------ reads
    def list(self, company: str, region: str = DEFAULT_REGION, node_id: int | None = None,
             limit: int = 50) -> list[dict]:
        rows = self.journal.list(company, node_id, limit, region=region)
        for row in rows:
            row["cmd_name"] = CMD_NAMES.get(row["cmd_id"], str(row["cmd_id"]))
        return rows

    def get(self, request_id: int, company: str, region: str, node_id: int) -> dict | None:
        return self.journal.get(request_id, company, node_id, region=region)
