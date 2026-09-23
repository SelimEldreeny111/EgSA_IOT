# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

WIOT (Water IoT) Server/Node platform. The repo contains three independent Python applications that share the same MQTT + AES + protobuf wire format:

1. **`server_web.py`** — Flask + Flask-SocketIO web dashboard (the primary "server"). Runs on `http://127.0.0.1:8000`.
2. **`server_gui.py`** — legacy Tkinter desktop dashboard (matplotlib charts). Same role as the web server but standalone.
3. **`main_gui.py`** — Tkinter desktop **node simulator** (acts as a device, publishes telemetry, can drive a real RS-485 flow meter via [rs485_tuf2000b.py](rs485_tuf2000b.py)).

All three talk to the same MQTT broker, share the same `.proto` definitions ([messages.proto](messages.proto) → [messages_pb2.py](messages_pb2.py)), and use the same encryption framing.

## Commands

```bash
pip install -r requirements.txt              # core deps (Flask, paho-mqtt, cryptography, protobuf, matplotlib)
pip install -r requirements_rs485.txt        # extra: pyserial for the simulator's RS-485 path

python server_web.py                         # web dashboard on :8000 (auto-creates iot_data.db, seeds admin/admin)
python server_gui.py                         # legacy desktop dashboard
python main_gui.py                           # node simulator GUI

python setup_admins.py                       # seed admin_1/Company_1 and admin_2/Company_2
python reset_users.py                        # wipe + reseed users
```

Regenerating protobuf bindings after editing [messages.proto](messages.proto):
```bash
protoc --python_out=. messages.proto
```

There is no test suite, no linter config, and no build step. [test.py](test.py) is a 5-line scratch file, not a test runner.

## Architecture

### Wire format (shared by all three apps)

MQTT payload layout, implemented in [mqtt_impl.py](mqtt_impl.py):

```
[1 byte code_version] [16 byte random IV] [AES-128-CBC( PKCS7( protobuf_bytes ) )]
```

Key/IV behavior comes from [node_config.json](node_config.json) (`encryption.key_hex`, `iv_mode: random_per_message_only`). The same key must be configured on every participating app/device. `MqttNodeClient` owns the paho client, the cipher, and exposes `publish_plaintext(topic, bytes)` / a plaintext callback for inbound — callers never see ciphertext.

### Topic convention

`EgSA/<Company>/<NodeID>/{Status|Telemetry|CMD}` plus a broadcast `EgSA/<Company>/BroadCast/CMD`. The web server validates that the `node_id` in the decoded protobuf matches the `<NodeID>` segment in the topic and drops mismatches — preserve this check when adding new message types.

### Message types ([messages.proto](messages.proto))

- `StatusMessage` — periodic flow/velocity readings + `node_status`
- `TelemetryMessage` — same fields plus `sampling_rate`, `Transmission_rate`, `active_sensor_count`
- `CMD_Message` — `cmd_id` + `cmd_data`. Command IDs are duplicated as a dict in **three** files ([command_impl.py](command_impl.py), [mqtt_impl.py](mqtt_impl.py), [server_web.py](server_web.py)) — keep them in sync:
  `1=SRATE, 2=STRAN, 3=STIME, 4=GOSTM, 5=VALVE` (0 reserved).

### Web server data model ([server_web.py](server_web.py))

SQLite (`iot_data.db`, created on first run by `init_db()`):
- `messages` — every decoded Status/Telemetry/Command row
- `users` — `username`, hashed `password`, `role`, `company`
- `companies`

`init_db()` performs idempotent `ALTER TABLE ... ADD COLUMN` migrations for `company` and `node_status` — when adding new columns, follow the same try/except pattern so existing databases upgrade in place.

### Multi-tenancy / auth model

- Roles: `admin` and regular user. Decorators `@login_required` and `@admin_required` in [server_web.py](server_web.py).
- Companies isolate data: non-admin queries are filtered by `session['company']` (see `/api/messages`, `/export_csv`).
- Special username `EgSA_Supervisor` bypasses company scoping in `can_manage_company()`.
- Default credentials seeded on first run: `admin / admin`. Flask `SECRET_KEY` is hardcoded — rotate before any non-local deployment.

### Realtime path

Decoded messages are both persisted via `save_message(...)` **and** pushed to browsers via `socketio.emit('iot_message', ...)`. Server logs go out on `socketio.emit('system_log', ...)`. When adding a new message type, mirror both sinks.

### Simulator ↔ real hardware

[main_gui.py](main_gui.py) can either generate synthetic flow data or read a real TUF-2000B ultrasonic flow meter over Modbus RTU via [rs485_tuf2000b.py](rs485_tuf2000b.py). Serial port / baud / register map live under `rs485.*` in [node_config.json](node_config.json).

## Conventions to preserve

- Command-ID dicts are duplicated across three modules — search-and-replace all of them together.
- Topic parsing assumes exactly `EgSA/<company>/<node_id>/<kind>`; preserve the topic-vs-payload `node_id` cross-check.
- Schema migrations live inline in `init_db()` as try/except `ALTER TABLE`; do not introduce a migrations framework for one-off column adds.
- The three apps are independent entry points, not a package — there is no shared `__init__.py` and no CLI multiplexer. Run each directly with `python <file>.py`.
