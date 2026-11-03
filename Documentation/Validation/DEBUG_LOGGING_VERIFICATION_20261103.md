# Debug logging verification — 3 November 2026

Branch: `feature/2026-11-03-professional-debug-logging`.
Base: `b307edfb6081a3f49f079255ce4db923b16838be` (working SRATE/STRAN LoRa WOR release).

## Scope

The Arduino STM32 node and gateway now share one diagnostic switch. Every owned
debug output is routed through `DebugLog.h`. Detailed command, telemetry, LoRa,
sampling, flash and power events supplement the existing sensor/readout logs.
Raw frames have a separate opt-in switch. The debug UART and serial Wi-Fi
enrollment are disabled in a silent build. Actual radio configuration, modem
operations, sampling, storage, command ACKs and watchdog work remain enabled.

There is no schema, server, ESP32, CubeIDE, sensor register, GPIO or power-policy
change. The existing CSQ diagnostic label was corrected to identify the modem's
raw signal-quality code rather than incorrectly calling that code dBm.

## Host evidence

All listed suites passed using MinGW g++, C++14, with the suites' own warning
and error policies:

| Suite | Evidence |
|---|---|
| Debug logger | Four master/raw policies; disabled arguments have no side effects; no UART initialization, writes, flushes or timestamp reads when disabled |
| Logger formatting | Timestamp/module/level prefixes, multiline text, shared framing across translation units, bounded truncation, full unsigned 64-bit command data |
| Binary/source audit | Unique diagnostic string absent from silent executable; owned direct SerialMon output calls prohibited outside logger |
| LoRa parity | Production large-frame reassembly, duplicates, CRC and bounds; fragment ACK bytes match exactly with debug true/false |
| Remote wake | Existing command validation, ACK policies, replay handling, app scheduling and counter-clear isolation |
| WOR Stop | 65 original scenarios plus 34 independent-scheduler scenarios across AUX/UART_RX |
| Real configuration | 61 policy checks, including valid debug selections and invalid-switch rejection |
| RTC/Supmea | 16 access/trust/synchronization/accumulation/persistence/calendar scenarios |
| Network recovery | SIM registration/GPRS and Wi-Fi firmware/saved-fallback recovery, 10+10 retry policy |
| MQTT priority | Command-first queues, replies/retries, modem/controller recovery, backpressure, real PubSubClient wire/keepalive and Modbus response handling |
| Flash | Journal recovery, retention, CRC/full/queue/I/O, 13 power-cut transitions, archive driver/download/timeout/cancel/resume/empty scenarios |
| Sensors | All four configured availability profiles, failed-read zeroing and validity behavior |
| Valve | Actual driver pulse/polarity/persistence/failure/timer cases and configuration guards |
| Reset counters | Power, brownout, reset pin, software reset, watchdog, Standby, persistence, saturation and clear/failure scenarios |

Minimal host UART/configuration fakes were extended for the new logger's clock,
printing and metadata dependencies. Assertions on production behavior remain in
place. Existing third-party ModbusMaster/PubSubClient host warnings were observed
in their original files; this change does not modify those libraries.

## ARM builds

Toolchain: Arduino CLI 1.4.1, STM32duino core 2.12.0, GNU Arm 14.2.1.
FQBN: `STMicroelectronics:stm32:GenF4:pnum=BLACKPILL_F401CC`.
Sizes below are Arduino CLI results (program bytes, static RAM bytes).

| Profile | Debug | Raw frames | Program | Static RAM |
|---|---|---|---:|---:|
| Four-sensor LoRa WOR node | true | false | 113,476 | 34,644 |
| Four-sensor LoRa WOR node | false | false | 87,072 | 34,644 |
| Final folder: Supmea/Sondas LoRa WOR node | true | false | 110,496 | 34,636 |
| Wi-Fi LoRa gateway, Mode-1 WOR downlink | true | true | 61,044 | 30,432 |
| Wi-Fi LoRa gateway, Mode-1 WOR downlink | false | false | 44,768 | 30,404 |
| Direct SIM node, controller/radio normal | false | false | 85,064 | 25,980 |

The gateway comparison includes optional raw-dump code in its enabled build.
The node comparison uses ordinary event logging. These are firmware sizes,
not measured current savings. ARM symbol inspection found no `WiotDebug`
symbols in silent node/gateway binaries, while sampling/storage/LoRa/MQTT
symbols remain present.

## Working copy and hardware acceptance

The final working folder is `WIOT_Final_PowerModes_20261001`.
Its local sleep interval of 20 seconds, disabled TUF/HNDA sensors, enabled
Supmea/Sondas sensors and all other current settings are preserved. Private
`AppConfig.cpp`, `AppSecrets.h`, server configuration and databases are not
overwritten. Replaced public files are backed up under
`backups/before_debug_logging_20261103`.

The release retains debug=true/raw=false for current testing. Choose
debug=false and rebuild/flash when preparing launch firmware.

No device was flashed or remotely commanded during these checks. The
read-only-command, live-server, quiet-console and current/timing bench checks
in `Node/IoT_Node_Encrypted/DEBUG_LOGGING_GUIDE.md` remain physical acceptance
steps. Software tests do not certify valve position, RF range or power savings.
