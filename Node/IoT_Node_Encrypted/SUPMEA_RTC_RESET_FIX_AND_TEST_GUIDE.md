# Supmea RTC consumption: reset fix and acceptance test

Scope: Arduino STM32F401 four-sensor node only. ESP32, STM32CubeIDE, the
simulator and the server protocol are unchanged. Keep the normal 25-second
watchdog enabled; the fix does not extend its deadline.

## What changed

- Supmea uses HAL register **numbers** DR0..DR13, not byte offsets. The RTC
  trust marker remains DR14; power-down state remains DR15..DR19.
- Backup-domain access is restored to its previous state. Reading or saving a
  snapshot no longer revokes STM32RTC's permission to set the clock or alarm.
- STIME validates the supported timestamp range, writes one complete date and
  one complete time, then reads the clock back. It reports success only if the
  readback is within two seconds of the requested UTC epoch and the trust
  marker is verified. A failed write is reported instead of claiming success.
- A Supmea flash checkpoint loads the existing EEPROM buffer, changes only
  bytes 128..183, commits once, and verifies from flash. Unchanged records need
  no commit. Other data, including stored WiFi credentials, is preserved.
- Watchdog stage names distinguish RTC synchronization, calendar calculation,
  backup snapshot and flash checkpoint. No watchdog reload occurs inside a
  blocking flash operation, so a real hang still triggers a reset.

The stored state format/version is unchanged. Valid earlier flash checkpoints
remain readable. Incorrect old backup snapshots are rejected by the existing
checksum/field checks; a valid flash copy is used instead. Without either valid
copy, the next trusted sample starts a new partial baseline. Do not deliberately
clear totals as part of applying this fix.

## Before flashing

1. Open `IoT_Node_Encrypted.ino` **from this four-sensor checkout**, not an older
   project copy. Select the same STM32 board/core used for the working firmware.
2. Preserve your `AppConfig.h` sensor switches, Modbus addresses, modem choice
   and node ID. This fix does not change them. Keep local `AppConfig.cpp` and
   `AppSecrets.h`; they are intentionally not published to GitHub.
3. Check that the node ID agrees with its local MQTT publish/command topics.
4. Leave `APP_RESET_SUPMEA_PERIOD_STATE` at **0** and the watchdog self-test
   disabled. Do not erase EEPROM or the RTC backup domain for a normal update.
5. For a controlled simulator test, select the Supmea address matching the node,
   set its flow unit to **Fixed, code 3 (m3/h)** and use fixed live/alarm values.
   Do not randomize its unit or jump its cumulative totals during this test.

## Test 1: boot without time synchronization

On a board with no previously trusted clock, start the node without STIME.
Supmea live/cumulative readings should continue. Calendar output should say
`RTC trusted : NO` and `TIME_UNCERTAIN`; a zero calendar value is unavailable,
not a measured zero. A retained trusted clock can already say YES after reset.

Pass: all enabled sensors continue to be polled; no unexplained watchdog reset.

## Test 2: STIME and first checkpoint (original failure)

1. Connect the server and node to MQTT. Select the matching company/node.
2. Send **STIME once** from the server Commands tab.
3. Confirm the node prints:

   ```text
   CMD: SYNC_RTC
   RTC synced from epoch (verified)
   Current RTC time is : <current UTC date and time>
   RTC synced to epoch: <timestamp>
   ```

   The RTC log is UTC, not Cairo local time. A normal current synchronization
   must not leave the clock at the 2024 placeholder date.
4. At the next valid Supmea sample, confirm `RTC trusted : YES`.
5. If there was no valid saved baseline, also confirm:

   ```text
   Supmea flash checkpoint starting: initial baseline
   Supmea period state saved to EEPROM: initial baseline (<duration> ms)
   ```

   A restored baseline does not need another initial-baseline save. The elapsed
   time is measured on the board; it must remain comfortably below the watchdog
   deadline. Totals initially remain zero only for a fresh baseline; `PARTIAL`
   is expected because the period was not observed from its start.

Pass: a verified current clock, continued sensor polling, no reset while
calculating or saving the baseline. Do not accept the server's publish-success
message alone as proof the node received STIME.

## Test 3: a known consumption increment

Manual deterministic test (within the same calendar day/month/year):

1. Disable automatic totalizer integration and use Fixed values in the simulator.
2. Wait for the node to accept a valid baseline/current Supmea forward total.
3. Record the node's day/month/year consumption values.
4. Increase the forward total by exactly **1.000 m3**; keep reverse total
   unchanged and adjust net total consistently. Apply the edited simulator
   values and wait for the next sensor sample.
5. Each calendar volume must increase by **1.000 m3**, within the meter float
   and displayed-value precision. A pre-existing saved total need not be zero.

For a continuous test, use Fixed flow **12 m3/h**, Fixed unit **3**, automatic
totalizer integration enabled, and time multiplier **1**. Forward consumption
increases by approximately **0.200 m3 per 60 seconds between samples**. The
node counts forward-counter differences; the simulator integrates the flow.

Pass: monotonically increasing forward consumption with no double-counting,
unexplained reset, or `TIME_UNCERTAIN` after successful STIME.

## Test 4: reset recovery and surrounding storage

1. After Test 3, record the current meter forward total and node consumption.
2. Reset the MCU without interrupting backup power or resetting simulator
   totalizers. Keep the same firmware configuration.
3. Confirm the node restores a valid snapshot and retained clock. If the clock
   lost trust, send STIME again before judging calendar validity.
4. Continue increasing the meter total. Previously recorded consumption must
   not be counted twice or reset to zero while its local period is unchanged.
5. Confirm stored fallback WiFi settings still work, if that feature is in use.

RTC backup loss falls back to the last durable checkpoint. It is not guaranteed
to retain a trusted clock without backup power. Calendar gaps crossing a
boundary cannot be claimed as perfectly measured; quality flags still apply.

## Test 5: production power-down and watchdog regression

For an already supported WiFi or LoRa periodic profile, perform the existing
power-down commissioning test and at least 20 sleep/wake cycles. Confirm the
alarm still wakes the controller and Supmea continues from saved state. SIM800
periodic power-down remains prohibited on the existing PCB; this fix does not
change that hardware limitation.

Run the existing watchdog self-test separately and confirm a genuine deliberate
hang still resets at the configured deadline. Return the self-test to disabled
afterward. There is no automatic fault injection in production firmware.

## If another reset occurs

Capture the last messages before reset, the measured pause, and the next boot's
`RESET CAUSE` and `Last watchdog stage`. New stage names are:

- `RTC STIME synchronization`
- `Supmea RTC consumption calculation`
- `Supmea RTC backup snapshot`
- `Supmea flash checkpoint`

A checkpoint-start log without its completion log identifies a storage-path
failure. An EEPROM verification error means the record was not confirmed saved;
the node retains its working backup state and retries at the next eligible
sample. Do not disable the watchdog to conceal either failure.

## Automated regression tests

From the repository root in PowerShell, with a host MinGW g++ on PATH:

```powershell
& .\Node\IoT_Node_Encrypted\tests\rtc_supmea\run_tests.ps1
```

The runner compiles the **actual** `RTC.cpp` and `SupmeaPeriodAccumulator.cpp`
against strict mock hardware. Sixteen isolated scenarios cover access-state
preservation, rejected/failed STIME, stale-marker protection, register bounds,
single-commit saving, unrelated-data preservation, flash failure/retry, backup
and flash recovery, UTC/Cairo boundaries, explicit reset and protected alarm
writes. Temporary test binaries are kept outside the repository.

These tests and compilation do not replace the board tests above. Actual flash
latency, RTC oscillator accuracy, MQTT delivery, IWDG tolerance and wake wiring
must be verified on hardware.

The current F401 build must also keep application flash below the EEPROM
emulation sector. For the 256-KiB F401xC, the final 128-KiB sector starts at
`0x08020000`; verify the load addresses in the linker map remain below it.
The standard board linker does not automatically reserve that sector for you.
