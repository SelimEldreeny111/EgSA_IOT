"""Prometheus metrics (scraped at ``/metrics``)."""
from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

REGISTRY = CollectorRegistry(auto_describe=True)

MESSAGES_INGESTED = Counter(
    "wiot_messages_ingested_total", "Decoded MQTT messages persisted", ["kind"], registry=REGISTRY)
MESSAGES_DROPPED = Counter(
    "wiot_messages_dropped_total", "MQTT messages rejected before storage", ["reason"], registry=REGISTRY)
COMMANDS_SUBMITTED = Counter(
    "wiot_commands_submitted_total", "Operator commands accepted", ["cmd_type", "delivery"], registry=REGISTRY)
COMMAND_RECEIPTS = Counter(
    "wiot_command_receipts_total", "Node command receipts", ["outcome"], registry=REGISTRY)
INGEST_SECONDS = Histogram(
    "wiot_ingest_seconds", "Decode+validate+persist latency", registry=REGISTRY,
    buckets=(0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0))
HTTP_REQUESTS = Counter(
    "wiot_http_requests_total", "HTTP requests", ["method", "route", "status"], registry=REGISTRY)
HTTP_SECONDS = Histogram(
    "wiot_http_request_seconds", "HTTP latency", ["route"], registry=REGISTRY,
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5))
BROKER_READY = Gauge("wiot_broker_ready", "1 when MQTT subscriptions are confirmed", registry=REGISTRY)
WS_CONNECTIONS = Gauge("wiot_websocket_connections", "Open dashboard sockets", registry=REGISTRY)
