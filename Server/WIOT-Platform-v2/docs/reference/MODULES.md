# Code map

_Generated from the code by `docs/tools/gen_reference.py` on 2026-11-16. Do not edit by hand._

| Module | Lines | Purpose (module docstring) | Public classes and functions |
|---|---|---|---|
| `wiot/__init__.py` | 8 | WIOT Platform v2 — industrial water-IoT ingestion, control and analytics server. |  |
| `wiot/__main__.py` | 225 | Command-line entry point: ``python -m wiot <command>``. | cmd_serve, cmd_backup, cmd_verify_backup, cmd_restore_backup, cmd_init, cmd_create_user, cmd_reset_password, cmd_import_v1, cmd_check, cmd_flash_timeline, cmd_analyze, cmd_simulate, cmd_maintain, cmd_loadtest … |
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
| `wiot/api/admin.py` | 173 | Tenant administration: users, companies, audit trail. | UserIn, CompanyIn, list_users, create_user, delete_user, list_companies, add_company, audit, PagesIn, set_user_pages, reset_user_totp, list_sessions, revoke_session, InviteIn … |
| `wiot/api/alerts.py` | 40 | Fleet alerts: silent nodes, low batteries and unstable flow readings. | list_alerts, acknowledge |
| `wiot/api/auth.py` | 274 | Login (password, two-factor, SSO), logout, sessions, invitations and password change. | LoginIn, PasswordIn, CodeIn, DisableIn, AcceptIn, login, logout, me, change_password, totp_status, totp_setup, totp_enable, totp_disable, my_sessions … |
| `wiot/api/commands.py` | 67 | Command submission, lifecycle timeline and pre-send delivery risk. | CommandIn, RiskIn, catalog, list_commands, get_command, submit, delivery_risk |
| `wiot/api/crop.py` | 148 | Crop care, farm diary, yields, WaPOR, the farmer view and regional dashboards (R2.5). | crop_status, DiaryIn, diary, add_diary, delete_diary, traceability, productivity, wapor, wapor_import, farmer_today, farmer_page, regional |
| `wiot/api/deps.py` | 95 | Request-scoped dependencies: runtime, authentication, tenant scoping. | get_runtime, authenticate, ws_authenticate, require_supervisor, require_admin, resolve_company, resolve_region |
| `wiot/api/eo.py` | 222 | Earth observation (R2.7): Copernicus catalogue, EUMETSAT Data Store and the open Sentinel-2 archive. | eo_status, scenes, eum_collections, eum_products, DownloadIn, eum_download, layers, RenderIn, render, render_script, availability, downloads |
| `wiot/api/farm.py` | 78 | Smart-agriculture endpoints: farm map, zones, weather/ET0, satellite readiness. | ZonePatch, overview, get_layout, put_layout, patch_zone, zone_history, weather, connectivity, public_map |
| `wiot/api/field.py` | 224 | Phone app and push alerts, commissioning, maintenance and the optional assistant (R2.6). | manifest, service_worker, SubscriptionIn, push_key, push_subscribe, push_unsubscribe, push_test, QrIn, RegisterIn, commission_parse, commission_register, commission_check, commission_clock, CompleteIn … |
| `wiot/api/notify.py` | 135 | Custom alert rules and notification channels (R2.3, point 22). | RuleIn, rule_catalog, list_rules, create_rule, update_rule, delete_rule, preview_rule, ChannelIn, list_channels, create_channel, update_channel, delete_channel, test_channel, channel_log |
| `wiot/api/operations.py` | 222 | Broker control, flash archive, analytics, logs and health endpoints. | BrokerIn, broker_status, broker_connect, broker_disconnect, flash_status, flash_nodes, flash_analysis, flash_lock, flash_records, PredictIn, analytics_index, analytics_live, model_schema, predict … |
| `wiot/api/org.py` | 385 | Organization API: companies, regions, nodes, gateways, API tokens, webhooks, world view. | CompanyBody, list_companies, create_company, update_company, RegionBody, list_regions, create_region, update_region, delete_region, NodeBody, CsvBody, list_nodes, create_node, update_node … |
| `wiot/api/reports.py` | 164 | Monthly reports, usage metering, integrations, data feeds and company logos (R2.3, points 23, 27-29). | monthly_report, report_archive, send_report, usage, IntegrationIn, list_integrations, create_integration, update_integration, delete_integration, test_integration, daily_feed, feed_metrics, company_logo |
| `wiot/api/satellite.py` | 113 | Satellite data: Sentinel-2 NDVI, pivot detection, WIOT-SAT products and passes (R2.5). | sat_status, ndvi, ndvi_refresh, field_image, pivots_detect, PivotsIn, pivots_add, passes, import_passes, products, import_product |
| `wiot/api/stream.py` | 59 | Live event stream (WebSocket). | stream |
| `wiot/api/system.py` | 49 | System health, maintenance, node health and the public status page (R2.2). | system_health, status_history, run_maintenance, nodes_health, public_status, status_page |
| `wiot/api/telemetry.py` | 137 | Fleet, node, message history, consumption and CSV export endpoints. | fleet, node_detail, node_series, messages, regions, consumption, export_csv |
| `wiot/api/water.py` | 172 | Irrigation planning and water accounts (R2.4). | catalog, fields, field_plan, ProfileIn, set_profile, TariffIn, tariffs, set_tariffs, costs, list_items, create_item, update_item, delete_item, schedule_log … |
| `wiot/app.py` | 154 | FastAPI application factory. | build_csp, tile_hosts, create_app |
| `wiot/config.py` | 218 | Typed runtime configuration loaded from environment variables and ``.env``. | Settings, get_settings |
| `wiot/domain/__init__.py` | 0 |  |  |
| `wiot/domain/command_queue.py` | 433 | Durable command intents, bounded mailbox and correlated execution audit. | ack_timeout_for, CommandConflict, flash_request_limit, CommandQueue |
| `wiot/domain/flash_analysis.py` | 196 | Analysis of a node's SPI-flash telemetry log, built from what the server already holds. | transfer_state, analyse |
| `wiot/domain/flash_archive.py` | 190 | Durable, tenant-scoped flash downloads; acknowledge only after SQLite commit. | FlashArchive |
| `wiot/logging_setup.py` | 53 | Structured logging with secret redaction and a rotating file sink. | redact, JsonFormatter, configure_logging |
| `wiot/protocol/__init__.py` | 0 |  |  |
| `wiot/protocol/flow_schema.py` | 197 | Flow-meter schema helpers shared by MQTT ingestion and tests. | flow_meter_name, period_source_name, period_quality_name, extract_flow_metadata, secondary_flow_reading, flow_reading_snapshot, select_measurement_timestamp, build_sample_fingerprint, calendar_period_rows, dashboard_flow_fields |
| `wiot/protocol/messages_pb2.py` | 0 | Generated protobuf module (from proto/messages.proto); do not edit. |  |
| `wiot/protocol/power.py` | 47 | Wire-level remote-wake validation and display metadata (no broker side effects). | validate_wake_seconds, power_metadata, power_dashboard_fields, is_confirmed_wake |
| `wiot/protocol/tenancy.py` | 75 | Stable, platform-independent tenant storage identities and legacy preflight. | storage_id, legacy_name, preflight, database_path |
| `wiot/protocol/topics.py` | 36 | Case-sensitive WIOT company/region topic contract; no legacy aliases. | region_id, command_topic, migrate_region_storage |
| `wiot/protocol/transport.py` | 504 | mqtt_impl.py ============ Annotated MQTT transport + AES-CBC/PKCS7 framing layer. | Counters, MqttNodeClient |
| `wiot/protocol/validation.py` | 102 | Fail-closed validation for the existing V1 wire/API contract (no schema change). | company_id, integer, parse_topic, validate_message |
| `wiot/security.py` | 180 | Authentication primitives: principals, password hashing, JWT and throttling. | AuthError, Principal, hash_password, verify_password, validate_new_password, issue_token, decode_token, LoginThrottle, seal, unseal |
| `wiot/services/__init__.py` | 0 |  |  |
| `wiot/services/agronomy.py` | 165 | Agronomy science for irrigation planning (R2.4): pure functions, no I/O. | Crop, crop_key, crop_stage, kc_curve, soil_water, salinity, deficit_factor, moisture_forecast, refill_plan |
| `wiot/services/alerts.py` | 282 | Fleet alert monitor: silent nodes, low batteries and implausible flow readings. | flow_jumps, flow_verdict, valve_flow_verdict, night_hours, in_night, AlertMonitor |
| `wiot/services/analytics.py` | 114 | Serves analysis artifacts, live KPIs and the command-delivery risk model. | AnalyticsService |
| `wiot/services/assistant.py` | 210 | Optional AI assistant (R2.6, point 31): answers fleet questions and writes a daily summary with Claude. | AssistantUnavailable, Assistant |
| `wiot/services/broker.py` | 127 | Single owner of the shared MQTT ingestion session. | BrokerParams, BrokerManager |
| `wiot/services/clocksync.py` | 114 | Automatic node clock synchronisation (R2.1, point 12). | ClockSync |
| `wiot/services/commands.py` | 303 | Operator command intents: validation, durable journal, publish and receipts. | CommandError, CommandRequest, CommandService |
| `wiot/services/commissioning.py` | 115 | Commissioning wizard (R2.6, point 25): QR scan -> register -> first uplink -> clock -> checks -> certificate. | parse_qr, Commissioning |
| `wiot/services/confwatch.py` | 102 | Configuration watch: desired versus reported node intervals (R2.2, point 15). | ConfigWatch |
| `wiot/services/cropcare.py` | 332 | Crop care and records (R2.5, points 44, 46, 48 and 50). | disease_risks, gdd, CropCare |
| `wiot/services/eo.py` | 571 | Earth-observation data access (R2.7): open Sentinel-2, the Copernicus catalogue and the EUMETSAT Data Store. | http_download, safe_name, utm_zone, utm_forward, utm_forward_np, Cog, polygon_mask, boa_offset, OpenSentinel2, browser_link, Catalogue, farm_bbox, utc_now, days_ago |
| `wiot/services/eo_layers.py` | 268 | Satellite layers for the Satellite viewer (R2.7): the Copernicus Browser's layers, rendered for any map view. | public_catalogue, custom_script, ramp_colors, render_numpy, bands_needed |
| `wiot/services/eo_render.py` | 492 | Satellite viewer (R2.7): render any layer for any map view, and list every dataset available over a farm. | ViewerInputError, NoImagery, Busy, QuotaExceeded, to_mercator, from_mercator_np, processing_units, covers, SatelliteViewer, browser_url |
| `wiot/services/farm.py` | 558 | Smart-agriculture layer: farm layout, weather/ET0, irrigation advisory, soil-moisture automation and satellite-backhaul readiness. | Site, Agronomy, Zone, Gateway, Device, FarmLayout, FarmStore, WeatherClient, FarmService |
| `wiot/services/ingest.py` | 366 | Decoded-MQTT ingestion: validate → persist → broadcast → release commands. | IngestService |
| `wiot/services/integrations.py` | 246 | Forward readings to other platforms (R2.3, point 29). | reading, azure_sas, IntegrationService |
| `wiot/services/maintenance.py` | 106 | Background maintenance (R2.2, point 10). | Maintenance |
| `wiot/services/maintenance_module.py` | 243 | Maintenance module (R2.6, point 26): assets, work orders, photos and calibration history. | MaintenanceModule |
| `wiot/services/metrics.py` | 37 | Prometheus metrics (scraped at ``/metrics``). |  |
| `wiot/services/nodehealth.py` | 134 | Per-node health scores (R2.2, point 16). | grade, NodeHealth |
| `wiot/services/notify.py` | 297 | Alert notifications and custom alert rules (R2.3, point 22). | http_request, node_tag, alert_text, Notifier, RuleEngine |
| `wiot/services/oidc.py` | 131 | OpenID Connect single sign-on (R2.3, point 21): authorization-code flow with PKCE. | OidcError, OidcClient, doc_issuer, username_for |
| `wiot/services/push.py` | 169 | Web Push for the installable dashboard (R2.6, point 24), with no third-party push library. | b64u, unb64u, encrypt, decrypt, PushService |
| `wiot/services/realtime.py` | 115 | Tenant-scoped WebSocket fan-out, safe to call from any thread. | Subscriber, RealtimeHub, LogBuffer |
| `wiot/services/regional.py` | 75 | Regional dashboards for ministries and water authorities (R2.5, point 62). | RegionalService |
| `wiot/services/reports.py` | 223 | Monthly operations report per company (R2.3, point 23): Excel (.xlsx), PDF and JSON. | month_bounds, previous_month, ReportService |
| `wiot/services/runtime.py` | 229 | Composition root: builds and owns every long-lived service. | Runtime |
| `wiot/services/satellite.py` | 455 | Satellite data (R2.5, points 49, 51 and 52). | http_raw, zone_geometry, field_share_of_bbox, bbox_of, detect_pivots, SatelliteService, b64png |
| `wiot/services/system.py` | 169 | System health, status history and the public status page (R2.2, points 7 and 8). | SystemService |
| `wiot/services/totp.py` | 45 | Time-based one-time passwords (RFC 6238 over RFC 4226 HOTP), standard library only. | new_secret, hotp, now_step, totp, verify, provisioning_uri |
| `wiot/services/usage.py` | 100 | Usage metering per company (R2.3, point 28) — the basis for service plans and billing. | UsageMeter |
| `wiot/services/water.py` | 581 | Irrigation planning and water accounts (R2.4, points 34-36, 38-43, 47). | WaterService, utc_day |
| `wiot/services/webhooks.py` | 124 | Outbound webhooks. | sign, check_destination, WebhookService |
| `wiot/sim/__init__.py` | 0 |  |  |
| `wiot/sim/bridge.py` | 98 | Two-way MQTT bridge between the local development broker and an upstream broker. | MqttBridge, parse_endpoint |
| `wiot/sim/devbroker.py` | 41 | Pure-Python MQTT broker for local development and demos (not for production). | main |
| `wiot/sim/fleet.py` | 304 | Encrypted WIOT fleet simulator for demos, load and end-to-end tests. | VirtualNode, FleetSimulator, agri_fleet, default_fleet, main |
| `wiot/storage/__init__.py` | 0 |  |  |
| `wiot/storage/alert_store.py` | 128 | Persistent fleet alerts: at most one open alert per (company, region, node, kind). | AlertStore |
| `wiot/storage/backup.py` | 167 | Consistent, optionally encrypted backups of every database, with verification and restore (R2.1, point 6). | database_files, create_backup, verify_backup, restore_backup |
| `wiot/storage/main_store.py` | 243 | Identity, tenant registry and audit trail (``iot_data.db``). | MainStore |
| `wiot/storage/notify_store.py` | 215 | Notification channels, their delivery log and custom alert rules (R2.3, point 22). Main database. | NotifyStore |
| `wiot/storage/org_store.py` | 582 | Organization registry: company profiles, regions, nodes, gateways, API tokens, webhooks. | sensors_from_mask, parse_sensors, check_timezone, check_country, check_point, check_logo, OrgStore |
| `wiot/storage/rollups.py` | 94 | Hourly and daily summaries of node readings, and raw-data retention (R2.2, point 10). | ensure_schema, update, series, apply_retention |
| `wiot/storage/security_store.py` | 229 | Sessions, two-factor enrolment, invitations and page permissions (R2.3, points 17 and 21). | SecurityStore |
| `wiot/storage/telemetry_store.py` | 531 | Per-tenant telemetry databases (``messages_dbs/<tenant>.db``). | decorate_row, TelemetryStore |
| `wiot/tools/__init__.py` | 0 |  |  |
| `wiot/tools/flash_timeline.py` | 137 | Flash-download diagnosis (R2.1, point 3): merge the server's records with the gateway's serial log. | parse_local, gateway_events, server_events, timeline, format_text |
| `wiot/tools/loadtest.py` | 157 | Load test: N simulated nodes against a throw-away server (R2.2, point 11). | Api, run, main |
| `wiot/tools/pdf.py` | 161 | Minimal PDF writer for reports (no third-party dependency). | text_width, Document |
| `wiot/tools/xlsx.py` | 134 | Minimal Office Open XML spreadsheet writer (no third-party dependency). | Sheet, Workbook |

## Web assets (`wiot/web`)

| File | Lines |
|---|---|
| `wiot/web/assets/api.js` | 128 |
| `wiot/web/assets/app.css` | 456 |
| `wiot/web/assets/app.js` | 287 |
| `wiot/web/assets/charts.js` | 330 |
| `wiot/web/assets/farm.css` | 208 |
| `wiot/web/assets/farmer.js` | 45 |
| `wiot/web/assets/favicon.svg` | 1 |
| `wiot/web/assets/forms.js` | 57 |
| `wiot/web/assets/global.css` | 228 |
| `wiot/web/assets/help-content.js` | 87 |
| `wiot/web/assets/i18n.js` | 1181 |
| `wiot/web/assets/invite.js` | 32 |
| `wiot/web/assets/login.js` | 65 |
| `wiot/web/assets/ops.css` | 219 |
| `wiot/web/assets/pages/admin.js` | 97 |
| `wiot/web/assets/pages/alerts.js` | 175 |
| `wiot/web/assets/pages/analytics.js` | 269 |
| `wiot/web/assets/pages/assistant.js` | 49 |
| `wiot/web/assets/pages/commands.js` | 157 |
| `wiot/web/assets/pages/commission.js` | 176 |
| `wiot/web/assets/pages/cropcare.js` | 139 |
| `wiot/web/assets/pages/farm.js` | 580 |
| `wiot/web/assets/pages/flash.js` | 331 |
| `wiot/web/assets/pages/health.js` | 72 |
| `wiot/web/assets/pages/help.js` | 98 |
| `wiot/web/assets/pages/history.js` | 57 |
| `wiot/web/assets/pages/integrations.js` | 100 |
| `wiot/web/assets/pages/maintenance.js` | 154 |
| `wiot/web/assets/pages/notify.js` | 186 |
| `wiot/web/assets/pages/org.js` | 422 |
| `wiot/web/assets/pages/overview.js` | 171 |
| `wiot/web/assets/pages/planning.js` | 210 |
| `wiot/web/assets/pages/regional.js` | 31 |
| `wiot/web/assets/pages/reports.js` | 80 |
| `wiot/web/assets/pages/satellite.js` | 188 |
| `wiot/web/assets/pages/satviewer.js` | 308 |
| `wiot/web/assets/pages/security.js` | 212 |
| `wiot/web/assets/pages/system.js` | 82 |
| `wiot/web/assets/pages/usage.js` | 42 |
| `wiot/web/assets/pages/wateraccounts.js` | 150 |
| `wiot/web/assets/pages/world.js` | 121 |
| `wiot/web/assets/status.js` | 26 |
| `wiot/web/assets/theme.js` | 14 |
| `wiot/web/assets/units.js` | 47 |
| `wiot/web/farmer.html` | 22 |
| `wiot/web/index.html` | 29 |
| `wiot/web/invite.html` | 31 |
| `wiot/web/login.html` | 36 |
| `wiot/web/status.html` | 22 |
| `wiot/web/sw.js` | 93 |

Vendored libraries in `wiot/web/assets/vendor/` (served locally, no CDN): leaflet.css, leaflet.js.
