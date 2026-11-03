# Light debug verification — 3 November 2026

Branch: `feature/2026-11-03-lite-debug`.
Base: `03a98258c689ee51dbca88f716ac1501bcad4db8` (professional debug release).

## Selection and behavior

| Selection | APP_ENABLE_DEBUG | APP_DEBUG_LITE |
|---|---|---|
| OFF | false | either |
| LITE | true | true |
| FULL | true | false |

`APP_DEBUG_RAW_FRAMES` is honored only in FULL. The master false always wins.
The source defaults to master true/lite true/raw false. The final working copy
retains the user's existing **master false**, with the new lite selector true.
Set its master true to use LITE; rebuild and flash after changing either flag.

LITE retains compact boot/reset summaries, command receipt/results/rejections,
telemetry preparation and local send results, gateway command forwarding,
flash-history transfer progress, and critical errors. It removes routine sensor
readouts, sample/heartbeat banners, LoRa fragment/retry detail, flash commit/sweep
logs, power snapshots and all raw dumps. Selected events use the same
timestamp/severity/module framing and command request identifiers as FULL.

The omitted calls and argument expressions are compiled out. LITE and OFF also
skip serial Wi-Fi enrollment, ESP firmware version and diagnostic CSQ queries;
FULL retains those diagnostics. Configured/saved Wi-Fi selection and recovery
continue in all modes. Protocol UARTs, command ACK policy, telemetry encoding,
sensor reads, flash operations, watchdog servicing and sleep scheduling remain
independent of logging selection.

## Evidence

- Eight master/lite/raw combinations passed logger tests. LITE retains key
  INFO/WARN and ERROR events, omits detailed output and argument side effects,
  and refuses raw dumps even when the raw switch is selected. OFF performs no
  debug UART initialization/write/flush or logging timestamp read.
- Full-only diagnostic literals are absent from LITE and OFF host executables.
  Prefixes, bounded truncation, cross-module framing and full unsigned 64-bit
  command arguments remain covered.
- Production LoRa large-frame reassembly and fragment ACK bytes match in
  FULL/LITE/OFF, including duplicates, CRC rejection and bounds.
- Thirty production MQTT command-priority, ACK retry, foreign-node rejection,
  write failure and pending-send reception scenarios passed across SIM/Wi-Fi
  and all three logging selections.
- The existing MQTT suite passed, including real PubSubClient wire/keepalive,
  ACK enable/disable and Modbus command-service behavior. Its original
  third-party compiler warnings remain; those libraries were not modified.
- All 65 real configuration checks passed, including the new lite option and
  invalid-lite rejection. The 99 WOR Stop/scheduler cases, remote-wake/command
  regression cases, reset-counter cases and flash journal/archive tests passed.

Arduino CLI 1.4.1 / STM32duino 2.12.0 / GNU Arm 14.2.1 compiled the firmware for
`STMicroelectronics:stm32:GenF4:pnum=BLACKPILL_F401CC`:

| Profile | Selection | Program bytes | Static RAM bytes |
|---|---|---:|---:|
| Four-sensor LoRa WOR node | OFF | 87,072 | 34,644 |
| Four-sensor LoRa WOR node | LITE | 92,900 | 34,644 |
| Four-sensor LoRa WOR node | FULL | 114,000 | 34,644 |
| Wi-Fi LoRa gateway with WOR downlinks | LITE | 48,088 | 30,408 |
| Final Supmea/Sondas WOR configuration | LITE, compiler override | 91,512 | 34,636 |

The final-copy build used `-DAPP_ENABLE_DEBUG=true` without editing its saved
false setting. Firmware sizes demonstrate code removal, not measured power or
timing savings. The STM32 devices were not flashed by these tests.

## Final folder and acceptance

Updated public files are applied to `WIOT_Final_PowerModes_20261001` and backed
up under `backups/before_lite_debug_20261103`. The existing master false, sensor
selection, addresses, power configuration and private files are preserved.
No server, protobuf, ESP32 or CubeIDE update is required.

See `Node/IoT_Node_Encrypted/DEBUG_LOGGING_GUIDE.md` for the three-mode table and
bench steps. Rebuild/flash LITE, confirm command request/result and telemetry
events, then confirm the server receives the same operations. FULL should add
detail; OFF should leave the debug console silent. Actual current/timing and
live radio/server acceptance remain hardware checks.
