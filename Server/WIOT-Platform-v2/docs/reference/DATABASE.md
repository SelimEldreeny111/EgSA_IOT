# Databases

_Generated from the code by `docs/tools/gen_reference.py` on 2026-11-13. Do not edit by hand._

Schemas read (read-only) from the live databases in `data/`. One `messages_dbs/<Company>.db` per tenant has the same schema; one is shown. No data values are included.

## `iot_data.db`

### `alert_rules`

| Column | Type | Not null | Default | PK |
|---|---|---|---|---|
| `id` | INTEGER |  |  | 1 |
| `company` | TEXT | yes |  |  |
| `name` | TEXT | yes |  |  |
| `region` | TEXT |  |  |  |
| `nodes` | TEXT |  |  |  |
| `metric` | TEXT | yes |  |  |
| `op` | TEXT | yes |  |  |
| `value` | REAL | yes |  |  |
| `duration_s` | INTEGER | yes | 0 |  |
| `severity` | TEXT | yes | 'warning' |  |
| `enabled` | INTEGER | yes | 1 |  |
| `created_by` | TEXT |  |  |  |
| `created_at` | INTEGER | yes |  |  |
| `updated_at` | INTEGER | yes |  |  |

### `alerts`

| Column | Type | Not null | Default | PK |
|---|---|---|---|---|
| `id` | INTEGER |  |  | 1 |
| `company` | TEXT | yes |  |  |
| `region` | TEXT | yes |  |  |
| `node_id` | INTEGER | yes |  |  |
| `kind` | TEXT | yes |  |  |
| `severity` | TEXT | yes |  |  |
| `state` | TEXT | yes | 'open' |  |
| `opened_at` | INTEGER | yes |  |  |
| `updated_at` | INTEGER | yes |  |  |
| `resolved_at` | INTEGER |  |  |  |
| `acknowledged_by` | TEXT |  |  |  |
| `acknowledged_at` | INTEGER |  |  |  |
| `details` | TEXT | yes | '{}' |  |

Indexes: `CREATE UNIQUE INDEX alerts_one_open                     ON alerts(company, region, node_id, kind) WHERE state='open'`; `CREATE INDEX alerts_by_company ON alerts(company, state, opened_at DESC)`

### `api_tokens`

| Column | Type | Not null | Default | PK |
|---|---|---|---|---|
| `id` | INTEGER |  |  | 1 |
| `company` | TEXT | yes |  |  |
| `name` | TEXT | yes |  |  |
| `token_hash` | TEXT | yes |  |  |
| `prefix` | TEXT | yes |  |  |
| `scope` | TEXT | yes |  |  |
| `created_by` | TEXT | yes |  |  |
| `created_at` | INTEGER | yes |  |  |
| `expires_at` | INTEGER |  |  |  |
| `last_used_at` | INTEGER |  |  |  |
| `revoked_at` | INTEGER |  |  |  |

### `assistant_log`

| Column | Type | Not null | Default | PK |
|---|---|---|---|---|
| `id` | INTEGER |  |  | 1 |
| `company` | TEXT | yes |  |  |
| `kind` | TEXT | yes |  |  |
| `user_id` | INTEGER |  |  |  |
| `question` | TEXT | yes |  |  |
| `answer` | TEXT |  |  |  |
| `tools` | TEXT |  |  |  |
| `input_tokens` | INTEGER |  |  |  |
| `output_tokens` | INTEGER |  |  |  |
| `ts` | INTEGER | yes |  |  |

### `audit_log`

| Column | Type | Not null | Default | PK |
|---|---|---|---|---|
| `id` | INTEGER |  |  | 1 |
| `ts` | INTEGER | yes |  |  |
| `actor` | TEXT | yes |  |  |
| `action` | TEXT | yes |  |  |
| `company` | TEXT |  |  |  |
| `target` | TEXT |  |  |  |
| `ip` | TEXT |  |  |  |
| `details` | TEXT |  |  |  |

Indexes: `CREATE INDEX idx_audit_ts ON audit_log(ts DESC)`

### `companies`

| Column | Type | Not null | Default | PK |
|---|---|---|---|---|
| `id` | INTEGER |  |  | 1 |
| `name` | TEXT |  |  |  |
| `created_at` | TEXT |  |  |  |
| `display_name` | TEXT |  |  |  |
| `country` | TEXT |  |  |  |
| `timezone` | TEXT |  |  |  |
| `units` | TEXT |  |  |  |
| `language` | TEXT |  |  |  |
| `lat` | REAL |  |  |  |
| `lon` | REAL |  |  |  |
| `notes` | TEXT |  |  |  |
| `active` | INTEGER | yes | 1 |  |
| `strict_nodes` | INTEGER | yes | 0 |  |
| `updated_at` | INTEGER |  |  |  |
| `retention_days` | INTEGER |  |  |  |
| `brand_name` | TEXT |  |  |  |
| `brand_color` | TEXT |  |  |  |
| `brand_logo` | TEXT |  |  |  |

### `crop_diary`

| Column | Type | Not null | Default | PK |
|---|---|---|---|---|
| `id` | INTEGER |  |  | 1 |
| `company` | TEXT | yes |  |  |
| `zone_id` | TEXT | yes |  |  |
| `date` | TEXT | yes |  |  |
| `type` | TEXT | yes |  |  |
| `data` | TEXT | yes | '{}' |  |
| `operator` | TEXT |  |  |  |
| `created_by` | TEXT | yes |  |  |
| `created_at` | INTEGER | yes |  |  |

Indexes: `CREATE INDEX crop_diary_by_zone ON crop_diary(company, zone_id, date)`

### `crop_wapor`

| Column | Type | Not null | Default | PK |
|---|---|---|---|---|
| `company` | TEXT | yes |  | 1 |
| `zone_id` | TEXT | yes |  | 2 |
| `month` | TEXT | yes |  | 3 |
| `aeti_mm` | REAL | yes |  |  |
| `source` | TEXT | yes |  |  |

### `crop_weather`

| Column | Type | Not null | Default | PK |
|---|---|---|---|---|
| `company` | TEXT | yes |  | 1 |
| `date` | TEXT | yes |  | 2 |
| `tmax` | REAL |  |  |  |
| `tmin` | REAL |  |  |  |
| `rain_mm` | REAL |  |  |  |
| `et0_mm` | REAL |  |  |  |

### `farm_layouts`

| Column | Type | Not null | Default | PK |
|---|---|---|---|---|
| `company` | TEXT |  |  | 1 |
| `layout` | TEXT | yes |  |  |
| `updated_at` | INTEGER | yes |  |  |
| `updated_by` | TEXT | yes |  |  |

### `integrations`

| Column | Type | Not null | Default | PK |
|---|---|---|---|---|
| `id` | INTEGER |  |  | 1 |
| `company` | TEXT | yes |  |  |
| `kind` | TEXT | yes |  |  |
| `name` | TEXT | yes |  |  |
| `config` | TEXT | yes | '{}' |  |
| `secrets` | TEXT |  |  |  |
| `enabled` | INTEGER | yes | 1 |  |
| `created_at` | INTEGER | yes |  |  |
| `updated_at` | INTEGER | yes |  |  |
| `sent` | INTEGER | yes | 0 |  |
| `failed` | INTEGER | yes | 0 |  |
| `dropped` | INTEGER | yes | 0 |  |
| `last_ok_at` | INTEGER |  |  |  |
| `last_error` | TEXT |  |  |  |
| `last_error_at` | INTEGER |  |  |  |

### `invitations`

| Column | Type | Not null | Default | PK |
|---|---|---|---|---|
| `id` | INTEGER |  |  | 1 |
| `token_hash` | TEXT | yes |  |  |
| `email` | TEXT | yes |  |  |
| `role` | TEXT | yes |  |  |
| `company` | TEXT | yes |  |  |
| `pages` | TEXT |  |  |  |
| `invited_by` | TEXT | yes |  |  |
| `created_at` | INTEGER | yes |  |  |
| `expires_at` | INTEGER | yes |  |  |
| `accepted_at` | INTEGER |  |  |  |
| `accepted_username` | TEXT |  |  |  |
| `revoked_at` | INTEGER |  |  |  |

### `mnt_assets`

| Column | Type | Not null | Default | PK |
|---|---|---|---|---|
| `id` | INTEGER |  |  | 1 |
| `company` | TEXT | yes |  |  |
| `kind` | TEXT | yes |  |  |
| `name` | TEXT | yes |  |  |
| `region` | TEXT |  |  |  |
| `node_id` | INTEGER |  |  |  |
| `serial` | TEXT |  |  |  |
| `model` | TEXT |  |  |  |
| `installed` | TEXT |  |  |  |
| `notes` | TEXT |  |  |  |
| `created_at` | INTEGER | yes |  |  |
| `updated_at` | INTEGER | yes |  |  |

Indexes: `CREATE UNIQUE INDEX mnt_assets_node ON mnt_assets(company, region, node_id) WHERE node_id IS NOT NULL`

### `mnt_events`

| Column | Type | Not null | Default | PK |
|---|---|---|---|---|
| `id` | INTEGER |  |  | 1 |
| `order_id` | INTEGER | yes |  |  |
| `ts` | INTEGER | yes |  |  |
| `actor` | TEXT | yes |  |  |
| `kind` | TEXT | yes |  |  |
| `text` | TEXT |  |  |  |
| `photo` | TEXT |  |  |  |

### `mnt_orders`

| Column | Type | Not null | Default | PK |
|---|---|---|---|---|
| `id` | INTEGER |  |  | 1 |
| `company` | TEXT | yes |  |  |
| `asset_id` | INTEGER |  |  |  |
| `alert_id` | INTEGER |  |  |  |
| `title` | TEXT | yes |  |  |
| `description` | TEXT |  |  |  |
| `priority` | TEXT | yes |  |  |
| `status` | TEXT | yes |  |  |
| `assignee` | TEXT |  |  |  |
| `due` | TEXT |  |  |  |
| `created_by` | TEXT | yes |  |  |
| `created_at` | INTEGER | yes |  |  |
| `updated_at` | INTEGER | yes |  |  |
| `closed_at` | INTEGER |  |  |  |
| `closure` | TEXT |  |  |  |

Indexes: `CREATE INDEX mnt_orders_by_status ON mnt_orders(company, status)`

### `mnt_records`

| Column | Type | Not null | Default | PK |
|---|---|---|---|---|
| `id` | INTEGER |  |  | 1 |
| `company` | TEXT | yes |  |  |
| `asset_id` | INTEGER | yes |  |  |
| `kind` | TEXT | yes |  |  |
| `date` | TEXT | yes |  |  |
| `data` | TEXT | yes |  |  |
| `next_due` | TEXT |  |  |  |
| `created_by` | TEXT | yes |  |  |
| `created_at` | INTEGER | yes |  |  |

Indexes: `CREATE INDEX mnt_records_by_asset ON mnt_records(company, asset_id, date)`

### `notify_channels`

| Column | Type | Not null | Default | PK |
|---|---|---|---|---|
| `id` | INTEGER |  |  | 1 |
| `company` | TEXT | yes |  |  |
| `name` | TEXT | yes |  |  |
| `kind` | TEXT | yes |  |  |
| `config` | TEXT | yes | '{}' |  |
| `secrets` | TEXT |  |  |  |
| `min_severity` | TEXT | yes | 'warning' |  |
| `events` | TEXT | yes | '["alert"]' |  |
| `enabled` | INTEGER | yes | 1 |  |
| `created_at` | INTEGER | yes |  |  |
| `updated_at` | INTEGER | yes |  |  |
| `last_ok` | INTEGER |  |  |  |
| `last_at` | INTEGER |  |  |  |
| `last_error` | TEXT |  |  |  |

### `notify_log`

| Column | Type | Not null | Default | PK |
|---|---|---|---|---|
| `id` | INTEGER |  |  | 1 |
| `channel_id` | INTEGER | yes |  |  |
| `ts` | INTEGER | yes |  |  |
| `event` | TEXT | yes |  |  |
| `ok` | INTEGER | yes |  |  |
| `detail` | TEXT |  |  |  |

Indexes: `CREATE INDEX notify_log_by_channel ON notify_log(channel_id, id DESC)`

### `org_gateways`

| Column | Type | Not null | Default | PK |
|---|---|---|---|---|
| `company` | TEXT | yes |  | 1 |
| `gw_id` | TEXT | yes |  | 2 |
| `name` | TEXT |  |  |  |
| `region` | TEXT |  |  |  |
| `lat` | REAL |  |  |  |
| `lon` | REAL |  |  |  |
| `backhaul` | TEXT |  |  |  |
| `primary_link` | TEXT |  |  |  |
| `notes` | TEXT |  |  |  |
| `created_at` | INTEGER | yes |  |  |
| `updated_at` | INTEGER | yes |  |  |

### `org_nodes`

| Column | Type | Not null | Default | PK |
|---|---|---|---|---|
| `company` | TEXT | yes |  | 1 |
| `region` | TEXT | yes |  | 2 |
| `node_id` | INTEGER | yes |  | 3 |
| `name` | TEXT |  |  |  |
| `kind` | TEXT |  |  |  |
| `lat` | REAL |  |  |  |
| `lon` | REAL |  |  |  |
| `gateway` | TEXT |  |  |  |
| `install_date` | TEXT |  |  |  |
| `report_interval_s` | INTEGER |  |  |  |
| `notes` | TEXT |  |  |  |
| `created_at` | INTEGER | yes |  |  |
| `updated_at` | INTEGER | yes |  |  |
| `node_type` | TEXT |  |  |  |
| `sensors` | TEXT |  |  |  |

### `org_regions`

| Column | Type | Not null | Default | PK |
|---|---|---|---|---|
| `company` | TEXT | yes |  | 1 |
| `region` | TEXT | yes |  | 2 |
| `display_name` | TEXT |  |  |  |
| `country` | TEXT |  |  |  |
| `timezone` | TEXT |  |  |  |
| `lat` | REAL |  |  |  |
| `lon` | REAL |  |  |  |
| `notes` | TEXT |  |  |  |
| `created_at` | INTEGER | yes |  |  |
| `updated_at` | INTEGER | yes |  |  |

### `push_subscriptions`

| Column | Type | Not null | Default | PK |
|---|---|---|---|---|
| `endpoint` | TEXT |  |  | 1 |
| `user_id` | INTEGER | yes |  |  |
| `p256dh` | TEXT | yes |  |  |
| `auth` | TEXT | yes |  |  |
| `user_agent` | TEXT |  |  |  |
| `created_at` | INTEGER | yes |  |  |
| `last_ok_at` | INTEGER |  |  |  |
| `failures` | INTEGER | yes | 0 |  |

### `sat_ndvi`

| Column | Type | Not null | Default | PK |
|---|---|---|---|---|
| `company` | TEXT | yes |  | 1 |
| `zone_id` | TEXT | yes |  | 2 |
| `date` | TEXT | yes |  | 3 |
| `mean` | REAL |  |  |  |
| `min` | REAL |  |  |  |
| `max` | REAL |  |  |  |
| `clear_share` | REAL |  |  |  |
| `source` | TEXT | yes |  | 4 |

### `sat_passes`

| Column | Type | Not null | Default | PK |
|---|---|---|---|---|
| `id` | INTEGER |  |  | 1 |
| `satellite` | TEXT | yes |  |  |
| `station` | TEXT |  |  |  |
| `aos` | INTEGER | yes |  |  |
| `los` | INTEGER | yes |  |  |
| `max_elevation` | REAL |  |  |  |

### `sat_products`

| Column | Type | Not null | Default | PK |
|---|---|---|---|---|
| `pass_id` | TEXT |  |  | 1 |
| `satellite` | TEXT | yes |  |  |
| `received_at` | INTEGER | yes |  |  |
| `imported_at` | INTEGER | yes |  |  |
| `records` | INTEGER | yes |  |  |
| `stored` | INTEGER | yes |  |  |
| `rejected` | INTEGER | yes |  |  |
| `companies` | TEXT | yes |  |  |

### `sessions`

| Column | Type | Not null | Default | PK |
|---|---|---|---|---|
| `jti` | TEXT |  |  | 1 |
| `user_id` | INTEGER | yes |  |  |
| `username` | TEXT | yes |  |  |
| `created_at` | INTEGER | yes |  |  |
| `expires_at` | INTEGER | yes |  |  |
| `last_seen_at` | INTEGER | yes |  |  |
| `ip` | TEXT |  |  |  |
| `user_agent` | TEXT |  |  |  |
| `method` | TEXT | yes | 'password' |  |
| `revoked_at` | INTEGER |  |  |  |
| `revoked_by` | TEXT |  |  |  |

Indexes: `CREATE INDEX sessions_by_user ON sessions(user_id, expires_at)`

### `status_history`

| Column | Type | Not null | Default | PK |
|---|---|---|---|---|
| `ts` | INTEGER |  |  | 1 |
| `broker` | INTEGER | yes |  |  |
| `ingest` | INTEGER | yes |  |  |
| `overall` | TEXT | yes |  |  |

### `usage_daily`

| Column | Type | Not null | Default | PK |
|---|---|---|---|---|
| `company` | TEXT | yes |  | 1 |
| `day` | TEXT | yes |  | 2 |
| `messages` | INTEGER | yes | 0 |  |
| `bytes` | INTEGER | yes | 0 |  |
| `commands` | INTEGER | yes | 0 |  |
| `api_calls` | INTEGER | yes | 0 |  |
| `exports` | INTEGER | yes | 0 |  |
| `nodes_active` | INTEGER | yes | 0 |  |
| `storage_bytes` | INTEGER | yes | 0 |  |

### `usage_meta`

| Column | Type | Not null | Default | PK |
|---|---|---|---|---|
| `key` | TEXT |  |  | 1 |
| `value` | TEXT |  |  |  |

### `users`

| Column | Type | Not null | Default | PK |
|---|---|---|---|---|
| `id` | INTEGER |  |  | 1 |
| `username` | TEXT |  |  |  |
| `password` | TEXT |  |  |  |
| `role` | TEXT |  |  |  |
| `company` | TEXT |  | 'Company_1' |  |
| `token_version` | INTEGER | yes | 0 |  |
| `created_at` | INTEGER |  |  |  |
| `last_login_at` | INTEGER |  |  |  |
| `disabled` | INTEGER | yes | 0 |  |
| `totp_secret` | TEXT |  |  |  |
| `totp_enabled` | INTEGER | yes | 0 |  |
| `totp_last_step` | INTEGER |  |  |  |
| `recovery_codes` | TEXT |  |  |  |
| `pages` | TEXT |  |  |  |
| `email` | TEXT |  |  |  |
| `sso_subject` | TEXT |  |  |  |

### `water_items`

| Column | Type | Not null | Default | PK |
|---|---|---|---|---|
| `id` | INTEGER |  |  | 1 |
| `company` | TEXT | yes |  |  |
| `kind` | TEXT | yes |  |  |
| `data` | TEXT | yes |  |  |
| `state` | TEXT | yes | '{}' |  |
| `enabled` | INTEGER | yes | 1 |  |
| `created_at` | INTEGER | yes |  |  |
| `updated_at` | INTEGER | yes |  |  |
| `updated_by` | TEXT |  |  |  |

Indexes: `CREATE INDEX water_items_by_kind ON water_items(company, kind)`

### `water_log`

| Column | Type | Not null | Default | PK |
|---|---|---|---|---|
| `id` | INTEGER |  |  | 1 |
| `company` | TEXT | yes |  |  |
| `item_id` | INTEGER |  |  |  |
| `ts` | INTEGER | yes |  |  |
| `action` | TEXT | yes |  |  |
| `detail` | TEXT |  |  |  |

Indexes: `CREATE INDEX water_log_by_item ON water_log(company, item_id, id DESC)`

### `water_profiles`

| Column | Type | Not null | Default | PK |
|---|---|---|---|---|
| `company` | TEXT | yes |  | 1 |
| `zone_id` | TEXT | yes |  | 2 |
| `data` | TEXT | yes |  |  |
| `updated_at` | INTEGER | yes |  |  |
| `updated_by` | TEXT |  |  |  |

### `water_settings`

| Column | Type | Not null | Default | PK |
|---|---|---|---|---|
| `company` | TEXT |  |  | 1 |
| `data` | TEXT | yes |  |  |
| `updated_at` | INTEGER | yes |  |  |

### `webhooks`

| Column | Type | Not null | Default | PK |
|---|---|---|---|---|
| `id` | INTEGER |  |  | 1 |
| `company` | TEXT | yes |  |  |
| `name` | TEXT | yes |  |  |
| `url` | TEXT | yes |  |  |
| `secret` | TEXT | yes |  |  |
| `events` | TEXT | yes |  |  |
| `active` | INTEGER | yes | 1 |  |
| `created_by` | TEXT | yes |  |  |
| `created_at` | INTEGER | yes |  |  |
| `last_delivery_at` | INTEGER |  |  |  |
| `last_status` | INTEGER |  |  |  |
| `last_error` | TEXT |  |  |  |
| `deliveries` | INTEGER | yes | 0 |  |
| `failures` | INTEGER | yes | 0 |  |

## `command_lifecycle.db`

### `command_attempts`

| Column | Type | Not null | Default | PK |
|---|---|---|---|---|
| `request_id` | INTEGER | yes |  | 1 |
| `attempt` | INTEGER | yes |  | 2 |
| `submitted_at` | INTEGER | yes |  |  |
| `broker_confirmed_at` | INTEGER |  |  |  |
| `mqtt_mid` | INTEGER |  |  |  |

### `command_events`

| Column | Type | Not null | Default | PK |
|---|---|---|---|---|
| `id` | INTEGER |  |  | 1 |
| `request_id` | INTEGER | yes |  |  |
| `event` | TEXT | yes |  |  |
| `timestamp` | INTEGER | yes |  |  |
| `details` | TEXT | yes |  |  |

### `command_metadata`

| Column | Type | Not null | Default | PK |
|---|---|---|---|---|
| `name` | TEXT |  |  | 1 |
| `value` | TEXT | yes |  |  |

### `command_receipts`

| Column | Type | Not null | Default | PK |
|---|---|---|---|---|
| `request_id` | INTEGER | yes |  | 1 |
| `node_id` | INTEGER | yes |  | 2 |
| `cmd_id` | INTEGER | yes |  |  |
| `success` | INTEGER | yes |  |  |
| `received_at` | INTEGER | yes |  |  |
| `late` | INTEGER | yes |  |  |

### `pending_commands`

| Column | Type | Not null | Default | PK |
|---|---|---|---|---|
| `id` | INTEGER |  |  | 1 |
| `request_id` | INTEGER | yes |  |  |
| `company` | TEXT | yes |  |  |
| `node_id` | INTEGER | yes |  |  |
| `cmd_id` | INTEGER | yes |  |  |
| `cmd_type` | TEXT | yes |  |  |
| `cmd_data` | INTEGER | yes |  |  |
| `actor` | TEXT | yes | '' |  |
| `delivery` | TEXT | yes |  |  |
| `broadcast` | INTEGER | yes | 0 |  |
| `created_at` | INTEGER | yes |  |  |
| `expires_at` | INTEGER | yes |  |  |
| `next_attempt_at` | INTEGER | yes |  |  |
| `attempts` | INTEGER | yes | 0 |  |
| `state` | TEXT | yes | 'pending' |  |
| `reason` | TEXT | yes | '' |  |
| `submitted_at` | INTEGER |  |  |  |
| `broker_confirmed_at` | INTEGER |  |  |  |
| `ack_deadline` | INTEGER |  |  |  |
| `acknowledged_at` | INTEGER |  |  |  |
| `superseded_by` | INTEGER |  |  |  |
| `outcome_uncertain` | INTEGER | yes | 0 |  |
| `region` | TEXT | yes | 'Region_1' |  |

Indexes: `CREATE INDEX pending_by_node                     ON pending_commands(company,node_id,state,expires_at)`; `CREATE INDEX command_active_by_state                     ON pending_commands(state,expires_at,ack_deadline)`; `CREATE INDEX command_timeline_by_company                     ON pending_commands(company,id DESC)`; `CREATE INDEX command_region_scope ON pending_commands(company,region,node_id,state)`

## `flash_archive.db`

### `flash_records`

| Column | Type | Not null | Default | PK |
|---|---|---|---|---|
| `company` | TEXT |  |  | 1 |
| `region` | TEXT |  |  | 2 |
| `node` | INTEGER |  |  | 3 |
| `generation` | INTEGER |  |  | 4 |
| `sequence` | INTEGER |  |  | 5 |
| `epoch` | INTEGER |  |  |  |
| `day` | INTEGER |  |  |  |
| `sample` | BLOB |  |  |  |
| `data` | TEXT |  |  |  |

### `flash_status`

| Column | Type | Not null | Default | PK |
|---|---|---|---|---|
| `company` | TEXT |  |  | 1 |
| `region` | TEXT |  |  | 2 |
| `node` | INTEGER |  |  | 3 |
| `received` | INTEGER |  |  |  |
| `info` | TEXT |  |  |  |

### `flash_transfer_rows`

| Column | Type | Not null | Default | PK |
|---|---|---|---|---|
| `company` | TEXT |  |  | 1 |
| `region` | TEXT |  |  | 2 |
| `node` | INTEGER |  |  | 3 |
| `request` | INTEGER |  |  | 4 |
| `idx` | INTEGER |  |  | 5 |
| `sequence` | INTEGER |  |  |  |

### `flash_transfers`

| Column | Type | Not null | Default | PK |
|---|---|---|---|---|
| `company` | TEXT |  |  | 1 |
| `region` | TEXT |  |  | 2 |
| `node` | INTEGER |  |  | 3 |
| `request` | INTEGER |  |  | 4 |
| `generation` | INTEGER |  |  |  |
| `total` | INTEGER |  |  |  |
| `received` | INTEGER |  |  |  |
| `phase` | INTEGER |  |  |  |
| `result` | INTEGER |  |  |  |
| `complete` | INTEGER |  |  |  |
| `updated` | INTEGER |  |  |  |

## `pending_commands.db`

### `pending_commands`

| Column | Type | Not null | Default | PK |
|---|---|---|---|---|
| `request_id` | INTEGER |  |  | 1 |
| `company` | TEXT | yes |  |  |
| `node_id` | INTEGER | yes |  |  |
| `cmd_id` | INTEGER | yes |  |  |
| `cmd_type` | TEXT | yes |  |  |
| `cmd_data` | INTEGER | yes |  |  |
| `created_at` | INTEGER | yes |  |  |
| `expires_at` | INTEGER | yes |  |  |
| `next_attempt_at` | INTEGER | yes |  |  |
| `attempts` | INTEGER | yes | 0 |  |
| `state` | TEXT | yes | 'pending' |  |
| `acknowledged_at` | INTEGER |  |  |  |

Indexes: `CREATE INDEX pending_by_node                 ON pending_commands(company, node_id, state, expires_at)`

## `messages_dbs/<Company>.db`

### `consumption_periods`

| Column | Type | Not null | Default | PK |
|---|---|---|---|---|
| `id` | INTEGER |  |  | 1 |
| `node_id` | INTEGER | yes |  |  |
| `sensor_id` | TEXT | yes |  |  |
| `flow_meter_type` | INTEGER | yes |  |  |
| `period_type` | TEXT | yes |  |  |
| `period_key` | TEXT | yes |  |  |
| `volume_liters` | INTEGER | yes |  |  |
| `source` | INTEGER | yes |  |  |
| `quality` | INTEGER | yes |  |  |
| `measured_at` | INTEGER | yes |  |  |
| `updated_at` | INTEGER | yes |  |  |
| `region` | TEXT | yes | 'Region_1' |  |

Indexes: `CREATE INDEX idx_region_periods ON consumption_periods(region,node_id,sensor_id,period_type,period_key)`; `CREATE INDEX idx_consumption_periods_lookup                  ON consumption_periods(node_id, sensor_id, period_type, period_key)`

### `messages`

| Column | Type | Not null | Default | PK |
|---|---|---|---|---|
| `id` | INTEGER |  |  | 1 |
| `timestamp` | INTEGER |  |  |  |
| `type` | TEXT |  |  |  |
| `node_id` | INTEGER |  |  |  |
| `sensor_id` | TEXT |  |  |  |
| `flow` | REAL |  |  |  |
| `velocity` | REAL |  |  |  |
| `flow_day` | REAL |  |  |  |
| `flow_month` | REAL |  |  |  |
| `flow_year` | REAL |  |  |  |
| `details` | TEXT |  |  |  |
| `company` | TEXT |  |  |  |
| `node_status` | INTEGER |  | 0 |  |
| `soil_temperature` | REAL |  |  |  |
| `soil_moisture` | REAL |  |  |  |
| `soil_moisture_temp_valid` | INTEGER |  |  |  |
| `ec_temperature` | REAL |  |  |  |
| `ec_moisture` | REAL |  |  |  |
| `electrical_conductivity` | REAL |  |  |  |
| `soil_moisture_temp_ec_valid` | INTEGER |  |  |  |
| `active_sensor_count` | INTEGER |  |  |  |
| `sensor_mask` | INTEGER |  |  |  |
| `battery_voltage` | REAL |  |  |  |
| `measured_at` | INTEGER |  |  |  |
| `time_source` | TEXT |  |  |  |
| `flow_meter_type` | INTEGER |  | 0 |  |
| `flow_period_source` | INTEGER |  | 0 |  |
| `flow_live_valid` | INTEGER |  | 0 |  |
| `flow_period_totals_valid` | INTEGER |  | 0 |  |
| `flow_cumulative_totals_valid` | INTEGER |  | 0 |  |
| `rtc_valid` | INTEGER |  | 0 |  |
| `forward_total_liters` | INTEGER |  | 0 |  |
| `reverse_total_liters` | INTEGER |  | 0 |  |
| `net_total_liters` | INTEGER |  | 0 |  |
| `flow_period_quality` | INTEGER |  | 0 |  |
| `flow_meter_alarm_flags` | INTEGER |  | 0 |  |
| `legacy_flow_schema` | INTEGER |  | 0 |  |
| `secondary_flow_json` | TEXT |  |  |  |
| `power_mode` | INTEGER |  | 0 |  |
| `power_state` | INTEGER |  | 0 |  |
| `wake_remaining_seconds` | INTEGER |  | 0 |  |
| `wake_command_ack` | INTEGER |  | 0 |  |
| `wake_request_id` | INTEGER |  | 0 |  |
| `wdt_reset_count` | INTEGER |  | 0 |  |
| `power_reset_count` | INTEGER |  | 0 |  |
| `region` | TEXT | yes | 'Region_1' |  |
| `sampling_rate_s` | INTEGER |  | 0 |  |
| `transmission_rate_s` | INTEGER |  | 0 |  |

Indexes: `CREATE INDEX idx_region_messages ON messages(region,node_id,id)`; `CREATE INDEX idx_v2_messages_time ON messages(region, timestamp)`; `CREATE INDEX idx_v2_messages_node_time ON messages(region, node_id, type, timestamp)`; `CREATE INDEX idx_v2_messages_node_measured ON messages(region, node_id, measured_at)`

### `meter_samples`

| Column | Type | Not null | Default | PK |
|---|---|---|---|---|
| `id` | INTEGER |  |  | 1 |
| `received_at` | INTEGER | yes |  |  |
| `measured_at` | INTEGER | yes |  |  |
| `time_source` | TEXT | yes |  |  |
| `message_type` | TEXT | yes |  |  |
| `node_id` | INTEGER | yes |  |  |
| `sensor_id` | TEXT | yes |  |  |
| `flow_meter_type` | INTEGER | yes |  |  |
| `flow_rate` | REAL |  |  |  |
| `velocity` | REAL |  |  |  |
| `volume_day` | REAL |  |  |  |
| `volume_month` | REAL |  |  |  |
| `volume_year` | REAL |  |  |  |
| `forward_total_liters` | INTEGER |  |  |  |
| `reverse_total_liters` | INTEGER |  |  |  |
| `net_total_liters` | INTEGER |  |  |  |
| `flow_live_valid` | INTEGER | yes |  |  |
| `period_totals_valid` | INTEGER | yes |  |  |
| `cumulative_totals_valid` | INTEGER | yes |  |  |
| `rtc_valid` | INTEGER | yes |  |  |
| `period_source` | INTEGER | yes |  |  |
| `period_quality` | INTEGER | yes |  |  |
| `alarm_flags` | INTEGER | yes |  |  |
| `sample_fingerprint` | TEXT | yes |  |  |
| `region` | TEXT | yes | 'Region_1' |  |

Indexes: `CREATE INDEX idx_meter_samples_node_time                  ON meter_samples(node_id, sensor_id, measured_at)`

### `rollup_state`

| Column | Type | Not null | Default | PK |
|---|---|---|---|---|
| `key` | TEXT |  |  | 1 |
| `value` | INTEGER | yes |  |  |

### `rollups`

| Column | Type | Not null | Default | PK |
|---|---|---|---|---|
| `grain` | TEXT | yes |  | 1 |
| `region` | TEXT | yes |  | 2 |
| `node_id` | INTEGER | yes |  | 3 |
| `metric` | TEXT | yes |  | 4 |
| `t` | INTEGER | yes |  | 5 |
| `n` | INTEGER | yes |  |  |
| `avg` | REAL |  |  |  |
| `lo` | REAL |  |  |  |
| `hi` | REAL |  |  |  |
