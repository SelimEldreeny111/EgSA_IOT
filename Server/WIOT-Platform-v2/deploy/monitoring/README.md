# Monitoring the WIOT platform

The server exposes Prometheus metrics at `/metrics` (set `WIOT_METRICS_PUBLIC=false` to allow localhost only)
and a built-in **System health** page (Settings → System health, supervisor) that needs no extra software.

For an external monitor:

1. Prometheus: add a scrape job for `http://<server>:8000/metrics` with `job_name: wiot`, and load
   `prometheus-rules.yml` (`rule_files:`). The rules page the operator when the server or the broker link is
   down, a company stops sending, the disk fills up, the last backup is old, or messages are being rejected.
2. Grafana: Dashboards → Import → upload `grafana-dashboard.json` and pick the Prometheus data source.

Key series: `wiot_broker_ready`, `wiot_ingest_last_message_age_seconds{company}`, `wiot_disk_free_ratio`,
`wiot_backup_age_seconds`, `wiot_messages_ingested_total{kind}`, `wiot_messages_dropped_total{reason}`,
`wiot_ingest_seconds`, `wiot_http_request_seconds{route}`, `wiot_maintenance_runs_total{outcome}`,
`wiot_config_corrections_total`.

The public page `/status` (on by default, `WIOT_STATUS_PUBLIC=false` to hide it) shows 30 days of availability
without any company or device data, for customers and partners.
