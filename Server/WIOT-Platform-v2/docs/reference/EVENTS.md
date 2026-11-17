# Realtime events and metrics

_Generated from the code by `docs/tools/gen_reference.py` on 2026-11-17. Do not edit by hand._

## Realtime hub events

Published on the internal hub, delivered to WebSocket clients of the same tenant (`/api/v2/ws`) and to the webhook service.

| Event | Published at |
|---|---|
| `alert` | `wiot/api/alerts.py:46` |
| `greenhouse_layout` | `wiot/api/greenhouses.py:46` |
| `alert` | `wiot/services/alerts.py:319` |
| `broker` | `wiot/services/broker.py:100` |
| `broker` | `wiot/services/broker.py:125` |
| `command` | `wiot/services/commands.py:416` |
| `device_reading` | `wiot/services/devices.py:311` |
| `automation` | `wiot/services/farm.py:564` |
| `telemetry` | `wiot/services/ingest.py:330` |
| `telemetry` | `wiot/services/ingest.py:346` |
| `flash` | `wiot/services/ingest.py:386` |
| `log` | `wiot/services/realtime.py:128` |
| `log` | `wiot/services/realtime.py:130` |

## Prometheus metrics (`/metrics`)

| Metric | Help |
|---|---|
| `wiot_messages_ingested_total` | Decoded MQTT messages persisted |
| `wiot_messages_dropped_total` | MQTT messages rejected before storage |
| `wiot_commands_submitted_total` | Operator commands accepted |
| `wiot_command_receipts_total` | Node command receipts |
| `wiot_ingest_seconds` | Decode+validate+persist latency |
| `wiot_http_requests_total` | HTTP requests |
| `wiot_http_request_seconds` | HTTP latency |
| `wiot_repeated_frames_total` | Uplinks whose plaintext repeats an earlier one (duplicate or out of order) |
| `wiot_foreign_commands_total` | Commands seen on command topics that this server did not send |
| `wiot_ingest_last_message_age_seconds` | Seconds since the newest message of each company |
| `wiot_disk_free_ratio` | Free share of the data disk (0..1) |
| `wiot_backup_age_seconds` | Seconds since the newest backup file |
| `wiot_maintenance_runs_total` | Maintenance cycles (summaries, retention, status) |
| `wiot_config_corrections_total` | SRATE/STRAN re-sent by the configuration watch |
| `wiot_broker_ready` | 1 when MQTT subscriptions are confirmed |
| `wiot_websocket_connections` | Open dashboard sockets |
