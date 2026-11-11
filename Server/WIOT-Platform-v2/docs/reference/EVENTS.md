# Realtime events and metrics

_Generated from the code by `docs/tools/gen_reference.py` on 2026-11-11. Do not edit by hand._

## Realtime hub events

Published on the internal hub, delivered to WebSocket clients of the same tenant (`/api/v2/ws`) and to the webhook service.

| Event | Published at |
|---|---|
| `alert` | `wiot/api/alerts.py:46` |
| `alert` | `wiot/services/alerts.py:154` |
| `broker` | `wiot/services/broker.py:97` |
| `broker` | `wiot/services/broker.py:118` |
| `command` | `wiot/services/commands.py:241` |
| `automation` | `wiot/services/farm.py:440` |
| `telemetry` | `wiot/services/ingest.py:254` |
| `telemetry` | `wiot/services/ingest.py:268` |
| `flash` | `wiot/services/ingest.py:284` |
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
| `wiot_broker_ready` | 1 when MQTT subscriptions are confirmed |
| `wiot_websocket_connections` | Open dashboard sockets |
