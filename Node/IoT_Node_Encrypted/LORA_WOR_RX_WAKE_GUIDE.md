# LoRa WOR wake using UART RX

29 October 2026 | Arduino STM32 sensor node

## Recorded initial bench result

On 29 October 2026, the user tested firmware b60388b and confirmed current dropped
to approximately **9 mA**, compared with the earlier unsuccessful sleep attempt
at approximately **42 mA** (about 33 mA / 79% lower). The supplied log selects
wake_source=UART_RX and reaches `WOR Stop requested` with M0=0/M1=1 and no pending
wake/input data. This is the first reported successful current-reduction result
for the RX wake implementation.

The measurement point and averaging method were not specified; 9 mA is a reported
bench assembly reading, not MCU-only current or a whole-cycle average. RTC
heartbeat/report cycles and server command wake/reply are separate checks still
awaiting reported bench results. Full evidence and acceptance status are in
[the bench record](../../Documentation/Validation/LORA_WOR_9MA_BENCH_RESULT_20261029.md).

## Select the behavior

Keep the existing controller/radio modes:

```cpp
#define APP_CONTROLLER_POWER_MODE APP_COMPONENT_MODE_LORA_WOR
#define APP_LORA_POWER_MODE APP_COMPONENT_MODE_WAKE_ON_RADIO
```

The new default is:

```cpp
#define APP_LORA_WOR_WAKE_SOURCE APP_LORA_WOR_WAKE_SOURCE_UART_RX
```

This selector is under the WOR timing settings in src/config/AppConfig.h.
It changes the wake source within LORA_WOR; it does not add a new controller
mode number or change protobuf/server data. Other power profiles remain available.
The old AUX wake path can be selected explicitly:

```cpp
#define APP_LORA_WOR_WAKE_SOURCE APP_LORA_WOR_WAKE_SOURCE_AUX
```

## Wiring and prerequisites

| Signal | STM32 sensor-node pin | Purpose |
|---|---|---|
| LoRa TXD | PA12 (UART RX) | Received data and falling-edge EXTI wake |
| LoRa RXD | PA11 (UART TX) | Transmitted data |
| LoRa M0 | PB2 | Radio mode control |
| LoRa M1 | PB1 | Radio mode control |
| LoRa AUX | PC13 | Ready/busy checks; no wake interrupt in UART_RX mode |
| Ground | Common GND | Logic reference |

Use the existing UART wires; no new wake wire or resistor is required by this
software change. Restore the normal AUX connection if it was disconnected for
diagnostics. AUX is still required by the current driver during mode transitions
and transmissions. This update removes AUX as a wake source, not all AUX usage.

Select sensor-node role and LoRa uplink. The gateway remains NORMAL with
APP_LORA_GATEWAY_WOR_TX=1. Keep channel, air rate, UART settings, network ID,
company/region and unique node IDs consistent. The existing gateway firmware
already sends the required Mode-1 probe followed by the actual command; no
gateway code change is needed for this update.

Send STIME while awake to establish trusted RTC time. The 30-second IWDG and
configured 2..15-second RTC watchdog heartbeat remain active.

## Operation

After a successful report and the command window, the node selects radio Mode 2
and arms falling-edge EXTI on PA12. The helper in src/power/WorWakeInput.h keeps
the pin's UART alternate function: STM32duino attachInterrupt() otherwise changes
it to GPIO input. Mode/speed bits are restored before CPU IRQ delivery resumes;
UART AF mapping, pull settings and neighbouring pins are preserved. An invalid
initial UART pin mode leaves the node awake with an error.

While STM32 is in Stop, UART clocks stop. When a gateway probe starts appearing
on TXD/PA12, its first serial edge wakes the controller through GPIO EXTI. The
first bytes may be lost or corrupted while clocks recover. The gateway's current
probe-plus-250-ms-guard-plus-command sequence allows a separate actual command
to follow. The guard is an existing implementation value, not a guaranteed
manufacturer wake-latency specification; verify it on the actual boards.

The node restores clocks before servicing pending IRQs, returns the radio to
Mode 0, then uses the normal frame parser, CRC, fragmentation ACKs, command
handling and configured application reply. A wake edge is never treated as
proof of a valid command. After the receive window/work finishes it returns to
Mode 2 and Stop. A WAKE lease can postpone sleep.

RTC heartbeat wakes only service foreground watchdog maintenance and re-enter
Stop with the radio still in Mode 2. The default
`APP_LORA_WOR_USE_APP_SCHEDULE=true` now restores Mode 0 for the independently
due SRATE or STRAN task, without forcing the other task. `APP_POWER_SLEEP_SECONDS`
controls the combined cycle only when that selector is false. See
[WOR application scheduling](LORA_WOR_APP_SCHEDULE_GUIDE.md) for configuration
and separate sample/send tests. A watchdog expiry resets the controller; it is
not a normal wake.

## Read the log

At startup expect `Power: WOR wake source=UART_RX; AUX retained for radio readiness`.
Snapshots report wake_source, wake_level, wake_irq, wake_edge_phase, wake_pending,
uart_rx, stop_calls and rtc_elapsed_s. AUX is still printed as a readiness level.

| Evidence | Meaning |
|---|---|
| wake_source=UART_RX | RX pin is selected; no AUX wake callback is attached |
| WOR Stop requested | A Stop attempt is about to be made |
| WOR RTC heartbeat stop_calls=1 | First RTC maintenance return after a Stop call |
| reason=WAKE_EDGE_AFTER_STOP | Selected RX/AUX edge detected after a Stop call |
| reason=WAKE_EDGE_BEFORE_STOP | Selected input callback prevented Stop entry |
| reason=WAKE_LOW_BEFORE_STOP / WAKE_ACTIVITY_AT_ARM | Selected input was LOW at entry/arming |
| reason=UART_DATA_BEFORE_STOP / UART_DATA_AFTER_STOP | Buffered UART input caused a receive window |
| reason=WAKE_PIN_ARM_FAILED | UART-mode preservation/readback failed; active recovery |
| RX pin is not in UART alternate-function mode | Preflight failed before changing radio mode |
| reason=REPORT_DEADLINE | Scheduled report is due |
| reason=APPLICATION_DEADLINE | Independent SRATE and/or STRAN work is due |
| reason=RTC_CLOCK_DISCONTINUITY | Invalid RTC elapsed interval; active recovery |

stop_calls counts HAL invocations, not measured low-power residence. Confirm
current reduction and timed heartbeats; logging time is included in elapsed RTC
seconds. A pulse on PA12 can also be noise; RX wake does not diagnose the original
PC13/AUX symptom or guarantee lower board current without a bench test.

## Step-by-step bench qualification

1. Rebuild/flash the final-folder node sketch; keep its ID and private settings.
   Confirm wake_source=UART_RX. Keep the other node off initially.
2. Enable the gateway, send STIME and confirm one successful report.
3. For the first quiet test, set SRATE and STRAN to at least 150 seconds, then
   turn the gateway off after delivery. Observe for 30 seconds before the next
   application deadline. Expect Stop requests, heartbeats
   near the configured heartbeat interval, and reduced idle current. Restore the
   gateway before the next report is due.
4. With gateway on and no commands, observe two report cycles. Verify fresh
   sensor readings, delivered data and return to low current each time. The
   final bench configuration's sleep interval is preserved; check its actual value.
5. Send one immediate GOSTM while the node is sleeping, before the next timer
   deadline. Verify RX wake, decoded command, matching server reply (when ACK
   replies are enabled), and return to sleep. Repeat several times.
6. Test a larger fragmented reply/command, then add the second node with a
   distinct ID. Check CRC/fragment/ACK statistics and command routing. Radios
   sharing module address/channel can physically wake for another node's traffic;
   application filtering happens after wake.
7. Verify RTC/WDT reset counters do not increment during normal Stop wakes.
   Compare NORMAL and timed Standby as separate checks. Do not call the mode
   qualified until current, timer reporting and command/reply tests all pass.

## Software verification

tests/wor_stop/run_tests.ps1 compiles the production power manager for both wake
sources. It covers UART AF/speed/pull/AFR preservation, AUX-only activity ignored
as a wake in RX mode, invalid RX mode rejection, buffered RX preservation, fresh
edges at arming/WFI/heartbeat boundaries, neighbouring EXTI bits, RTC deadlines,
restoration errors and watchdog/WAKE leases. ARM builds cover UART_RX and AUX
WOR, timed-deep-sleep LoRa and the gateway. Host tests cannot establish RF timing
or actual current consumption.

References: [ST RM0368, GPIO and Stop mode](https://www.st.com/resource/en/reference_manual/DM00096844.pdf),
[Ebyte E32 manual, Mode 2](https://fccid.io/2ALPH-E32-TTL-100/User-Manual/User-manual-3359170.pdf).
