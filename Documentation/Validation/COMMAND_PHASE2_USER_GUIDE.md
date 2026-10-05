# WIOT command lifecycle — Phase 2

5 October 2026. Branch: `feature/2026-10-05-command-lifecycle-phase2`.
Baseline: `353b70e783519af637b722b0ee4807221c0d55d4` (server Phase 1).

## Scope

This compatible release implements the command reliability stage of the approved
node/server validation plan. Every command now has a nonzero unique 32-bit request
ID and a durable record of its company, target, operator, type, data, delivery,
acceptance time, expiry, attempts/MQTT MIDs, broker receipt, matching node reply and events.
No protobuf changes are required: the existing request/ACK fields are used.
SIM, WiFi and LoRa share the ordinary STM32 command handler; WAKE keeps its separate
expiry-aware PowerManager behavior. No ESP32/CubeIDE port changes are included.
All four sensors, RTC consumption, zero-on-failed-poll, 30-second WDT, 10+10
network recovery, voltage, power profiles and valve safety settings are retained.

## Deploy and operate

1. Stop the old server normally. Keep a backup of the entire runtime DB set while
   it is stopped, including any SQLite sidecars. Run one ingestion server only.
2. Work in `WIOT_Final_PowerModes_20261001`. Private AppConfig.cpp/AppSecrets.h,
   node_config.json and live databases are not replaced. No power-mode or valve
   commissioning setting needs to change for this release.
3. Flash the updated Arduino STM32 sketch using the existing STM32 core/RTC
   versions and your existing board configuration. No automated upload is performed.
   The supplied ARM test profiles are compile fixtures, not valve pulse specifications.
4. Start the existing server launcher/environment. On first journal use, the server
   creates `command_lifecycle.db` beside server_web.py. It reads the old
   `pending_commands.db` once, without modifying it. Imported rows have unknown
   legacy actor/publication proof. Earlier active value/valve intents are retired
   in favor of their newest legacy replacement. The old mailbox remains recoverable.
   Import failure blocks dispatch; it never starts an empty replacement silently.
5. Sign in as EgSA_Supervisor to connect the shared MQTT client. Wait for successful
   SUBACK readiness. Company admins may then command their own nodes.
6. In Commands, select the company/node, command and delivery. Send once, retain
   its request ID, and inspect **Command execution timeline**, refreshed every five
   seconds while the tab is visible. It shows the last 50 intents, not wire echoes.
   Hard-refresh the browser after deployment if the new panel is missing.
7. Backup `command_lifecycle.db` with the other runtime files going forward.
   Do not delete it to clear a timeout: this loses audit/receipt history.

The journal must be writable before a command may be dispatched. If it is
unavailable/full/locked beyond SQLite's five-second bound, dispatch fails closed.
There is no unaudited emergency bypass. A failure after submission is reported as
unknown and retains the request ID. A separate historical message-copy failure
does not negate submission; the command journal is authoritative for this feature.

## State meanings

| Timeline / DB state | What it means | What it does not mean |
| --- | --- | --- |
| Queued / pending | Persisted, not yet claimed for dispatch | Node has received it |
| Submitted / dispatched | A publication attempt started; await node ACK | Broker receipt or execution success |
| Broker receipt timestamp | QoS 1 PUBACK received and audit persisted | Node execution |
| Waiting retry / waiting_retry | A queued rate request may retry on a later Status | Continuous background retry |
| Node accepted / acknowledged | Matching company, node, request ID and command ID replied success | Physical valve position or newly sampled sensors |
| Node rejected / rejected | Matching reply reports rejection | A hardware measurement proving closed/open |
| Expired / expired | TTL ended before any submission | Submitted action definitely failed |
| Replaced / superseded | Newer desired-value intent retired this one | An earlier submitted packet was cancelled at the broker/node |
| Outcome unknown / outcome_unknown | Submitted, but no matching reply by the deadline/TTL | Success, failure, or safe permission to resend a physical action |
| Individual replies / broadcast_partial | One or more nodes replied to a company broadcast | All expected nodes executed it |

Late matching replies are recorded. A direct unknown result can become accepted
or rejected when proof arrives. A superseded row remains superseded even after a
late reply. Duplicate replies cannot create duplicate receipts/audit effects.
Broadcast node target is 0 in the journal; per-node receipts are available through
inspection below. No expected fleet registry exists, so aggregate broadcast
completion is intentionally never asserted.

GOSTM/command ACK payloads may use cached sensor values. Existing handling excludes
them from new flow samples/consumption calculations. Confirm actual new sensor
readings using the regular fresh Status/Telemetry validity fields.

## Delivery, timing and ordering

| Policy | Behavior |
| --- | --- |
| Now | Requires MQTT readiness; one automatic publication attempt for any command |
| Next wake | Direct node only; one eligible command claimed after each valid Status |
| ACK deadline | 30 seconds after the latest claim; state evaluated on inspection or new queue activity |
| Retry | Only queued SRATE/STRAN, at most three attempts total, at least 15 seconds apart and only on Status |
| Never auto-retry | VALVE, WAKE, STIME, GOSTM; transport QoS duplicates remain possible |
| TTL | Default 86,400 seconds; configurable 60–604,800 seconds |
| Queue bounds | At most 32 active intents per company/target; timeline API limit 1–200 |
| Priority | Operator-requested queued VALVE first, then fresh pending commands, then old rate retries; stable FIFO ID order within each group |
| Supersession | New SRATE/STRAN/STIME/VALVE retires earlier active same-type intents for that company/node; a new company broadcast also retires earlier direct same-type intents |

STIME uses the current server epoch once at first dispatch; it is never refreshed
and resent automatically. A newer direct command does not undo a previously sent
broadcast. WAKE and GOSTM are not superseded as desired-value settings.
Only one command is sent per Status to protect the awake window. An operator
command marked `now` is not automatically converted into a sleeping-node mailbox
command on failure. Choose `next_wake` explicitly for RTC-sleeping nodes.

PUBACK handling enqueues bounded audit work on a separate worker: it never waits
for publication completion inside MQTT RX. There are at most 256 unresolved
publication callbacks and 256 completion jobs. Saturation/failure cannot be shown
as confirmation. If the confirmation window remains full because the connection
has failed, inspect unknown outcomes before an explicit broker disconnect/reconnect.
The command journal remains intact. This is not a disk-retention/operations release.

## STM32 duplicate behavior

Eight recent nonzero ordinary request IDs are remembered in RAM with the complete
command data, target and broadcast flag. Same ID/same intent returns the original
accept/reject result without repeating the side effect. Same ID/different intent
is rejected. Request ID 0 keeps legacy behavior. WAKE uses its existing lease-aware
duplicate checks, so an expired duplicate does not restart the awake lease.

FIFO eviction after eight distinct ordinary intents and any reboot/Standby loses
this cache. It is not persistent security anti-replay. A packet first seen after a
newer command cannot be classified as stale by this cache. MQTT delivery can still
be delayed/duplicated, especially across reconnects. Do not treat a submitted valve
command as cancelled just because it is superseded. Check the commanded-state
telemetry and the actual valve safely before deciding whether to issue a new intent.

## Inspect through the API

Use the authenticated browser/session; admin company scope still applies:

- `GET /api/commands?company=Company_1&limit=50`: bounded recent intents.
- Add `node_id=7` to filter one node, or `node_id=0` for broadcasts.
- `GET /api/command/REQUEST_ID?company=Company_1&node_id=7`: intent, receipts and
  ordered audit events; use node_id=0 for a broadcast.
- `/api/queued_command/REQUEST_ID` remains a compatible inspection alias.

## Step-by-step acceptance tests

Perform bench tests first with valve actuation inhibited (existing zero pulse
defaults / unconfirmed polarity). Never invent coil pulse times. Network/hardware
tests below are required acceptance work, not automated-test claims.

| Test | Action | Expected |
| --- | --- | --- |
| T1 — every command | Send SRATE=60, STRAN=120, STIME, GOSTM, WAKE in a compatible mode; test VALVE only inhibited or safely commissioned | Each API result has a different nonzero ID; timeline actor/target correct; matching replies accept or reject |
| T2 — broker versus node | Disconnect the test node but keep broker ready; send one GOSTM | Broker timestamp may appear; after 30 seconds/polling result unknown, never accepted |
| T3 — delayed reply | Restore the node/allow delayed same-request reply | One late receipt recorded; unknown resolves only on matching reply |
| T4 — queued supersession | Offline node: queue SRATE=60 then SRATE=120; bring it online | First is superseded; only the newest pending rate dispatched |
| T5 — no head blocking | Leave a submitted rate request unacknowledged; queue a new STRAN and, if safe, a VALVE intent | Fresh intent selected ahead of old rate retry; VALVE priority is explicit operator intent only |
| T6 — bounded retry | Drop rate ACKs with a controlled broker/test harness; emit repeated Status | Same request ID, at most three claims; no fourth automatic retry |
| T7 — non-repeatable | Drop a WAKE/VALVE/STIME/GOSTM reply | No automatic application resend on later Status; unknown is shown |
| T8 — duplicate side effects | Controlled harness sends an identical ordinary command twice, then reuses ID with changed data | Original result replied without second effect; changed tuple rejected; STIME does not rewind and VALVE does not pulse twice within cache scope |
| T9 — scope and broadcast | Try another company's API; send safe GOSTM broadcast to two test nodes | Cross-company API denied; receipts are individual, no all-fleet success claim |
| T10 — expiry/restart | Queue 60-second TTL command offline; let it expire; restart server with same journal | Expired-before-submission never dispatched; history retained; import is not repeated |
| T11 — all uplinks | Repeat direct and next-wake tests under appropriate SIM/WiFi/LoRa power policies | Same correlation/duplicate policy; no bypass of sleep-profile restrictions |
| T12 — preserved features | Run four-sensor simulator, failed polls, RTC totals, WDT and network retry tests | Existing readings/validity, reset count, 30-second watchdog and 10+10 recovery remain correct |

Automated checks: run the root `Validate-Release.ps1` with your installed Python,
g++ and Node.js paths. For full firmware compilation use the existing
`Node/IoT_Node_Encrypted/tests/remote_wake/run_build_matrix.ps1`. For API reference
run `Node/IoT_Node_Encrypted/generate_doxygen.ps1`. None of these uploads firmware.

## Rollback and remaining stages

Stop the server first. Public pre-change files are backed up in the final folder's
dated Phase 2 backup; restore only those scoped files and their previous sketch
if rollback is required. Never overwrite private settings or live DBs. The old
server ignores command_lifecycle.db and would resume its old pending_commands.db;
reconcile those old pending intents before running it, or they can be dispatched
again. Obtain operator approval before retiring/cancelling intents. Keep both DBs
and backups; no automatic backward DB migration is provided.

Phase 3 consumption quality/storage, Phase 4 authenticated framing/TLS, Phase 5
outbox/receipt/freshness and Phase 6 operations remain separate stages. Existing
AES-CBC/plain MQTT cannot authenticate node ACKs or prevent adversarial replay.
This release is not a production security certificate or physical valve-position
confirmation. Hardware current/sleep/coil/network acceptance remains necessary.
