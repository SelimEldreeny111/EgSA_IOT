# Command lifecycle Phase 2 verification

5 October 2026. Baseline: `353b70e783519af637b722b0ee4807221c0d55d4`.
Branch: `feature/2026-10-05-command-lifecycle-phase2`.

The first three regression tests failed on the baseline: an old rate retry
blocked a new valve intent, newer rate settings did not retire older queued
settings, and retries had no attempt ceiling. They pass after this update.
Tests were expanded to cover publication/ACK races, timeout semantics, late and
duplicate replies, scoped audit access, concurrent claims, read-only legacy
import/corruption rejection, FIFO duplicate-cache eviction and actual dashboard
rendering. No sensor registers, pins, protobuf field numbers or private settings
were changed.

| Verification | Result and scope |
| --- | --- |
| Server Python | 98 passed: existing 78 plus 20 new lifecycle/PUBACK/API tests. Temporary DBs, mocked transport, no production DB writes. |
| Simulator Python | Existing 54 passed: 24 multi-sensor + 20 TUF + 10 Supmea. Implementations and EXEs unchanged. |
| Cross-component contracts | Existing six passed; all three protobuf sources and generated tags/descriptors remain consistent. |
| STM32 host | All seven suites passed. Actual command handler now tests repeated valve/RTC commands, old-rate duplicates after a newer setting, conflicting IDs, legacy zero IDs and eight-entry FIFO limits. Existing network, sensor, RTC, WDT and power regressions remain passing. |
| Policy checks | 39 power/network and eight valve configuration guards passed. |
| Dashboard | Five suites passed, including actual timeline escaping, unknown labels, overlapping-poll suppression, company-switch races and fetch errors. DOM fixtures, not exhaustive real-browser testing. |
| Doxygen | Regenerated in development and final folder; warnings.log is empty. Generated HTML/XML are ignored local artifacts. |
| Final-folder ARM matrix | All 13 profiles freshly passed with all four sensor drivers: normal SIM; remote SIM/WiFi/LoRa; RTC WiFi/LoRa; queued WiFi/LoRa; LoRa WOR; two gateways; two inhibited/synthetic valve test profiles. Every flash load ends below 0x08020000; maximum observed end 0x08015F6C. No upload. |
| Source syntax / whitespace | Actual Python imports and Node checks passed; git diff --check passed. CRLF normalization messages are not runtime failures. |
| Private/runtime preservation | Eight protected files (three private files, AppConfig.h and four live SQLite DBs) retain pre-release hashes; tests did not create a live command_lifecycle.db. |

The final-folder full runner passed with 158 Python tests total and five
JavaScript suites. Evidence is stored locally under
`Documentation/Validation/Phase2Evidence_20261005` in the final folder.
Changed public files are individually backed up and hash-checked against the
development checkout. Baseline sources and FINAL_COPY_INFO.md are preserved in
`backups/before_command_lifecycle_phase2_20261005`.

Compiler outputs were safely reused in `Documentation/FirmwareBuild_20261004`;
the new dated evidence contains the 5 October build transcript. That older-named
compiler directory now contains this release's builds, not the prior firmware.
Valve 60/80 ms test pulses are compile-only synthetic fixtures, not supplier
specifications. Do not upload those fixture binaries to a connected valve.

Existing third-party host warnings in ModbusMaster/PubSubClient and Paho's v1
callback deprecation are unchanged. They were not suppressed or claimed fixed.

## Acceptance boundaries

- PUBACK proves broker receipt, not node application or physical valve position.
- Journal dispatch/claim is committed before transport; failure in the narrow
  claim-to-publish window remains unknown rather than triggering a physical retry.
- VALVE, WAKE, STIME and GOSTM are not automatically application-resubmitted.
  MQTT QoS 1 may still duplicate/delay wire packets.
- Node ordinary duplicate suppression is eight entries in RAM only. Reboot,
  Standby or FIFO eviction removes the guard. No authenticated sequence/anti-replay
  guarantee is delivered. Supersession cannot cancel an already submitted packet.
- A successful cached ordinary-command reply reports original acceptance, not
  necessarily the currently effective setting; a newer intent may have changed it.
- Broadcast receipts are per-node only; no expected-fleet aggregate is asserted.
- Legacy immediate command history is not retroactively converted into proven
  execution audit. Only the existing legacy queued mailbox is imported.
- One server owns the journal. Multi-process deployments, retention, session
  revocation, authenticated framing/TLS, durable sensor outbox and finalized
  calendar quality/storage are later-stage work.
- No controller upload, live SIM/WiFi/RF broker session, coil pulse or power/current
  measurement occurred. Complete the guide's bench tests before field deployment.

Use [the operator guide](COMMAND_PHASE2_USER_GUIDE.md) for deployment, exact state
meanings, timing, rollback precautions and the individual T1–T12 hardware tests.
