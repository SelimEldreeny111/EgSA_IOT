# Reset counters and SUPMEA independent reference — verification

Date: 25 October 2026. Active final working folder and public Git sources only.
No ESP32/CubeIDE changes, no live node flashing, no MQTT broker contact by tests,
and no production database mutation.

## Implemented

- POR/BOR counter separate from IWDG count; early RCC/PWR capture excludes planned
  Standby wake and warm/software/pin-only resets. Existing WDT storage preserved.
- All RCC reset flags are explicitly cleared after capture/classification. The
  installed IWatchdog library only clears them conditionally on IWDG, so relying
  on isReset(true) would leave stale POR flags after a normal power boot.
- Power count at 232..251; Status tag36 and Telemetry tag45. Existing tags unchanged.
- Commands 7 CLEAR_POWER_RESETS / 8 CLEAR_WDT_RESETS, data0, direct-only,
  nonzero correlation, independent durable clear/readback, cached duplicate result.
- Server command validation/journal, dashboard/node details, additive DB migration
  and CSV updated. Clear commands are once-only, not auto-retry commands.
- Independent SUPMEA positive-flow calendar integral in multi-sensor and standalone
  GUIs. No period registers added. Per-address references and multi-GUI JSON export.
- Device edits preserve the selected reference calendar. A discovered pre-existing
  editor issue was repaired: editable numeric fields no longer contain thousands
  separators (which float() rejected for SUPMEA totals such as 1,250.75).

## Completed checks

- Full Validate-Release.ps1 -UseFactoryConfigurationFixture: PASS.
- Seven node host suites: valve, MQTT priority, network recovery, reset counters,
  sensor availability, RTC/SUPMEA and remote-wake scheduling.
- Reset-counter host suite: 24 fresh-process scenarios, including power-on,
  brownout, mixed WDT/power flags, cleared Standby flag snapshot, saturation,
  corrupt records, boot/clear write failures, independent clear, durable zero,
  preservation of surrounding records and no extra write for verified zero.
- Actual CommandHandler host tests: both clears, invalid data, missing ID,
  broadcast, foreign node, duplicate, changed outcome and failed-operation ACK.
- Python: 34 multi-sensor, 20 TUF, 11 standalone SUPMEA, 101 server and
  8 cross-component tests: 174 total, PASS.
- Cross-component oracle compiles actual production RTC.cpp and
  SupmeaPeriodAccumulator.cpp, compares constant-flow samples across UTC and
  Cairo year rollover and both Cairo DST transitions, and verifies both simulators
  ship identical reference math. The fall trace spans the repeated hour through
  the following local midnight.
- Analytical oracle tests cover month boundary, leap day, Cairo spring DST,
  reverse flow, paused auto totals, invalid timezones and no invented Modbus map.
- Server tests cover both command APIs/correlation, invalid/broadcast rejection,
  no repeated queued dispatch, power field wire roundtrip/legacy readers,
  storage/latest API/CSV and preservation through timestamp migration.
- Existing dashboard JavaScript, wake, valve, safety and timeline suites: PASS.
- Additional actual-command-UI test covers clear confirmation/cancel, no broadcast
  publication and fixed zero data; dashboard render checks both reset counters.
- 45 real configuration-policy checks remain passing.
- All 13 default ARM firmware matrix profiles: PASS, all four drivers enabled.
  Maximum load end 0x08016CD4 (queued Wi-Fi), below EEPROM sector 0x08020000;
  remaining load margin 37,676 bytes. Largest static RAM 26,500 bytes (queued LoRa);
  39,036 bytes nominally remain before runtime stack/heap use.
- Doxygen regenerated in the final node folder; warnings.log empty.
- Both simulator EXEs rebuilt with tzdata. The old multi-sensor process held the
  original EXE open, so the new version was built in dist/20261025, without
  stopping the user's process. Packaged multi-sensor --validate-config on the
  STM32 four-sensor profile exits 0 (including packaged timezone loading).

## Evidence locations (local, not committed binaries/log archives)

- Documentation/reset-counters-full-regression.log
- Documentation/reset-command-host-tests.log
- Documentation/reset-counter-host-tests.log
- Documentation/FirmwareBuildResetCounters_20261025/build-matrix.log
- Documentation/reset-counters-doxygen.log
- Documentation/multi-sensor-reset-reference-build-20261025.log
- Documentation/supmea-reference-build.log
- Node/IoT_Node_Encrypted/Documentation/Doxygen/html/index.html
- SENSORS/Multi Sensor RS485 Simulator/dist/20261025/
- SENSORS/Supmea Flow meter/simulator/dist/

The corrected once-only server test uses claim_on_status, not an invented queue
API. A discovered cmd_type input-length limit was raised from 16 to 32 to permit
the clear-command names; command whitelist validation remains in force.

## Remaining physical acceptance

Test real supply cycles, IWDG stalls, pin/software resets, Standby wakes and both
clear commands on the actual board. Check failed/unknown ACK outcomes explicitly.
Compare a stable real-node SUPMEA run with matched time/calendar and a common
baseline, allowing measured sample-age and Float32/integer-liter quantization.
Host fixtures are not physical power-integrity, timing or sensor qualification.
The shared EEPROM sector remains non-atomic under power interruption. The
existing AES-CBC/MQTT design is unchanged, not upgraded to authenticated commands.
The 7 October Word file is retained as a historical baseline with this supplement.
