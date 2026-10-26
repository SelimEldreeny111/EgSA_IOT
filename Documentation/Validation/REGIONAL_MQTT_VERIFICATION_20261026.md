# Regional MQTT routing — verification

Date: 26 October 2026. Arduino STM32 node and active Python web server.

## Delivered contract

Bench identity: Company_1 / Region_1 / node 3.

- `wiot/Company_1/Region_1/3/data` — existing Telemetry protobuf/replies.
- `wiot/Company_1/Region_1/3/status` — existing Status_Message protobuf.
- `wiot/Company_1/Region_1/3/cmd` — direct command.
- `wiot/Company_1/Region_1/broadcast` — regional broadcast.

Public identity macros generate all node topics and its client ID. Compile-time
checks reject invalid/oversized segments, noncanonical node literals and a
packet buffer too small for the maximum encrypted telemetry plus topic.
Gateway parsing/forwarding and the public configuration template use the same
contract. APP_LORA_NETWORK_ID exposes the existing wire network ID so different
co-located regional radio networks can be commissioned separately.

The server parses exact lowercase topics and stores region in messages, meter
samples, consumption-period uniqueness and the command journal. Region scopes
queued dispatch, supersession, ACKs, current readings, charts, history and CSV.
Company/region are both included in CSV output. Browser WAKE tracking, map
positions and thresholds include region; legacy browser settings are read only
as Region_1 settings. Stale responses and pending STIME startup cannot switch
an operation/view into another company or region.

Existing database rows and command intents default to Region_1. Consumption
uniqueness is rebuilt transactionally and timestamp migration preserves region
and both reset counters. Server API calls that omit region use Region_1;
explicit invalid regions fail validation. Company permissions remain unchanged.

No protobuf, encryption, reset-counter storage format, sensor Modbus protocol,
ESP32 or CubeIDE-port changes. Source/deployment credentials are not committed.
No live MQTT publication, server restart, node upload or production migration
is performed by the verification commands.

## Completed checks

- Full release validator: PASS in the final folder with the factory-configuration
  test fixture; PASS in the development copy with shipped defaults.
- Server regression: 110 tests PASS, including nine new regional tests.
- Cross-component regression: nine tests PASS, including compilation of the
  production gateway parser and generated topic definitions.
- Seven node host suites PASS: valve, MQTT priority, network recovery, watchdog
  counters, sensor availability, RTC/SUPMEA and remote-wake scheduling.
- Existing simulator suites remain passing: multi-sensor 34, TUF 20, standalone
  SUPMEA 11 tests. Source/EXEs for the simulators are not changed by this feature.
- Dashboard JavaScript suites PASS, including actual region-switch timeline
  race handling, regional WAKE/broadcast ACK matching and legacy browser-setting
  isolation. Actual dashboard HTML contains one Region control and region list.
- Same company/node ID in Region_1 and Region_2 retains separate live records,
  meter samples, day/month/year periods, history, CSV and command outcomes.
- Bad topic shapes, uppercase aliases, old root, wildcard identifiers, node-ID
  aliases, invalid explicit API regions and foreign-region gateway commands fail.
- Disposable backups of both live company databases migrate without changing
  counts. Snapshot Company_1: 2,766 messages / 2,919 meter samples / nine periods;
  Company_2: 1,247 messages / 1,954 meter samples / nine periods. Source connections
  are read-only; the migrated copies are discarded.
- Doxygen regenerated in both locations with empty warning logs.

## ARM firmware evidence

All four sensor drivers are enabled in each profile. These are compile checks,
not physical timing/radio tests.

| Profile | End of flash load |
|---|---|
| normal-sim | 0x080162FC |
| remote-wifi | 0x08016184 |
| remote-lora | 0x08015A34 |
| queued-wifi | 0x08016CFC |
| gateway-wifi | 0x0800E4E0 |
| gateway-wor | 0x0800E550 |

The final normal-sim build was repeated after adding the last configuration
guards and passed. Maximum load end stays below the reserved EEPROM sector
0x08020000, leaving 37,636 bytes. Maximum static RAM among these six profiles is
26,492 bytes; stack/heap and physical timing remain hardware acceptance items.

## Local evidence and deployment

- Documentation/region-full-regression.log
- Documentation/region-server-regression.log
- Documentation/region-isolation-tests.log
- Documentation/region-node-mqtt-tests.log
- Documentation/region-arm-build.log
- Documentation/region-final-arm-smoke.log
- Documentation/FirmwareBuildRegionTopics_20261026/build-matrix-six-profiles.log
- Documentation/region-doxygen.log
- Development copy: Documentation/region-development-regression.log
- Development copy: Documentation/region-development-doxygen.log

The full validator predates the final CSV/HTML assertion and browser-setting
refinements; the final server and JavaScript suites are rerun for those changes.
The user must coordinate updated node flashing and server restart/broker
reconnection, hard-refresh the browser, then perform the hardware tests in
Node/IoT_Node_Encrypted/REGIONAL_MQTT_TOPICS_GUIDE.md.
