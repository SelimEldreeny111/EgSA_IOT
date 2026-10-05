# Optional command telemetry acknowledgements

5 October 2026. Arduino STM32 node only. Default is enabled; ESP32, CubeIDE,
server source and protobuf field numbers are unchanged.

## Configuration

Edit the existing definition near the beginning of `src/config/AppConfig.h`:

```cpp
#define APP_ENABLE_COMMAND_ACK_REPLIES true
```

Use `true` to keep current command success/rejection replies, or `false` to
suppress them. Rebuild and flash your normal configured sketch after changing it;
this is not a runtime server command. Do not add a second conflicting definition.
Compiler overrides are also supported, for example
`-DAPP_ENABLE_COMMAND_ACK_REPLIES=false`. Invalid values such as 2 are rejected.

| Command/path | true | false |
| --- | --- | --- |
| SRATE / STRAN / STIME | Apply or reject, then correlated Telemetry ACK | Apply or reject without automatic Telemetry ACK |
| VALVE | Existing commissioning/safety checks, then result reply | Same safety checks/action; no automatic result reply, including legacy request ID 0 |
| WAKE | Apply or reject lease, then result/power reply | Same lease behavior; no automatic result/power reply |
| GOSTM | Requested Telemetry response | Still responds: telemetry is the command's purpose; correlation fields are retained |
| Periodic Status | Existing scheduled reports | Unchanged |
| MQTT/PUBACK and LoRa fragment ACKs | Existing transport operation | Unchanged; this switch controls application replies, not transport handshakes |

The policy is shared by SIM/WiFi MQTT sensor nodes and the LoRa sensor-node
command path. A LoRa gateway forwards commands/replies unchanged; configure the
sensor node's ACK switch. Wrong-node and undecodable packets remain ignored.
The eight-entry ordinary duplicate cache and WAKE lease duplicate checks remain
active even if application replies are disabled. Turning off replies does not
enable an inhibited valve, disable WDT, change sensors or put a modem to sleep.
With true, the existing request-ID rules are preserved: correlated ordinary
action replies require a nonzero request ID. Existing legacy VALVE/WAKE reply
rules are not expanded; their automatic replies are also gated by this switch.

The switch suppresses response creation before encryption/queueing/transmission,
not merely the ACK fields in an otherwise transmitted payload. Debug command and
rejection logs remain available; a suppression log replaces the automatic reply.
GOSTM still uses cached RS485 measurements; it does not force a new sensor poll.

## Server consequence — important

The server cannot infer this compile-time setting, so it continues journaling
commands and waiting for matching execution replies. With false, a submitted
action will normally become **Outcome unknown** after its 30-second ACK deadline
(checked on inspection/activity), even if it was applied. Broker receipt is not
node execution. WAKE's immediate confirmed-active indicator also requires its
reply; ordinary later Status can show power state but does not complete that
command journal entry. Do not display assumed success or disable server checks.

Queued SRATE/STRAN may still be submitted up to three times because no matching
reply arrives. Choose delivery **Now** if you want a single application dispatch
attempt rather than that queued-rate retry policy. WAKE/VALVE/STIME/GOSTM are
not automatically application-resubmitted. Duplicate physical wire delivery is
still possible; no persistent exactly-once/security guarantee is introduced.
GOSTM's explicit correlated response can still complete its journal entry.

## Step-by-step tests

1. Keep valve actuation inhibited unless separately and safely commissioned.
   Compile with true. Send SRATE=60, STRAN=120, STIME, WAKE in a supported mode
   and an inhibited VALVE command. Confirm matching accepted/rejected ACKs.
2. Change only the macro to false; rebuild and flash. Send SRATE=60 once with
   delivery Now. Debug must show the setting applied and ACK disabled, without
   `HANDLE GET TELEMETRY CMD` for this action. Later periodic telemetry/Status
   should reflect the changed setting. Timeline execution remains unknown.
3. Repeat with STRAN, STIME and WAKE. WAKE still changes the active lease; it must
   not send an immediate application ACK. Test an inhibited VALVE request:
   rejection remains in debug, no automatic telemetry reply and no coil pulse.
4. Send GOSTM with false. Confirm that the requested Telemetry response still
   arrives, with its matching request ID. Normal periodic Status must continue.
5. Repeat under SIM and WiFi. For LoRa, flash the sensor-node false configuration
   and use a normal available gateway. Compare logical SystemTelemetry frames:
   action commands do not produce them; GOSTM still does. LoRa fragment ACK frames
   continue as required for transport reliability.
6. Restore true, rebuild and flash; automatic ACKs must return. Do not compare
   multiple settings using binaries from different folders by accident.

Automated verification includes actual SIM/WiFi MQTT callbacks with replies
enabled/disabled, shared reply-policy decisions for all six commands, policy
configuration guards and real STM32 builds with ACKs disabled for all three
transports. Full host/server/simulator checks use root `Validate-Release.ps1`.
Compile-only valve test binaries are not safe commissioning specifications.
