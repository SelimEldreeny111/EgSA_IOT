# WIOT server validation — Phase 1 release

4 October 2026. Branch: `feature/2026-10-04-server-validation-phase1`.
Baseline: `24b538846340d4d59c495b16004dd818d46f5e5f`.

This is the first compatible implementation of the approved validation plan.
It changes the Python server/dashboard and regression runner, not the STM32
firmware, ESP32, CubeIDE, simulator behavior or protobuf field numbers.
Keep the existing 30-second WDT, power policies, four sensors and valve inhibit.

## What changed

| Reviewed finding | Delivered behavior |
| --- | --- |
| S01 — log isolation | Infrastructure/MQTT/raw diagnostics and shared log export are supervisor-only. Authenticated browser logs go to their own company and the supervisor. Invalid log objects/overlong messages are ignored; line breaks and common named secret assignments are sanitized. |
| S02 — HTML injection | Logs use textContent, with at most 1,000 visible lines. Dynamic history, users, companies, toasts, thresholds, map popups and locations escape text and quoted attributes. Dynamic buttons use event handlers, not interpolated JavaScript. Browser headers and same-origin socket checks are enabled. |
| S03 — shared MQTT ownership | Only **EgSA_Supervisor** can connect/disconnect the one shared MQTT client. It subscribes to all companies. Company admins still command their own nodes; Super_User still monitors/switches companies but cannot stop shared ingestion. Company switching updates monitoring socket rooms without restarting MQTT. |
| S04 — storage identity | New tenant filenames use a full SHA-256 identity derived from the immutable, case-sensitive company topic ID. Existing uniquely owned legacy DBs retain their names/data. Windows case-folding and lossy-name collisions/mixed ownership are blocked. The preflight tool does not migrate anything. |
| S05 — topic routing | Exact four-segment `EgSA/company/node/suffix` validation. Status, Telemetry and CMD suffixes are explicitly supported, case-insensitively. Root remains exactly EgSA. Company names containing Status/CMD no longer select the wrong parser. BroadCast is allowed only for CMD echo/history. |
| S08 — semantic validation | Non-finite primary/secondary measurements, unsupported known enums/masks/counts, out-of-range times/SQLite totals and invalid IDs are rejected before storage, live updates or command-ACK handling. Legacy omitted fields/zero defaults and legitimate reverse flow remain supported. |
| S09 — MQTT readiness | CONNACK is not readiness. All subscription MIDs require successful SUBACK before the UI/commands consider MQTT ready. Local failure, broker rejection or 15-second missing SUBACK fail closed and disconnect. Fix ACL/network, then explicitly reconnect; no endless ACL-denial retry loop. |

API bodies are bounded to 64 KiB; body-bearing mutations require JSON objects.
Rate command data is seconds (5–86,400); the current firmware's Telemetry rate
fields remain milliseconds (5,000–86,400,000), with zero accepted for legacy defaults.
Company/node/port inputs reject signs, booleans, fractional IDs and invalid types.
Cross-origin mutations with an Origin header are rejected. Session cookies use
HttpOnly and SameSite=Lax. This is not a complete CSRF/session-revocation release.

## Start and use it

1. Stop the previous server normally. Back up runtime databases before deployment.
   Do not run two ingestion servers against the same files.
2. Use your existing final folder and Python environment. The private files,
   node configuration, databases and passwords are not replaced by this release.
3. Run the **read-only** preflight from the server directory:

   ```powershell
   & C:\Python314\python.exe .\tenant_storage.py --main-db .\iot_data.db --messages-dir .\messages_dbs
   ```

   Expected: `safe_to_start: true`, `issues: []`. The real final-folder preflight
   passed during delivery. If issues are reported, stop: preserve originals and
   obtain approval for a tenant-specific migration. Do not manually rename/delete
   a shared DB or create empty replacements. This tool has no write/migrate option.
4. Launch from the server directory, as before:

   ```powershell
   & C:\Python314\python.exe .\server_web.py
   ```

   First-time user creation still requires private `WIOT_ADMIN_PASSWORD`,
   `WIOT_SUPERVISOR_PASSWORD` and `WIOT_MONITOR_PASSWORD` environment settings.
   This release does not restore insecure hard-coded passwords. For stable sessions,
   configure `WIOT_FLASK_SECRET_KEY` privately. Existing accounts keep their passwords.
5. Log in as **EgSA_Supervisor**, open Configuration, enter broker host/port,
   client ID and the matching node AES key, then click Connect.
   The duplicate hidden broker fields were removed: each input now has one ID.
6. Wait for **Ready — SUBACK confirmed**, not just “connection requested”.
   A successful HTTP Connect response means initiation only. Check System Logs
   for subscription failure; reconnect after resolving it. Network loss clears
   readiness and ordinary Paho reconnects must resubscribe successfully.
7. Log in as a company admin to monitor that company's nodes and send commands.
   Connect/Disconnect, shared broker configuration and shared log download are
   deliberately unavailable there. Shared readiness is refreshed every five seconds.
8. Reloading any page no longer automatically replaces MQTT ingestion.
   Broker/client settings remain in browser storage, but AES keys do not. Previous
   cached key fields are removed on dashboard loading. Enter the key again when
   explicitly reconnecting. Do not enter secrets into client/system log messages.

Company IDs use 1–80 ASCII letters/digits/spaces/underscore/hyphen, without
leading/trailing spaces, MQTT wildcards or slash. `__all__` is reserved for the
supervisor room. Names are immutable topic identities in this compatible release;
there is no rename API. Friendly display names/approved ambiguous-DB migration
are later registry work, not automatically applied here.

## Test each correction separately

Use an isolated bench/test database and harmless text markers. Keep the valve
coil disconnected; no actuator or real MQTT test was run during delivery.

| Test | Expected |
| --- | --- |
| Company A and B browsers; A submits a harmless log marker | A and supervisor see it; B does not. Infrastructure logs and export are supervisor-only. |
| Log/user/history text containing `<b>text</b>` and quotes | Text appears literally; it does not become a tag or new attribute. |
| Company admin/monitor calls Connect or Disconnect | HTTP 403; existing global client is untouched. Supervisor can initiate it. |
| Supervisor switches dashboard company; Super_User switches company | Ingestion stays unchanged. The monitoring socket leaves the old room and joins the chosen registered company. |
| New names `Audit Space`, `Audit_Space`, `audit_space` | Different stable filenames; no case-insensitive alias. An ambiguous existing legacy file blocks startup/access. |
| Telemetry on `EgSA/AuditStatusCompany/7/Telemetry` | Parsed as Telemetry, never Status. Wrong root/extra segments/unknown suffix are rejected. |
| Inject NaN/Inf or invalid known mask/enum into either meter | No DB/live/ACK effect; validation diagnostic visible to supervisor. |
| Broker accepts connection but denies subscription | Never shows ready; direct commands remain unavailable. Missing SUBACK times out after 15 seconds. |
| Node ID true, 1.7, 0 or 65536 in any command | HTTP 400, no publish. Whole node IDs 1–65535 remain supported. |
| Status/Telemetry from the existing four-sensor node | Both meters, soil sensors, battery, power, WDT count and command replies still decode without schema changes. |

Automated verification from the final release root:

```powershell
.\Validate-Release.ps1 -Python C:\Python314\python.exe -Compiler "D:\Library\3-Programs\IMT Tools\TOOL\mingw64\bin\g++.exe" -NodeJs "C:\Users\Selim\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe"
```

This command uses temporary databases/fakes, never production credentials or MQTT.
See [verification](SERVER_PHASE1_VERIFICATION.md) for results and limits.

## Compatibility, remaining work and rollback

This is not production security certification. AES-CBC still lacks authentication
and replay protection; broker TLS/ACL and per-node keys remain Phase 4. Do not
activate valves on an untrusted/public command channel. Semantic validation does
not authenticate who sent a packet. Raw encrypted byte dumps default off; debug
must be enabled deliberately in code and is for controlled bench diagnostics only.

The approved following phases remain: command ordering/correlation (including
S07); sticky/calendar-finalization and reviewed durable storage; authenticated
envelopes; receipt/outbox/freshness diagnostics (including S06); deployment/CI,
session revocation, full CSRF and strict no-inline CSP. Current CSP intentionally
allows existing inline UI handlers/styles and approved CDNs; it is not a complete
HTML-injection defense by itself. Full browser/hardware/load/soak tests remain.

No live DB migration or firmware upload was performed. Ambiguous migration,
storage hardware, calendar authority and authenticated protocol need the design
choices identified in the validation plan. Current relative runtime paths still
require launching from the server directory; absolute-path/app-factory work is later.

Replaced final-folder public files and metadata are recoverable under
`backups/before_server_validation_phase1_20261004`. Stop the server before restoring
them. Restore only the backed-up public files, not private settings or databases.
New modules/tests can remain unused by the old source; the old server/template
must be restored together. Keep data backups and do not downgrade an ambiguously
owned tenant DB into the old lossy-name implementation.
