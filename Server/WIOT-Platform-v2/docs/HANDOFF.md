# WIOT Platform v2 — hand-over for the next agent

**Date:** 11 November 2026 · **Version:** 2.0.0 (`wiot/__init__.py`) · **Owner:** EgSA R&D IoT team
(lead researcher Selim Eldreeny; supervisor Dr. Haitham Akah).

This is the entry point. Read §1 before touching anything. The other documents:

| Document | What it gives you |
|---|---|
| `docs/CHANGELOG.md` | Everything done on the server, by date |
| `README.md` | Feature guide: quick start, CLI, configuration, security, Flash data, farm, organization, alerts, operations |
| `docs/reference/API.md` | Every HTTP route: method, module, handler, dependencies, description (85 operations) |
| `docs/reference/CONFIG.md` | Every `WIOT_*` setting with type and default |
| `docs/reference/CLI.md` | Every `python -m wiot` command and option |
| `docs/reference/DATABASE.md` | Schema of every SQLite database |
| `docs/reference/MODULES.md` | Code map: every module with its purpose and public names; web assets |
| `docs/reference/TESTS.md` | Every test file and test |
| `docs/reference/EVENTS.md` | Realtime hub events and Prometheus metrics |
| `Documentation/ServerSoftware/` (project root) | User Manual, System Analysis & Design, Test Report (Word/PDF, 9 Nov 2026 — before the Phase 0 changes) |
| `Documentation/Flowcharts/` (project root) | Flowcharts; F31–F41 are the server |
| `data/analytics/REPORT.md` | Data-analysis report (8 Nov 2026) |

Regenerate the reference files after any change: `.venv\Scripts\python docs\tools\gen_reference.py`.

## 1. Rules — read first

1. **Secrets.** `.env` holds the live AES-128 key (it must equal `WIOT_AES_KEY_BYTES` in the node firmware's
   `AppSecrets.h`) and the account passwords. Never print, log, copy, commit or quote them. Check for a value without
   showing it (for example print only its length). Screenshot scripts read credentials through
   `Video/tools/capture.py` (`creds()`, `new_context()`).
2. **Real nodes.** Company_1 / Region_1 nodes 1–3 are real hardware; node 2 is the live LORA_WOR_STOP test node.
   Send them no command (including flash downloads) unless the user asks. The user operates the Flash page and the
   Command center at the same time, and extra downlinks collide on the LoRa channel.
3. **Git.** Commit or push only when the user asks; push only the server branch with an explicit refspec. The
   repository `SelimEldreeny111/EgSA_IOT` is **public**: scan for secrets before every push (§4).
4. **Do not modify** the v1.31 server (`Server/WIOT-Server-Web v1.31 - Fixed Sensor Readings in Dashboard`) or the
   uncommitted changes in the old clone `D:\WorkSpace\EgSA\R&D_WS\IOT\IOT\WIOT`.
5. **Field compatibility.** The nodes and gateways in the field must keep working without re-flashing: do not change
   topics, the AES frame, `proto/messages.proto` field numbers or command IDs unless a firmware change is agreed.
6. **One worker.** MQTT ingestion has exactly one owner; never run the server with more than one worker or process
   against the same `data/`.
7. **Downloads.** Installing packages or downloading files needs the user's permission.
8. **UI quality bar.** The user expects enterprise-SaaS polish, especially in the Day view. Reuse the existing CSS
   tokens (`app.css`, `global.css`), add Arabic strings for every new text (`i18n.js`), and check Night, Day and
   Arabic (right-to-left) before calling a UI change done.
9. **Windows environment.** The path contains `&` (`R&D_WS`): npm `.cmd` shims fail, call `node …/cli.js` directly;
   set `PYTHONIOENCODING=utf-8` for non-ASCII console output; in Bash, do not `rm` paths held in variables (use
   literal paths).

## 2. What the server is

WIOT Platform v2 is the ingestion, control and analytics server of the EgSA WIOT water and smart-irrigation IoT
system. STM32 sensor nodes (flow meters TUF-2000B and Supmea SUP-FMC240, soil probes HNDA and Sondas, a latching valve)
report over 433 MHz LoRa to an STM32 gateway, or directly over Wi-Fi / GSM, as AES-128-CBC encrypted protobuf messages
on MQTT. The server:

- ingests and validates every frame and stores it per company (tenant) in SQLite;
- serves the **Control Center** web UI (10 pages) and a REST + WebSocket API;
- sends commands through a durable journal that separates broker receipt, radio delivery and node execution, with
  *next wake* delivery for sleeping nodes;
- downloads and analyses the nodes' 24-hour SPI-flash journal;
- raises persistent fleet alerts; gives irrigation advice and valve automation; checks satellite-backhaul readiness;
- runs a data-analysis and machine-learning pipeline (command-delivery risk model).

## 3. Where things are

| Item | Path |
|---|---|
| **Development copy (edit here)** | `D:\WorkSpace\EgSA\R&D_WS\IOT\WIOT Server\WIOT_Final_PowerModes_20261001\Server\WIOT-Platform-v2` |
| Git worktree (commit here) | `D:\WorkSpace\EgSA\R&D_WS\IOT\IOT\WIOT_server_v2_20261109\Server\WIOT-Platform-v2`, branch `feature/2026-11-09-server-v2` |
| Remote | `https://github.com/SelimEldreeny111/EgSA_IOT` (public), last pushed commit `356e60c`, CI passed |
| CI workflow | `.github/workflows/server-v2-tests.yml` at the repository root (also in the final-copy root) |
| Python environment | `.venv\` in the development copy (Python 3.14 on this PC; the Docker image uses 3.12) |
| Runtime data (never committed) | `data\` — databases, `logs\`, `analytics\` |
| Node firmware (for protocol facts) | `WIOT_Final_PowerModes_20261001\Node\IoT_Node_Encrypted` (`src/config/AppConfig.*`, `proto/sensor.proto`) |
| v1.31 server (read-only) | `WIOT_Final_PowerModes_20261001\Server\WIOT-Server-Web v1.31 - Fixed Sensor Readings in Dashboard` |
| Screenshots | `docs\screenshots\` (night, day, global, flash); capture scripts in `WIOT_Final_PowerModes_20261001\Video\` |

The development copy is **not** a git checkout. Workflow: edit and test in the development copy → mirror into the
worktree → commit there (§4).

## 4. Run, test, commit

**Run (local demo with the real gateway bridged):**

```powershell
cd "D:\WorkSpace\EgSA\R&D_WS\IOT\WIOT Server\WIOT_Final_PowerModes_20261001\Server\WIOT-Platform-v2"
powershell -ExecutionPolicy Bypass -File .\run-dev.ps1        # broker + bridge + server + simulator
```

or the three processes separately (what the previous agent ran in the background):

```powershell
.\.venv\Scripts\python -m wiot devbroker --port 1883 --bridge broker.hivemq.com:1883 --bridge-topic "wiot/Company_1/#"
.\.venv\Scripts\python -m wiot serve
.\.venv\Scripts\python -m wiot simulate --host 127.0.0.1 --port 1883 --companies Demo_Utility,Demo_AgriFarm --report-seconds 5
```

Open <http://127.0.0.1:8000>. Accounts and passwords are in `.env` (do not print them). Check `GET /readyz`.
The real gateway publishes to `broker.hivemq.com`; without the bridge the server sees only the simulator.

**Tenants in `data/`:** `Company_1` (real nodes 1–3 at the EgSA site, live via the bridge, plus imported v1.31 data),
`Company_2` (imported v1.31 field data), `Demo_Utility` and `Demo_AgriFarm` (simulator; the farm has six East Owainat
pivots).

**Test:** `.\.venv\Scripts\python -m pytest` → 119 tests and 13 subtests pass (about 64 s). The analytics timing test
can fail on a cold start because importing scikit-learn takes long; re-run it.

**Mirror into the worktree (PowerShell):**

```powershell
$src = 'D:\WorkSpace\EgSA\R&D_WS\IOT\WIOT Server\WIOT_Final_PowerModes_20261001\Server\WIOT-Platform-v2'
$dst = 'D:\WorkSpace\EgSA\R&D_WS\IOT\IOT\WIOT_server_v2_20261109\Server\WIOT-Platform-v2'
robocopy $src $dst /MIR /XD "$src\.venv" "$src\data" .pytest_cache __pycache__ wiot_platform.egg-info /XF .env *.pyc WIOT_Control_Center_screenshots.zip /NFL /NDL /NJH /NP
New-Item -ItemType Directory -Force "$dst\data" | Out-Null; Copy-Item "$src\data\.gitkeep" "$dst\data\.gitkeep"
```

Then `git status` in the worktree, commit with a conventional message (`feat(server): …`, `fix(server): …`,
`docs(server): …`).

**Before any push (only when the user asks):** confirm that no `.env`, no database and no file containing the live
key or a password is staged — compare against the values in `.env` without printing them; then
`git push -u origin feature/2026-11-09-server-v2:feature/2026-11-09-server-v2`. Do not push other branches.

## 5. Architecture

```
MQTT broker ──► protocol/transport.py (paho, SUBACK-gated readiness, PUBACK tracking)
                   │ frame bytes + topic
                   ▼
            services/ingest.py ── protocol/{topics,tenancy,validation,power,flow_schema}.py, messages_pb2
                   │ validated message
     ┌─────────────┼───────────────────────┬─────────────────────┐
     ▼             ▼                       ▼                     ▼
storage/telemetry_store  domain/command_queue (ACK match)  domain/flash_archive   services/realtime (hub)
 (per-tenant DB)         services/commands                 (history rows → ACK)    ├─► WebSocket /api/v2/ws
                         services/farm (automation)                                └─► services/webhooks
services/alerts (thread, every 60 s) ──► storage/alert_store ──► hub
api/* (FastAPI routers, deps.py = auth/roles/CSRF) ──► services ──► storage
web/ (index.html + ES modules, no build step, no CDN)
```

- **`services/runtime.py`** builds every service once (`Runtime`), starts them in `startup()` (MQTT autoconnect,
  alert monitor, webhooks) and stops them in `shutdown()`; `app.state.runtime` gives routes access.
- **Threads:** paho network loop and a publish-completion worker (`transport.py`), `alert-monitor`, `webhook-0..n`.
  Request handlers run in FastAPI's thread pool; the realtime hub hands events to the asyncio loop.
- **Storage:** SQLite in WAL mode. `iot_data.db` = accounts, companies, audit, farm layouts, organization registry,
  API tokens, webhooks, alerts. `messages_dbs/<Company>.db` = one telemetry database per tenant (uplinks, meter
  samples, consumption periods). `command_lifecycle.db` = command journal. `flash_archive.db` = flash transfers and
  rows. `pending_commands.db` = legacy v1 queue (import and analytics only).
- **Security:** `security.py` (JWT, scrypt, CSRF, tokens), `api/deps.py` (`authenticate`, `require_*`, principal with
  company scope and `can_write`), CSP and headers in `app.py`.

## 6. Domain facts an agent needs

**Wire protocol.** Topics `wiot/<company>/<region>/<node>/status|data` (uplink), `…/<node>/cmd` (downlink),
`wiot/<company>/<region>/broadcast`. Frame `[0x01][16-byte IV][AES-128-CBC, PKCS#7]`, one shared key, no
authentication tag. Protobuf `proto/messages.proto` = node `sensor.proto` byte for byte (nanopb 0.4.9.1 on the
node); regenerate `wiot/protocol/messages_pb2.py` only from that file. Ingest rejects frames whose payload node ID
differs from the topic, non-finite floats, out-of-range enums and unknown tenants (and, with strict provisioning,
unregistered nodes). Meter samples are deduplicated by fingerprint.

**Commands** (`services/commands.py`, `domain/command_queue.py`). IDs: 1 SRATE, 2 STRAN, 3 STIME, 4 GOSTM, 5 VALVE,
6 WAKE, 7 CLEAR_POWER_RESETS, 8 CLEAR_WDT_RESETS, 9 CLEAR_FLASH, 10 FLASH_STATUS, 11 FLASH_LAST, 12 FLASH_TODAY,
13 FLASH_CANCEL, 14 HISTORY_ACK (sent by the server only). States: `pending → dispatched → acknowledged`, or
`rejected`, `outcome_unknown` (no reply in 30 s; a late reply still completes it), `waiting_retry` (SRATE/STRAN only,
3 attempts, 15 s), `superseded`, `broadcast_partial`, `expired` (TTL default 24 h, max 7 days). At most 32 active
per node. Delivery *now* or *next wake* (released on the node's next uplink). PUBACK = broker receipt only; only the
node's reply with the request ID proves execution. Valve commands to a registered *monitoring* node → 409.
STIME carries the server epoch at dispatch.

**Flash journal** (`domain/flash_archive.py`, `domain/flash_analysis.py`). Node log: 14,322 records, 24-hour
generations. Download = phases 1 (count), 2 (rows), 3 (end + result code). The server stores each row in one
transaction, then sends `HISTORY_ACK` with `(phase << 32) | index`. Flash request IDs stay below
`flash_request_limit(node_id)` so the ACK is one 33-byte frame. **Flash lock:** one flash conversation per node;
other flash commands → 409 while a transfer runs (idle limit 360 s) or a flash command awaits its reply;
`FLASH_CANCEL` always allowed (`GET /api/v2/flash/lock`).

**Alerts** (`services/alerts.py`, `storage/alert_store.py`). `node_offline` (critical, 6 × median interval),
`low_battery` (< 3.3 V, clears at ≥ 3.4 V), `flow_unstable` (constants at the top of `alerts.py`). One open alert per
node and kind; hub events `alert` with `alert_kind` / `state`; resolution events `node_online`, `<kind>_resolved`.

**Farm** (`services/farm.py`, `api/farm.py`, `web/assets/pages/farm.js`). Layout per company (JSON, validated;
format `wiot/data/demo_farm_layout.json`). Deficit D = (θ_target − θ)/100 × Z_r (Z_r default 300 mm), run time
D / application rate, ETc = Kc · ET₀ (Open-Meteo). Automation: hysteresis on each fresh Status, minimum interval
`WIOT_AUTOMATION_MIN_INTERVAL_S` (120 s), always through the command journal. Satellite budget
`WIOT_SATELLITE_MSGS_PER_DAY` (48).

**Organization** (`storage/org_store.py`, `api/org.py`). Company and region IDs are part of the topic and cannot be
renamed (display names can). Node types *monitoring* / *control*; sensors from `sensor_mask` (1 TUF, 2 HNDA, 4 Sondas,
8 Supmea). API tokens `wiot_…` (company-scoped; never manage users, tokens or webhooks). Webhooks: HMAC-SHA256
`X-WIOT-Signature`, retries after 0, 2 and 8 s, private destinations refused outside development.

**Analytics** (`wiot/analytics/*`, `services/analytics.py`). `python -m wiot analyze` → `data/analytics/` (JSON
artifacts, `figures/`, `model.joblib`, `REPORT.md`). Risk model: 21 features computed *as of* submission
(`riskmodel.py`; same code for training and live scoring), temporal hold-out, tiers, SHAP. Figures use a dark theme
(`figures.py`).

**Simulator and broker** (`wiot/sim/`). `fleet.py` = encrypted virtual nodes that follow power modes, ACK only while
awake, survive broker outages. `devbroker.py` = amqtt broker; `bridge.py` = two-way topic bridge to an upstream broker
with echo suppression.

**Web UI** (`wiot/web/`). Hash routes: `farm` (landing), `world`, `overview`, `alerts`, `commands` (Operations);
`analytics`, `history`, `flash` (Insights); `org`, `admin` (Settings). One ES module per page in `assets/pages/`;
shared code in `app.js`, `api.js` (fetch, icons), `charts.js`, `theme.js` (Night/Day), `units.js`, `i18n.js` (DOM
translator: English source strings mapped to Arabic, plus patterns for dynamic text). Strict CSP: no inline script,
no CDN — vendored libraries are in `assets/vendor/`.

## 7. Configuration essentials

All settings are `WIOT_*` environment variables (`docs/reference/CONFIG.md`). The ones that matter in practice:
`WIOT_MQTT_HOST` / `PORT` / `AUTOCONNECT` (127.0.0.1 with the dev broker; the field uses `broker.hivemq.com`),
`WIOT_MQTT_AES_KEY_HEX` (= firmware key), `WIOT_SECRET_KEY` (session signing; set it or sessions reset at restart),
`WIOT_ENV=production` (enforces a strong secret), `WIOT_COOKIE_SECURE=true` behind HTTPS, `WIOT_DATA_DIR`,
`WIOT_ALERT_MONITOR`, `WIOT_WEATHER_ENABLED`, `WIOT_MAP_TILE_URL` (default Esri World Imagery — check its terms for
production and publications).

## 8. Current state (11 November 2026)

- Code: branch at `356e60c`, identical to the development copy apart from this documentation (`docs/HANDOFF.md`,
  `docs/CHANGELOG.md`, `docs/reference/`, `docs/tools/gen_reference.py`), which is **not committed yet**.
- Tests: 119 passed, 13 subtests passed (local, 11 Nov). CI passed on `356e60c` (10 Nov).
- Processes: the background broker, server and simulator of the previous session stopped on 10 Nov at 14:54; the
  databases show writes on 11 Nov between 10:37 and 10:46, so someone ran the server since. Check what is running
  (port 8000, port 1883) before starting another copy.
- Field: node 2 (Company_1) last behaved normally in LORA_WOR_STOP; its flash log holds data that has not been
  downloaded (downloads fail, see OI-01).
- Documents: the Word User Manual, System Analysis & Design and Test Report predate the flash lock, the persistent
  alerts and the Alerts page; they need an update (V1.1).

## 9. Known issues and open items

| ID | Issue | Status / next step |
|---|---|---|
| OI-01 | Per-row `HISTORY_ACK` downlinks to a node in LORA_WOR_STOP are mostly lost; flash downloads end in *ACK timeout* (1 of 5 completed). Uplinks are reliable. | Capture the gateway serial log (`FLASH_HISTORY_ACK`, `downlink_wake` lines) during a download. Then a cumulative ACK every N records — needs node firmware (`TelemetryArchive.cpp` accepts only the exact next index); keep the server compatible with both ACK styles. |
| OI-02/03 | Implausible flow values (e.g. Supmea cycling 0 … 4800 m³/h — a simulator on the RS-485 port) | `flow_unstable` alert done; real sensor acceptance outstanding |
| OI-04 | Several flash commands at once collide on LoRa | **Done** (flash lock, 10 Nov) |
| OI-05 | Public broker, one shared AES key, no authentication tag; commands can be forged or replayed | Private broker (TLS, per-gateway logins, ACLs) and per-company keys — needs node and gateway firmware |
| OI-06 | Analytics timing test flaky on a cold start (slow scikit-learn import) | Re-run; consider a longer timeout |
| — | Server accepts SRATE/STRAN 5–86,400 s; the node accepts 10–86,400 s | Not fixed: align the server minimum to 10 s (`services/commands.py`, lines 32–34 and 139) |
| — | GitHub Actions warns that its standard actions run on an old Node.js | Bump action versions in the workflow |
| — | Repository is public | User's decision (GitHub → Settings → General → Change visibility) |
| — | Starlette deprecation warning for `httpx` in the test client | Harmless; revisit when upgrading |
| — | Company_1 site coordinates came from Wikipedia | User to confirm |

## 10. Roadmap (update plan of 9 Nov 2026)

**Phase 0 — close open issues.** Done: git + CI; one flash command per node; silent-node and flow alerts.
Remaining (need firmware): cumulative flash ACK (OI-01), private broker with per-company keys (OI-05).

**Phase 1 — performance and data lifecycle.** Batched ingest (one writer thread, commit every ~250 ms or 200 rows);
SQLite tuning (`synchronous=NORMAL`, larger cache, `mmap_size`, incremental vacuum); retention per company with
hourly / daily rollups (charts beyond 7 days read rollups); in-memory latest value per node; load test with the
simulator (target example: 500 nodes × 1 msg/min, p95 API < 200 ms, ingest lag < 1 s — not measured yet);
scale-out path (PostgreSQL / TimescaleDB, separate ingest process) only when needed. Measured growth: Company_1 about
0.2 MB/day; Demo_AgriFarm about 29 MB/day.

**Phase 2 — farm and water features.** Irrigation advisor with a water budget per pivot; alert centre (rule engine,
escalation, e-mail / SMS / Telegram on top of webhooks); seasonal anomaly detection; scheduled consumption reports
(PDF / Excel).

**Phase 3 — device management.** Link-quality dashboard (downlink success per node, battery forecast; the radio has no
RSSI readout); remote gateway diagnostics over MQTT; desired vs reported configuration ("device twin"); gateway OTA
over Wi-Fi; satellite backhaul mode (store-and-forward priorities, daily budget — see the WIOT-SAT design in
`D:\WorkSpace\EgSA\R&D_WS\WIOT\WIOT_SAT`).

**Phase 4 — platform and security.** Run as a service or in Docker behind HTTPS; TOTP two-factor for supervisors and
admins; session list and revocation; scheduled off-site backups with a tested restore; Grafana on `/metrics`; PWA.

## 11. How to make a change safely

1. Read the module in `docs/reference/MODULES.md` and its tests in `docs/reference/TESTS.md`.
2. Keep the wire contract and command IDs; keep one worker.
3. Add or update tests; run the full suite.
4. For UI: English + Arabic strings, Night + Day + Arabic checks, no inline script, no CDN.
5. Update `README.md` and `docs/CHANGELOG.md`; regenerate `docs/reference/`.
6. Mirror into the worktree and commit only when the user asks; push only on request, after the secret check.
