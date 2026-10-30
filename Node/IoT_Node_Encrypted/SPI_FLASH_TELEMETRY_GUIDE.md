# S25FL064L telemetry logging — design and user guide

Release: 30 October 2026. Scope: Arduino STM32 node and matching Python server.
The ESP32 and STM32CubeIDE projects are unchanged.

## Behavior

Enable `APP_ENABLE_SPI_FLASH` in `src/config/AppConfig.h`. After each completed
sampling cycle the node queues one complete four-sensor Telemetry snapshot.
Disabled/failed sensors keep their existing zero values and invalid flags. The
snapshot includes battery voltage, both flow-meter period totals and reset
counters. No RS485 register map changes are needed.

Routine transmission uses the **latest committed snapshot** to build the existing
Status message. Its timestamp remains the acquisition time, with
`stored_sample=true`, `sample_sequence` and `sample_time_valid`. Valve command
state, reset counters and current power state are refreshed at transmission so
operational information does not wait for another sample. Sampling/transmission
still follow the selected power policy; LORA_WOR and timed Standby retain their
existing report-cycle behavior.

If storage is missing, unformatted, recovering, faulted, empty or temporarily
busy, reporting continues with runtime values and `live_fallback=true`. This is
explicit degraded operation, not a claim that a record was saved. The drop count
exposes skipped/failed storage samples. GOSTM retains live telemetry behavior;
FLASH_LAST explicitly requests an archived sample.

## Hardware and part identification

The intended device is **Infineon/Cypress S25FL064L**, 64 Mbit = 8 MiB. Check its
marking; `S52FL064L` is not the part used by this driver. The driver accepts JEDEC
**01 60 17** only. It refuses writes to other IDs rather than guessing geometry.

| STM32 / schematic net | Flash signal | Direction |
| --- | --- | --- |
| PA4 / SPI1_CS | CS# | STM32 output |
| PA5 / SPI1_SCK | SCK | STM32 output |
| PA6 / SPI1_MISO | SO / IO1 | STM32 input |
| PA7 / SPI1_MOSI | SI / IO0 | STM32 output |
| Regulated 3.3 V | VCC | Supply |
| Common GND | VSS | Supply return |

Use 3.3 V logic/supply, 100 nF close to VCC/VSS, short wires and a CS# pull-up so
the device remains deselected during reset/Standby. For single SPI, hold the
package's WP#/IO2 and IO3/RESET#/HOLD functions at their required inactive levels.
Verify the exact package pinout in the datasheet: these are signal names, not
assumed package pin numbers. Do not power this flash from 5 V. SPI1 is dedicated
here; another user of these pins must coordinate chip selects and transactions.

Explicit four-byte-address opcodes 13h (read), 12h (program) and 21h (4 KiB erase)
avoid dependence on a retained three/four-byte address mode. Software never
issues whole-chip erase or changes nonvolatile protection registers. A protected
device reports a fault and needs investigation, not guessed register writes.

## Configuration

```cpp
#ifndef APP_ENABLE_SPI_FLASH
#define APP_ENABLE_SPI_FLASH true       // false: existing live reporting
#endif
#ifndef APP_FLASH_SPI_HZ
#define APP_FLASH_SPI_HZ 4000000UL       // start at 4 MHz on the bench
#endif
#ifndef APP_FLASH_HISTORY_ACK_TIMEOUT_MS
#define APP_FLASH_HISTORY_ACK_TIMEOUT_MS 60000UL
#endif
#ifndef APP_FLASH_HISTORY_MAX_ATTEMPTS
#define APP_FLASH_HISTORY_MAX_ATTEMPTS 3U
#endif
```

SPI accepts 100 kHz–12 MHz. ACK timeout accepts 10–300 seconds; attempts accept
1–5 and include the first send. A large low-air-rate LoRa frame or busy gateway
may need a longer timeout. A download keeps the controller active until completion,
cancel or bounded timeout. A format migration is needed before changing layout.
Gateways forward storage messages without keeping a local sensor archive.
Disabled builds do not open SPI and report Disabled when explicitly queried.

## First use

1. Update/run the server. For LoRa also update the gateway firmware; retain its
   normal controller mode and enable gateway WOR TX for WOR nodes. Match IDs,
   company/region and radio settings.
2. Wire with power off, then start the node. JEDEC should read `0x16017`.
   Unformatted is expected on a blank chip; boot does not silently erase it.
3. Send STIME to establish trusted RTC time. The default January 2024 clock
   is not trusted for storage/retention.
4. Send CLEAR_FLASH directly to this node with data **0** to initialize a blank
   log or start a new generation on a used chip.
5. Send FLASH_STATUS. Wait for Ready, then for `clear_sectors_remaining=0`.
   Sampling may coexist with reclamation; current-generation sectors are protected.
6. Wait for two completed sampling cycles. Check increasing frame count using
   FLASH_STATUS; compare FLASH_LAST values/time with that simulator sample.
7. Send FLASH_TODAY. Completion requires all declared records plus a successful
   terminal packet. Export CSV to compare. Replays do not enter live charts.

The archive card is on the Commands tab. **Refresh server archive** reads what
the server already saved; it does not query the physical node. FLASH_STATUS does.
The target is the selected company, region and command node.

## Commands

All storage commands target one node; broadcasts are rejected. The server assigns
a nonzero request ID. Use these IDs when diagnosing replies.

| Name | CMD ID | Data | Effect / reply |
| --- | --- | --- | --- |
| CLEAR_FLASH | 9 | 0 | Accept a new durable generation, cancel export and reclaim old sectors asynchronously. Requires trusted RTC. |
| FLASH_STATUS | 10 | 0 | Geometry, used/free, frame count, state, RTC trust and erase progress. |
| FLASH_LAST | 11 | 0 | Last retained committed sample, original time and sequence. Reject unavailable/busy storage; no sensor request. |
| FLASH_TODAY | 12 | 0 normally | Retained samples for the current node calendar day, frozen at request acceptance. |
| FLASH_CANCEL | 13 | 0 | Stop bulk transfer with a Cancelled terminal result. |
| HISTORY_ACK | 14 | `(phase << 32) | index` | Internal server persistence ACK with the same transfer request ID; not an operator command. |

STATUS/LAST/TODAY return requested data even if `APP_ENABLE_COMMAND_ACK_REPLIES=false`.
CLEAR/CANCEL automatic command replies follow that switch; execution continues.
Internal HISTORY_ACK is independent of that switch. A command ACK confirms
**acceptance**, not completed sector erase or a completed download. Poll status
for erase progress.

Repeating CLEAR_FLASH with the most recent manual-clear request ID is a no-op
across controller resets and automatic clears. This is not a permanent ledger
of all historical clear IDs: never replay an older clear after a newer one.
The server does not automatically retry flash commands. Use a new intentional
request if an outcome remains uncertain.

Advanced resume via `/api/command`: TODAY data can contain
`(generation << 32) | next_sequence`. Pass a **decimal string** to avoid JavaScript
integer precision loss and use a new request ID. The generation must still exist.
The normal menu starts at record one. A fresh full download is safe because the
server deduplicates records already received.

## 24-hour retention and “today”

Clearing is **every 24 elapsed hours**, not midnight. A batch starting at 14:20
expires around 14:20 next day. Persisted UTC start survives resets; power removal
does not deliberately restart the timer. If RTC trust is lost, capture and
time-based erase wait for STIME. Following a long outage, expired records clear
after recovery and trusted time become available. A forward time correction can
expire a batch sooner. Backward time blocks capture/automatic erase until it
catches up or an operator starts a new generation with CLEAR_FLASH.

TODAY filters the **retained batch** with the existing node calendar/timezone.
It may not contain a whole day's records because earlier ones expired or were
manually cleared. Day and final sequence are frozen at acceptance, excluding
later samples. Scheduled acquisition remains allowed during a bulk download.
New records are saved for a later download. Clearing this log does not reset
TUF-native or Supmea RTC totals.

At expiry a new metadata generation makes old records inaccessible through the
archive API. Physical erase follows in bounded foreground steps. Power modes may
pause the sweep between active windows; progress is reported. This is ordinary
flash reclamation, not a certified secure wipe.

## Capacity and format

| Item | Size / count |
| --- | ---: |
| Physical capacity | 8,388,608 bytes |
| Metadata | 2 × 4,096-byte sectors |
| Data sectors | 2,046 |
| Per sector | 512-byte header area + seven 512-byte slots |
| Maximum records | **14,322** |
| Record-slot space | 7,332,864 bytes |
| Stored protobuf payload | 1–472 bytes per record |
| Generated Telemetry maximum | 546 bytes before encryption |
| Encrypted frame maximum | 577 bytes (640-byte buffer) |
| MQTT packet buffer | 1,024 bytes |

A record contains version, sequence, epoch, calendar-day key, payload length,
payload, CRC32 and final commit marker. The stored protobuf omits history and
command ACKs. Actual payload lengths vary; allocation is always 512 bytes.
Used/free describe **record-slot capacity**, not all chip bytes. Torn occupied
slots count as used, but not as valid frames.

| Sampling | Samples / 24 h | Slot bytes | Fits |
| --- | ---: | ---: | --- |
| 1 hour | 24 | 12,288 | Yes |
| 1 minute | 1,440 | 737,280 | Yes |
| 10 seconds | 8,640 | 4,423,680 | Yes |
| 5 seconds | 17,280 | 8,847,360 | **No** |

Full storage stops appending and counts drops; it does not overwrite unexpired
records. Reports keep using the latest committed sample: inspect its timestamp.
Provision at least a 10-second sampling interval for a full-day batch here.

## Reliability, command priority and power

- Alternating metadata copies and commit-last CRC verification preserve the old
  generation if a metadata update tears. Record bodies are read back before commit.
- Recovery skips torn/CRC-bad records, consumes their slots and scans cooperatively.
  Queue capacity is four complete samples. Recovery can take noticeable time;
  reporting falls back explicitly while it runs.
- Drops/unavailable samples and recovery corruption are counted separately.
  These diagnostics are RAM since boot. Record count, generation, retention start
  and last manual-clear ID recover from flash. Existing reset counters keep their
  prior storage mechanism.
- Program/erase completion is polled in later passes, with 10 ms program and
  1,000 ms sector deadlines. There is no new busy-loop feeding of the WDT. The
  existing 30-second IWDG still handles a controller hang. Missing chips are probed
  every five seconds; protection/status/timeout faults need investigation/reboot.
- Commands precede sampling, routine uploads and bulk sends. At most one logical
  history record is sent per opportunity. Existing blocking Modbus/modem/radio
  calls cannot be preempted; measure real command latency during large downloads.
- Capture depends on completed sampling cycles. Existing modem startup and
  network-retry/controller-reset policies are retained; a prolonged network
  outage can prevent cycles from completing. This update preserves committed
  records across those resets; it does not make the existing network scheduler
  a lossless offline acquisition service. Include that outage case in mission tests.
- The server commits each record before ACK. Duplicates must have identical sample
  bytes. Missing rows, cancellation, expiry and timeout stay visibly incomplete.
  Transfers survive radio loss by retry, not MCU reset; reboot needs a new download.
- No sleep during recovery, writes or a transfer. Idle flash enters B9h deep
  power-down for Stop/Standby; ABh wakes it with a 50 µs guard. RTC sleep is
  shortened for a retention deadline. Other controller/modem policies remain intact.
- The external journal adds no STM32 internal flash writes. Existing EEPROM,
  reset-counter and Supmea consumption storage remain separate.

Data-sector start rotates, but this is not a full wear-levelling filesystem.
Two fixed metadata sectors limit endurance under frequent clears. A normal
automatic clear plus sweep completion produces two revisions/day, alternating
copies (about one erase per metadata sector/day). Do not use CLEAR_FLASH as a
poll command. Endurance/retention depend on temperature and cycling; no blanket
multi-decade retention guarantee is made.

External records are **plaintext** with CRC for accidental corruption. Existing
AES transport remains unchanged; this adds neither authenticated commands nor
encryption at rest. Replacing/externally erasing a chip may restart generation
numbers; conflicting archived identities are rejected, never silently overwritten.

## Server and wire contract

`flash_archive.db` is separate from live/consumption databases. Company, region,
node, generation/sequence and request/index scope records and transfers. UI/CSV
use the selected scope. Clearing a node does not erase the server's received rows;
maintain server backups and an appropriate disk retention policy.

Topics remain `wiot/{company}/{region}/{node}/status`, `/data` and `/cmd`.
Status appends tags 37–40 for sample source/time. Telemetry appends FlashLogInfo
(46), HistoryInfo (47), sequence (48), time-valid (49), stored-source (50), and
live-fallback (51). Existing tags are unchanged.

History kind: Last=1, Today=2. Phase: Preparing=1, Record=2, End=3.
Result: 0 OK, 1 Empty, 2 Not ready, 3 Time untrusted, 4 Cancelled,
5 Retention changed, 6 ACK timeout, 7 Read/encode failure, 8 Busy.

LoRa physical framing/version/CRC are unchanged. Reassembly now uses a 32-bit
mask and 640-byte logical buffer: up to 24 fragments of 27 data bytes. Old
16-fragment gateways cannot handle all new replies. Deploy **server, gateway,
then nodes**, keeping the previous release available for rollback.

Regenerate with repository-root `regenerate_protocol.py`, protoc 33.5 and nanopb
0.4.9.1. Canonical input is `src/generated/sensor.proto`. Run release checks and
firmware builds after generation.

## Qualification and source

Follow [the step-by-step acceptance plan](SPI_FLASH_TEST_PLAN.md). Native tests
use actual journal/driver/archive/reassembly code over simulated NOR/SPI; server
tests use temporary SQLite. Builds check internal EEPROM boundaries. Physical
wiring, RF delivery, long-duration retention, power stability and energy savings
remain hardware acceptance work.

Source: [S25FL064L manufacturer datasheet](https://www.infineon.com/dgdl/Infineon-S25FL064L_64-Mbit_(8-Mbyte)_3.0_V_FL-L_SPI_Flash_Memory-DataSheet-v07_00-EN.pdf),
JEDEC/command tables, program/erase timing, endurance and retention specifications.
Verify the exact purchased package and conditions.
