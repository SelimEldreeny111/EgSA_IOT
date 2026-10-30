# SPI telemetry storage implementation worklog

Active task: implement S25FL064L SPI NOR telemetry logging in Arduino STM32 node
and Python server, same final folder; preserve ESP32/CubeIDE. User explicitly
selected **every 24 elapsed hours**, not midnight, for auto-clearing. Today export
filters retained samples by existing node calendar timezone. Keep commands first.

Base commit 4c34379, branch feature/2026-10-30-spi-flash-telemetry. Development
worktree C:/Users/Selim/.codex/worktrees/stm32-doxygen-docs/WIOT; final copy
D:/WorkSpace/EgSA/R&D_WS/IOT/IOT/WIOT/WIOT_Final_PowerModes_20261001. Publish a
new branch through connected GitHub app (CLI credentials are not reliable).

## Chosen design

- Chip S25FL064L, JEDEC 01 60 17, 8 MiB, 256-byte pages, 4 KiB sectors. SPI1
  PA4 CS / PA5 SCK / PA6 MISO / PA7 MOSI from supplied schematic. 3.3 V only.
  Verify exact chip via JEDEC; refuse unknown chips, do not change protection NV
  registers. Read 13h / program 12h / erase 21h explicit 4-byte-address commands
  avoid dependence on the chip's retained 3/4-byte address setting.
- Use abstract asynchronous NOR driver + independently testable log core.
  Two metadata sectors; 2046 data sectors. Sector header 512 bytes, seven
  512-byte record slots each: capacity 14322 samples. Canonical sample is plain
  nanopb Telemetry (no command/flash/history fields); transport still uses existing
  AES envelope. Slot contains length/version/time/day/sequence, CRC, commit-last.
- Metadata revision/generation, start UTC, start sector, node ID, last manual
  clear request ID and pending sweep. Alternating copies, CRC + commit last.
  New generation logically clears immediately after durable metadata commit.
  Old data physically erased cooperatively, never active-generation sectors.
  No chip-erase command / no busy-wait erase loops. Blank/unknown format requires
  explicit CLEAR_FLASH first. Full log stops appending with explicit error/count.
- Recovery scans fixed slots cooperatively; never exposes torn writes. Sequence
  is physical generation-relative slot index (holes allowed), so direct retrieval
  is O(1). One bounded state-machine phase per service step. Queue complete samples,
  never partial sensor cycles. Count errors/dropped samples, preserve latest RAM.
- Trusted RTC required for persisted samples/retention; never erase on untrusted
  or backward clock. 24-hour start persists across reset. "Today" uses existing
  CalendarPeriodKeys. Historic samples retain original acquisition timestamp.
- Routine Status reads latest committed sample; explicit live fallback if flash
  unavailable/empty. Add sample sequence/time-valid/source flags. GET_TELEMETRY
  existing behavior preserved; new storage commands distinguish archived replies.
- Commands 9 CLEAR_FLASH, 10 FLASH_STATUS, 11 FLASH_LAST, 12 FLASH_TODAY,
  13 FLASH_CANCEL, 14 internal HISTORY_ACK. Direct-only for destructive/bulk work,
  clear requires data=0 and nonzero request ID, persisted duplicate protection.
- Bulk export one record at a time with request/generation/index/sequence/total,
  frozen end sequence, CRC-verified record reads, terminal result. Server commits
  each row to separate SQLite archive before sending CMD14 ACK; bounded retry /
  timeout / cancel; no giant payload. ACK14 bypasses ordinary replay cache and
  emits no telemetry ACK. Command pump remains first between sends. Status/action
  replies outrank bulk sends. Clear/expiry cancels stale transfer explicitly.
- Extend Telemetry with optional FlashLogInfo + HistoryInfo, no renumbered tags;
  bounded buffers are codec 640 / MQTT 1024; generated maximum 546 plaintext,
  577 encrypted. The LoRa reassembly mask is widened to 32 bits (24 fragments).
  Keep node/server schemas identical; regenerate nanopb and messages_pb2 with
  installed protoc + Python nanopb. Native tests need disabled-feature stubs.
- Power guard prevents sleep during an in-flight write or transfer; deep-power
  down B9 / AB when idle. WOR heartbeat must return for storage retention/service
  deadlines even if report period is days. Standby deadline clamp to retention.
- Server commands/UI memory status + transfer progress + separate history table /
  CSV. Do not feed archive replay into live charts/consumption or command sample
  fingerprints. Company/region/node scope, dedup, safe HTML and bounds required.

## Implementation and verification

- Driver, commit-last journal, sampling/Status integration, direct storage commands,
  acknowledged history, scoped SQLite/UI/CSV, schema regeneration and sleep guards
  implemented. Current valve/reset/power metadata stays live in routine reports.
- Native tests cover 13 actual mutating cut points across record allocation and
  clear/sweep, CRC corruption, queue/full, I/O failure, interleaved allocation/sweep
  and recovery. The regression rejects the old sweep behavior. Nine actual
  SPI driver/archive scenarios cover capture, missing chip, resume, cancellation,
  timeout and retention. Production LoRa reassembly passes 17/22/24-fragment tests.
- Release validation passes: 53 configuration policies, 65 WOR scenarios,
  16 RTC/Supmea scenarios, 124 server tests, 65 sensor-simulator tests, 10 release
  consistency/oracle tests, existing valve/MQTT/network/reset suites and UI checks.
- Seven ARM profiles and the exact final node-2 configuration compile below the
  reserved internal EEPROM boundary: normal SIM/Wi-Fi, timed LoRa Standby,
  LoRa WOR, gateway WOR, flash-disabled Wi-Fi and remote-wake Wi-Fi.
- Doxygen HTML/XML generated with an empty warning log. Design/use guide and
  step-by-step hardware plan are SPI_FLASH_TELEMETRY_GUIDE.md / SPI_FLASH_TEST_PLAN.md.
- Final-copy baseline comparison found no conflicting user edits. Only intended
  release files are synchronized; private files/live databases remain local.

Physical SPI and radio qualification, 24/48-hour soak and energy/endurance
measurements remain bench work. Software tests do not claim hardware acceptance.

Source: https://www.infineon.com/dgdl/Infineon-S25FL064L_64-Mbit_(8-Mbyte)_3.0_V_FL-L_SPI_Flash_Memory-DataSheet-v07_00-EN.pdf
