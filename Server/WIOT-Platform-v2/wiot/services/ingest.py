"""Decoded-MQTT ingestion: validate → persist → broadcast → release commands.

Behaviour mirrors v1.31 ``on_mqtt_plaintext`` exactly where it matters for the
field contract: topic/payload node cross-check, fail-closed validation before
any side effect, ACK/WAKE replies never becoming meter samples, flash-history
replies routed to the archive and acknowledged only after commit.
"""
from __future__ import annotations

import json
import logging
import time

from ..domain.flash_archive import HISTORY_ACK, FlashArchive
from ..protocol import messages_pb2
from ..protocol.flow_schema import (
    build_sample_fingerprint,
    DEFAULT_CALENDAR_TIMEZONE,
    calendar_period_rows,
    extract_flow_metadata,
    flow_reading_snapshot,
    secondary_flow_reading,
    select_measurement_timestamp,
)
from ..protocol.power import is_confirmed_wake, power_metadata
from ..protocol.topics import command_topic
from ..protocol.validation import MAX_PROTO_BYTES, parse_topic, validate_message
from ..storage.telemetry_store import TelemetryStore, decorate_row
from .commands import CMD_NAMES, CommandService
from .metrics import COMMAND_RECEIPTS, INGEST_SECONDS, MESSAGES_DROPPED, MESSAGES_INGESTED
from .realtime import LogBuffer, RealtimeHub

log = logging.getLogger(__name__)



def _base_fields(msg) -> dict:
    return {
        "flow": msg.flow_rate, "velocity": msg.velocity, "flow_day": msg.flow_rate_per_day,
        "flow_month": msg.flow_rate_per_month, "flow_year": msg.flow_rate_per_year,
        "node_status": msg.node_status, "soil_temperature": msg.soil_temperature,
        "soil_moisture": msg.soil_moisture, "soil_moisture_temp_valid": msg.soil_moisture_temp_valid,
        "ec_temperature": msg.ec_temperature, "ec_moisture": msg.ec_moisture,
        "electrical_conductivity": msg.electrical_conductivity,
        "soil_moisture_temp_ec_valid": msg.soil_moisture_temp_ec_valid,
        "active_sensor_count": msg.active_sensor_count, "sensor_mask": msg.sensor_mask,
        "battery_voltage": msg.battery_voltage,
    }


def _secondary(msg, scope: str, measured_at: int, tz: str = DEFAULT_CALENDAR_TIMEZONE) -> dict | None:
    reading = secondary_flow_reading(msg)
    if reading is None:
        return None
    meta = extract_flow_metadata(reading)
    return {
        "metadata": meta,
        "fingerprint": build_sample_fingerprint(scope, msg, meta, measured_at, reading=reading),
        "period_rows": calendar_period_rows(reading, meta, measured_at, tz),
        "flow_rate": float(reading.flow_rate), "velocity": float(reading.velocity),
        "volume_day": float(reading.flow_rate_per_day),
        "volume_month": float(reading.flow_rate_per_month),
        "volume_year": float(reading.flow_rate_per_year),
        "snapshot": flow_reading_snapshot(reading),
    }


def _sample_details(msg) -> str:
    if getattr(msg, "stored_sample", False):
        return f"Stored sample #{msg.sample_sequence}; acquired epoch={msg.timestamp}"
    if getattr(msg, "live_fallback", False):
        return "Live fallback; no committed flash sample available"
    return ""


class IngestService:
    def __init__(self, store: TelemetryStore, commands: CommandService, hub: RealtimeHub,
                 logs: LogBuffer, flash_path, known_companies):
        self.store = store
        self.commands = commands
        self.hub = hub
        self.logs = logs
        self._flash_path = flash_path
        self._flash: FlashArchive | None = None
        self.known_companies = known_companies
        self.last_by_node: dict[tuple[str, str, int], float] = {}
        self.frame_stats: dict[tuple[str, str, int], dict] = {}
        self.farm = None  # FarmService, injected by the runtime
        self.org = None  # OrgStore, injected by the runtime (strict provisioning, company time zone)

    @property
    def flash(self) -> FlashArchive:
        if self._flash is None:
            self._flash = FlashArchive(self._flash_path)
        return self._flash

    # ------------------------------------------------------------------ entry
    def on_plaintext(self, topic: str, plaintext: bytes) -> None:
        started = time.perf_counter()
        try:
            company, region, topic_node, kind = parse_topic(topic)
            if not isinstance(plaintext, bytes) or not 0 < len(plaintext) <= MAX_PROTO_BYTES:
                raise ValueError("Empty or oversized protobuf")
        except ValueError as exc:
            MESSAGES_DROPPED.labels("topic").inc()
            self.logs.emit(f"[VALIDATION] Dropped packet on {topic[:120]}: {exc}", level="warning")
            return
        if company not in self.known_companies():
            MESSAGES_DROPPED.labels("unknown_tenant").inc()
            self.logs.emit(f"[VALIDATION] Dropped packet for unregistered company '{company}'",
                           level="warning")
            return
        if self.org is not None and kind in ("status", "telemetry") and not self.org.accepts(company, region, topic_node):
            MESSAGES_DROPPED.labels("unregistered_node").inc()
            self.logs.emit(f"[PROVISIONING] Dropped {kind} from unregistered node {company}/{region}/{topic_node} "
                           "(strict provisioning is on; register the node in Organization)", company=company,
                           level="warning")
            return
        try:
            self._count_frame(company, region, topic_node, len(plaintext))
            if kind == "status":
                self._status(company, region, topic_node, plaintext)
            elif kind == "telemetry":
                self._telemetry(company, region, topic_node, plaintext)
            elif kind == "cmd":
                self._command_echo(company, region, topic_node, plaintext)
        except ValueError as exc:
            MESSAGES_DROPPED.labels("validation").inc()
            self.logs.emit(f"[VALIDATION] Dropped {kind} from {company}/{region}/{topic_node}: {exc}",
                           company=company, level="warning")
        except Exception as exc:  # never let one bad frame kill the MQTT thread
            MESSAGES_DROPPED.labels("error").inc()
            log.exception("Ingest failure on %s", topic)
            self.logs.emit(f"[INGEST] Unexpected {type(exc).__name__} on {topic}", level="error")
        finally:
            INGEST_SECONDS.observe(time.perf_counter() - started)

    def _count_frame(self, company: str, region: str, node: int, payload: int) -> None:
        """Rolling payload statistics for satellite-backhaul sizing."""
        if not node:
            return
        frame = 1 + 16 + 16 * (payload // 16 + 1)  # version + IV + PKCS7-padded AES-CBC
        s = self.frame_stats.setdefault((company, region, node), {"count": 0, "payload_bytes": 0, "frame_bytes": 0})
        s["count"] += 1
        s["payload_bytes"] += payload
        s["frame_bytes"] += frame

    # ---------------------------------------------------------------- uplinks
    def _decode(self, cls, plaintext: bytes, topic_node: int):
        msg = cls()
        msg.ParseFromString(plaintext)
        validate_message(msg, topic_node)
        return msg

    def _status(self, company: str, region: str, node: int, plaintext: bytes) -> None:
        msg = self._decode(messages_pb2.Status_Message, plaintext, node)
        now = int(time.time())
        fields, samples = self._reading(msg, company, region, now)
        fields["details"] = _sample_details(msg)
        self._persist_and_emit(company, region, "Status", msg, now, fields, samples)
        if self.farm is not None:
            try:
                self.farm.on_status(company, region, msg.node_id, fields)
            except Exception:
                log.exception("Irrigation automation failed")
        self.commands.dispatch_on_status(company, region, msg.node_id)

    def _telemetry(self, company: str, region: str, node: int, plaintext: bytes) -> None:
        msg = self._decode(messages_pb2.Telemetry, plaintext, node)
        if msg.HasField("flash_log") or msg.HasField("history"):
            self._flash_reply(company, region, node, msg)
            return
        now = int(time.time())
        fields, samples = self._reading(msg, company, region, now)
        meta = fields["_meta"]
        details = (f"Node-TS:{msg.timestamp} S-Rate:{msg.sampling_rate} T-Rate:{msg.Transmission_rate} "
                   f"sensors:{msg.active_sensor_count} meter:{meta['flow_meter_name']} "
                   f"period:{meta['flow_period_source_name']}")
        if msg.command_ack_request_id:
            ok = self.commands.acknowledge(company, region, msg.node_id, msg.command_ack_request_id,
                                           msg.command_ack_cmd_id, bool(msg.command_ack_success))
            COMMAND_RECEIPTS.labels("ack" if msg.command_ack_success else "rejected").inc()
            verdict = "ACK" if msg.command_ack_success else "REJECTED"
            if ok:
                self.logs.emit(f"[CMD {verdict}] node {msg.node_id} request={msg.command_ack_request_id} "
                               f"cmd={CMD_NAMES.get(msg.command_ack_cmd_id, msg.command_ack_cmd_id)}",
                               company=company)
            details += f" CMD_{verdict} request={msg.command_ack_request_id} cmd={msg.command_ack_cmd_id}"
        power = fields["_power"]
        if power["wake_command_ack"] or msg.command_ack_request_id:
            # Replies carry cached sensor state: keep the history row but never
            # manufacture a meter sample, chart point or consumption snapshot.
            samples = []
            fields["time_source"] = "wake_ack_cached" if power["wake_command_ack"] else "command_ack_cached"
            fields["flow_live_valid"] = 0
        if power["wake_command_ack"]:
            details += (f" WAKE_ACK request={power['wake_request_id']} power={power['power_mode']} "
                        f"state={power['power_state']} remaining={power['wake_remaining_seconds']}s")
            if is_confirmed_wake(power):
                self.logs.emit(f"[WAKE ACK] node {msg.node_id} active for "
                               f"{power['wake_remaining_seconds']}s", company=company)
        fields["details"] = details
        self._persist_and_emit(company, region, "Telemetry", msg, now, fields, samples, extra={
            "command_ack_request_id": int(msg.command_ack_request_id),
            "command_ack_cmd_id": int(msg.command_ack_cmd_id),
            "command_ack_success": bool(msg.command_ack_success),
            "sampling_rate_ms": int(msg.sampling_rate),
            "transmission_rate_ms": int(msg.Transmission_rate),
        })

    def _reading(self, msg, company: str, region: str, now: int) -> tuple[dict, list[dict]]:
        scope = f"{company}/{region}"
        tz = self.org.timezone(company) if self.org is not None else DEFAULT_CALENDAR_TIMEZONE
        meta = extract_flow_metadata(msg)
        power = power_metadata(msg)
        measured_at, time_source = select_measurement_timestamp(msg, now)
        primary = {
            "metadata": meta,
            "fingerprint": build_sample_fingerprint(scope, msg, meta, measured_at),
            "period_rows": calendar_period_rows(msg, meta, measured_at, tz),
            "flow_rate": msg.flow_rate, "velocity": msg.velocity,
            "volume_day": msg.flow_rate_per_day, "volume_month": msg.flow_rate_per_month,
            "volume_year": msg.flow_rate_per_year,
        }
        secondary = _secondary(msg, scope, measured_at, tz)
        fields = _base_fields(msg)
        fields.update({k: meta.get(k, 0) for k in (
            "flow_meter_type", "flow_period_source", "flow_live_valid", "flow_period_totals_valid",
            "flow_cumulative_totals_valid", "rtc_valid", "forward_total_liters", "reverse_total_liters",
            "net_total_liters", "flow_period_quality", "flow_meter_alarm_flags", "legacy_flow_schema")})
        fields.update(power)
        fields["measured_at"] = measured_at
        fields["time_source"] = time_source
        fields["secondary_flow_json"] = json.dumps(secondary["snapshot"]) if secondary else None
        fields["_meta"], fields["_power"] = meta, power
        samples = [primary] + ([secondary] if secondary else [])
        return fields, samples

    def _persist_and_emit(self, company, region, kind, msg, now, fields, samples, extra=None) -> None:
        fields = dict(fields)
        fields.pop("_meta", None)
        fields.pop("_power", None)
        self.store.save_message(company=company, region=region, received_at=now, msg_type=kind,
                                node_id=msg.node_id, sensor_id=msg.sensor_id, fields=fields,
                                samples=samples)
        MESSAGES_INGESTED.labels(kind.lower()).inc()
        self.last_by_node[(company, region, msg.node_id)] = time.time()
        row = {k: v for k, v in fields.items()}
        row.update(timestamp=now, type=kind, node_id=msg.node_id, sensor_id=str(msg.sensor_id),
                   company=company, region=region)
        row = decorate_row(row)
        if extra:
            row.update(extra)
        self.hub.publish("telemetry", row, company=company)

    # ---------------------------------------------------------- command echo
    def _command_echo(self, company: str, region: str, node: int, plaintext: bytes) -> None:
        msg = self._decode(messages_pb2.CMD_Message, plaintext, node)
        if msg.cmd_id == HISTORY_ACK:
            return  # internal persistence receipt
        name = CMD_NAMES.get(msg.cmd_id, str(msg.cmd_id))
        details = f"Cmd={name}({msg.cmd_id}), Data={msg.cmd_data}"
        now = int(time.time())
        self.store.save_message(company=company, region=region, received_at=now, msg_type="Command",
                                node_id=msg.node_id, sensor_id="-", fields={"details": details,
                                "wake_request_id": int(msg.request_id)})
        MESSAGES_INGESTED.labels("command").inc()
        self.hub.publish("telemetry", decorate_row({
            "timestamp": now, "type": "Command", "node_id": msg.node_id, "sensor_id": "-",
            "company": company, "region": region, "details": details}), company=company)

    def write_command_history(self, company: str, region: str, node_id: int, details: str,
                              request_id: int) -> None:
        self.store.save_message(company=company, region=region, received_at=int(time.time()),
                                msg_type="Command", node_id=node_id, sensor_id="-",
                                fields={"details": details, "wake_request_id": request_id})

    # ------------------------------------------------------------------ flash
    def _flash_reply(self, company: str, region: str, node: int, msg) -> None:
        event, ack = self.flash.accept(company, region, node, msg)
        if msg.command_ack_request_id:
            self.commands.acknowledge(company, region, node, msg.command_ack_request_id,
                                      msg.command_ack_cmd_id, bool(msg.command_ack_success))
        self.hub.publish("flash", event, company=company)
        client = self.commands.broker.client
        if ack and client is not None and client.is_connected():
            request_id, data = ack
            reply = messages_pb2.CMD_Message(node_id=node, cmd_id=HISTORY_ACK, cmd_data=data,
                                             request_id=request_id)
            client.publish_plaintext(command_topic(company, region, node, False), reply.SerializeToString())
        self.logs.emit(f"[FLASH] {company}/{region}/{node} reply persisted; history ACK={bool(ack)}",
                       company=company)
