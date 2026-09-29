# STM32 Arduino Remote Wake: Configuration and Acceptance Tests

## 1. Scope and important limits

Implemented in the Arduino STM32 node and Python web server only. ESP32 and
STM32CubeIDE are not modified. Existing NORMAL and RTC_PERIODIC modes remain
available; NORMAL remains the factory/default configuration.

REMOTE_WAKE is **not deep sleep or radio shutdown**. The selected ESP8266,
SIM800L or LoRa receiver remains NORMAL/connected. The STM32 pauses scheduled
sensor work and uses CPU Sleep (WFI), with UART and SysTick interrupts running.
This avoids a new wake wire and preserves UART data, MQTT keepalive and IWDG.
Radio power, external sensor supplies and regulator/LED consumption remain.
Measure whole-board current; no unmeasured mA reduction is promised.

An RTC_PERIODIC node whose ESP is in deep sleep or whose LoRa is in Mode 3
cannot receive this command while asleep. The new server does not persist a
WAKE queue for those nodes. Do not confuse broker publication with node wake.

## 2. Profiles and configuration

Edit the first block in `src/config/AppConfig.h`:

```cpp
#define APP_CONTROLLER_POWER_MODE APP_COMPONENT_MODE_REMOTE_WAKE
#define APP_LORA_POWER_MODE       APP_COMPONENT_MODE_NORMAL
#define APP_WIFI_POWER_MODE       APP_COMPONENT_MODE_NORMAL
#define APP_SIM_POWER_MODE        APP_COMPONENT_MODE_NORMAL

#define APP_POWER_SLEEP_SECONDS          300UL
#define APP_POWER_COMMAND_WINDOW_MS      5000UL
#define APP_REMOTE_WAKE_DEFAULT_SECONDS  60UL
#define APP_REMOTE_WAKE_POLL_INTERVAL_MS  100UL
```

Change the existing definitions inside their `#ifndef` blocks; do not add a
second conflicting definition farther down the file. Keep the existing
sensor true/false selections, unique Modbus addresses, credentials and node ID.

Select the transport as usual:

| Path | Application routing | IP modem selection |
|---|---|---|
| Direct SIM800 | SENSOR_NODE + MQTT_DIRECT | USE_SIM800 only |
| Direct Wi-Fi | SENSOR_NODE + MQTT_DIRECT | USE_ESP8266 only |
| LoRa node | SENSOR_NODE + LORA_TO_GATEWAY | Either one IP selection; IP is inactive |
| LoRa gateway | LORA_GATEWAY; controller and active radios NORMAL | Selected Wi-Fi or SIM |

The compiler rejects REMOTE_WAKE on a gateway, or REMOTE_WAKE with its selected
radio set to POWER_DOWN. SIM800 is supported in REMOTE_WAKE because it is never
powered off: the missing PWRKEY/DTR/RI wires do not need to wake an off modem.
SIM800 RTC_PERIODIC power-down remains blocked on this PCB.

### Timing meanings

| Setting | REMOTE_WAKE meaning |
|---|---|
| APP_POWER_SLEEP_SECONDS | Reachable-idle duration before an automatic fresh measurement/report cycle (5 seconds..7 days). Uses monotonic millis, not an RTC alarm. |
| APP_POWER_COMMAND_WINDOW_MS | Initial/automatic cycle stays active this long after its first successful Status send (0..60000 ms). |
| APP_REMOTE_WAKE_DEFAULT_SECONDS | Active duration when WAKE data is 0 (1..86400 seconds). |
| APP_REMOTE_WAKE_POLL_INTERVAL_MS | Maximum scheduled foreground radio/network poll interval while idle (10..1000 ms). UART activity can trigger earlier work. This is NOT an end-to-end command latency guarantee. |
| APP_POWER_SLEEP_ENTRY_TIMEOUT_MS | Used by the old RTC_PERIODIC handoff; no radio deep-sleep handoff occurs in REMOTE_WAKE. |

Use `APP_POWER_SLEEP_SECONDS 30UL` during the first bench test, and a WAKE
duration of 15 or 60 seconds. Restore the intended field interval afterward.

## 3. Runtime behavior

1. Boot normally, arm IWDG, connect the selected radio and initialize sensors.
2. Force a fresh sensor reading and Status send. A failed periodic report stays
   active for retry; existing network/watchdog recovery policy is unchanged.
3. After a successful Status and the command window, enter REACHABLE_IDLE.
   No scheduled RS485 sampling or Status transmission occurs here. MQTT/LoRa
   reception, keepalive, reconnect attempts and watchdog checkpoints continue.
4. UART interrupt or the 1-ms SysTick resumes CPU Sleep. Foreground polling is
   throttled by the configured interval when there is no UART activity.
5. A decoded, correctly targeted WAKE starts a timed ACTIVE lease without a
   controller reset. An immediate Telemetry acknowledgement confirms acceptance.
6. The normal loop then forces a fresh read of enabled sensors and a fresh
   Status report. Normal SRATE/STRAN settings govern further active sampling.
7. The active lease expires independently of ordinary telemetry success. Finish
   an in-flight publish/LoRa transaction, then return to REACHABLE_IDLE.
8. The next automatic cycle starts after the configured reachable-idle interval.

The lease is checked between foreground operations. An already-running Modbus
read or radio transaction can delay the return to idle; it is not cancelled
mid-frame. Report failures do not silently extend a commanded WAKE lease.

Other valid commands (STIME, GOSTM, rate changes, VALVE) remain processable while
reachable-idle, but only WAKE activates scheduled fresh sensor work. NORMAL
and RTC_PERIODIC profiles explicitly reject WAKE instead of pretending to wake.

## 4. Sending WAKE from the web server

Restart the updated web server normally using your existing private secrets.
Hard-refresh the browser so it loads the updated JavaScript/protobuf behavior.
No credentials are changed and tests never connect to a real broker.

In **Commands**:

1. Select the correct company and target node (topic and payload IDs must match).
2. Select **WAKE - remote active period**.
3. Enter seconds: `60` means active for 60 seconds; `0` uses the node default.
4. Click **Send Command**. Admin permission and owning-company access are required.
5. Observe **published; waiting for acknowledgement**. This is not an awake claim.
6. Wait for the same request ID in the node's Telemetry acknowledgement. The
   panel reports **confirmed ACTIVE** and seconds remaining at ACK generation.
7. The next fresh Status contains newly read sensor values.

The UI reports "no acknowledgement yet" after 20 seconds. That means unconfirmed,
not definitely asleep or failed. Late matching ACKs are still accepted. Latency
depends on modem/network, foreground sensor reads and LoRa retries.

Broadcast deliberately addresses all eligible nodes in that company. Each
node has its own acknowledgement. One ACK proves only that node is active,
not that the entire broadcast population received the command.

API example (requires an authenticated admin session):

```json
{"company":"Company_1","node_id":1,"cmd_type":"WAKE","cmd_data":60,"broadcast":false}
```

The API returns a nonzero request ID, `awaiting_node_ack: true` and
`node_awake: false`. The latter is intentionally not changed by broker acceptance.
The live ACK stream is the evidence of acceptance. Command history/logs retain
the request ID to match it with the responding node. Omitting `cmd_data` on a
WAKE API request sends 0, so the node uses its configured default duration.

## 5. Wire compatibility, ACKs and persistence

Existing command IDs 1..5 and all original protobuf field numbers are unchanged.
New fields are appended, so older receivers ignore them rather than misdecode
the established sensors. Old firmware does not support WAKE.

| Record | New tags / meanings |
|---|---|
| CMD_Message | ID 6=WAKE; cmd_data remains tag 3 (seconds). request_id appended at tag 4. |
| Status_Message | power_mode=32, power_state=33, wake_remaining_seconds=34. |
| Telemetry | power_mode=36, power_state=37, wake_remaining_seconds=38, wake_command_ack=39, wake_request_id=40. |

Wire mode: 0=unknown/legacy, 1=NORMAL, 2=RTC_PERIODIC, 3=REMOTE_WAKE.
Wire state: 0=unknown/legacy, 1=ACTIVE, 2=REACHABLE_IDLE.
These wire numbers differ deliberately from controller configuration values
0/1/2, so an old zero-filled payload is not mistaken for a capable remote node.

An accepted WAKE replies on the existing node Telemetry topic. LoRa carries the
same acknowledgement through the gateway's SystemTelemetry forwarding path.
ACK includes cached sensor values; it is **not a newly measured flow sample**.
The server stores the response/power fields in message history but does not
create meter_samples or consumption_periods from it, and does not plot it as a
fresh flow point. A subsequent Status is the fresh sensor report.

The last nonzero request ID is deduplicated in RAM. Repeating it while the
original lease remains active re-ACKs without extending the timer or resampling.
Changed-duration or expired duplicates are rejected. A new ID renews the lease.
Deduplication is intentionally bounded to the most recent request and clears
on controller reset; it is not durable replay protection or authentication.

RAM/application state is retained in CPU Sleep. Supmea RTC/backup/flash state is
unchanged, and its next reading accounts for cumulative volume during idle if
the meter remains powered. TUF period totals remain meter-native. Ordinary
power cycling or IWDG resets still reinitialize software and lose WAKE leases.

The existing AES-CBC/protobuf transport is preserved, not upgraded to an
authenticated transport. Request IDs are for correlation/deduplication only.
Do not interpret encryption or admin UI access as full network-level integrity,
replay prevention or protection against radio/broker-driven battery exhaustion.

## 6. Step-by-step hardware acceptance

Do these on a bench before field deployment. Host tests and successful builds
do not prove actual current, modem timing or packet delivery on your PCB.

| Test | Action | Expected evidence |
|---|---|---|
| 1. NORMAL regression | Compile NORMAL with all four sensors. | Existing sampling/publishing, RTC totals and WDT behavior unchanged. WAKE rejected. |
| 2. Remote startup | Compile controller REMOTE_WAKE, selected radio NORMAL; idle interval 30 s. | Boot logs report REMOTE_WAKE; first sensor sample and Status succeed. |
| 3. Reachable idle | Wait for 5-s command window. | `REACHABLE_IDLE; sensor work paused, radio and watchdog remain active`; no reset/reconnect handoff. |
| 4. Direct WAKE | During idle send WAKE 15 or 60 s. | Same request ID in Telemetry ACK; dashboard confirmed ACTIVE; fresh Status follows. |
| 5. Return to idle | Wait for active duration without another WAKE. | Original deadline is not extended by repeated Status sends; idle resumes after outstanding work finishes. |
| 6. Default / renewal | Send 0, then send a new WAKE request with a new ID. | Configured default accepted; new ID renews active duration. |
| 7. Duplicate | Republish exactly the same encrypted/request-ID command while its lease is active. | ACK again; no extra sampling and no lease extension. Expired duplicate cannot re-wake. |
| 8. Filtering | Send wrong node ID, malformed cipher, invalid duration or unauthorized company request. | No accepted WAKE/ACK and no activation of scheduled sensor work. |
| 9. LoRa path | Updated gateway NORMAL; remote LoRa node NORMAL radio. Send direct and broadcast WAKE. | Gateway forwards commands and node Telemetry ACKs. A single broadcast ACK does not confirm all nodes. |
| 10. Network loss | Disable Wi-Fi/GSM access or gateway connectivity while idle. | No false awake claim; existing reconnect/retry/watchdog recovery remains operational. |
| 11. Automatic cycle | Send no command for the 30-s reachable-idle interval. | Fresh sample/report, command window, then reachable idle again. |
| 12. RTC totals | STIME-sync; advance Supmea cumulative total while idle. | Next sample updates RTC consumption; TUF/HNDA/Sondas fields remain distinct. |
| 13. WDT | Use the existing controlled watchdog fault-injection guide. | Blocked foreground function resets at the configured hardware deadline; CPU Sleep does not feed the watchdog from an ISR. |
| 14. Legacy deep sleep | Compile existing Wi-Fi/LoRa RTC_PERIODIC profiles. | Existing radio deep sleep, reset-to-Standby and RTC wake remain; no remote-wake claim. |
| 15. Current | Measure whole-board NORMAL, REMOTE_WAKE idle and RTC_PERIODIC sleep. | Record actual average/peak current and wake latency. Remote idle is expected to save less than deep sleep. |

## 7. Automated verification commands

From the repository root in PowerShell:

```powershell
& 'Node/IoT_Node_Encrypted/tests/remote_wake/run_tests.ps1'
& 'Node/IoT_Node_Encrypted/tests/rtc_supmea/run_tests.ps1'
python -m unittest discover -s 'Server/WIOT-Server-Web v1.31 - Fixed Sensor Readings in Dashboard/tests' -v
node 'Server/WIOT-Server-Web v1.31 - Fixed Sensor Readings in Dashboard/tests/test_wake_control.js'
& 'Node/IoT_Node_Encrypted/tests/remote_wake/run_build_matrix.ps1'
```

The remote host runner compiles the real PowerManager.cpp and CommandHandler.cpp
with strict warnings; only hardware/transport seams are fake. It also checks
18 valid/invalid policies against the real AppConfig preprocessor guards.
The build matrix
uses the actual STM32 Arduino core and all four sensor drivers. It writes only
temporary build outputs, never private configuration files or hardware flash.

If a tool is not on PATH, pass `-CompilerPath` to either host runner, or
`-ArduinoCli` / `-ConfigFile` to the firmware matrix script. Existing bench
settings are overridden only by compiler flags, never rewritten in AppConfig.h.

### Verification record: 2026-09-29

- Actual PowerManager/command host regression: PASS, including rollover,
  failed delivery, UART polling, request filtering, duplicate leases and ACKs.
- Real AppConfig compile-time policy guards: 18 checks passed.
- Existing RTC/Supmea regressions: 16 scenarios passed.
- Python wire/API/SQLite/sensor regressions: 32 tests passed.
- Dashboard acknowledgement tracker and JavaScript syntax checks: PASS.
- All seven builds below: PASS with STM32 Arduino core 2.12.0 and the
  `GenF4:pnum=BLACKPILL_F401CC` target. All four sensors are enabled for sensor
  node builds; the gateway role retains its existing no-sensor behavior.

| Build profile | Flash load end (exclusive) | RAM reported by Arduino |
|---|---|---|
| NORMAL / SIM800 | 0x080143E4 | 18960 bytes |
| REMOTE_WAKE / SIM800 | 0x08014804 | 18996 bytes |
| REMOTE_WAKE / Wi-Fi | 0x080148A4 | 18996 bytes |
| REMOTE_WAKE / LoRa | 0x08014ABC | 23648 bytes |
| RTC_PERIODIC / Wi-Fi | 0x0801543C | 18992 bytes |
| RTC_PERIODIC / LoRa | 0x0801551C | 23636 bytes |
| NORMAL gateway / Wi-Fi | 0x0800E0AC | 23880 bytes |

The build runner verifies LOAD sections stay below the EEPROM emulation sector
at 0x08020000. The synchronized node/server schemas also have identical hashes.
These are software verification results, not completed hardware acceptance:
no controller was flashed, no production server was restarted, and current or
physical wake latency was not measured. Complete section 6 before deployment.

Regenerate bindings after changing the canonical node schema and synchronized
server messages.proto/sensor.proto:

```powershell
python -m nanopb.generator.nanopb_generator -I 'Node/IoT_Node_Encrypted/src/generated' -D 'Node/IoT_Node_Encrypted/src/generated' -L '#include "../third_party/nanopb/%s"' 'Node/IoT_Node_Encrypted/src/generated/sensor.proto'
protoc '--proto_path=Server/WIOT-Server-Web v1.31 - Fixed Sensor Readings in Dashboard' '--python_out=Server/WIOT-Server-Web v1.31 - Fixed Sensor Readings in Dashboard' messages.proto
```

## 8. Troubleshooting

- **No ACK:** verify REMOTE_WAKE configuration, company/node IDs, gateway version,
  selected radio NORMAL, MQTT connection and matching request ID in node logs.
- **ACK but old sensor values:** expected for the immediate ACK. Look for the
  following fresh Status; verify the sensor simulator responds at each address.
- **No idle:** first periodic report has not succeeded, command window not expired,
  or an active publish/LoRa transaction is still finishing.
- **Current remains high:** radio and externally powered sensors remain on; CPU
  Sleep is short-lived because UART/SysTick must maintain remote reachability.
- **WDT reset while idle:** inspect last watchdog stage. Network/AT calls may
  still hang; the watchdog must recover them rather than be fed by an ISR.
