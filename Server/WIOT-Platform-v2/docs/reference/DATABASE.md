# Databases

_Generated from the code by `docs/tools/gen_reference.py` on 2026-11-11. Do not edit by hand._

Schemas read (read-only) from the live databases in `data/`. One `messages_dbs/<Company>.db` per tenant has the same schema; one is shown. No data values are included.

## `iot_data.db`

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

### `farm_layouts`

| Column | Type | Not null | Default | PK |
|---|---|---|---|---|
| `company` | TEXT |  |  | 1 |
| `layout` | TEXT | yes |  |  |
| `updated_at` | INTEGER | yes |  |  |
| `updated_by` | TEXT | yes |  |  |

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

Indexes: `CREATE INDEX idx_region_messages ON messages(region,node_id,id)`; `CREATE INDEX idx_v2_messages_time ON messages(region, timestamp)`; `CREATE INDEX idx_v2_messages_node_time ON messages(region, node_id, type, timestamp)`

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
