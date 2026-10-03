# WIOT complete-release audit — 3 October 2026

Release branch: `feature/2026-10-03-complete-release-audit`.
Use `RELEASE_GUIDE.md` for package entry points, configuration and verification.
The active bench copy remains `WIOT_Final_PowerModes_20261001`; its local
`FINAL_COPY_INFO.md` records the commit and actual GitHub publication status.

## Scope and findings

The branch contains complete tracked node, server, simulator, documentation,
manual and specification sources, not only this audit's changed files. The
Arduino STM32 runtime includes all four independent sensor interfaces, both
flow-meter records, RTC consumption, voltage, LoRa node/gateway, watchdog and
reset counter, unavailable-reading zeros, power profiles, remote wake and
command-priority MQTT handling. ESP32 and CubeIDE ports are included unchanged.

The earlier Doxygen branch was not part of the latest runtime branch. It has
now been merged while retaining current implementations. Stale API comments
about sensor selection, cached unavailable values and MQTT publication were
corrected. Private configuration and generated/vendor code are excluded from
the API reference. Host regression success does not prove hardware behavior.

| Finding | Resolution |
| --- | --- |
| Public MQTT example used suffixes with incorrect case | Example now matches `Status`, `Telemetry`, `CMD` and `BroadCast/CMD`; regression verifies case. Existing private topics were not changed. |
| Oversized command values could truncate or overflow | Node validates rate bounds before milliseconds conversion and rejects STIME epochs wider than 32 bits; actual command-handler tests cover boundaries and unchanged state on rejection. |
| Simulator example fleet did not match the four-sensor bench | Added `stm32_four_sensor_config.json`: TUF 1, Supmea 2, HNDA 3, Sondas 4, 9600 N81. The multi-device demo remains available. Change COM3 to your adapter. |
| Packaging could proceed after a failed native command | All three simulator recipes stop on failed tests/builds and verify the EXE exists; Supmea now has a PowerShell build recipe. |
| No single complete-release validation entry point | Added `Validate-Release.ps1` and six cross-component schema/package/topic tests. |
| Missing current radio/voltage reference | Added `RADIO_AND_VOLTAGE_GUIDE.md`, covering supported RSSI behavior, UART roles and calibrated voltage verification. |

Your existing private node/server configuration and local sensor/power switches
were preserved. Previous overwritten public files can be recovered from
`backups/before_complete_release_audit_b1fe57183676424f886cdc688c918da0`
inside the final folder. The original dirty working checkout was not reset.

## Verification record

The following checks passed from the final working copy, using its actual local
configuration for firmware builds. Tests use simulated interfaces unless stated
otherwise. They do not contact a live MQTT broker or flash a controller.

| Check | Result |
| --- | --- |
| STM32 ARM compiler matrix | 11 normal, power and gateway profiles; four drivers compiled; flash load sections remain below the EEPROM sector |
| MQTT host tests | 10 priority/failure scenarios, 3 actual ModbusMaster receive scenarios, actual PubSubClient wire/keepalive/partial-write checks |
| Persistent watchdog counter | 11 scenarios including corruption, saturation, normal boot and shared records |
| Unavailable sensor mapping | 4 profiles: valid, failed and recovered data contracts |
| RTC / Supmea accumulation | 16 scenarios including backup access, invalid RTC, counter reset, persistence retry, midnight and new year |
| Power manager / commands | Actual implementation host tests plus 28 real AppConfig policy checks; added command-width/rate edge cases |
| Simulator Python tests | Multi-sensor 24, TUF 20, Supmea 10 |
| Server Python tests | 47 |
| Cross-component contract tests | 6: all three schemas, Python descriptor, nanopb tags, expected fields, source/templates and topic case |
| Dashboard / WAKE JavaScript | Both suites passed |
| Doxygen | HTML/XML generated; zero warnings |
| Windows simulator packaging | All three EXEs built; packaged multi-sensor EXE accepted the new bench preset |

There are 107 Python tests across the simulator, server and release-contract
suites. Generated HTML and EXEs are delivered locally, not committed as source.
Scripts, dependency manifests, templates and simulator presets are committed so
the deliverables can be rebuilt. Core 2.12.0, STM32RTC 1.9.0, TinyGSM 0.12.0,
PubSubClient 2.8 and AESLib 2.3.6 were used for this verification.

## Acceptance limits and follow-up tests

- Reflash the final sketch and test each sensor alone, all four together,
  failed reads, recovery, positive flow and calendar transitions. Load the new
  bench preset rather than the differently addressed demonstration fleet.
- Validate node/server company, ID, key and topics, then verify received Status,
  Telemetry and correlated command ACKs over SIM800 and Wi-Fi while sensors poll.
  MQTT QoS-0 local write success is not server receipt. Command priority remains
  cooperative inside blocking modem operations.
- Test LoRa delivery/gateway, wake probes and AUX wiring, RTC restoration,
  physical sleep/wake, watchdog reset count and power consumption. The present
  PCB lacks SIM800 DTR/RI/PWRKEY control; no unsupported SIM sleep is claimed.
- The supplied Sondas manual describes SDI-12; its WIOT Modbus compatibility
  profile is not a verified physical register map for the purchased sensor.
- The nominal watchdog timeout depends on the MCU low-speed oscillator.
  Shared flash-emulated EEPROM updates are not power-fail atomic; test uploader
  preservation, stable power and persistence according to the counter guide.
- Existing AES-CBC framing lacks authenticated encryption and uses a non-secure
  IV source. Security migration is outside this compatibility-preserving audit.
- Existing third-party warnings in unused ModbusMaster `requestFrom` and a
  PubSubClient signed comparison remain. No warning was hidden by this audit.
- Older Excel reports and alternate-port documents remain historical material,
  not evidence that alternate ports contain the latest Arduino runtime features.

Git authentication is required before publication. A local branch or commit
alone is not a successful GitHub push; see the final copy's publication record.
