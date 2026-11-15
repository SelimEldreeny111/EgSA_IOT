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
- Development plan `Documentation/ServerSoftware/WIOT_Platform_Development_Plan_V1.0` (Markdown, Word, PDF; 21 pages):
  all 62 improvement points in six server-only releases (R2.1–R2.6, 16 Nov 2026 – 16 Jul 2027) and Track G
  (greenhouses and new sensors); linked from `HANDOFF.md` §10.

## 2026-11-11 — Release 2.1 "Foundation and quick wins" (version 2.1.0, server only)

Points of `Documentation/ServerSoftware/WIOT_Platform_Development_Plan_V1.0`. No node or gateway software change.

- **1 · Interval minimum 10 s.** SRATE/STRAN below 10 s are refused (the node firmware accepts 10–86,400 s).
- **13 · ACK deadline by power mode** (`domain/command_queue.py` `ack_timeout_for`): NORMAL 30 s, RTC_PERIODIC /
  REMOTE_WAKE / RTC_QUEUED 60 s, LORA_WOR_STOP 90 s, from the node's last reported power mode
  (`TelemetryStore.latest_power_mode`). Measured p99 reply latency Oct–Nov 2026: NORMAL 21 s, REMOTE_WAKE 58 s,
  LORA_WOR_STOP 69 s (max 153 s). A late reply still completes an *outcome unknown* command.
- **14 · Auto delivery.** `delivery: "auto"` (API and the Command center's new default *Auto*): the delivery-risk
  model decides; tier UNLIKELY → next wake, otherwise now; broadcast → now; broker down → next wake; no model → now.
  The response and the audit entry carry the decision.
- **12 · Automatic clock sync** (`services/clocksync.py`, `WIOT_CLOCK_SYNC`): STIME queued for the next wake when a
  node reports an unset clock or drifts more than `WIOT_CLOCK_SYNC_DRIFT_S` (120 s; robust to store-and-forward
  delay), at most once per 6 h per node (30 min for an unset clock), never while an STIME is pending or a flash
  download runs; journaled and audited as `system:clock-sync`. **On the live server this sends STIME to real nodes
  whose clocks drift.**
- **18 · Command-topic watchdog.** A command on a node's topic with no journal entry → critical `foreign_command`
  event alert, metric `wiot_foreign_commands_total`, history row marked FOREIGN.
- **19 · Replay flagging.** A Status whose plaintext repeats an older message after newer data → `possible_replay`
  warning, not processed (no automation, commands or clock sync); repeats of the newest message are harmless
  duplicates. Metric `wiot_repeated_frames_total{kind}`. Event alerts resolve after 24 h without a new event.
- **33 · Leak / no-flow / night-flow alerts** on valve nodes: `leak_suspected` (critical), `no_flow` (warning), optional
  `night_flow` (`WIOT_NIGHT_FLOW_HOURS`, off by default).
- **45 · Frost and heat warnings** from the farm forecast (today and tomorrow): `frost_risk` (≤ `WIOT_FROST_WARN_C`
  = 2 °C) and `heat_stress` (≥ `WIOT_HEAT_WARN_C` = 40 °C) as site alerts (node 0, shown as SITE) and in the farm
  page's weather card.
- **37 · Irrigation index** per field: applied water (daily meter volumes ÷ area) vs ETc = ET₀ × Kc over the last
  7 days (Open-Meteo `past_days=7`); zone panel cell and `under_irrigated` / `over_irrigated` KPIs. The weather client
  now separates past and forecast days and counts the 24-hour rain from the current hour.
- **6 · Backups** (`storage/backup.py`): `python -m wiot backup | verify-backup | restore-backup` — online SQLite copies,
  integrity checks, SHA-256 manifest, AES-256-GCM encryption (scrypt key, 4 MiB authenticated chunks) with
  `WIOT_BACKUP_PASSWORD`, pruning to `WIOT_BACKUP_KEEP`, restore only into an empty folder.
- **4 · HTTPS and Windows service.** `WIOT_TLS_CERTFILE` / `WIOT_TLS_KEYFILE` serve TLS from the platform (and force
  secure cookies); `deploy/windows/install-tasks.ps1` / `uninstall-tasks.ps1` (Task Scheduler: server at boot with
  restart, nightly backup). Prepared, not installed.
- **5 · Production broker.** `deploy/windows/mosquitto.conf`: Mosquitto with persistence and a bridge to HiveMQ for the
  real companies; steps in `deploy/windows/README.md`. Prepared, not installed.
- **20 · Dependency audit** job (pip-audit) in `.github/workflows/server-v2-tests.yml`.
- **3 · Flash download diagnosis.** `python -m wiot flash-timeline` merges server records with the gateway serial log;
  bench procedure `docs/procedures/FLASH_DOWNLOAD_DIAGNOSIS.md`. The bench session itself is still to be run.
- **UI:** Alerts page labels and texts for all new kinds (English and Arabic), Auto delivery, irrigation index,
  weather warnings; checked in Night, Day and Arabic with no console errors.
- **Tests:** `tests/test_r21.py` (21 tests). Full suite 140 passed, 13 subtests passed. The predictor load-time limit
  in `tests/test_analytics.py` was raised from 10 s to 30 s (a cold scikit-learn import took 13 s on Windows; OI-06).
- **Point 2** (Word documents V1.1) is delivered with this release in `Documentation/ServerSoftware/`.

## 2026-11-12 — Releases 2.2 to 2.6 (version 2.6.0)

All server-only points of the development plan except Track G (points 53–60). No node or gateway software change;
topics, AES frame, protobuf fields and command IDs unchanged. One server process (one MQTT owner).

### R2.2 — Operations and data platform (points 7–11, 15, 16, 32)
- **7 · Monitoring.** `services/system.py`: System health page (supervisor) with checks for broker, ingestion per
  company, disk, backups, alert monitor and maintenance threads; new gauges `wiot_ingest_last_message_age_seconds`,
  `wiot_disk_free_ratio`, `wiot_backup_age_seconds`, counters `wiot_maintenance_runs_total`,
  `wiot_config_corrections_total`. `deploy/monitoring/`: Prometheus alert rules and a Grafana dashboard.
- **8 · Status page.** Public `/status` (service health only, no company data; `WIOT_STATUS_PUBLIC`), 30-day
  availability from 5-minute samples (`status_history`). `docs/DISASTER_RECOVERY.md` (RPO 24 h, RTO 2 h, scenarios).
- **9 · Faster writes.** SQLite tuning (WAL + `synchronous=NORMAL`, memory temp store, 16 MB cache, 256 MB mmap),
  optional group commit (`WIOT_INGEST_BATCH_MS`, 250 ms recommended), in-memory latest reading per node, 2-second
  fleet cache cleared on every write.
- **10 · Summaries and retention.** `storage/rollups.py`: hourly and daily summaries (n, mean, min, max) per node and
  metric, recomputed for late store-and-forward samples; charts longer than 7 days read them. Retention per company
  (`retention_days`, minimum 365 days, 0 = forever) deletes only summarised raw rows. `services/maintenance.py` runs
  every 10 minutes; `python -m wiot maintain [--vacuum]`.
- **11 · Load test.** `python -m wiot loadtest`: throw-away data folder, local broker, server subprocess, N encrypted
  virtual nodes, API latency. Recorded: 1000 nodes × 2 uplinks/min for 3 min — 5943 published, 5943 stored (0 % loss),
  32.6 msg/s, ingest mean 21 ms, API p95 259 ms (fleet 285 ms, 24 h series 82 ms, message page 89 ms)
  (`docs/loadtest/R2.2_1000nodes.json`).
- **15 · Configuration watch.** Telemetry carries the node's sampling and report intervals (ms); when they differ from
  the last acknowledged SRATE / STRAN the value is queued again for the next wake, at most once a day per node
  (`system:config-watch`, `WIOT_CONFIG_WATCH`). Reported intervals are stored (`sampling_rate_s`, `transmission_rate_s`).
- **16 · Node health.** `services/nodehealth.py`, page Node health and `GET /api/v2/fleet/health`: score 0–100 from
  battery trend (days to 3.3 V), resets, reporting regularity, store-and-forward share, clock trust, command success
  and configuration drift, with findings in words.
- **32 · Engineering quality.** `ruff.toml` (defect rules only), CI jobs *lint and type check* (ruff, mypy
  informational) and *browser smoke test* (Playwright: every page in English and Arabic without console errors;
  skipped locally without Playwright), `requirements.lock`.

### R2.3 — Security, alerts by message, reports, integrations (points 17, 21–23, 27–30)
- **17 · Two-factor sign-in** (RFC 6238 TOTP, standard library; secrets sealed with AES-GCM under a key derived from
  `WIOT_SECRET_KEY`), 10 one-time recovery codes, session registry with per-session sign-out, audit viewer with
  filters and CSV (Security page).
- **21 · Single sign-on** (OpenID Connect, authorization code + PKCE, ID token verified against the provider's JWKS),
  e-mail invitations with one-time links, page access per user.
- **22 · Alert rules and notifications.** Custom threshold rules (metric, condition, duration, nodes, severity) run in
  the alert monitor; channels: e-mail (SMTP), Telegram, SMS and WhatsApp (Twilio, Meta Cloud API, generic HTTPS),
  Microsoft Teams; burst limit 20 per 10 minutes per channel; delivery log (Rules & notifications page).
- **23 · Monthly reports** in Excel and PDF (writers in `tools/xlsx.py`, `tools/pdf.py`, no dependency), built on the
  1st and sent to report channels (`WIOT_REPORTS_AUTO`); Reports page with archive.
- **27 · Branding** per company: name, colour, logo (PNG / JPEG ≤ 40 KB).
- **28 · Usage metering** per company and day: uplinks, air-time bytes, commands, API calls, exports, active nodes,
  storage; Usage page and CSV; history back-filled from stored messages.
- **29 · Integrations.** Forwarding of every reading to ThingsBoard, Azure IoT Hub (SAS over HTTPS) or any HTTPS
  endpoint; daily CSV feed for Power BI / Excel; `docs/integrations/README.md` with examples.
- **30 · Help center**, guided tour on the first visit, *What's new* after an upgrade.

### R2.4 — Agronomy and water management (points 34–36, 38–43, 47)
- `services/agronomy.py`: FAO-56 crop calendar and stage Kc (**43**), soil water-holding capacity from texture or lab
  values (**47**), FAO-29 yield potential and leaching requirement (**34**), deficit programmes for olives, dates and
  grapes (**39**), daily root-zone balance (**41**: 7-day moisture forecast, date and amount of the next irrigation).
- `services/water.py`: field profiles; irrigation schedules through the command journal with rain, rotation and
  quota skips (**40**); canal rotations and quotas (**35**); wells against their licence with projection and alert
  (**36**); water and pumping cost per field (**38**); utility districts with monthly non-revenue water and a
  billing statement in Excel (**42**). The farm advice now uses the stage Kc and the leaching requirement.
- Pages Irrigation planning and Water accounts; alerts `salinity_risk`, `well_licence`, `quota_<id>`.

### R2.5 — Crop records, satellite, regional views (points 44, 46, 48–52, 61, 62)
- `services/cropcare.py`: stored daily weather, growing degree days, disease and pest risk from the hourly forecast
  (**44**); farm diary and GlobalG.A.P.-style traceability with pre-harvest-interval check, Excel and PDF (**46**);
  yields and water productivity (**48**); WaPOR AETI import (CSV) and comparison (**50**).
- `services/satellite.py`: Sentinel-2 NDVI per field and pass through the Copernicus Data Space Sentinel Hub APIs
  (**49**, needs an account); pivot detection from an image (excess green + Otsu + distance transform, **51**);
  WIOT-SAT products marked `satellite` and pass schedule (**52**).
- Farmer view `/farmer` — one Arabic-first card per field with what to do today (**61**); regional dashboard for
  national accounts with areas below `WIOT_REGIONAL_MIN_FARMS` suppressed (**62**).

### R2.6 — Field apps, maintenance, assistant (points 24–26, 31)
- **24 · Installable app**: web manifest, service worker (offline app shell, last API answers with an offline banner,
  map tiles saved per farm), Web Push alerts (VAPID + RFC 8291 encryption, no extra package).
- **25 · Commissioning wizard**: QR label (camera or typed) → register with GPS position → first uplink → clock →
  acceptance checks → certificate (PDF) stored with the node's asset.
- **26 · Maintenance module**: assets, work orders (from an alert or by hand) with timeline and photos, calibration
  history with deviation and next due date; an overdue calibration opens an alert.
- **31 · Optional AI assistant** (Claude, `claude-opus-5-5`, official SDK as the `assistant` extra): read-only tools
  scoped to the user's company, no personal data, audited, rate-limited, daily summary; off by default.

### Tests and checks
- New: `tests/test_r22.py` (14), `test_r23.py` (19), `test_r24.py` (13), `test_r25.py` (13), `test_r26.py` (10).
- UI checked on a copy of the data in Night, Day and Arabic (R2.2–R2.4 pages), no console errors besides the
  expected WebSocket reconnects during server restarts.
- Version 2.6.0.

## 2026-11-13 — Release 2.7 "Earth observation" (version 2.7.0)

Access to Copernicus Sentinel and EUMETSAT data from the server, built with the remote-sensing course
(`RemoteSensing/` next to `Server/`). Nothing changes for the nodes.

- `services/eo.py` (new):
  - **Open Sentinel-2 NDVI without an account** (`WIOT_SATELLITE_PROVIDER=open`). Earth Search STAC search, one pass
    per date whose tile holds the farm, then a standard-library + numpy reader for cloud-optimised GeoTIFFs: HTTP range
    requests, classic and BigTIFF, DEFLATE, horizontal predictor, tie point / pixel scale, EPSG from the GeoKeys.
    UTM by the Krüger series; even-odd polygon mask at pixel centres; SCL clear-sky mask (4, 5, 6, 7, 11).
  - The BOA offset is removed only when the metadata says it is still present (`earthsearch:boa_offset_applied`,
    processing baseline ≥ 04.00).
  - Checked on real data: the reader is bit-identical to GDAL. UTM agrees with PROJ to < 1 mm. NDVI and pixel counts
    are identical to the course's rasterio processing for the six East Owainat pivots (10 March 2026; 11 s for the
    farm).
  - **Copernicus Data Space catalogue**: public STAC search of Sentinel-1 GRD, Sentinel-2 L2A and Sentinel-3 SLSTR
    LST, OLCI land and SYN, newest first, with Copernicus Browser links.
  - **EUMETSAT Data Store**: collections (cached a day) and product search over the farm are public. Downloads use
    the API key (`WIOT_EUMETSAT_KEY` / `_SECRET`, client-credentials token), are streamed to
    `data/eo/eumetsat/<collection>/` with a size cap (`WIOT_EO_DOWNLOAD_MAX_MB`), checked ids and safe file names,
    and are audited.
- `services/satellite.py`:
  - `ndvi_provider` (auto / sentinelhub / open / off); `fetch_ndvi` dispatches to the configured provider.
  - The open path stores into the same `sat_ndvi` table (source `sentinel-2-open`) and remembers the passes it has
    read (`sat_open_scenes`), so each pass is read once, at most `WIOT_SATELLITE_OPEN_MAX_SCENES` per run.
  - *Update now* runs in the background with a status. Field images (true colour or NDVI) are rendered from the
    open archive.
- API `GET /api/v2/eo/status`, `/eo/scenes`, `/eo/eumetsat/collections`, `/eo/eumetsat/products`, `/eo/downloads`,
  `POST /eo/eumetsat/download` (administrators); remote failures return 502 with the provider's message.
  `/satellite/status` reports the provider and the background job; `/satellite/ndvi/refresh` takes `days`.
- Satellite page: *Copernicus catalogue* and *EUMETSAT Data Store* panels, background refresh progress.
- Defaults keep the previous behaviour: with `auto` and no Copernicus OAuth client, nothing is fetched.
- Tests: `tests/test_r27.py` (10). They run offline: a minimal tiled-GeoTIFF writer, fake STAC / EUMETSAT servers
  with range support, the BOA offset both ways, cloud masking, read-once, background refresh, permissions, path
  safety and upstream errors.
