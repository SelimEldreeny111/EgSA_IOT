# Remote wake using the sampling and transmission schedule

5 October 2026 | Arduino STM32 node | SIM800, ESP8266 or LoRa NORMAL

## Configuration

Change the existing definitions in `src/config/AppConfig.h`, then rebuild and
flash the node. Keep your transport selection, node ID, credentials, sensor
addresses and commissioned valve settings unchanged.

```cpp
#define APP_CONTROLLER_POWER_MODE APP_COMPONENT_MODE_REMOTE_WAKE
#define APP_SIM_POWER_MODE        APP_COMPONENT_MODE_NORMAL
#define APP_WIFI_POWER_MODE       APP_COMPONENT_MODE_NORMAL
#define APP_LORA_POWER_MODE       APP_COMPONENT_MODE_NORMAL
#define APP_REMOTE_WAKE_USE_APP_SCHEDULE true
```

`APP_REMOTE_WAKE_USE_APP_SCHEDULE` defaults to true. NORMAL is still the factory
controller default. This switch affects REMOTE_WAKE only; RTC_PERIODIC,
RTC_QUEUED, LORA_WOR_STOP and NORMAL retain their existing behavior. Gateways
must remain NORMAL. Leave unused radios NORMAL; their physical power is not
automatically disconnected.

| Remote scheduling policy | Sampling/report behavior |
| --- | --- |
| true (new default) | Independent SRATE sampling and STRAN Status deadlines; idle between work and incoming commands |
| false (legacy) | Fresh sample and report after APP_POWER_SLEEP_SECONDS; active command window after successful reporting |

With true, `APP_POWER_SLEEP_SECONDS` and `APP_POWER_COMMAND_WINDOW_MS` do not
schedule remote work. They still apply to other policies/legacy mode and must
remain within the existing configuration guards. Do not set them to invalid
values to disable them.

## What the node does

1. At boot, it schedules an initial fresh sensor cycle and Status report.
2. It finishes the sensor cycle and queued transmissions/replies before idle.
3. When SRATE is due, it reads enabled sensors. Sampling alone does not force a
   Status report.
4. When STRAN is due, it sends the latest completed sensor snapshot. Transmission
   alone does not force another sensor read. If a cycle is unfinished, Status
   waits for the complete snapshot.
5. Incoming server commands keep their existing priority. An ordinary command
   executes, sends its configured reply, then the node returns to idle when
   nothing else is due. GOSTM explicitly replies with cached telemetry.
6. Explicit `WAKE N` still means an ACTIVE lease for N seconds, not a sleep
   interval. It schedules initial fresh work and permits ordinary scheduling
   during that lease. Data 0 uses APP_REMOTE_WAKE_DEFAULT_SECONDS. Duplicates
   do not extend the lease; expiry waits for outstanding work to finish.

Rate changes use the existing scheduling timestamps: the sampling period is
measured from sensor-cycle start, and transmission from its attempt. Shortening
a rate can make work immediately due. These are elapsed-millis timers, not
calendar-aligned RTC alarms or exact completion-time guarantees. If sensor work
takes longer than SRATE, little or no idle time is expected.

`APP_ENABLE_COMMAND_ACK_REPLIES` is unchanged. When false, ordinary automatic
command replies are silent; explicit GOSTM and periodic Status still work. A
server broker receipt is not confirmation of node execution.

## Important sleep limits

This is **light CPU Sleep (WFI), not Stop or Standby**. SIM/WiFi/LoRa stays
NORMAL and reachable. UART interrupts, the 1-ms SysTick, foreground MQTT
servicing (normally every APP_REMOTE_WAKE_POLL_INTERVAL_MS, default 100 ms),
keepalive and watchdog checkpoints continue. Therefore brief maintenance CPU
wakeups still happen even with no command/sample/report due. This is required
by the existing always-connected architecture; the CPU cannot literally remain
asleep until only those three events while maintaining this implementation.

No ISR feeds the watchdog. The 30-second IWDG stuck-path protection and existing
10+10 network retry/modem/controller recovery are unchanged. Lost connectivity
requires reconnection work; remote command reception is only possible while
the link is available. No new modem wiring, schema or server update is needed.
No current-saving figure is claimed without a whole-board measurement.

## Bench tests, one at a time

Use the same node ID and AES configuration at both ends. Use SRATE/STRAN controls
in the existing server and observe the node debug log and server timestamps.
Short periods are test settings; restore your production periods afterward.

| Test | Action | Expected result |
| --- | --- | --- |
| Boot | Flash with the configuration above | New schedule-driven remote message, initial sample/report, then idle |
| Sample only | SRATE=10 seconds, STRAN=30 seconds | Sensor cycles every approximately 10 seconds; ordinary Status every approximately 30 seconds |
| Transmit only | SRATE=30 seconds, STRAN=10 seconds | Status may repeat a valid completed snapshot; no forced read at every transmission |
| Command while idle | Set both periods to 120 seconds; send GOSTM or an ordinary valid command | Command/reply is handled without waiting for the next scheduled sample; return to idle afterward |
| Complete snapshot | Enable four sensors; send a command during their polling | Command priority preserved; sensor cycle resumes and completes before periodic Status |
| Explicit WAKE | Send WAKE=15 | ACTIVE lease for 15 seconds; then idle when work completes; duplicate request does not extend it |
| No fixed idle trigger | Set valid APP_POWER_SLEEP_SECONDS=5, SRATE=60 seconds, STRAN=120 seconds | No forced fresh sample/report every 5 seconds under the true policy |
| Both IP transports | Repeat idle-command and schedule tests separately in SIM and WiFi builds | Same scheduling behavior in both; reception depends on connection availability |
| Network loss | Disconnect network, then restore it | Existing bounded recovery operates; no false claim of remote reception while offline |
| Legacy compatibility | Rebuild with APP_REMOTE_WAKE_USE_APP_SCHEDULE=false | Old fixed-interval remote cycle and command window return |

Software regression fixtures and ARM compilation do not prove electrical
current reduction, modem latency or physical valve movement. Hardware timing
and current traces are acceptance evidence to collect on your board.

For repeatable offline regression checks, run the repository's
`Validate-Release.ps1` with your installed Python, g++ and Node.js paths. On a
commissioned bench copy, also pass `-UseFactoryConfigurationFixture`: this
isolates the factory valve guard tests without editing your working valve
configuration. The development release is checked without that flag so its
shipped inhibited-valve defaults remain verified. Both remote policies run in
the host suite; the ARM matrix also accepts
`-RemoteWakeApplicationSchedule false` to compile the preserved legacy policy.
