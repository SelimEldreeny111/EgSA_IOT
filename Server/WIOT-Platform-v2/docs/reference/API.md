# HTTP and WebSocket API

_Generated from the code by `docs/tools/gen_reference.py` on 2026-11-11. Do not edit by hand._

71 HTTP paths, 85 operations (HEAD excluded), 1 WebSocket route(s); OpenAPI documents 67 paths. Interactive docs: `/api/docs` on a running server.

**Dependencies** are the FastAPI dependency functions on each route; they carry authentication (`current_principal`), role checks (`require_*`, `can_*`) and CSRF checks. Read them in `wiot/api/deps.py`.

| Path | Method | Module | Handler | Dependencies | Description |
|---|---|---|---|---|---|
| `/` | GET | wiot.app | `root` |  |  |
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
| `/api/v2/audit` | GET | admin | `audit` | require_admin, authenticate |  |
| `/api/v2/auth/login` | POST | auth | `login` |  |  |
| `/api/v2/auth/logout` | POST | auth | `logout` |  |  |
| `/api/v2/auth/me` | GET | auth | `me` | authenticate |  |
| `/api/v2/auth/password` | POST | auth | `change_password` | authenticate |  |
| `/api/v2/broker` | GET | operations | `broker_status` | authenticate |  |
| `/api/v2/broker/connect` | POST | operations | `broker_connect` | require_supervisor, authenticate |  |
| `/api/v2/broker/disconnect` | POST | operations | `broker_disconnect` | require_supervisor, authenticate |  |
| `/api/v2/commands` | GET | commands | `list_commands` | authenticate |  |
| `/api/v2/commands` | POST | commands | `submit` | authenticate |  |
| `/api/v2/commands/catalog` | GET | commands | `catalog` | authenticate |  |
| `/api/v2/commands/risk` | POST | commands | `delivery_risk` | authenticate | Predict, before sending, whether the node will acknowledge this command. |
| `/api/v2/commands/{request_id}` | GET | commands | `get_command` | authenticate |  |
| `/api/v2/companies` | GET | admin | `list_companies` | authenticate |  |
| `/api/v2/companies` | POST | admin | `add_company` | require_supervisor, authenticate |  |
| `/api/v2/consumption` | GET | telemetry | `consumption` | authenticate |  |
| `/api/v2/export.csv` | GET | telemetry | `export_csv` | authenticate |  |
| `/api/v2/farm/connectivity` | GET | farm | `connectivity` | authenticate |  |
| `/api/v2/farm/layout` | GET | farm | `get_layout` | authenticate |  |
| `/api/v2/farm/layout` | PUT | farm | `put_layout` | authenticate |  |
| `/api/v2/farm/overview` | GET | farm | `overview` | authenticate |  |
| `/api/v2/farm/weather` | GET | farm | `weather` | authenticate |  |
| `/api/v2/farm/zones/{zone_id}` | PATCH | farm | `patch_zone` | authenticate |  |
| `/api/v2/farm/zones/{zone_id}/history` | GET | farm | `zone_history` | authenticate |  |
| `/api/v2/flash/analysis` | GET | operations | `flash_analysis` | authenticate | Memory health, retention projection, coverage, statistics and live-gap recovery. |
| `/api/v2/flash/lock` | GET | operations | `flash_lock` | authenticate | Whether a new flash command for this node would be refused now, and why. |
| `/api/v2/flash/nodes` | GET | operations | `flash_nodes` | authenticate | Nodes that have flash status, transfers or archived samples in this region. |
| `/api/v2/flash/records` | GET | operations | `flash_records` | authenticate |  |
| `/api/v2/flash/status` | GET | operations | `flash_status` | authenticate |  |
| `/api/v2/fleet` | GET | telemetry | `fleet` | authenticate |  |
| `/api/v2/messages` | GET | telemetry | `messages` | authenticate |  |
| `/api/v2/nodes/{node_id}` | GET | telemetry | `node_detail` | authenticate |  |
| `/api/v2/nodes/{node_id}/series` | GET | telemetry | `node_series` | authenticate |  |
| `/api/v2/org/companies` | GET | org | `list_companies` | authenticate |  |
| `/api/v2/org/companies` | POST | org | `create_company` | require_supervisor, authenticate |  |
| `/api/v2/org/companies/{name}` | PATCH | org | `update_company` | authenticate |  |
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
| `/api/v2/regions` | GET | telemetry | `regions` | authenticate |  |
| `/api/v2/system/info` | GET | operations | `system_info` | authenticate |  |
| `/api/v2/system/logs` | GET | operations | `system_logs` | authenticate |  |
| `/api/v2/system/logs/download` | GET | operations | `download_logs` | require_supervisor, authenticate |  |
| `/api/v2/users` | GET | admin | `list_users` | require_admin, authenticate |  |
| `/api/v2/users` | POST | admin | `create_user` | require_admin, authenticate |  |
| `/api/v2/users/{user_id}` | DELETE | admin | `delete_user` | require_admin, authenticate |  |
| `/favicon.svg` | GET | wiot.app | `favicon` |  |  |
| `/healthz` | GET | operations | `healthz` |  |  |
| `/login` | GET | wiot.app | `login_page` |  |  |
| `/metrics` | GET | operations | `metrics` |  |  |
| `/readyz` | GET | operations | `readyz` |  |  |

## WebSocket

| Path | Module | Handler |
|---|---|---|
| `/api/v2/ws` | wiot.api.stream | `stream` |
