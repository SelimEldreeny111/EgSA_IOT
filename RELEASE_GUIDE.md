# WIOT STM32 release guide

**4 November 2026.** The [current system review](Documentation/Validation/WIOT_SYSTEM_REVIEW_20261104.md)
describes the node, gateway, server, simulators, two-node bench setup and checks.
The gateway subscribes to direct and regional broadcast commands. A due
Status takes its turn after an acquisition completes, even when sensor
timeouts run past the sampling interval.

New: separate retained power/WDT counters; direct-node clear commands 7/8;
server reporting/migration/CSV; independent SUPMEA D/M/Y reference in both
sensor simulators, with no new Modbus registers. See
Node/IoT_Node_Encrypted/RESET_COUNTERS_AND_SUPMEA_REFERENCE_GUIDE.md.
The updated multi-sensor EXE is in SENSORS/Multi Sensor RS485 Simulator/dist/20261025.
The old running instance was left untouched. ESP32/CubeIDE remain unchanged.

REMOTE_WAKE now defaults to independent SRATE/STRAN deadlines with reachable
CPU idle between work and commands. The old fixed-interval policy remains
available through APP_REMOTE_WAKE_USE_APP_SCHEDULE=false. Explicit WAKE remains
an active lease. See [configuration and tests](Node/IoT_Node_Encrypted/REMOTE_WAKE_APP_SCHEDULE_GUIDE.md).
No server/schema/pin or separate ESP32/CubeIDE changes are required.
See [remote scheduling verification](Documentation/Validation/REMOTE_WAKE_APP_SCHEDULE_VERIFICATION_20261005.md)
for both-copy regressions, all 16 ARM builds and remaining physical acceptance.

Automatic command ACK replies are now independently configurable through
`APP_ENABLE_COMMAND_ACK_REPLIES` in the Arduino STM32 AppConfig.h (default true).
See [ACK configuration and tests](Node/IoT_Node_Encrypted/COMMAND_ACK_CONFIG_USER_GUIDE.md).
GOSTM and periodic Status remain available when automatic ACKs are disabled;
the server cannot then confirm silent action execution. No schema/port changes.

Phase 2 adds a durable command execution timeline, IDs for every command,
bounded queued-rate retries, supersession and asynchronous broker receipt audit.
The Arduino STM32 command handler suppresses eight recent ordinary duplicate
requests in RAM. See [Command lifecycle guide](Documentation/Validation/COMMAND_PHASE2_USER_GUIDE.md)
for deployment, limits and step-by-step tests. No protobuf numbers or pins changed;
private settings, sensor/RTC/WDT/power behavior and separate ports are preserved.

The compatible server-validation Phase 1 update is documented in
[Server Phase 1 guide](Documentation/Validation/SERVER_PHASE1_USER_GUIDE.md).
Shared MQTT controls/log export are now EgSA_Supervisor-only, and readiness
requires successful SUBACK. Firmware, schema and private bench settings are unchanged.

This branch contains the full project sources, not just changed files. Continue
bench work in `WIOT_Final_PowerModes_20261001`. Its `FINAL_COPY_INFO.md` records
the matching commit and local backups. The separate development Git checkout
is used for commits; the final folder is a standalone snapshot with private
settings, not a Git checkout. Do not upload that entire folder.

## Package and entry points

See `RELEASE_AUDIT_20261003.md` for audit findings, verified checks and remaining
physical acceptance tests.

The 4 October latching-valve addition uses TB6612FNG channel A: PB9/PB15
direction and original PC13 as STBY. Read
[Valve commissioning and tests](Node/IoT_Node_Encrypted/LATCHING_VALVE_USER_GUIDE.md)
before connecting or enabling the coil. Zero pulse times and unconfirmed
polarity inhibit actuation. This branch carries the earlier commissioned 50 ms
values. Valve telemetry reports commanded, not measured,
position; missing/interrupted records report Unknown. Earlier static-PC13 and
RAM-only valve descriptions are superseded. All sensor/RTC/WDT/power policies
and the separate ESP32/CubeIDE projects remain unchanged.

| Component | Entry point / documentation |
| --- | --- |
| STM32 Arduino node and LoRa gateway | `Node/IoT_Node_Encrypted/IoT_Node_Encrypted.ino`, project `README.md` |
| Python web server | `Server/WIOT-Server-Web v1.31 - Fixed Sensor Readings in Dashboard/server_web.py` |
| Four-sensor/multiple-address simulator | `SENSORS/Multi Sensor RS485 Simulator/multi_sensor_simulator.py`, `README.md`, `TEST_PLAN.md` |
| TUF focused simulator | `SENSORS/TUF2000B Flow meter/simulator/tuf2000b_simulator.py`, `README.md` |
| Supmea focused simulator | `SENSORS/Supmea Flow meter/simulator/supmea_fmc240_simulator.py`, `README.md` |
| Arduino API documentation | `Node/IoT_Node_Encrypted/Doxyfile`, `generate_doxygen.ps1`, `DOXYGEN_MAINPAGE.md` |
| Behavioral/configuration guides | Node `*_GUIDE.md`, server guides; consolidated `Documentation/PowerModes/WIOT_Power_Modes_Reference.md` and printable PDF |
| Supplied manuals and specifications | `SENSORS`, `Node SW Specs`, `outputs` |
| Repeatable verification | `Validate-Release.ps1`, `tests/release_audit`, node/server/simulator tests |

ESP32 and STM32CubeIDE are included as existing alternate ports, unchanged by
this release audit. They do not automatically inherit recent STM32 Arduino
features. Spreadsheet reports and legacy server notes are historical records;
the current feature guides and code below take precedence over older claims.

## Features retained and checked

| Feature | Current contract and guide |
| --- | --- |
| Four sensors | Independent enables and addresses; unique enabled RS485 IDs. TUF/Supmea are separate flow records; HNDA and Sondas have separate soil fields. `FLOW_METER_PROFILES_AND_CONSUMPTION_GUIDE.md` |
| Calendar volumes | TUF reads native day/month/year registers. Supmea uses cumulative volume differences with trusted RTC and persisted calendar baselines. `SUPMEA_RTC_RESET_FIX_AND_TEST_GUIDE.md` |
| Zero unavailable readings | Failed groups encode zero plus invalid flags; saved Supmea baseline/history is retained. `SENSOR_UNAVAILABLE_ZERO_GUIDE.md` |
| SIM800 / ESP8266 | Compiled Wi-Fi credentials first, saved credentials fallback. TinyGSM owns modem AT traffic. Commands/replies precede routine work. `SIM_MQTT_COMMAND_PRIORITY_FIX_GUIDE.md` |
| LoRa node/gateway | Existing addressing, fragmentation, ACKs and wake probing remain. Unsupported-radio profiles do not invent RSSI; see `RADIO_AND_VOLTAGE_GUIDE.md` |
| Battery voltage | ADC/divider measurement is included in Status and Telemetry, stored/displayed by server |
| Global IWDG | Nominal 30 s, setup and runtime checkpoints, no ISR or Modbus-idle feeding. Persistent reset count uses Status tag 35 / Telemetry tag 44. `WATCHDOG_RECOVERY_AND_TEST_GUIDE.md`, `WDT_RESET_COUNTER_GUIDE.md` |
| Network recovery | 10 failed network attempts reset the active modem RST; another 10 reset modem and STM32. Success clears both stages; global hang detection takes priority. `NETWORK_RECOVERY_USER_GUIDE.md` |
| Power policies | NORMAL, RTC_PERIODIC, REMOTE_WAKE, RTC_QUEUED, LORA_WOR_STOP; per-component policies and unsafe-pairing checks. `NEW_POWER_MODES_USER_GUIDE.md`, `REMOTE_WAKE_USER_GUIDE.md` |
| Server commands | Correlated application ACKs, WAKE lease, queued commands/expiry and topic/payload node validation |
| Wire compatibility | Shared protobuf tags/types, optional second flow record and existing AES envelope retained; cross-component tests verify all schema fields |
| Simulators | Multiple same-type devices, independent values/addresses, fixed/dynamic modes, totalizers, exceptions, silence, latency and CRC faults |

## Fresh clone configuration

1. Copy node `src/config/AppConfig.cpp.example` to `AppConfig.cpp` and
   `AppSecrets.example.h` to `AppSecrets.h`. Enter your network/broker/topics
   and common AES key locally. Do not commit these files.
2. Set each sensor's enable/address and role/uplink/power choices in
   `src/config/AppConfig.h`. The final working copy's bench values are preserved.
   Committed defaults may intentionally differ from your local bench setup.
3. For the server, create a virtual environment and install
   `requirements_web.txt`. Copy `node_config.example.json` to `node_config.json`.
   Configure `.env.example` values in a local `.env` and load them into the
   server process; creating `.env` alone does not imply automatic loading.
   Initial user creation requires the documented account passwords.
4. Node/server company, node ID, broker, AES key and MQTT topics must agree.
   Each concurrently connected MQTT client needs a unique client ID. Local node
   identity is preserved during feature updates; verify its configured ID agrees
   with the private MQTT topic values. Verify the gateway company-prefix
   separately before a gateway test.
5. Use the Arduino STM32 board configuration documented in the node project.
   This machine was verified with core 2.12.0, STM32RTC 1.9.0, TinyGSM 0.12.0,
   PubSubClient 2.8, AESLib 2.3.6 and IWatchdog from the core. Re-test upgrades.

The current routes use case-sensitive lowercase `status`, `data`, `cmd` and
`broadcast` under `wiot/{company}/{region}`. The node rejects rate values above 86400
seconds before converting them to milliseconds, and rejects STIME values wider
than its 32-bit RTC epoch instead of silently truncating them. Its production
minimum rate remains 10 seconds; although the server accepts 5..86400 seconds,
5..9 are rejected by this node. Use 10..86400 and check the application ACK.

## One-command regression check

Requirements: Python with the server/simulator requirements installed, g++,
Node.js, and the actual PubSubClient Arduino source for the protocol host test.
No live broker, physical COM port, flashed node or deployment credentials are
needed for the default checks. Simulator GUI tests create withdrawn Tk windows.

From this package root in PowerShell:

```powershell
./Validate-Release.ps1 -Python 'C:/Python314/python.exe' -UseFactoryConfigurationFixture
```

Optional, after local firmware configuration and tools are ready:

```powershell
./Validate-Release.ps1 -Python 'C:/Python314/python.exe' -UseFactoryConfigurationFixture -BuildFirmware -BuildDocumentation -BuildSimulators -ArduinoCli 'C:/Program Files/Arduino PLC IDE Tools/arduino-cli.exe'
```

The checks fail on a failed native command instead of continuing to package a
failed build. A timestamp-independent temporary `verification.log` path is
printed. The factory fixture verifies inhibited valve configuration with
compile-only overrides because this branch carries commissioned valve settings.
Firmware checks compile the selected profiles with all four sensor drivers and
verify no load section overlaps EEPROM emulation. They do not flash hardware.
Simulator packaging uses installed dependencies without changing them; run an
individual `build_exe.ps1` without `-SkipDependencyInstall` when dependencies
need installation. Pass `-Python` to choose the interpreter consistently.
For a faster repeat of the firmware matrix, pass its previously printed
compiler-output directory as `-BuildRoot` to
`Node/IoT_Node_Encrypted/tests/remote_wake/run_build_matrix.ps1`. It still compiles
every selected profile and repeats flash-boundary checks; it only reuses cache.

## Doxygen and executable deliverables

Run `Node/IoT_Node_Encrypted/generate_doxygen.ps1` to create
`Documentation/Doxygen/html/index.html`, XML and a warnings log. Current
guides and first-party Arduino modules are included. Third-party code,
generated protobuf and private configuration are excluded. The earlier Doxygen
branch has been integrated with the current runtime rather than replacing it
with old firmware.

Each simulator's `build_exe.ps1` creates its Windows EXE under that simulator's
`dist` folder. The multi-sensor EXE needs its editable `default_config.json`
beside it for an external configuration; an internal fallback is also bundled.
For the final four-sensor bench, load `stm32_four_sensor_config.json` in the GUI:
TUF 1, Supmea 2, HNDA 3, Sondas 4 at 9600 N81. Change its COM3 to your adapter.
The demo `default_config.json` deliberately uses a different multi-device fleet.
Generated EXEs, Doxygen output, build/cache directories, runtime databases and
local logs are not Git source files. Build scripts and sources are included in
the branch, and local generated deliverables are placed in the final folder.

## Remaining physical acceptance / known limits

- Reflash the final Arduino sketch, restart the matching server and hard-refresh
  the browser. Test each sensor alone, then all four, then unavailable/recovery
  cases. Use the individual feature guides for their independent tests.
- Test SIM800/Wi-Fi commands during polling and publication; MQTT QoS-0 local
  acceptance is not proof of server receipt. Confirm RX and correlated ACKs.
  Priority is cooperative, not interruptible inside a modem operation.
- Test physical LoRa node/gateway, WOR AUX wiring, RTC/clock restoration,
  Standby wake, MQTT reconnect, retention and watchdog count on actual hardware.
  Current PCB lacks SIM800 DTR/RI/PWRKEY connections; SIM sleep is not enabled.
- Supplied Sondas documentation is SDI-12, not a confirmed Modbus register map.
  The node/simulator Sondas profile is WIOT compatibility behavior; confirm the
  purchased hardware protocol before claiming physical acceptance.
- AES-CBC has no authentication tag and the IV source is not cryptographically
  secure. Do not treat successful decryption as command authenticity. Security
  migration is separate from this compatibility-preserving release.
- Flash-emulated EEPROM shares a sector with credentials and flow state;
  interrupted erase/program is not power-fail atomic. Check uploader preservation,
  power stability and flash endurance as described in the counter guide.
- Third-party host warnings in unused ModbusMaster `requestFrom` and
  PubSubClient signed comparison remain; the active tested paths pass.

GitHub publication requires working Git authentication. A local commit is not
a completed push; check `FINAL_COPY_INFO.md` for the actual publication status.

## 26 October 2026: regional MQTT contract

Active node/web topics now use lowercase `wiot/{company}/{region}/{node}/data|status|cmd`; broadcast is `wiot/{company}/{region}/broadcast`. Bench identity is Company_1 / Region_1 / node 3. Follow [the regional migration guide](Node/IoT_Node_Encrypted/REGIONAL_MQTT_TOPICS_GUIDE.md) before coordinated server/node deployment.

## 30 October 2026 — external telemetry log

The S25FL064L update is described in
[storage design/use](Node/IoT_Node_Encrypted/SPI_FLASH_TELEMETRY_GUIDE.md) and
[acceptance steps](Node/IoT_Node_Encrypted/SPI_FLASH_TEST_PLAN.md). It logs completed
samples, transmits the last committed sample, clears every 24 elapsed hours,
and adds direct commands 9–13 plus internal persistence ACK 14. Historical replies
are isolated from live charts/consumption. Install the matching server and gateway
before updated nodes; larger frames need the widened LoRa reassembly buffer.

Read `FINAL_COPY_INFO.md` in the working folder for the current bench profile.
The LoRa profile reserves PC13 for AUX, which inhibits the valve output.
SPI logging defaults enabled. First commissioning of a blank chip requires
STIME and explicit CLEAR_FLASH.

`regenerate_protocol.py --protoc <path-to-protoc>` regenerates checked-in schemas
using nanopb 0.4.9.1 / protoc 33.5. Validate-Release.ps1 includes native flash,
server archive and dashboard regressions. Build profiles normal-wifi and
flash-disabled-wifi are available in the existing firmware build matrix. Hardware
SPI qualification and a 24/48-hour soak are still required.
