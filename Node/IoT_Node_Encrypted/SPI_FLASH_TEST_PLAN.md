# SPI flash acceptance plan

Release: 30 October 2026. Record board/chip marking, JEDEC ID, firmware commit,
server revision, profile, company/region/node, RTC timezone, SPI clock, sampling
and transmission periods with each result. Software checks do not replace these
physical tests. Use the matching updated gateway for every LoRa test.

## Preparation

1. Back up the current configuration and server databases. Use a bench node and
   simulator with unique sensor addresses. Keep the coil inhibited for storage
   tests unless a valve operation is intentionally part of the test.
2. Verify the 3.3 V SPI wiring against the exact S25FL064L package. Connect common
   ground and decoupling. Measure the MCU/flash supply during erase/radio TX.
3. First use controller/modem NORMAL, all four enabled sensors, sampling 10 s,
   transmission 60 s and SPI 4 MHz. Leave WDT at 30 s. Run the updated server.
4. For the first initialization explicitly approve the loss of existing external
   log data by sending CLEAR_FLASH. This does not clear reset counters or Supmea
   consumption accumulators. Store the server result and boot log as evidence.

## Tests in order

| ID | Procedure | Expected result / evidence |
| --- | --- | --- |
| F01 Identification | Start with the intended chip; request FLASH_STATUS. | JEDEC 01 60 17; capacity 8,388,608 B; max frames 14,322. Blank log is Unformatted until F03. |
| F02 Missing / wrong chip | Power off, disconnect flash or use a known different device, restart. Do not hot-plug. | Missing state; no write to unknown JEDEC; normal reporting continues with live fallback. No reset loop. Reconnect while off and retest. |
| F03 Time / initialization | Before STIME request clear, then send STIME and clear with data 0. Poll status. | Untrusted clear rejected. Trusted clear accepted; generation advances, old count becomes 0 after metadata commit, physical progress reaches 0. |
| F04 Complete samples | Enable all four simulator types with fixed distinctive values; let 3 full cycles finish. | Record count increases once per completed cycle, not per sensor. FLASH_LAST contains both meters, HNDA, Sondas, battery and original time. |
| F05 Routine latest | Sampling 10 s, transmission 60 s. Change simulator values between samples. | Routine Status uses the newest committed sample and its timestamp/sequence. No partial four-sensor snapshot. |
| F06 Failed acquisition | Disable replies from one sensor for a cycle, then all sensors; restore them. | Stored failed groups are zero plus invalid flags. FLASH_LAST and routine sample reflect failure/recovery; they do not reuse the previous successful group. |
| F07 Reset recovery | After 3 committed samples press RESET, then power-cycle. Resynchronize time if needed. | Recovering then Ready; same retained generation/start and valid records. No automatic format. Power/WDT counters retain their separate prior behavior. |
| F08 Torn write | Repeatedly remove power during a new record write, then during CLEAR_FLASH. Repeat at several offsets using a controlled bench supply. | Previous committed records/generation or completed new generation only. No mixed generation, garbage sensor values, queue underflow or unbounded boot. Torn slots may count as occupied/corrupt. |
| F09 Clear idempotence | Resend exactly the same clear request ID before/after reboot; acquire a sample between repeats. | Latest manual-clear ID is a no-op; the new sample survives. A new intentional ID starts a new generation. |
| F10 Today download | Acquire N known samples for the current node calendar day; request FLASH_TODAY. | N unique scoped rows, matching sequence/time/values, declared count and successful End. Live charts and consumption do not change from replay. CSV contains those rows. |
| F11 Duplicate / RF loss | Interrupt the server connection or RF after one row; restore before bounded timeout. | Same record retries until server persistence ACK. One stored row per generation/sequence. No false complete if terminal/rows are missing. |
| F12 Timeout / cancel | Keep server unavailable past configured attempts; separately send FLASH_CANCEL during another transfer. | ACK timeout / Cancelled terminal result. Node returns to normal scheduling/sleep after terminal delivery or bounded retries. A fresh download can recover missing rows. |
| F13 Command priority | During a bulk download send GOSTM and a rate change; use a commissioned valve only if desired. | Commands/replies precede the next bulk packet. Measure worst real latency; in-flight blocking modem/LoRa calls remain non-preemptible. |
| F14 Calendar filter | Acquire across node-local midnight while the 24-hour batch remains valid; request TODAY after midnight. | Only records from the newly selected node day, original times intact. No midnight clear merely because day changed. |
| F15 24-hour clear | Note retention start. For a controlled functional test use STIME near start+86,399, then start+86,400. Also perform a real 24-hour soak. | Before expiry records remain. At/after expiry new generation and count 0, with physical erase progress. Reset does not restart the timer. Time jump is only a boundary test, not endurance proof. |
| F16 Invalid/backward RTC | Move time behind retention start in a bench test or remove RTC trust, then request capture/automatic clear. | No time-based erase or falsely dated stored sample. Drops/live fallback visible. Trusted corrected time or explicit trusted clear resumes operation. |
| F17 Clear during export | Clear manually or cross the 24-hour deadline while TODAY is active. | Old transfer ends Cancelled or Retention changed. No old/new-generation mixing or claim of complete old history. |
| F18 Full log | Run the native reduced-geometry/full test. Physical filling needs a separately reviewed stress harness; do not change production geometry/retention to simulate it. | Full state at the available physical slots, no overwrite of retained data, drop count increases. Clear/expiry restores capacity. Production geometry has 14,322 slots. |
| F19 Tenant boundaries | Select another company/region/node; request archive status/CSV; try broadcast flash commands. | Queries stay scoped; unauthorized company denied; no other node's rows shown; broadcast rejected. |
| F20 Power modes | Repeat F04/F05/F10 under REMOTE_WAKE, timed Standby and LORA_WOR with the proper modem policy. | No sleep during write/recovery/export; idle flash DPD; records recover after Standby reset. WOR RX wake still works and retention alarm can shorten sleep. |
| F21 Disabled feature | Build with APP_ENABLE_SPI_FLASH=false and repeat normal sensor/report/command tests. | Existing live behavior; no SPI access, explicit flash queries show Disabled/rejection. |
| F22 Long operation | Run at least 48 h with sampling/transmission and periodic history download; capture current and supplies. | Two elapsed-time rollovers, no resets/hangs or unexplained drops/duplicates. Compare frame count with completed cycles, excluding documented unavailable periods. |
| F23 Network outage | Remove Wi-Fi/GSM service during acquisition, observe existing retry/reset policy, then restore service. | Committed records survive. Identify gaps caused by blocked setup/retries/resets; continuous offline sampling is not guaranteed by this unchanged network scheduler. |

## Protocol and diagnostic checks

- A clear command success is acceptance. Physical completion requires
  `clear_sectors_remaining=0` and no pending write. New-generation samples may
  increase the count before physical reclamation finishes.
- Download Complete means all declared rows persisted and a successful End
  arrived. A broker receipt, modem SEND OK or LoRa fragment ACK alone does not
  prove server record persistence. Empty is a valid complete result with zero rows.
- Record used/free capacity counts 512-byte slots, including unusable torn slots.
  Valid record count can therefore be less than used/512 after a torn write.
- Record the acquisition time separately from server receipt time. A full or
  unavailable log must not be interpreted as a fresh flash sample.
- Test bulk latency and energy with the actual RF rate and gateway traffic. A
  day's samples can require many individual logical/physical frames.

## Reproducible software checks

From repository root, with the dependencies in RELEASE_GUIDE.md:

```powershell
.\Validate-Release.ps1 -UseFactoryConfigurationFixture
.\Node\IoT_Node_Encrypted\tests\remote_wake\run_build_matrix.ps1 `
  -Profiles normal-sim,normal-wifi,rtc-lora,wor-lora,gateway-wor,flash-disabled-wifi
.\Node\IoT_Node_Encrypted\generate_doxygen.ps1
```

The factory fixture is only for the final commissioned bench configuration. It
does not edit AppConfig.h. Native flash tests cover actual SPI commands, page and
address limits, program/erase timeout, missing chip retry, complete snapshots,
last/today/resume, cancel, timeout, retention change, corruption, queue/full,
metadata/record cut transitions, and production large-frame LoRa reassembly.
Server tests cover persistence-before-ACK, dedup, conflict rollback, partial
transfer, scope, CSV routes and separation from live ingestion. No test contacts
a live broker or physical COM port.

Hardware results are **not yet recorded** for this new SPI feature. Fill this
plan with pass/fail, evidence paths and defects after running the bench sequence.
