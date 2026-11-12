# Code map

_Generated from the code by `docs/tools/gen_reference.py` on 2026-11-12. Do not edit by hand._

| Module | Lines | Purpose (module docstring) | Public classes and functions |
|---|---|---|---|
| `wiot/__init__.py` | 8 | WIOT Platform v2 — industrial water-IoT ingestion, control and analytics server. |  |
| `wiot/__main__.py` | 199 | Command-line entry point: ``python -m wiot <command>``. | cmd_serve, cmd_backup, cmd_verify_backup, cmd_restore_backup, cmd_init, cmd_create_user, cmd_reset_password, cmd_import_v1, cmd_check, cmd_flash_timeline, cmd_analyze, cmd_simulate, cmd_devbroker, main |
| `wiot/analytics/__init__.py` | 14 | WIOT data-analysis and machine-learning pipeline. |  |
| `wiot/analytics/common.py` | 93 | Small shared helpers: JSON serialisation, robust statistics, histograms, time zones. | to_jsonable, write_json, percentiles, histogram, wilson_ci, downsample_indices, local_hour, local_day |
| `wiot/analytics/dataset.py` | 372 | Read-only loaders for the WIOT databases and the shared command feature builder. | FeatureSpec, connect_ro, message_db_paths, command_db_path, node_key, load_messages, load_meter_samples, load_consumption_periods, load_command_events, load_command_receipts, load_commands, link_features, history_features, command_features … |
| `wiot/analytics/descriptive.py` | 355 | Descriptive analyses: fleet & link reliability, power & health, sensors, command outcomes. | uplinks, node_link_stats, fleet_and_link, day_hour_heatmap, store_forward, counter_events, power_health, sensor_samples, robust_z, anomalies, sensors_analysis, data_quality, commands_analysis |
| `wiot/analytics/energy.py` | 84 | Battery-life model from the project's power-down study. | PowerConfig, average_current_ma, life_days, energy_model |
| `wiot/analytics/figures.py` | 379 | Matplotlib figures for REPORT.md, rendered from the JSON artifacts (dark surface #0b1220). | fig_uplinks_daily, fig_heatmap, fig_intervals, fig_store_forward, fig_battery, fig_energy, fig_cmd_by_type, fig_ack_recency, fig_ack_latency, fig_model_cv, fig_holdout_curves, fig_calibration, fig_shap, fig_tiers … |
| `wiot/analytics/modeling.py` | 622 | Training and evaluation of the "Command Delivery Risk" model. | candidate_factories, sessions, temporal_split, make_folds, best_f1_threshold, youden_threshold, threshold_metrics, all_metrics, bootstrap_compare, curve_points, calibration_bins, RecencyRule, CVResult, fit_members … |
| `wiot/analytics/pipeline.py` | 287 | WIOT analytics pipeline CLI. | build_nodes, headline, findings, holdout_nodes_note, model_notes, run, main |
| `wiot/analytics/predictor.py` | 101 | Serve-time "Command Delivery Risk" predictor. | CommandRiskPredictor |
| `wiot/analytics/repo_stats.py` | 266 | Project-wide statistics: firmware footprint per build profile, power-guard verification, code size. | elf_section_sizes, elf_usage, parse_build_log, firmware_stats, power_guard_stats, iter_source_files, is_generated, is_vendor, is_test, project_stats |
| `wiot/analytics/report.py` | 434 | REPORT.md writer: a data-driven analysis report built only from the JSON artifacts. | pct, num, day, ci, table, fig, write_report |
| `wiot/analytics/riskmodel.py` | 201 | Serialisable "Command Delivery Risk" model with exact additive explanations. | safe_log1p, logit, sigmoid, make_preprocessor, output_to_feature_index, Member, FittedRiskModel |
| `wiot/api/__init__.py` | 0 |  |  |
| `wiot/api/admin.py` | 64 | Tenant administration: users, companies, audit trail. | UserIn, CompanyIn, list_users, create_user, delete_user, list_companies, add_company, audit |
| `wiot/api/alerts.py` | 40 | Fleet alerts: silent nodes, low batteries and unstable flow readings. | list_alerts, acknowledge |
| `wiot/api/auth.py` | 75 | Login, logout, session introspection and password change. | LoginIn, PasswordIn, login, logout, me, change_password |
| `wiot/api/commands.py` | 67 | Command submission, lifecycle timeline and pre-send delivery risk. | CommandIn, RiskIn, catalog, list_commands, get_command, submit, delivery_risk |
| `wiot/api/deps.py` | 93 | Request-scoped dependencies: runtime, authentication, tenant scoping. | get_runtime, authenticate, ws_authenticate, require_supervisor, require_admin, resolve_company, resolve_region |
| `wiot/api/farm.py` | 78 | Smart-agriculture endpoints: farm map, zones, weather/ET0, satellite readiness. | ZonePatch, overview, get_layout, put_layout, patch_zone, zone_history, weather, connectivity, public_map |
| `wiot/api/operations.py` | 222 | Broker control, flash archive, analytics, logs and health endpoints. | BrokerIn, broker_status, broker_connect, broker_disconnect, flash_status, flash_nodes, flash_analysis, flash_lock, flash_records, PredictIn, analytics_index, analytics_live, model_schema, predict … |
| `wiot/api/org.py` | 379 | Organization API: companies, regions, nodes, gateways, API tokens, webhooks, world view. | CompanyBody, list_companies, create_company, update_company, RegionBody, list_regions, create_region, update_region, delete_region, NodeBody, CsvBody, list_nodes, create_node, update_node … |
| `wiot/api/stream.py` | 59 | Live event stream (WebSocket). | stream |
| `wiot/api/telemetry.py` | 137 | Fleet, node, message history, consumption and CSV export endpoints. | fleet, node_detail, node_series, messages, regions, consumption, export_csv |
| `wiot/app.py` | 131 | FastAPI application factory. | build_csp, create_app |
| `wiot/config.py` | 157 | Typed runtime configuration loaded from environment variables and ``.env``. | Settings, get_settings |
| `wiot/domain/__init__.py` | 0 |  |  |
| `wiot/domain/command_queue.py` | 411 | Durable command intents, bounded mailbox and correlated execution audit. | ack_timeout_for, CommandConflict, flash_request_limit, CommandQueue |
| `wiot/domain/flash_analysis.py` | 196 | Analysis of a node's SPI-flash telemetry log, built from what the server already holds. | transfer_state, analyse |
| `wiot/domain/flash_archive.py` | 190 | Durable, tenant-scoped flash downloads; acknowledge only after SQLite commit. | FlashArchive |
| `wiot/logging_setup.py` | 53 | Structured logging with secret redaction and a rotating file sink. | redact, JsonFormatter, configure_logging |
| `wiot/protocol/__init__.py` | 0 |  |  |
| `wiot/protocol/flow_schema.py` | 197 | Flow-meter schema helpers shared by MQTT ingestion and tests. | flow_meter_name, period_source_name, period_quality_name, extract_flow_metadata, secondary_flow_reading, flow_reading_snapshot, select_measurement_timestamp, build_sample_fingerprint, calendar_period_rows, dashboard_flow_fields |
| `wiot/protocol/messages_pb2.py` | 0 | Generated protobuf module (from proto/messages.proto); do not edit. |  |
| `wiot/protocol/power.py` | 47 | Wire-level remote-wake validation and display metadata (no broker side effects). | validate_wake_seconds, power_metadata, power_dashboard_fields, is_confirmed_wake |
| `wiot/protocol/tenancy.py` | 75 | Stable, platform-independent tenant storage identities and legacy preflight. | storage_id, legacy_name, preflight, database_path |
| `wiot/protocol/topics.py` | 36 | Case-sensitive WIOT company/region topic contract; no legacy aliases. | region_id, command_topic, migrate_region_storage |
| `wiot/protocol/transport.py` | 505 | mqtt_impl.py ============ Annotated MQTT transport + AES-CBC/PKCS7 framing layer. | Counters, MqttNodeClient |
| `wiot/protocol/validation.py` | 102 | Fail-closed validation for the existing V1 wire/API contract (no schema change). | company_id, integer, parse_topic, validate_message |
| `wiot/security.py` | 153 | Authentication primitives: principals, password hashing, JWT and throttling. | AuthError, Principal, hash_password, verify_password, validate_new_password, issue_token, decode_token, LoginThrottle |
| `wiot/services/__init__.py` | 0 |  |  |
| `wiot/services/alerts.py` | 273 | Fleet alert monitor: silent nodes, low batteries and implausible flow readings. | flow_jumps, flow_verdict, valve_flow_verdict, night_hours, in_night, AlertMonitor |
| `wiot/services/analytics.py` | 114 | Serves analysis artifacts, live KPIs and the command-delivery risk model. | AnalyticsService |
| `wiot/services/broker.py` | 127 | Single owner of the shared MQTT ingestion session. | BrokerParams, BrokerManager |
| `wiot/services/clocksync.py` | 114 | Automatic node clock synchronisation (R2.1, point 12). | ClockSync |
| `wiot/services/commands.py` | 294 | Operator command intents: validation, durable journal, publish and receipts. | CommandError, CommandRequest, CommandService |
| `wiot/services/farm.py` | 529 | Smart-agriculture layer: farm layout, weather/ET0, irrigation advisory, soil-moisture automation and satellite-backhaul readiness. | Site, Agronomy, Zone, Gateway, Device, FarmLayout, FarmStore, WeatherClient, FarmService |
| `wiot/services/ingest.py` | 352 | Decoded-MQTT ingestion: validate → persist → broadcast → release commands. | IngestService |
| `wiot/services/metrics.py` | 27 | Prometheus metrics (scraped at ``/metrics``). |  |
| `wiot/services/realtime.py` | 115 | Tenant-scoped WebSocket fan-out, safe to call from any thread. | Subscriber, RealtimeHub, LogBuffer |
| `wiot/services/runtime.py` | 103 | Composition root: builds and owns every long-lived service. | Runtime |
| `wiot/services/webhooks.py` | 124 | Outbound webhooks. | sign, check_destination, WebhookService |
| `wiot/sim/__init__.py` | 0 |  |  |
| `wiot/sim/bridge.py` | 98 | Two-way MQTT bridge between the local development broker and an upstream broker. | MqttBridge, parse_endpoint |
| `wiot/sim/devbroker.py` | 41 | Pure-Python MQTT broker for local development and demos (not for production). | main |
| `wiot/sim/fleet.py` | 303 | Encrypted WIOT fleet simulator for demos, load and end-to-end tests. | VirtualNode, FleetSimulator, agri_fleet, default_fleet, main |
| `wiot/storage/__init__.py` | 0 |  |  |
| `wiot/storage/alert_store.py` | 128 | Persistent fleet alerts: at most one open alert per (company, region, node, kind). | AlertStore |
| `wiot/storage/backup.py` | 167 | Consistent, optionally encrypted backups of every database, with verification and restore (R2.1, point 6). | database_files, create_backup, verify_backup, restore_backup |
| `wiot/storage/main_store.py` | 218 | Identity, tenant registry and audit trail (``iot_data.db``). | MainStore |
| `wiot/storage/org_store.py` | 533 | Organization registry: company profiles, regions, nodes, gateways, API tokens, webhooks. | sensors_from_mask, parse_sensors, check_timezone, check_country, check_point, OrgStore |
| `wiot/storage/telemetry_store.py` | 435 | Per-tenant telemetry databases (``messages_dbs/<tenant>.db``). | decorate_row, TelemetryStore |
| `wiot/tools/__init__.py` | 0 |  |  |
| `wiot/tools/flash_timeline.py` | 137 | Flash-download diagnosis (R2.1, point 3): merge the server's records with the gateway's serial log. | parse_local, gateway_events, server_events, timeline, format_text |

## Web assets (`wiot/web`)

| File | Lines |
|---|---|
| `wiot/web/assets/api.js` | 125 |
| `wiot/web/assets/app.css` | 453 |
| `wiot/web/assets/app.js` | 217 |
| `wiot/web/assets/charts.js` | 330 |
| `wiot/web/assets/farm.css` | 208 |
| `wiot/web/assets/favicon.svg` | 1 |
| `wiot/web/assets/global.css` | 225 |
| `wiot/web/assets/i18n.js` | 452 |
| `wiot/web/assets/login.js` | 50 |
| `wiot/web/assets/pages/admin.js` | 97 |
| `wiot/web/assets/pages/alerts.js` | 148 |
| `wiot/web/assets/pages/analytics.js` | 269 |
| `wiot/web/assets/pages/commands.js` | 157 |
| `wiot/web/assets/pages/farm.js` | 566 |
| `wiot/web/assets/pages/flash.js` | 331 |
| `wiot/web/assets/pages/history.js` | 57 |
| `wiot/web/assets/pages/org.js` | 401 |
| `wiot/web/assets/pages/overview.js` | 171 |
| `wiot/web/assets/pages/world.js` | 121 |
| `wiot/web/assets/theme.js` | 14 |
| `wiot/web/assets/units.js` | 47 |
| `wiot/web/index.html` | 25 |
| `wiot/web/login.html` | 33 |

Vendored libraries in `wiot/web/assets/vendor/` (served locally, no CDN): leaflet.css, leaflet.js.
