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

## 2026-11-15 — fixes found while writing the User Manual V2.0 (version unchanged, 2.7.0)

Review of every page for `Documentation/ServerSoftware/WIOT_Control_Center_User_Manual_V2.0` (81 pages, all screenshots
retaken with `capture_manual_v2.py` on a demonstration copy). Eight defects found and fixed:

- **Availability read about 50 %.** With the default 10-minute maintenance interval only one status sample was taken
  per 10 minutes, while the availability expected one per 5 minutes, so System health and the public `/status` page
  showed about 50 % for a healthy server.
  - The maintenance thread now wakes every 5 minutes for the sample and still runs the full cycle at its own interval.
  - Availability now counts covered time: a sample stands for the time until the next one, at most 15 minutes. Days
    recorded at the old cadence read correctly, and longer gaps still count as downtime.
- **Calibration alert title.** The overdue-calibration alert showed its raw kind (`calibration_due_7`). It is now
  **Calibration overdue** with the asset and the due date, on the page and in e-mail and push messages.
- **Page access list.** It did not offer Regional dashboard, Administration, Integrations or Usage, so saving a page
  list silently hid them from users whose role allows them.
- **Node health intervals.** The cell showed "Sampling ? s" when an interval was set from WIOT but not yet reported.
  It now shows "set *Y* s (not reported yet)".
- **Alerts page.** **Acknowledge** and **Work order** are stacked, so a long alert text no longer pushes them out of
  view.
- **Water accounts and Crop care.** The editors go under their wide tables on screens narrower than 1800 px; columns
  were cut off before.
- New tests:
  - `test_r22.py`: status sampling between longer cycles; availability for 5- and 10-minute cadences.
  - `test_r26.py`: calibration alert title.
- **Browser smoke test (CI).** The `browser smoke test` job failed on the release 2.2–2.7 commit (`30890e1`); every
  other job passed. The test waited for `/**` after pressing Sign in, which already matches `/login`, so its first
  navigation cancelled the sign-in request and no page rendered. It now waits until the address leaves `/login`.
  This is a test defect, not an application one. The test had never run before: it is skipped where Playwright is
  missing. It passes locally in English and Arabic.
- **Sentinel Hub cloud-free share.**
  - The problem: the Statistical API counts every cell of the request's bounding box in `sampleCount`, and the cells
    outside the field polygon in `noDataCount`. A fully clear round pivot was therefore stored as about 78 % clear,
    and the 50 % minimum effectively required about 64 %.
  - The fix: the clear share is now measured against the field's own share of the box (`field_share_of_bbox`),
    counted cell by cell on the 0.0001° request grid.
  - Checked against the live service with the project's Copernicus client: P-08 and P-19 went from 80–81 % to 100 %
    on clear days.
  - Stored values are corrected by the next update of the same dates (**Update now** re-reads the last 30 days).
  - New test: `test_r27.py::test_sentinel_hub_clear_share_is_measured_against_the_field`.
- **Commissioning push check.** The page asked the browser's push service for its subscription without catching a
  refusal. Headless or locked-down browsers (for example Chromium on Linux) can refuse, and the error surfaced
  whenever the service worker finished starting, possibly on another page. This is the likely cause of an
  intermittent CI browser-test failure on `bc12fd0`; the test passes locally, also with a CPU slowed six-fold. The
  page now shows "Push alerts are not available in this browser (…)". The CI browser job also turns failing lines
  into public annotations, so a failure can be read without a GitHub sign-in.

## 2026-11-15 — Satellite viewer and satellite data over the farm (R2.7 addition, version unchanged 2.7.0)

The Satellite page now has the Copernicus Browser's layers on the farm map, and a list of every satellite dataset
over the farm. Nothing changes for the nodes.

- `services/eo_layers.py` (new): the layer catalogue.
  - Five missions: Sentinel-2 L2A and L1C, Sentinel-1 GRD, Sentinel-3 OLCI and SLSTR.
  - 20 layers with Sentinel Hub evalscripts (v3), legends and swatches:
    - Sentinel-2: True color, False color, Highlight Optimized Natural Color, NDVI (the Browser's palette),
      Wildfires, False color (urban), Moisture index, SWIR, NDWI, NDSI, Scene classification map, Agriculture,
      NDRE, Custom;
    - Sentinel-1: VV and VH decibel, radar false colour (gamma-0 terrain-corrected, orthorectified);
    - Sentinel-3: OLCI true colour and NDVI, SLSTR brightness temperature.
  - Custom = a composite of any three bands or a normalised-difference index of two (band names validated).
  - Numpy renderers of the same Sentinel-2 layers for the open archive.
- `services/eo_render.py` (new): `SatelliteViewer`.
  - **Copernicus Sentinel Hub** (with the OAuth client): Process API in EPSG:3857 so the PNG lies exactly on the
    Leaflet map. Least-cloudy mosaic of the last 30 days, the most recent pass for radar and Sentinel-3, or one
    chosen day.
  - **Open archive** (no account, Sentinel-2 L2A): the pass that covers the centre of the view; each band read in
    parallel at the matching COG overview, nearest-pixel sampling onto the Mercator grid, transparent where there is
    no data or SCL = 0. Views up to 0.6° across, images up to 1024 px; about 25 s for a farm view the first time.
    Open-archive and Sentinel Hub NDVI agree pixel for pixel.
  - Images are cached on disk (`data/satellite/render/`, newest 600, at most `WIOT_VIEWER_CACHE_MB`).
  - **Availability**: CDSE STAC (S2 L2A, S1 GRD, S3 OLCI, S3 SLSTR), Earth Search Landsat C2 L2 and EUMETSAT
    counts for 5 collections, queried in parallel within one 60 s deadline. Cached 20 minutes (2 minutes when a
    catalogue failed); a failing catalogue is reported in its row and does not hide the others.
- `services/eo.py`: the COG reader follows the IFD chain and reads the overview pyramid (`levels`, `level_for`,
  `read(level=…)`, `sample()`; overviews identical to GDAL). New `utm_forward_np`. Earth Search results carry every
  band's URL.
- API:
  - `GET /api/v2/eo/layers`: missions, layers, legends, which renderer draws each, the farm's bounds, fields and
    base map.
  - `GET /api/v2/eo/render.png`: a PNG of a layer for a map view, with an `X-Imagery` header (provider, dates,
    mosaic, scene, cloud). 150 images per user per 10 minutes and 2 at a time; daily Sentinel Hub allowances.
  - `POST /api/v2/eo/render.png`: your own evalscript (the supervisor only, Sentinel Hub only; it must define
    `evaluatePixel`).
  - `GET /api/v2/eo/availability?days=30|90|180|365`: every pass and product over the farm, plus the NDVI and
    WIOT-SAT data stored on the server and Copernicus Browser links. 30 look-ups per user per 10 minutes.
- Satellite page (`pages/satviewer.js`, new):
  - **Satellite viewer**: satellite, pass date (from the catalogue, with cloud cover), maximum cloud, layer cards with
    the legend under the chosen layer, Custom (composite, index, evalscript). Above the map: opacity, field outlines,
    Download image, Open in Copernicus Browser. The image is redrawn after each pan or zoom; the old one stays until
    the new one has loaded.
  - **Satellite data over this farm**: one strip per satellite with a cell per day, Sentinel-2 and Landsat coloured
    by cloud, counts and latest dates, EUMETSAT products, data held on the server. Clicking a day opens it in the
    viewer.
  - Arabic texts, Day and Night views, phone layout. The service worker does not keep the images (the server cache
    does).
- Default behaviour: with `WIOT_SATELLITE_PROVIDER=auto` and no OAuth client, the viewer draws Sentinel-2 from the
  open archive, and only when someone opens the Satellite page. The background NDVI update is unchanged.
  `open` uses only the open archive, `sentinelhub` only Sentinel Hub, `off` hides the viewer.
- Checked live on the demo farm (East Owainat):
  - all 33 satellite / layer combinations through Sentinel Hub (1–3 s each for a farm view);
  - Sentinel-2 from the open archive with no account;
  - a company without farm fields opens at country scale and asks to zoom in instead of drawing all of Egypt;
  - an own evalscript and a custom index from the page;
  - availability for 90 days: S2 45, S1 13, OLCI 93, SLSTR 210, Landsat 20 passes; EUMETSAT MTG LST 12,999, MSG LST
    8,675, MTG precipitation 2,505, ASCAT 146 products.
- Manual V2.0 chapter 21 rewritten (21.1 Satellite viewer, 21.2 Satellite data over this farm, new screenshots
  `s26a`, `s26b`); Help article updated.
- New tests in `tests/test_r27.py` (5, and 5 more from the review below):
  - layer catalogue and numpy renderers;
  - COG overviews and point sampling;
  - Sentinel Hub rendering with cache, limits and permissions;
  - open-archive rendering;
  - availability with a failing catalogue.

## 2026-11-16 — Satellite viewer: fixes from the pre-push review (before the first commit)

Four reviews (back end, front end, security, docs and tests) before the viewer was committed to the public
repository; every finding was checked against the code before it was fixed.

- **Server protection** (`eo_render.py`, `api/eo.py`):
  - At most 2 open-archive and 4 Sentinel Hub images are drawn at once on the whole server, and 2 per user. A request
    that finds no free slot within 15 s gets 503 with `Retry-After`. The page then waits and asks again; a busy answer
    does not count against the user's images. Before this, about 40 large open-archive requests from one read-only
    account could take every worker thread and several GB of memory.
  - Open-archive images are at most 1024 px on their longest side, and the bands are read 4 at a time.
- **The shared Copernicus account**:
  - Daily allowances of Sentinel Hub processing units: `WIOT_VIEWER_COMPANY_DAILY_PU` (400) and
    `WIOT_VIEWER_DAILY_PU` (1000), 0 = no limit, 429 when used up.
  - The cost of each image is estimated like Sentinel Hub does (512 × 512 pixels and 3 input bands = 1 unit).
  - Only cache misses are charged.
  - Own evalscripts are for the supervisor only (`own_evalscript` in `/eo/layers`).
- **Disk cache**:
  - One file per image (metadata line + PNG), written to a temporary name and renamed, so readers never see half a
    file.
  - A clean-up that never fails a request: one at a time, files that vanish are skipped, the newest 600 within
    `WIOT_VIEWER_CACHE_MB` (1024) are kept.
  - Unreadable files are cache misses.
  - Before this, renders that finished together could fail with 502 and the server's data path in the message, and
    the `.json` sidecar files were never deleted.
- **Errors**:
  - Network failures give 502 "could not be reached".
  - Unreadable remote data (IncompleteRead, DEFLATE, TIFF or JSON errors) gives 502 "could not be read" instead of
    500 or a misleading 400 / 404.
  - Local storage errors give 502 without any path.
  - The viewer's own input and no-data errors stay 400 / 404.
- **Correct results**:
  - The cloud threshold is rounded once, so the cache key and the request agree.
  - Dates are normalised to YYYY-MM-DD; the POST body has the same date pattern and bounds as the GET query.
    NaN and infinite bounds are refused.
  - The open-archive search is inclusive (`lte`; 0 % now finds cloud-free passes) and has no cloud filter for a
    chosen date.
  - The pass is chosen by its data footprint, not its bounding box, so swath-edge slivers are not drawn as an empty
    latest image.
  - `WIOT_SATELLITE_PROVIDER=open` / `sentinelhub` are respected by the viewer.
- **Availability**:
  - Every STAC page is followed, up to 2,000 items, on the same host, with the POST body merged when the catalogue
    asks for it. Before this, the list stopped at 400 items, so 12 months of Sentinel-3 SLSTR showed 400 passes and
    empty early months.
  - The count comes from `numberMatched` when the catalogue gives it; the page shows "+" and "older passes not
    drawn" when the list is cut.
  - One 60 s deadline for all catalogues, and a hanging catalogue no longer holds the request.
  - Periods are 30, 90, 180 or 365 days.
  - One query per farm and period at a time; expired answers are dropped (at most 64 kept).
- **Page**:
  - An older image can no longer replace a newer one. An image that fails to load is removed and its memory freed.
  - Satellite images have their own map pane under the field outlines.
  - The download name matches the image shown.
  - A typed evalscript survives re-renders.
  - The pass-date list belongs to the chosen satellite.
  - Only the newest availability answer is drawn. The timeline scrolls sideways on phones and has no gaps for long
    periods.
  - The page-leave guard uses this page's own containers.
  - Day tooltips and the new server messages are translated into Arabic.
  - The panel names Earth Search (AWS) as the Landsat source.
- **Tests** (`tests/test_r27.py`):
  - New: server protection and allowances; cache races, size limit and old files; cloud filter, footprint and
    unreadable data; availability paging, deadline, cache and limits; the provider setting.
  - Tighter: each layer is rendered from only the bands it declares; the open-archive test checks the chosen pass.
- Manual V2.0 chapter 21, its troubleshooting rows and settings table, and `.env.example` updated.
- Checked again in the browser on the demo farm (Day, Night, Arabic, phone): every layer tried draws, an own
  evalscript and a custom index run, a busy answer is retried by the page, and the 90-day timeline fits a phone.
- Full suite: 231 passed + 13 subtests, 1 skipped (the browser smoke test without Playwright); the browser smoke test
  passes locally in English and Arabic. (In one run on a busy machine the analytics timing test took 30.7 s against
  its 30 s limit; it passes on its own.)

## 2026-11-16 — Smart farm: fields of working nodes no longer shown as faults (version unchanged, 2.7.0)

Reported on Company_1: nodes 2 and 3 were online and visible in Fleet overview, but on Smart farm all three fields were
red with "–". Company_1's live readings showed three different cases, all drawn the same way.

- `services/farm.py` `zone_state`: without a moisture value, the field now says why.
  - **Offline**: node 1 (last uplink 18 days ago) was shown as **Probe fault**, because the moisture check came before
    the link check. "Need attention" therefore said "0 offline".
  - **No soil probe** (new status `no_probe`, neutral): node 3 reports no sensors (`sensor_mask` 0). Not a fault, no
    alert.
  - **Probe fault**: node 2 reports a Sondas probe and a Supmea flow meter (`sensor_mask` 12), but no valid value.
  - Every field carries `sensors` (from `sensor_mask`). New KPIs `probe_fault` and `no_probe`.
- Smart farm page:
  - Without a moisture value, the field label shows **Offline**, or the battery with **no reading** / **no probe**.
  - The field panel shows the battery with its last uplink and the node's **Sensors**.
  - The legend lists **No soil probe** and **Probe fault** when present.
  - "Need attention" counts probe faults.
  - Arabic texts added.
- Farmer view: a **No soil probe** card instead of "check the probe".
- Manual V2.0: field panel and troubleshooting rows updated.
- Checked on a read-only snapshot of the live data: F-1 "Offline", F-2 "3.70 V · no reading", F-3 "7.25 V · no probe";
  "Need attention 2 — 1 offline · 1 probe fault".
- New test `test_farm.py::test_field_without_moisture_says_why`; the Farmer view test accepts the new card.
- Full suite: 232 passed + 13 subtests, 1 skipped (the browser smoke test without Playwright).

## 2026-11-16 — Commands reach the gateway at once and are not lost in bursts (version unchanged, 2.7.0)

Reported: commands from v2 reached the gateway late or never, while v1.31 delivered them at once. Investigated
read-only with five parallel checks: node and gateway firmware, the v1.31 and v2 command paths, and both
servers' journals of the same day.

- **Delay.** The node firmware, gateway build `gateway-wor`, `APP_LORA_GATEWAY_WOR_TX=1` lets the gateway wake a
  LORA_WOR_STOP node (mode 5) for every command: v1.31's immediate commands were answered in 10-20 s. v2 instead
  held them until the node's next Status ("next wake"), and released only one per Status:
  - the farm valve buttons held every command for any mode other than NORMAL;
  - the Command center's **Auto** followed the delivery-risk model, which rated node 3 UNLIKELY.

  Result: 12 s to 6 min of waiting.
  - Fix: **Auto** now follows the power mode (`protocol.power.delivery_for_power_mode`). Modes 1, 3 and 5 send
    now. Modes 2 and 4 (radio off between the node's own uplinks, E32 Mode 3 and MCU in Standby) wait for the next
    Status. The model decides only when the mode is unknown.
  - The farm valve buttons use **Auto** and are disabled for a moment after each click.
- **Lost commands.** Every node hears every command; the gateway forwards each one synchronously with a wake probe,
  with no queue and no retry; the link is half duplex.
  - Today 20 SRATE to node 2 within about one minute (12 within 6 s) produced 1 acknowledgement. v1.31 lost 9 of 14 fast VALVE
    clicks the same way.
  - Fix: one command on a gateway's (company, region) radio at a time (`command_queue._in_flight`). A command
    counts as on air until it is answered, or for at most 45 s (`RADIO_BUSY_S`); its reply is still accepted until
    the deadline.
  - Commands sent meanwhile stay pending and go out first come, first served (`claim_held`). They are released
    when the reply arrives, when the radio becomes free (a per-gateway timer), or at a Status.
  - A superseded command that was already sent still counts as on air, so repeated clicks send only the first and
    the last.
  - Broadcasts wait too. FLASH_CANCEL never waits.
  - A running history download counts as on air (its per-row ACK downlinks are not in the journal).
  - Queued commands of listening nodes no longer wait for a Status when the radio is free. RTC nodes keep their
    Status window.
  - A command held for 5 minutes expires and is never sent late (`HELD_LIMIT_S`).
- **Transport.** The PUBACK callback no longer takes the publish lock: it was an ABBA deadlock risk with paho's
  message mutex, found in review and older than this change. It now uses a short lock that is never held while
  calling paho.
- Reviewed by two independent reviewers (concurrency and journal; firmware behaviour), each finding checked by a
  second agent. All 10 confirmed findings are fixed.
- New `tests/test_command_delivery.py` (8): power-mode delivery, the per-gateway radio rule and its timeout, order,
  expiry, the Status path, history downloads, the release timer.
- Not changed (firmware, reported to the user):
  - nodes answer CMD_REJECTED to commands addressed to other nodes (`IoT_Node_Encrypted.ino` reply path), which
    costs airtime and battery;
  - the gateway defers MQTT for up to 15 s while it reassembles an uplink.
- Checked end to end over MQTT: local broker, throwaway server, simulator for the demo companies only.
  - Five fast SRATE clicks to a LORA_WOR_STOP node: the first was sent at once, the three in the middle were never
    sent, and the last was sent when the first was answered (answered 2 s later). A GOSTM sent after the clicks
    followed when the radio was free.
  - A GOSTM to an RTC_PERIODIC node waited for its next Status (+6 s) and was answered at +7 s.
- Full suite: 240 passed + 13 subtests, 1 skipped (the browser smoke test without Playwright).

## 2026-11-17 — Track G: third-party devices and greenhouse layouts (version 2.8.0)

Points 53 and 58 of the development plan (Track G, phase G2), server only: no firmware change.

**Third-party devices (point 53)**: off-the-shelf climate, soil, water-quality and tank sensors next to the WIOT nodes.
- **MQTT JSON** on the same broker session as the nodes, topic `wiotx/<company>/<device_id>/up` (added to the
  subscriptions; `transport.py` hands `wiotx/` messages to the device service before AES framing). The field broker is
  public, so a device is **signed** by default: `{"p": "<JSON text>", "sig": "<hex>"}` with
  `sig = HMAC-SHA256(device secret, topic + "\n" + p)` and `ts` (Unix seconds) inside `p`. A message must be newer than
  the last one stored (replays refused, also after a restart) and at most 7 days old. The secret is sealed with
  `WIOT_SECRET_KEY` and shown once (create or "New secret"). **Unsigned** devices publish plain JSON; their readings are
  stored but marked untrusted.
- **LoRaWAN** through The Things Stack v3 (webhook, `POST /api/v2/ingest/ttn`) or ChirpStack v4 (HTTP integration, JSON,
  `POST /api/v2/ingest/chirpstack?event=up|status`), with a per-company **connection key** (`wiotsrc_…`, stored as a
  SHA-256 hash, shown once, revocable; never usable as an API token). Devices are matched by DevEUI; RSSI and SNR of the
  best gateway are stored with each uplink; ChirpStack status events add the battery level.
- **Metric catalog** (`wiot/domain/ext_metrics.py`, 26 metrics in 5 groups, one SI unit and a valid range each). A
  device's **payload mapping** (field → metric, scale, offset) turns vendor fields into metrics; without a mapping,
  common field names (temperature, humidity, co2, par, battery …) map automatically. Out-of-range values are rejected.
- **Storage** per company (`ext_readings` raw, `ext_hourly` count/sum/min/max, `ext_latest`); duplicates ignored;
  raw rows follow the company's retention (at least 365 days), hourly summaries are kept. Live hub event
  `device_reading`; each uplink counts as a message in Usage.
- **Alerts**: `device_silent_<id>` (warning, site level) after 3 missed reports (at least 15 min), cleared by the next
  reading; shown with the device name on the Alerts page and in e-mail/SMS/Telegram/Teams texts.
- **Devices page** (Operations → Devices): tiles, device list with live readings and status, editor with payload
  mapping and the last payload (Map buttons), secret box with a ready-to-run Python example, readings chart
  (24 h … 1 year; hourly mean with min/max band), "Heard but not registered" list with one-click Register, LoRaWAN
  connections tab with set-up steps, set-up guide with the catalog. Read-only users see everything except secrets
  and keys; API tokens cannot create devices, secrets or keys.
- API: `GET/POST /api/v2/devices`, `PATCH/DELETE /devices/{id}`, `POST /devices/{id}/secret`,
  `GET /devices/{id}/series`, `GET /devices/catalog`, `GET/POST /devices/sources`, `DELETE /devices/sources/{id}`.

**Greenhouse layout editor (point 58)**: Operations → Greenhouses.
- One layout per company: houses (glass, plastic, net, tunnel, shade, other) → zones → benches, as polygons on the
  satellite map, each with attached sensors (third-party devices or WIOT nodes). Kept separate from the Smart-farm
  layout, whose zones are irrigated fields.
- Editor (hand-written on Leaflet): 3-click rectangles (any rotation) and polygons, corner/midpoint/move handles,
  snapping, **Bench rows…** generator (width, path, margin, direction, live preview), undo/redo, keyboard shortcuts,
  drafts kept in the browser tab, containment warnings. Saving is versioned: a save based on an older version is
  refused (409) instead of overwriting; other open editors reload, or warn when they have unsaved edits
  (hub event `greenhouse_layout`).
- Latest readings per house, zone and bench (mean of fresh readings over the element's subtree, last 3 h).
- API: `GET/PUT /api/v2/greenhouses/layout` (up to 2 MB, 5,000 benches), `GET /greenhouses/live`,
  `GET /greenhouses/attachables`.

**Demo**: Demo_AgriFarm gets two greenhouses (66 benches) west of the pivots and four unsigned devices (two climate
sensors, a substrate probe with a µS/cm → dS/m mapping, a tank level sensor); `python -m wiot simulate` publishes their
JSON. `run-dev.ps1` and `devbroker --bridge` now also bridge `wiotx/Company_1/#`.

**Shell**: new icons, page-access keys `devices` and `greenhouses`, help articles, tour steps and What's new 2.8,
service-worker shell cache `wiot-shell-v2`, Arabic for every new string. Phone fixes for all pages: no more 16 px
sideways scroll (top-bar background), and Leaflet maps no longer paint over the bottom navigation or the sticky top bar.

**Review before commit.** Five independent reviewers (security, back end, Devices page, greenhouse editor,
integration), each finding checked by a skeptical second agent: 56 reported, 52 confirmed, all fixed. The main ones:
- Signed MQTT devices are rate-limited only after their signature is checked, so junk published to their topic on the
  public broker cannot block them (allowance 500 messages, then one per second, room for a buffered backlog).
- Field names that cannot be encoded (lone surrogates), integers too large for a float, nesting bombs and malformed
  TTN/ChirpStack bodies are ignored or answered with 4xx; webhook keys are checked before the body is parsed.
- Company names cached for the MQTT path (no query per message); registry cache cannot be refilled with stale rows;
  a device deleted while one of its messages is being stored does not get readings back.
- Deleting, disabling or moving a device publishes the "resolved" event of its silence alert.
- The demo devices are seeded once only; deleting them is final.
- Greenhouse readings: unsigned readings are counted and flagged ("untrusted"), a future unsigned time stamp is
  clamped, a sensor attached at two levels counts once, Sondas probes of WIOT nodes are included; layout warnings are
  computed once per save; at most 50,000 corners per layout.
- New settings `WIOT_DEVICE_MQTT_HOST/PORT` (the broker shown to devices); the page warns when the broker or the
  webhook address is not reachable from outside (set `WIOT_PUBLIC_URL`).
- Windows Mosquitto bridge (`deploy/windows/mosquitto.conf`) now carries `wiotx/Company_1/#`.
- Raw series keep the newest 20,000 points (`truncated` flag).
- Shell: a page left while it was loading no longer replaces the current page's clean-up (listener and timer leak);
  sign-out clears greenhouse drafts; the service worker keeps the old shell's files across the cache rename (offline
  start); the phone navigation scrolls sideways; map overlays stay under the sticky top bar.
- Devices page: exact scale/offset kept on save, live points only inside the chart window, gaps for silent periods,
  side panel refreshed live without touching the form, keyboard focus kept, secret box kept after Save, interval shown
  to the second, stale list responses ignored. Greenhouse editor: drafts survive a re-render, keyboard shortcuts
  right after drawing, saves in flight across re-renders, slanted-slot bench rows, readings only when the saved
  layout matches, corner drags that would collapse a shape are undone, size check in UTF-8 bytes, drafts per user.
- Help texts corrected (Bench rows fields, Latest readings, drafts kept per tab).

Tests: new `tests/test_trackg.py` (12). Full suite: 252 passed; browser smoke test (every page incl. Devices and Greenhouses, English and Arabic) passed.

## 2026-11-18 — Track G: second review (2.8.0)

A fresh, independent review of the pushed Track G code (`cb4fe72..5e086cf`) found five more defects, all fixed and
covered by `tests/test_trackg.py::test_overflow_clock_step_radio_range_and_alert_race` (each assertion was checked to
fail on the old code):
- A huge value times a mapping scale overflowed to infinity; the rejected value was kept for **Last payload** and the
  whole device list then failed with 400 ("not JSON compliant") until the device's next message. Non-finite results
  are now rejected with no value.
- A device whose clock stepped back (older `ts`, accepted for unsigned devices) stayed "heard" only at its previous
  message, so it turned **Silent** and raised `device_silent` while still reporting. The latest value still follows
  the newest measurement; the time of arrival now always advances.
- A silence sweep that had already read a device could reopen its alert after the device was deleted or moved to
  another region, and that alert was never resolved. The sweep and the clean-up now take one lock.
- RSSI and SNR from a network server skipped the metric range check; out-of-range values are now rejected like any
  mapped value.
- A page that failed after the user had already moved on (slow network) replaced the new page with its error.

Devices page: the **Readings** chart now sits under the device list, beside the editor, instead of below both (no
empty column on wide screens); on narrow screens the order is unchanged (list, editor, chart). Manual V2.1 rebuilt
with the new Devices screenshot (89 pp).

Tests: full suite 253 passed.
