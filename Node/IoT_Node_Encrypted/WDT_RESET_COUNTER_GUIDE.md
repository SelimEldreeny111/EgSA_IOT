# Watchdog reset counter — Arduino STM32 node and server

## What is sent

The new `uint32 wdt_reset_count` is the node's cumulative count of hardware
**independent watchdog (IWDG)** resets. It is not an uptime counter, retry count,
or count of all reboots. It is populated in Status, periodic Telemetry, and
command-response Telemetry through the shared sensor payload mapper.

| Message | New protobuf field | Tag |
| --- | --- | --- |
| `Status_Message` | `uint32 wdt_reset_count` | 35 |
| `Telemetry` | `uint32 wdt_reset_count` | 44 |

Existing tags and encryption framing are unchanged. Old firmware omits the
field and the new server displays 0; this does **not** prove that an old node
never reset. Old protobuf readers ignore this appended field. Update the
STM32 node and server together. No ESP32/CubeIDE files were changed.

## Counting and storage

- The STM32 hardware IWDG reset flag is captured at watchdog initialization.
  After an IWDG boot, the stored count is increased by one before publishing.
  Initialization is idempotent: a second call in the same boot cannot add one.
- Real application stalls, intentional IWDG network-recovery resets, and the
  existing watchdog self-test all count. The value does not diagnose the cause;
  the existing reset-stage log is still available for that purpose.
- Power-on, reset-button, software reset, and successful scheduled sleep/wake
  cycles do not add one. A genuine IWDG timeout during power-mode preparation
  still counts as a watchdog reset.
- The value is retained in STM32 flash-backed EEPROM at bytes **192–211**.
  WiFi credentials occupy the earlier area; the Supmea checkpoint remains at
  128–183. No RTC backup registers are taken from the power/RTC/flow features.
- A versioned 20-byte record includes an inverted count and integrity checksum.
  One buffered flash commit preserves surrounding EEPROM data, followed by
  readback verification. Normal boots/sleep wakes do not write this record.
- Counts saturate at **4,294,967,295**, rather than wrapping to zero. There is
  intentionally no automatic reset of the counter or server reset command.
- A previously unused flash record starts at 0; past resets before installing
  this firmware cannot be reconstructed. A full flash/EEPROM erase also clears
  the stored history. Ordinary firmware updates retain it only if the uploader
  preserves the EEPROM sector.

Flash has finite erase endurance. Repeated watchdog-reset loops cause repeated
commits, and the existing Supmea/WiFi storage shares the same erase sector.
Use the count to investigate/fix such loops, not to intentionally generate
resets indefinitely. This emulation is **not power-fail atomic**: interrupted
sector erases can damage the counter and other records. A corrupt counter
restarts at 0 (or 1 for the current IWDG boot), with a serial warning. A failed
commit leaves the updated value in RAM for the current boot and logs an error;
that increment is not guaranteed to survive the next reset/power loss. This
is a diagnostic counter, not a certified tamper-proof event log.

Serial output includes `Cumulative WDT resets: N`. Existing WDT enable,
timeout, recovery and self-test settings keep their meanings. There is no new
enable macro needed for reporting the count. Disabling IWDG prevents future
hardware watchdog resets, but does not erase the saved count.

## Server use

1. Reflash the updated Arduino STM32 sketch from this copy using your existing
   local `AppConfig.cpp` and `AppSecrets.h` (never the compile-only test values).
2. Back up your server databases, then restart the updated server. The messages
   table automatically gains `wdt_reset_count` with default 0 for older rows;
   existing sensor data and consumption history are retained.
3. Hard-refresh the browser and select the node. **WDT Resets** appears below
   the node summary. The node detail popup also includes the count.
4. Each received Status/Telemetry row stores the reported value. It is exposed
   in `/api/node_latest` and message history as `wdt_reset_count`, in the live
   socket payload as `WDT Resets`, and in CSV export as `WDT Resets`.
   The gateway forwards the sensor node's value unchanged; it must not replace
   it with the gateway's own reset count. Sensor errors/zero readings do not
   clear this controller-level diagnostic.

## Step-by-step bench acceptance

Use a test node with stable power. Do not run intentional hangs on production.
Keep `APP_ENABLE_HARDWARE_WATCHDOG` enabled and use NORMAL controller mode for
the first test; leave modem and sensor settings appropriate for your hardware.

1. **Baseline:** flash with `APP_WATCHDOG_SELF_TEST_MODE` disabled (0). Record N
   from the boot log and from the next Status/Telemetry on the server.
2. **Non-WDT restart:** press reset, then power-cycle normally. Both boots must
   report N, not N+1, provided the EEPROM sector has not been erased.
3. **One controlled WDT timeout:** select
   `APP_WATCHDOG_SELF_TEST_AFTER_SETUP` (1), compile and flash. The existing
   self-test blocks until the configured watchdog timeout, nominally 30 s.
   The next boot should log the IWDG cause, self-test pass, and count N+1.
   The recovered Status and GOSTM/Telemetry must both report N+1.
   If uploading erases EEPROM, establish a new baseline after that erase.
4. **Persistence:** restore self-test mode 0, reflash while preserving EEPROM,
   and restart normally. The count stays N+1. Confirm stored CSV/API/live values.
5. **Power profiles:** in RTC_PERIODIC/RTC_QUEUED, let two successful report,
   sleep, and wake cycles complete; count stays fixed. Repeat in reachable-idle
   and LoRa WOR profiles where applicable. A real IWDG fault must add one.
6. **Sensor failure:** disconnect one sensor on the test bench. Its failed
   readings become zero as before, but the reset count remains unchanged unless
   the controller actually times out and reboots.

Host checks: `tests/watchdog_counter/run_tests.ps1` compiles the actual watchdog
and counter against fake flash/reset flags and covers 11 boot/storage scenarios.
The availability suite checks both payloads even when all sensors fail. Server
tests verify protobuf tags, legacy-reader compatibility, database migration,
Status/Telemetry ingestion, maximum uint32, latest API and dated CSV export.
The dashboard test exercises the actual render function. Bench measurements
are still required to prove reset flags, uploader preservation and power-mode
behavior on your physical board.
