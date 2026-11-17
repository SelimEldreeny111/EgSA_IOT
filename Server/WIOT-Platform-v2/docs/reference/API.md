# HTTP and WebSocket API

_Generated from the code by `docs/tools/gen_reference.py` on 2026-11-17. Do not edit by hand._

172 HTTP paths, 204 operations (HEAD excluded), 1 WebSocket route(s); OpenAPI documents 175 paths. Interactive docs: `/api/docs` on a running server.

**Dependencies** are the FastAPI dependency functions on each route; they carry authentication (`current_principal`), role checks (`require_*`, `can_*`) and CSRF checks. Read them in `wiot/api/deps.py`.

| Path | Method | Module | Handler | Dependencies | Description |
|---|---|---|---|---|---|
| `/` | GET | wiot.app | `root` |  |  |
| `/api/v2/alert-rules` | GET | notify | `list_rules` | authenticate |  |
| `/api/v2/alert-rules` | POST | notify | `create_rule` | authenticate |  |
| `/api/v2/alert-rules/catalog` | GET | notify | `rule_catalog` | authenticate |  |
| `/api/v2/alert-rules/preview` | POST | notify | `preview_rule` | authenticate | Which nodes would breach this rule with their latest readings (nothing is saved). |
| `/api/v2/alert-rules/{rule_id}` | DELETE | notify | `delete_rule` | authenticate |  |
| `/api/v2/alert-rules/{rule_id}` | PATCH | notify | `update_rule` | authenticate |  |
| `/api/v2/alerts` | GET | alerts | `list_alerts` | authenticate | Open alerts, or (``status=all``) everything open or changed in the last ``days``. |
| `/api/v2/alerts/{alert_id}/acknowledge` | POST | alerts | `acknowledge` | authenticate | Mark an open alert as seen. It stays open until its condition clears. |
| `/api/v2/analytics` | GET | operations | `analytics_index` | authenticate |  |
| `/api/v2/analytics/figures/{name}` | GET | operations | `analytics_figure` | authenticate |  |
| `/api/v2/analytics/live` | GET | operations | `analytics_live` | authenticate |  |
| `/api/v2/analytics/model/schema` | GET | operations | `model_schema` | authenticate |  |
| `/api/v2/analytics/predict` | POST | operations | `predict` | authenticate | What-if scoring: edit the model inputs and see delivery probability + SHAP drivers. |
| `/api/v2/analytics/report` | GET | operations | `analytics_report` | authenticate |  |
| `/api/v2/analytics/retrain` | POST | operations | `retrain` | require_supervisor, authenticate |  |
| `/api/v2/analytics/{name}` | GET | operations | `analytics_artifact` | authenticate |  |
| `/api/v2/assistant` | GET | field | `assistant_status` | authenticate |  |
| `/api/v2/assistant/ask` | POST | field | `assistant_ask` | authenticate |  |
| `/api/v2/audit` | GET | admin | `audit` | require_admin, authenticate | Audit trail with filters (actor, action, free text, time range) and CSV export. |
| `/api/v2/auth/invitations/accept` | POST | auth | `accept_invitation` |  |  |
| `/api/v2/auth/invitations/{token}` | GET | auth | `invitation_info` |  |  |
| `/api/v2/auth/login` | POST | auth | `login` |  |  |
| `/api/v2/auth/logout` | POST | auth | `logout` |  |  |
| `/api/v2/auth/me` | GET | auth | `me` | authenticate |  |
| `/api/v2/auth/oidc` | GET | auth | `oidc_info` |  |  |
| `/api/v2/auth/oidc/callback` | GET | auth | `oidc_callback` |  |  |
| `/api/v2/auth/oidc/login` | GET | auth | `oidc_login` |  |  |
| `/api/v2/auth/password` | POST | auth | `change_password` | authenticate |  |
| `/api/v2/auth/sessions` | GET | auth | `my_sessions` | authenticate |  |
| `/api/v2/auth/sessions/revoke-others` | POST | auth | `revoke_other_sessions` | authenticate |  |
| `/api/v2/auth/sessions/{jti}` | DELETE | auth | `revoke_my_session` | authenticate |  |
| `/api/v2/auth/totp` | GET | auth | `totp_status` | authenticate |  |
| `/api/v2/auth/totp/disable` | POST | auth | `totp_disable` | authenticate |  |
| `/api/v2/auth/totp/enable` | POST | auth | `totp_enable` | authenticate |  |
| `/api/v2/auth/totp/setup` | POST | auth | `totp_setup` | authenticate | Start enrolment: returns the secret (for manual entry) and the otpauth:// URI (for a QR code). |
| `/api/v2/broker` | GET | operations | `broker_status` | authenticate |  |
| `/api/v2/broker/connect` | POST | operations | `broker_connect` | require_supervisor, authenticate |  |
| `/api/v2/broker/disconnect` | POST | operations | `broker_disconnect` | require_supervisor, authenticate |  |
| `/api/v2/commands` | GET | commands | `list_commands` | authenticate |  |
| `/api/v2/commands` | POST | commands | `submit` | authenticate |  |
| `/api/v2/commands/catalog` | GET | commands | `catalog` | authenticate |  |
| `/api/v2/commands/risk` | POST | commands | `delivery_risk` | authenticate | Predict, before sending, whether the node will acknowledge this command. |
| `/api/v2/commands/{request_id}` | GET | commands | `get_command` | authenticate |  |
| `/api/v2/commission/check` | GET | field | `commission_check` | authenticate |  |
| `/api/v2/commission/clock` | POST | field | `commission_clock` | authenticate |  |
| `/api/v2/commission/complete` | POST | field | `commission_complete` | authenticate |  |
| `/api/v2/commission/parse` | POST | field | `commission_parse` | authenticate |  |
| `/api/v2/commission/register` | POST | field | `commission_register` | authenticate |  |
| `/api/v2/companies` | GET | admin | `list_companies` | authenticate |  |
| `/api/v2/companies` | POST | admin | `add_company` | require_supervisor, authenticate |  |
| `/api/v2/consumption` | GET | telemetry | `consumption` | authenticate |  |
| `/api/v2/crop/diary` | GET | crop | `diary` | authenticate |  |
| `/api/v2/crop/diary` | POST | crop | `add_diary` | authenticate |  |
| `/api/v2/crop/diary/{entry_id}` | DELETE | crop | `delete_diary` | authenticate |  |
| `/api/v2/crop/productivity` | GET | crop | `productivity` | authenticate |  |
| `/api/v2/crop/status` | GET | crop | `crop_status` | authenticate | Growing degree days since planting and disease / pest risk from the forecast, per field. |
| `/api/v2/crop/traceability` | GET | crop | `traceability` | authenticate | GlobalG.A.P.-style traceability record of one field and season (operations, sprays, PHI check). |
| `/api/v2/crop/wapor` | GET | crop | `wapor` | authenticate |  |
| `/api/v2/crop/wapor/import` | POST | crop | `wapor_import` | authenticate | CSV body: field,month,aeti_mm (monthly AETI exported from the FAO WaPOR portal). |
| `/api/v2/eo/availability` | GET | eo | `availability` | authenticate | Every satellite pass and product over the farm in the last ``days`` (30, 90, 180 or 365), plus what this |
| `/api/v2/eo/downloads` | GET | eo | `downloads` | authenticate |  |
| `/api/v2/eo/eumetsat/collections` | GET | eo | `eum_collections` | authenticate |  |
| `/api/v2/eo/eumetsat/download` | POST | eo | `eum_download` | authenticate | Download one product into data/eo/eumetsat (EUMETSAT API key on the server; administrators). |
| `/api/v2/eo/eumetsat/products` | GET | eo | `eum_products` | authenticate | Products of a Data Store collection over the farm in the last ``hours`` (search is public). |
| `/api/v2/eo/layers` | GET | eo | `layers` | authenticate | Missions and layers of the satellite viewer, which renderer draws them, and the farm's bounds. |
| `/api/v2/eo/render.png` | GET | eo | `render` | authenticate | One picture of a layer for the current map view (PNG with transparency outside the data). |
| `/api/v2/eo/render.png` | POST | eo | `render_script` | authenticate | Custom layer with your own Sentinel Hub evalscript (the supervisor only: it runs at Sentinel Hub on the |
| `/api/v2/eo/scenes` | GET | eo | `scenes` | authenticate | Copernicus Data Space products over the farm (public STAC catalogue), newest first. |
| `/api/v2/eo/status` | GET | eo | `eo_status` | authenticate |  |
| `/api/v2/export.csv` | GET | telemetry | `export_csv` | authenticate |  |
| `/api/v2/farm/connectivity` | GET | farm | `connectivity` | authenticate |  |
| `/api/v2/farm/layout` | GET | farm | `get_layout` | authenticate |  |
| `/api/v2/farm/layout` | PUT | farm | `put_layout` | authenticate |  |
| `/api/v2/farm/overview` | GET | farm | `overview` | authenticate |  |
| `/api/v2/farm/weather` | GET | farm | `weather` | authenticate |  |
| `/api/v2/farm/zones/{zone_id}` | PATCH | farm | `patch_zone` | authenticate |  |
| `/api/v2/farm/zones/{zone_id}/history` | GET | farm | `zone_history` | authenticate |  |
| `/api/v2/farmer/today` | GET | crop | `farmer_today` | authenticate |  |
| `/api/v2/feeds/daily.csv` | GET | reports | `daily_feed` | authenticate | One row per node and day (mean / min / max of each metric) from the summaries — for Power BI, Excel or |
| `/api/v2/feeds/metrics` | GET | reports | `feed_metrics` | authenticate |  |
| `/api/v2/flash/analysis` | GET | operations | `flash_analysis` | authenticate | Memory health, retention projection, coverage, statistics and live-gap recovery. |
| `/api/v2/flash/lock` | GET | operations | `flash_lock` | authenticate | Whether a new flash command for this node would be refused now, and why. |
| `/api/v2/flash/nodes` | GET | operations | `flash_nodes` | authenticate | Nodes that have flash status, transfers or archived samples in this region. |
| `/api/v2/flash/records` | GET | operations | `flash_records` | authenticate |  |
| `/api/v2/flash/status` | GET | operations | `flash_status` | authenticate |  |
| `/api/v2/fleet` | GET | telemetry | `fleet` | authenticate |  |
| `/api/v2/fleet/health` | GET | system | `nodes_health` | authenticate | Health score per node: battery trend, resets, regularity, store-and-forward, clock, commands, config. |
| `/api/v2/integrations` | GET | reports | `list_integrations` | authenticate |  |
| `/api/v2/integrations` | POST | reports | `create_integration` | authenticate |  |
| `/api/v2/integrations/{integration_id}` | DELETE | reports | `delete_integration` | authenticate |  |
| `/api/v2/integrations/{integration_id}` | PATCH | reports | `update_integration` | authenticate |  |
| `/api/v2/integrations/{integration_id}/test` | POST | reports | `test_integration` | authenticate |  |
| `/api/v2/invitations` | GET | admin | `list_invitations` | require_admin, authenticate |  |
| `/api/v2/invitations` | POST | admin | `create_invitation` | require_admin, authenticate |  |
| `/api/v2/invitations/{inv_id}` | DELETE | admin | `revoke_invitation` | require_admin, authenticate |  |
| `/api/v2/maintenance/assets` | GET | field | `assets` | authenticate |  |
| `/api/v2/maintenance/assets` | POST | field | `create_asset` | authenticate |  |
| `/api/v2/maintenance/assets/{asset_id}` | PATCH | field | `update_asset` | authenticate |  |
| `/api/v2/maintenance/assets/{asset_id}/calibrations` | POST | field | `add_calibration` | authenticate |  |
| `/api/v2/maintenance/orders` | GET | field | `orders` | authenticate |  |
| `/api/v2/maintenance/orders` | POST | field | `create_order` | authenticate |  |
| `/api/v2/maintenance/orders/{order_id}` | GET | field | `order` | authenticate |  |
| `/api/v2/maintenance/orders/{order_id}` | PATCH | field | `update_order` | authenticate |  |
| `/api/v2/maintenance/orders/{order_id}/photos` | POST | field | `add_photo` | authenticate |  |
| `/api/v2/maintenance/photos/{name}` | GET | field | `photo` | authenticate |  |
| `/api/v2/maintenance/records` | GET | field | `records` | authenticate |  |
| `/api/v2/messages` | GET | telemetry | `messages` | authenticate |  |
| `/api/v2/nodes/{node_id}` | GET | telemetry | `node_detail` | authenticate |  |
| `/api/v2/nodes/{node_id}/series` | GET | telemetry | `node_series` | authenticate |  |
| `/api/v2/notify/channels` | GET | notify | `list_channels` | authenticate |  |
| `/api/v2/notify/channels` | POST | notify | `create_channel` | authenticate |  |
| `/api/v2/notify/channels/{channel_id}` | DELETE | notify | `delete_channel` | authenticate |  |
| `/api/v2/notify/channels/{channel_id}` | PATCH | notify | `update_channel` | authenticate |  |
| `/api/v2/notify/channels/{channel_id}/log` | GET | notify | `channel_log` | authenticate |  |
| `/api/v2/notify/channels/{channel_id}/test` | POST | notify | `test_channel` | authenticate |  |
| `/api/v2/org/companies` | GET | org | `list_companies` | authenticate |  |
| `/api/v2/org/companies` | POST | org | `create_company` | require_supervisor, authenticate |  |
| `/api/v2/org/companies/{name}` | PATCH | org | `update_company` | authenticate |  |
| `/api/v2/org/companies/{name}/logo` | GET | reports | `company_logo` | authenticate |  |
| `/api/v2/org/gateways` | GET | org | `list_gateways` | authenticate |  |
| `/api/v2/org/gateways` | POST | org | `create_gateway` | authenticate |  |
| `/api/v2/org/gateways/{gw_id}` | DELETE | org | `delete_gateway` | authenticate |  |
| `/api/v2/org/gateways/{gw_id}` | PATCH | org | `update_gateway` | authenticate |  |
| `/api/v2/org/nodes` | GET | org | `list_nodes` | authenticate |  |
| `/api/v2/org/nodes` | POST | org | `create_node` | authenticate |  |
| `/api/v2/org/nodes/export.csv` | GET | org | `export_nodes` | authenticate |  |
| `/api/v2/org/nodes/import` | POST | org | `import_nodes` | authenticate |  |
| `/api/v2/org/nodes/{region}/{node_id}` | DELETE | org | `delete_node` | authenticate |  |
| `/api/v2/org/nodes/{region}/{node_id}` | PATCH | org | `update_node` | authenticate |  |
| `/api/v2/org/regions` | GET | org | `list_regions` | authenticate |  |
| `/api/v2/org/regions` | POST | org | `create_region` | authenticate |  |
| `/api/v2/org/regions/{region}` | DELETE | org | `delete_region` | authenticate |  |
| `/api/v2/org/regions/{region}` | PATCH | org | `update_region` | authenticate |  |
| `/api/v2/org/tokens` | GET | org | `list_tokens` | authenticate |  |
| `/api/v2/org/tokens` | POST | org | `create_token` | authenticate |  |
| `/api/v2/org/tokens/{token_id}` | DELETE | org | `revoke_token` | authenticate |  |
| `/api/v2/org/webhooks` | GET | org | `list_webhooks` | authenticate |  |
| `/api/v2/org/webhooks` | POST | org | `create_webhook` | authenticate |  |
| `/api/v2/org/webhooks/{hook_id}` | DELETE | org | `delete_webhook` | authenticate |  |
| `/api/v2/org/webhooks/{hook_id}` | PATCH | org | `update_webhook` | authenticate |  |
| `/api/v2/org/webhooks/{hook_id}/deliveries` | GET | org | `webhook_deliveries` | authenticate |  |
| `/api/v2/org/webhooks/{hook_id}/rotate` | POST | org | `rotate_webhook` | authenticate |  |
| `/api/v2/org/webhooks/{hook_id}/test` | POST | org | `test_webhook` | authenticate |  |
| `/api/v2/org/world` | GET | org | `world` | authenticate | Every readable company with its regions/sites, coordinates and live node counts. |
| `/api/v2/public/map` | GET | farm | `public_map` |  | Basemap + backdrop for the sign-in page (no tenant data). |
| `/api/v2/public/status` | GET | system | `public_status` | _public_enabled | Service availability only — no company names, node data or counts. |
| `/api/v2/push/key` | GET | field | `push_key` | authenticate |  |
| `/api/v2/push/subscribe` | POST | field | `push_subscribe` | authenticate |  |
| `/api/v2/push/test` | POST | field | `push_test` | authenticate |  |
| `/api/v2/push/unsubscribe` | POST | field | `push_unsubscribe` | authenticate |  |
| `/api/v2/regional` | GET | crop | `regional` | authenticate | Aggregated water use and crop health per area; no farm-level data (global readers only). |
| `/api/v2/regions` | GET | telemetry | `regions` | authenticate |  |
| `/api/v2/reports` | GET | reports | `report_archive` | authenticate |  |
| `/api/v2/reports/monthly` | GET | reports | `monthly_report` | authenticate |  |
| `/api/v2/reports/monthly/send` | POST | reports | `send_report` | authenticate | Build the report files now and send them to the company's report channels. |
| `/api/v2/satellite/image/{zone_id}.png` | GET | satellite | `field_image` | authenticate |  |
| `/api/v2/satellite/ndvi` | GET | satellite | `ndvi` | authenticate |  |
| `/api/v2/satellite/ndvi/refresh` | POST | satellite | `ndvi_refresh` | authenticate |  |
| `/api/v2/satellite/passes` | GET | satellite | `passes` | authenticate |  |
| `/api/v2/satellite/passes` | POST | satellite | `import_passes` | authenticate |  |
| `/api/v2/satellite/pivots/add` | POST | satellite | `pivots_add` | authenticate |  |
| `/api/v2/satellite/pivots/detect` | POST | satellite | `pivots_detect` | authenticate | Find centre pivots in an image (request body: PNG / JPEG covering the bounds) or in the Sentinel-2 image. |
| `/api/v2/satellite/products` | GET | satellite | `products` | authenticate |  |
| `/api/v2/satellite/products` | POST | satellite | `import_product` | authenticate | One WIOT-SAT ground-tool product (JSON): node readings received in a satellite pass. |
| `/api/v2/satellite/status` | GET | satellite | `sat_status` | authenticate |  |
| `/api/v2/sessions` | GET | admin | `list_sessions` | require_admin, authenticate |  |
| `/api/v2/sessions/{jti}` | DELETE | admin | `revoke_session` | require_admin, authenticate |  |
| `/api/v2/system/health` | GET | system | `system_health` | require_supervisor, authenticate | Supervisor view: broker, ingestion per company, disk, backups, databases and background threads. |
| `/api/v2/system/info` | GET | operations | `system_info` | authenticate |  |
| `/api/v2/system/logs` | GET | operations | `system_logs` | authenticate |  |
| `/api/v2/system/logs/download` | GET | operations | `download_logs` | require_supervisor, authenticate |  |
| `/api/v2/system/maintenance/run` | POST | system | `run_maintenance` | require_supervisor, authenticate | Fold new readings into the summaries now (retention runs on the daily cycle only). |
| `/api/v2/system/status-history` | GET | system | `status_history` | require_supervisor, authenticate |  |
| `/api/v2/usage` | GET | reports | `usage` | require_admin, authenticate | Daily and monthly usage per company: uplinks, bytes, commands, API calls, exports, active nodes, storage. |
| `/api/v2/users` | GET | admin | `list_users` | require_admin, authenticate |  |
| `/api/v2/users` | POST | admin | `create_user` | require_admin, authenticate |  |
| `/api/v2/users/{user_id}` | DELETE | admin | `delete_user` | require_admin, authenticate |  |
| `/api/v2/users/{user_id}/pages` | PUT | admin | `set_user_pages` | require_admin, authenticate | Limit which dashboard pages a user sees (null = every page of the role). |
| `/api/v2/users/{user_id}/totp/reset` | POST | admin | `reset_user_totp` | require_admin, authenticate | Turn off a user's two-factor sign-in (lost phone); they can enrol again after signing in. |
| `/api/v2/water/catalog` | GET | water | `catalog` | authenticate | Crops (FAO-56 / FAO-29), soil textures and deficit programmes. |
| `/api/v2/water/costs` | GET | water | `costs` | authenticate |  |
| `/api/v2/water/districts/{item_id}/balance` | GET | water | `district_balance` | authenticate | Monthly water balance of a district: system input, billed consumption, non-revenue water and the |
| `/api/v2/water/fields` | GET | water | `fields` | authenticate |  |
| `/api/v2/water/fields/{zone_id}` | GET | water | `field_plan` | authenticate |  |
| `/api/v2/water/fields/{zone_id}` | PUT | water | `set_profile` | authenticate |  |
| `/api/v2/water/schedules/run` | POST | water | `run_schedules_now` | authenticate | Run one scheduler tick now (normally every minute). |
| `/api/v2/water/schedules/{item_id}/log` | GET | water | `schedule_log` | authenticate |  |
| `/api/v2/water/tariffs` | GET | water | `tariffs` | authenticate |  |
| `/api/v2/water/tariffs` | PUT | water | `set_tariffs` | authenticate |  |
| `/api/v2/water/{kinds}` | GET | water | `list_items` | authenticate |  |
| `/api/v2/water/{kinds}` | POST | water | `create_item` | authenticate |  |
| `/api/v2/water/{kinds}/{item_id}` | DELETE | water | `delete_item` | authenticate |  |
| `/api/v2/water/{kinds}/{item_id}` | PATCH | water | `update_item` | authenticate |  |
| `/farmer` | GET | crop | `farmer_page` |  |  |
| `/favicon.svg` | GET | wiot.app | `favicon` |  |  |
| `/healthz` | GET | operations | `healthz` |  |  |
| `/invite` | GET | wiot.app | `invite_page` |  |  |
| `/login` | GET | wiot.app | `login_page` |  |  |
| `/manifest.webmanifest` | GET | field | `manifest` |  |  |
| `/metrics` | GET | operations | `metrics` |  |  |
| `/readyz` | GET | operations | `readyz` |  |  |
| `/status` | GET | system | `status_page` | _public_enabled |  |
| `/sw.js` | GET | field | `service_worker` |  |  |

## WebSocket

| Path | Module | Handler |
|---|---|---|
| `/api/v2/ws` | wiot.api.stream | `stream` |
