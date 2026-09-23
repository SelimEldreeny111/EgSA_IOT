# WIOT server flow-schema v2 guide

This server version accepts both STM32 product images:

- TUF + HNDA
- Supmea + Sondas

It also continues to decode previously deployed protobuf payloads because no
old field number was changed or reused.

## Deployment

1. Stop the running Python server.
2. Back up iot_data.db and the complete messages_dbs directory.
3. Install or verify dependencies with:

       python -m pip install -r requirements_web.txt

   The `tzdata` dependency supplies the Africa/Cairo calendar rules on hosts
   (notably Windows) that do not provide an IANA timezone database.

4. Keep messages.proto, sensor.proto, and messages_pb2.py from this same
   version together.
5. Start server_web.py normally.
6. Watch system.log for database errors.
7. Connect MQTT and send STIME to newly flashed nodes.

Each company database is migrated on first access. Existing messages are kept.
Old TUF rows are identified from sensor-mask bit 0 and marked legacy. They are
not assigned a fake trusted-RTC flag or fake cumulative totals.

## Incoming schema

The original HNDA fields remain:

| Protobuf field | Dashboard meaning |
|---|---|
| soil_temperature | HNDA temperature, degrees C |
| soil_moisture | HNDA moisture, percent |
| soil_moisture_temp_valid | Latest HNDA Modbus read succeeded |

The original Sondas fields remain:

| Protobuf field | Dashboard meaning |
|---|---|
| ec_temperature | Sondas temperature, degrees C |
| ec_moisture | Sondas moisture, percent |
| electrical_conductivity | Sondas EC value |
| soil_moisture_temp_ec_valid | Latest Sondas Modbus read succeeded |

The appended flow fields identify TUF or Supmea, calculation source, live and
period validity, RTC trust, cumulative litres, period quality, and alarms.

## Stored tables

messages is the complete received-message audit history. meter_samples is a
flow-focused history with an idempotency fingerprint, so an MQTT QoS retry or
duplicate LoRa forward does not create two raw meter samples.

consumption_periods stores one current snapshot for each node, sensor,
period type, and period key. A newer snapshot replaces an older snapshot; an
out-of-order older packet cannot roll a period backward.

Server receipt time is always retained. Node time is used as measured_at only
when the node explicitly reports rtc_valid and its epoch passes plausibility
checks. This distinction is visible through time_source.

## Dashboard interpretation

Flow is m3/h. Today, Month, and Year are consumption volumes in m3.

The Flow Meter Status card shows:

- Meter: TUF or Supmea
- Period source: Meter native or Node RTC calculated
- Quality: Valid, Partial, Estimated, Counter reset, Anomaly, or Time uncertain
- RTC: Trusted or Not trusted

For Supmea, Forward, Reverse, and Net display cumulative meter totals in m3.
TUF does not expose these through the current driver, so they display as
unavailable.

Never infer validity from a nonzero number. Zero flow and zero consumption are
valid. Use Flow Live Valid, Period Totals Valid, HNDA Valid, and Sondas Valid.

## Consumption API

Authenticated requests may use:

    GET /api/consumption
    GET /api/consumption?period=day
    GET /api/consumption?node_id=1
    GET /api/consumption?node_id=1&sensor_id=1&period=month

The response contains company and rows. Each row includes period_type,
period_key, volume_liters, volume_m3, meter/source/quality codes, readable
names, and measured/update times.

## Database checks

Example SQLite checks:

    SELECT node_id, flow_meter_type, flow_live_valid,
           flow_period_totals_valid, rtc_valid
    FROM messages
    ORDER BY id DESC LIMIT 10;

    SELECT node_id, measured_at, flow_rate,
           forward_total_liters, period_quality
    FROM meter_samples
    ORDER BY id DESC LIMIT 10;

    SELECT node_id, period_type, period_key, volume_liters,
           source, quality
    FROM consumption_periods
    ORDER BY period_key DESC;

## Automated verification

From this server directory:

    python -m py_compile server_web.py flow_schema.py protobuf_impl.py messages_pb2.py
    python -m unittest discover -s tests -v
    node --check static/js/app.js

The tests verify protobuf field-number stability, HNDA and Sondas round trips,
legacy TUF inference, Cairo calendar keys, safe handling of missing timezone
data and invalid numbers, database migration, deterministic latest/history
selection, sample deduplication, and period upserts.

## Recovery

If startup migration reports an error, stop the server and restore the database
backup before investigating. Do not manually delete the messages table.
Schema creation is additive and idempotent, so a normal restart is safe after
the underlying issue is corrected.
