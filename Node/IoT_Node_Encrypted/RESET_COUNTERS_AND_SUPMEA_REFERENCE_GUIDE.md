# Power/WDT counters and independent SUPMEA comparison

Release: 25 October 2026. Applies to the Arduino STM32 node, web server and
SUPMEA simulators. ESP32 and CubeIDE ports are unchanged. This supplements
the 7 October Word design baseline.

## 1. Reset classification

| Detected event | Power count | WDT count |
|---|---|---|
| Power-on / brownout (POR/BOR) | +1 | Unchanged |
| IWDG timeout, including deliberate network-recovery IWDG reset | Unchanged | +1 |
| Software reset / reset-before-Standby handoff | Unchanged | Unchanged |
| Standby wake, Stop wake or light Sleep wake | Unchanged | Unchanged |
| NRST/reset-button only | Unchanged | Unchanged |
| Other/unknown cause, including WWDG | Unchanged | Unchanged |

“Power” does not mean every non-WDT reset. RCC and PWR Standby flags are captured
before PowerManager clears them. Standby and specific warm-reset flags take
precedence over mixed power flags. PINRSTF can accompany POR, so POR+PIN counts.
The hardware cannot reconstruct downtime or classify every supply fault.

No new enable/config switch is required. Power counting works even if the
application watchdog is disabled. The existing nominal WDT deadline stays 30 s.
Both counters saturate at UINT32_MAX and retain their values in flash.

| Record | EEPROM-emulation offsets |
|---|---|
| Existing WDT counter, unchanged format | 192..211 |
| Existing valve record | 212..231 |
| New power counter | 232..251 |

Wi-Fi and SUPMEA records are not relocated. Blank storage starts at zero; a
qualifying boot then increments to one. Programming firmware does not necessarily
perform a power cycle. A corrupt record is rejected and logged, starting a new
count. A failed boot write may leave a RAM-only count with a warning.
Buffered updates preserve other logical records, but all share an erase sector:
power loss during erase is not transaction-atomic. Full-chip erase can remove
the counters. They are retained diagnostics, not tamper-proof lifetime records.

## 2. Reporting and server deployment

| Message | WDT field (unchanged) | New field |
|---|---|---|
| Status_Message | wdt_reset_count, tag 35 | power_reset_count, tag 36 |
| Telemetry | wdt_reset_count, tag 44 | power_reset_count, tag 45 |

The common mapper supplies both fields to SIM, Wi-Fi and LoRa paths. Existing
tags and the encryption envelope are unchanged. Old readers ignore the additive
field; an old node's absent power field decodes as zero, not proof of zero resets.
The server dashboard/node details, latest-node API and CSV show both counters.
Its additive DB migration preserves existing rows; historical power counts
cannot be reconstructed and default to zero.

Update/restart the web server with its usual secrets and settings. No new AES
key or password is needed. Back up production databases before deployment.
The automated tests use temporary databases, not your production records.
Hard-refresh the browser (Ctrl+F5) so the new command controls and JavaScript load.

## 3. Clear commands

| Server selection | Command ID | Data | Effect |
|---|---|---|---|
| CLEAR_POWER_RESETS | 7 | 0 | Clear power counter only |
| CLEAR_WDT_RESETS | 8 | 0 | Clear WDT counter only |

1. Select company and individual node in the command panel.
2. Select the appropriate Clear command. Data is fixed to zero.
3. Choose immediate delivery for a reachable node, or next-wake delivery for
   RTC_QUEUED, then accept the browser confirmation.
4. Inspect the command timeline for the matching node/request ID.
5. Check the selected count is zero in the reply or later GOSTM/Status, with the
   other count, sensors, consumption history and valve state unchanged.

Broadcast clears are rejected. A nonzero request ID is mandatory; the server
allocates it. Nonzero data and foreign-node requests are rejected.
For a decoded manual request: cmd_id=7, cmd_data=0, request_id=12345. Use a new
request ID for each intentional action; do not repeatedly reuse that example ID.

Clear persists and verifies zero before returning success. Failure rejects the
command and retains the previous RAM value. An already verified zero needs no
new flash write. This operation does not reset the MCU/modem, actuate the valve,
clear meter cumulative totals or erase the SUPMEA RTC consumption history.
The next qualifying reset after clear increments the relevant count to one.

APP_ENABLE_COMMAND_ACK_REPLIES still controls automatic replies. With true,
Telemetry carries the matching request ID, command ID and application result.
With false, the operation is silent; use GOSTM to inspect counts. Broker receipt
alone is not execution confirmation.
The bounded RAM replay cache prevents an exact duplicate clear during its cache
window; reboot loses that cache. The server does not automatically retry clears.
An unknown outcome requires operator reconciliation before a new clear action.

## 4. What the simulator calculates

The simulator independently integrates positive volumetric flow:

    volume_m3 = max(flow_m3h, 0) * elapsed_seconds / 3600

It splits elapsed time at local-calendar day boundaries and resets day/month/year
buckets when their keys change. Reverse flow does not increase forward
consumption, matching the node's use of forward totals.
Volumetric unit codes 0..5 are supported; mass codes 6..11 have no assumed density.
Auto totalizers off or mass units pause volume accumulation.

This oracle uses flow, monotonic elapsed time and Python timezone data.
The node instead subtracts cumulative forward totals and applies its RTC
calendar. The oracle does not import the node's accumulation algorithm.

**No day/month/year Modbus registers are added.** Reference fields are outside
the register-value dictionary. They are displayed/exported only; the original
SUPMEA register replies remain the same.
These are session totals, not reconstructed history before the test started.
Restarting/reloading/editing devices can start a new session; export results
before discarding a run.

## 5. Multi-sensor GUI

The old EXE was running during this build and was left untouched. Updated build:

    SENSORS/Multi Sensor RS485 Simulator/dist/20261025/WIOT_MultiSensor_RS485_Simulator.exe

1. When ready, close/disconnect the old instance so only one program owns the COM
   port. Load stm32_four_sensor_config.json for node addresses TUF1/SUPMEA2/HNDA3/Sondas4.
2. Select SUPMEA. Start with fixed flow 36 m3/h, unit code 3, time multiplier 1,
   auto totalizers enabled, no injected faults, and a matching node Modbus address.
3. Open the SUPMEA RTC test tab. Select the node's calendar:
   Africa/Cairo, UTC, or a matching fixed +HH:MM/-HH:MM offset.
4. Leave start time blank for PC UTC now. Press Start / reset comparison reference.
5. Watch Today/Month/Year, UTC/local clock, session start and state.
   Export selected SUPMEA reference JSON to save the device profile and result.

Each SUPMEA address has a separate reference. Muting communication does not turn
off simulated flow. Device edits restart runtime; do not treat edits as continuous
measurement. Explicit ISO start time such as 2026-12-31T23:59:30Z changes only the
virtual reference clock, not the PC or MCU clock. For real nodes use time x1:
accelerating the simulator does not accelerate the MCU RTC.
If timezone data is unavailable, install the simulator requirements (tzdata) or
choose UTC/a fixed offset. Packaged executables include timezone data.

The standalone updated simulator also includes the independent reference:

    SENSORS/Supmea Flow meter/simulator/dist/SUPMEA_FMC240_Simulator.exe

Choose its calendar, start the bus, then use Reset comparison only for alignment.
Starting the standalone bus creates a fresh reference session. Reset meter totals
is a different action that changes wire cumulative totals; reserve it for
deliberate counter-reset fault tests.

## 6. Physical-node comparison procedure

1. Flash the updated Arduino STM32 image with the established toolchain. Preserve
   retained flash records unless a deliberate commissioning reset is required.
2. Confirm IDs/topics/keys and sensor address. Use NORMAL mode first to remove
   sleep/reconnection timing from the initial measurement.
3. Send STIME and confirm trusted node RTC. The startup 2024 fallback is not trusted.
4. Match PC UTC, MCU UTC and calendar policy. For Cairo the oracle uses tzdata;
   the node uses its coded offline DST rule. Check agreement for the test dates.
5. Allow a valid SUPMEA cumulative baseline. Automatic cumulative totals must
   advance; a nonzero flow display with fixed totals cannot produce node consumption.
6. Record node D/M/Y values N0 and start the reference near that acquisition.
   If the node already has history, compare N1 minus N0 with simulator session
   growth while endpoints remain in the same bucket. Do not compare a historical
   node bucket directly to a newly zeroed session.
   With TUF and SUPMEA both enabled, use SUPMEA's secondary_flow_meter periods
   or the SUPMEA RTC serial-debug group. The primary/legacy flow fields belong
   to TUF in that configuration and are not the SUPMEA comparison target.
7. At 36 m3/h expect 0.6 m3 after 60 s, 6 m3 after 10 min, and 36 m3 after 1 h.
   Save elapsed time, meter forward totals, node validity/quality and reference JSON.
8. Align acquisition times, not merely browser arrival times. SRATE, STRAN,
   simulator tick, transport delay and UTC-second rounding cause apparent offset.
9. Repeat with zero/reverse flow, equivalent volumetric units and muted replies.
   Invalid node values must be zero/invalid, not interpreted as valid zero volume.
   Recovery should use the retained cumulative baseline.
10. Use the automated production-C++/oracle tests for boundaries first. A
    simulator-only accelerated clock is not a valid MCU day/month/year test.

A conservative constant-flow tolerance includes meter quantization plus
flow_m3h * timestamp_skew_seconds / 3600. A difference between two endpoint
changes has uncertainty at both endpoints. Establish skew from acquisition/report
intervals and logs, not arrival time alone.
Integer-liter node storage and Float32 meter/protobuf precision prevent assuming
bit-exact equality. At very large cumulative totals Float32 error can exceed 1 L.
Variable flow between samples can make the node's estimated boundary allocation
differ from the finer simulator integral; check flow_period_quality and start with
constant-flow boundary tests. Session totals never reconstruct pre-test history.

## 7. Individual counter acceptance tests

| Test | Required result |
|---|---|
| One actual MCU supply cycle | Power +1, WDT unchanged |
| Controlled IWDG self-test, valve safely disconnected | WDT +1, power unchanged |
| NRST then separate software reset | Neither increments |
| Several scheduled Standby wakes | Neither increments |
| Clear power then clear WDT separately | Selected count zero, other unchanged, matching ACK if enabled |
| Nonzero clear data, broadcast, missing ID, wrong node | Rejected; no clear |
| Repeat an exact request in the current RAM-cache window | Original result, no repeated write |
| Reboot after clear | Zero retained, except a qualifying reset increments it |
| Host-only failed flash verification | Rejected; previous RAM value retained |

Restore WDT self-test configuration after testing. Do not damage live flash or
inject unsafe power faults with the valve energized. Host and compilation tests
do not replace physical reset-flag, supply, sensor and power-mode acceptance.
