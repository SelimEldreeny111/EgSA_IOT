# WIOT Platform v2 — change log

Everything done on the server, newest last. Test counts are the full `pytest` run at that point.
Git: branch `feature/2026-11-09-server-v2` of `SelimEldreeny111/EgSA_IOT` (see `HANDOFF.md` §4).

## 2026-11-08 — v2 server created

**New server replacing the v1.31 Flask server** (`Server/WIOT-Platform-v2`; v1.31 left untouched).

- Field compatibility kept: same MQTT topics (`wiot/<company>/<region>/<node>/{status,data,cmd}`,
  `wiot/<company>/<region>/broadcast`), same AES-128-CBC frame `[0x01][IV 16 B][ciphertext]`, same
  `messages.proto`. No firmware change needed. v1.31 databases are imported with `python -m wiot import-v1`
  (SQLite online-backup API) and opened in place, including its user accounts.
- Layered FastAPI package: `protocol`, `domain`, `storage`, `services`, `api`, `analytics`, `sim`, `web`.
- Security: signed JWT sessions (cookie or Bearer), CSRF double-submit, session revocation on password change,
  login throttling, password policy, role model (supervisor, admin, monitor, user), tenant isolation in one
  dependency layer, strict CSP, request-size cap, audit trail.
- Observability: JSON rotating logs with request IDs and secret redaction, Prometheus `/metrics`, `/healthz`,
  `/readyz`, OpenAPI at `/api/docs`.
- Durable command journal ported from v1 with explicit lifecycle states; *now* or *next wake* delivery.
- Deployment: `python -m wiot serve`, Dockerfile, docker-compose with Mosquitto, systemd unit, nginx TLS proxy
  (`deploy/`).
- Encrypted fleet simulator (`python -m wiot simulate`) that follows the node power modes and ACKs commands only
  while awake; development MQTT broker (`python -m wiot devbroker`, amqtt); `run-dev.ps1` starts broker, server
  and simulator together.
- Dashboard (dark "mission control" style): Fleet overview, Command center, Data science, History,
  Administration. 57 tests, including the ported v1 journal and flash regression suites.

**Analytics and ML pipeline** (`wiot/analytics`, `python -m wiot analyze`): reads the databases read-only and writes
JSON artifacts, figures, a trained model and `data/analytics/REPORT.md` — link and power behaviour,
store-and-forward delay, command delivery, energy model, sensor data quality, firmware footprint, project size, and a
command-delivery risk model (logistic regression on 21 as-of features, temporal hold-out, tiers LIKELY / UNCERTAIN /
UNLIKELY, SHAP drivers). The Data science page renders it; the command form shows the pre-send delivery risk;
`POST /api/v2/analytics/predict` does what-if scoring; supervisors can retrain from the UI.

**Night / Day view** toggle (header and sign-in page); follows the OS setting until chosen, remembered per browser;
charts switch to a validated light palette.

**Smart agriculture redesign** (reference: Milesight smart agriculture):
- New landing page **Smart farm**: satellite map (Leaflet, served locally; Esri World Imagery by default), fields
  coloured by soil moisture against the crop's target band (or EC, soil temperature, irrigation state), turning arm on
  irrigating pivots, probes, gateway and live links, weather and backhaul overlay cards.
- Demo tenant **Demo_AgriFarm**: six real centre pivots in East Owainat (~281 ha), located by circle detection.
- Zone panel: moisture gauge, EC, soil temperature, flow, water applied today, crop ET (ET₀ × FAO-56 Kc),
  Start / Stop irrigation through the command journal, 24-hour charts.
- Irrigation advice (deficit to band midpoint over the root zone → run time; held when forecast rain covers it).
- Automation per zone: hysteresis valve control on each fresh Status, rate-limited, audited.
- Weather and ET₀ from Open-Meteo (only coordinates are sent; `WIOT_WEATHER_ENABLED=false` disables it).
- Satellite backhaul readiness view: frame sizes per node, reports per day against a message budget (default 48).
- 68 tests.

**Guided farm-layout set-up** for companies without a layout (place the gateway, drag fields, name, crop, radius,
target), JSON editor kept under *Advanced*. Fixed: live data reloaded the page and wiped an admin's unsaved input.

**Company_1 farm placed at the EgSA Space City compound** (New Cairo, about 30.0498 N, 31.6071 E — taken from
Wikipedia, still to be confirmed by the team): gateway on the main roof, three 22 m garden plots for nodes 1–3.
Fixed: an offline node's last reading was counted as "irrigating now" and as water applied today.

**Global operation**:
- Organization page with Companies, Regions, Nodes, Gateways, API & webhooks tabs; discovered (unregistered)
  regions and nodes are listed with a *Register* button; CSV import / export of nodes.
- Strict provisioning per company (reject telemetry from unregistered nodes).
- World operations map; per-company time zone and metric / imperial units (stored in SI).
- English / Arabic interface with right-to-left layout (`wiot/web/assets/i18n.js`).
- API tokens (`wiot_…`, company-scoped, read or read-write, SHA-256 stored) and HMAC-SHA256-signed webhooks with
  retries and SSRF checks. 79 tests.

**Visual redesign** (enterprise dashboard, Day view in particular): navy sidebar with labelled, grouped pages,
compact top bar with status chips, company / region pickers, clock, Night/Day and language switches, Segoe UI
typography, cards with depth, soft badges, cleaner tables, forms and tabs.

**Node types**: *Monitoring* (sensors only) or *Control* (sensors + valve), with the fitted sensors (HNDA, Sondas,
TUF-2000B, Supmea) auto-detected from `sensor_mask`. Valve commands to a registered monitoring node are refused with
HTTP 409 (Command center, farm buttons and automation). CSV gained `type` and `sensors` columns. Company_1's three
nodes stay *Control* (user's decision). 82 tests.

## 2026-11-09 — live gateway, Flash data, documents

**Live gateway path.** The real gateway publishes to `broker.hivemq.com`; the server used the local dev broker and a
key different from the firmware's. Added a two-way bridge (`wiot/sim/bridge.py`, `devbroker --bridge HOST[:PORT]
--bridge-topic FILTER`): uplinks are copied down, the server's commands up, the demo fleet never leaves the PC,
echoes are suppressed. `run-dev.ps1` starts the bridge by default (`-Bridge ""` runs offline). `.env` now holds the
firmware's AES key (never printed). 4 tests. Node 2 (Company_1) appeared live.

**Flash data page** (Insights → Flash data) for the node SPI-flash journal: chip state and accounting, 24-hour window
fill projection, samples not logged, gap recovery (archived samples with no live uplink within
max(60 s, 2 × report interval)), coverage per generation, downloads and their outcome, valid-only statistics and
charts, paged records, CSV export; actions Read status, Download today, Latest sample, Cancel, Erase log (confirmed).
Server: `wiot/domain/flash_analysis.py`, `GET /api/v2/flash/analysis`. 92 tests.

**Compact history ACK.** Flash commands get request IDs below `flash_request_limit(node_id)` so every per-row
`HISTORY_ACK` plaintext is ≤ 15 bytes, i.e. one AES block and a 33-byte LoRa frame instead of 49 bytes
(`tests/test_flash_ack_size.py` checks node IDs 1–65535). 100 tests.

**Live flash downloads on node 2** (diagnosis, no code change): uplinks reliable; most per-row ACK downlinks to the
node in LORA_WOR_STOP are lost; the compact ACK got the first one through but downloads still end in *ACK timeout*.
Open issue OI-01 (needs the gateway serial log; see `HANDOFF.md` §9).

**Simulator resilience**: a broker blip (`rc=7`) no longer crashes the simulator; it skips reports while the client
reconnects (`tests/test_sim_resilience.py`).

**Release documents** in `Documentation/ServerSoftware/` (Markdown → Word → PDF with `build_docs.py`):
Control Center User Manual V1.0 (35 pp, English + Arabic quick guide), Server v2 System Analysis & Design V1.0
(23 pp), Server v2 Test Report V1.0 (17 pp); server flowcharts F31–F41 added to `Documentation/Flowcharts`.
Screenshots: `docs/screenshots/`, captured with `Video/capture_manual.py`. These documents describe the server **before**
the 2026-11-10 changes below.

**Update plan** written (Phases 0–4; see `HANDOFF.md` §10).

## 2026-11-10 — git, CI, Phase 0 (server-only items)

- **Git.** The firmware and documents were already in `EgSA_IOT`; the v2 server was committed for the first time on
  branch `feature/2026-11-09-server-v2` (worktree `D:\WorkSpace\EgSA\R&D_WS\IOT\IOT\WIOT_server_v2_20261109`):
  `d433dcd` server (without `.env`, `data/`, the 40 MB screenshot zip), `09d2d02` CI workflow
  `.github/workflows/server-v2-tests.yml` (Ubuntu / Python 3.12, Windows / Python 3.14), `356e60c` Phase 0.
  Pushed to `origin` with an explicit refspec; CI passed on both jobs. The repository turned out to be **public**;
  a scan of all 46 branches found no `.env`, no live AES key and only `*.example` secret templates.
- **One flash conversation per node (OI-04).** While a download is running (until it ends or 6 minutes pass without a
  message from it, `TRANSFER_IDLE_S = 360`) or a flash command awaits its reply, every other flash command to that node
  is refused with **409** and the reason; `FLASH_CANCEL` is always accepted. `GET /api/v2/flash/lock`; the Flash page
  shows a *Node busy* strip and disables the other buttons. `CommandConflict`, `CommandService.flash_lock`.
- **Persistent fleet alerts.** New `alerts` table in `iot_data.db` (`wiot/storage/alert_store.py`), monitor moved to
  `wiot/services/alerts.py`: `node_offline` (6 × median interval), `low_battery` (< 3.3 V, clears ≥ 3.4 V),
  `flow_unstable` (≥ 3 jumps of × 5 between readings ≥ 1, ≥ 2 direction changes, ≥ 6 readings, within 1 h). One open
  alert per node and kind, reported once on open and once on clear, also across restarts. `GET /api/v2/alerts`,
  `POST /api/v2/alerts/{id}/acknowledge`; **Alerts** page (Operations) and an unacknowledged-count badge in the
  sidebar; Arabic strings added.
- 119 tests + 13 subtests (132 checks) pass.

## 2026-11-11 — documentation for hand-over

- `docs/HANDOFF.md` (this hand-over), `docs/CHANGELOG.md` (this file), `docs/reference/*.md` generated from the code
  by `docs/tools/gen_reference.py` (API, configuration, CLI, database schemas, code map, tests, events and metrics).
- Re-run of the full suite: 119 passed, 13 subtests passed (64 s).
