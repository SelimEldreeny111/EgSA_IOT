# LoRa WOR arming and wake diagnostics

**2 November 2026 scheduling update:** the default WOR policy now follows
independent SRATE/STRAN deadlines. See the [current scheduling and bench
guide](LORA_WOR_APP_SCHEDULE_GUIDE.md). The fixed APP_POWER_SLEEP_SECONDS timing
in the older diagnostic examples below applies only with
`APP_LORA_WOR_USE_APP_SCHEDULE=false`.

**29 October 2026: the default WOR wake input is now UART_RX (PA12 on a sensor
node).** Use [the RX wake guide](LORA_WOR_RX_WAKE_GUIDE.md) for the active
configuration, new wake_source/wake_irq diagnostics and bench tests. The
AUX-specific logs and investigations below describe the earlier implementation,
which remains selectable with APP_LORA_WOR_WAKE_SOURCE_AUX. That implementation
continued to exit before Stop in the supplied bench logs; it is not recorded as
physically fixed.

29 October 2026 | Active Arduino STM32 node only

The bench log repeatedly reported `LoRa AUX woke STM32` while UART counters did
not change. An AUX reading of 3.3 V rules out a continuous LOW at the instant
measured, but does not exclude a short pulse or an already pending interrupt.
The previous message also covered a LOW/edge before Stop was called. It could
not establish either sustained Stop residence or reception of a command.

## Latest bench finding and correction

The latest log shows `before=0x0 tamper1=0`: no retained RTC pin ownership was
observed. It reports `AUX_EDGE_BEFORE_STOP`, `stop_calls=0`, and callback delivery
phase `RADIO_ARMING`, while received-byte counters remain unchanged. The RTC
ownership guard did not resolve that test. Callback delivery phase does not
identify the exact electrical source of the edge.

The previous arming sequence cleared EXTI history **before** Mode 2 preparation,
then attached the AUX callback with interrupts enabled. History accumulated during
mode preparation or GPIO routing could therefore be delivered as a new wake.
The installed STM32 core's GPIO interrupt attachment does not clear that history.
The repeated exit also restored Mode 0, repeating the preparation on the next try.

The new receive boundary is established **after** Mode 2 preparation:

1. Keep the LoRa UART initialized during the mode transition and Stop cycle.
   STM32 HardwareSerial.end() discards buffered received bytes, and begin() resets
   its receive indices. Neither operation is used for WOR entry/resume now.
   Stop gates the F401 peripheral clocks while retaining UART configuration and
   RAM; this does not make the UART capable of receiving while clocks are stopped.
2. Mask CPU IRQ delivery briefly while attaching the AUX callback. If AUX is HIGH
   and the UART RX ring is empty, clear only the AUX line's pre-arm EXTI history.
   This is an explicit arming boundary, not a timed debounce or a claim that the
   earlier edge was definitely a modem busy pulse.
3. Preserve LOW AUX or buffered RX at the boundary; recheck both after clearing.
   Leave all new edges after that clear pending. Never clear the shared NVIC IRQ
   or neighbouring GPIO pending bits. Set phase `RECEIVE_ARMED` before restoring
   IRQ delivery.
4. Buffered UART data also prevents Stop and opens the receive window. RX bytes
   remain available to the existing frame parser when Mode 0 is restored.

An edge that completed before this boundary with AUX HIGH and no buffered RX is
classified as pre-arm history. Actual RF commands still require a decoded frame
and matching reply. The gateway probe-plus-command exchange remains required;
a probe can be missed while the STM32 clocks are stopped. Only the new bench test
can establish whether the observed high-current loop is resolved.

## Change and scope

- Follow-up to the `AUX_EDGE_BEFORE_STOP / stop_calls=0` bench log: reserve PC13
  for the AUX GPIO by disabling unused external RTC alarm/calibration outputs,
  timestamp input and tamper-1 input in the WOR profile. Preserve the internal
  alarm, RTC calendar, backup registers and oscillator configuration. Log the
  previous ownership bits; a zero value means no retained RTC pin conflict was
  observed. The installed RTC library can retain an already initialized backup
  domain, so its requested default output configuration alone is not readback
  evidence of actual pin ownership.
- Clear only the AUX GPIO EXTI pending bit, while the line is HIGH, before
  switching the radio into Mode 2. Do not clear the shared NVIC interrupt vector
  or any neighbouring GPIO pending bit. A LOW line preserves its pending bit.
- Initialize the AUX software flag before radio preparation; establish the final
  idle EXTI baseline after preparation and interrupt routing as described above.
  Preserve all edges after that boundary, including alarm programming and the
  heartbeat-to-next-Stop interval; never erase them at each loop iteration.
- Flush debug UART transmission before Stop and restore system clocks only
  when the Stop HAL call was actually made.
- Report arming, every Stop request, RTC heartbeat and exit reason in foreground.
  AUX opens a receive window; it is never reported as a decoded command ACK.
- Capture the phase in which each AUX callback was delivered: RADIO_ARMING, RECEIVE_ARMED,
  ALARM_SETUP, STOP_ENTRY, STOP_RETURN or HEARTBEAT. This does not measure the
  exact electrical edge time; an interrupt can be delivered after it was pending.

This is an interrupt-arming correction and diagnostic update. It does not prove
the electrical cause of the bench symptom. It does not add a timed debounce or
suppress events after the final receive boundary. Node/gateway roles, radio pin assignments, command payloads,
encryption, server schema, independent remote scheduling, timed Standby and
watchdog settings are unchanged. ESP32/CubeIDE are outside this update.

## Configuration and isolated retest

Build the node with its normal ID (for this bench test, node 2):

```cpp
#define APP_ROLE APP_ROLE_SENSOR_NODE
#define APP_UPLINK APP_UPLINK_LORA_TO_GATEWAY
#define APP_CONTROLLER_POWER_MODE APP_COMPONENT_MODE_LORA_WOR
#define APP_LORA_POWER_MODE APP_COMPONENT_MODE_WAKE_ON_RADIO
#define APP_POWER_SLEEP_SECONDS 150UL
#define APP_LORA_WOR_COMMAND_WINDOW_MS 5000UL
#define APP_LORA_WOR_WATCHDOG_WAKE_SECONDS 15UL
#define APP_LORA_GATEWAY_WOR_TX 0
```

These are test instructions, not changes to the user's AppConfig.h. Leave unused
WiFi/SIM policies NORMAL. Keep the 30-second WDT. Build the gateway separately
with role GATEWAY, controller/radios NORMAL and APP_LORA_GATEWAY_WOR_TX=1.
Keep matching radio channel/network/settings and company/region/node routing.

1. Flash the updated node. Turn off the other node and spare transmitting radios.
2. Send STIME once to the tested node and confirm `RTC synced to epoch`. Stop
   periodic STIME/WAKE/GOSTM activity for the quiet test.
3. Wait for a successful report and the five-second command window to finish.
4. Capture all `Power: WOR` lines. Expect M0=0 and M1=1 when armed. Check actual
   AUX-to-PC13 wiring and common ground; measure at both ends if readings differ.
5. Look for `WOR Stop requested` and `stop_calls` greater than zero. In a quiet
   interval, expect RTC heartbeats near the configured heartbeat
   interval and a report at APP_POWER_SLEEP_SECONDS after successful delivery.
   Changing SRATE/STRAN alone does not replace this WOR deadline.
6. After timer operation passes, send one immediate GOSTM before the next report
   deadline. A valid probe can be intentionally lost while UART is restored;
   verify the subsequent decoded command and matching server reply.
7. If AUX activity repeats without a decoded command, temporarily turn off the
   gateway after a successful report, observe before the next report deadline,
   and capture the reason/IRQ fields. A scope/logic analyser can see pulses that
   a multimeter misses. Do not disconnect an actively driven AUX and leave PC13
   floating as a diagnostic shortcut.

## Read the new output

| Output/field | Meaning |
|---|---|
| `WOR PC13 RTC pin functions before=0x... tamper1=...` | Actual RTC external-function ownership before release. `0x0 tamper1=0` means no retained conflict was observed. |
| `WOR released retained RTC pin functions; PC13 reserved for AUX` | An unused RTC external function was enabled and has been disabled; internal alarm IRQ remains enabled. |
| `WOR AUX GPIO ownership unavailable; staying awake` | Handle/readback failed; no Stop attempted. |
| `WOR cleared pre-arm stale AUX pending flag while line HIGH` | An old AUX EXTI pending bit was observed and cleared before Mode 2; not proof that it caused the prior symptom. |
| `WOR pre-arm AUX LOW; pending flag preserved` | AUX was LOW at pre-arm sampling; no potentially live edge was cleared. |
| `WOR idle receive baseline; pre-arm AUX history cleared` | AUX was HIGH with no queued UART data at the final arming boundary; only earlier AUX EXTI history was cleared. |
| `WOR armed ...` | Mode-2 preparation and the atomic receive boundary completed. |
| `WOR Stop requested; alarm_epoch=...` | Foreground is about to attempt Stop; pending activity may still skip/immediately end it. |
| `stop_calls=N` | Number of HAL Stop invocations in this run, not proof of low-power duration. |
| `rtc_elapsed_s=N` | RTC seconds elapsed since arming, including foreground work; coarse, not an exact Stop timer. |
| `AUX=HIGH/LOW` | GPIO level sampled while logging. |
| `aux_irq=1` | A falling-edge callback has been latched. AUX may already be HIGH again. |
| `aux_edge_phase=...` | Foreground phase when the AUX callback ran. ALARM_SETUP localises callback delivery, not necessarily the electrical pulse's cause. |
| `aux_pending=1` | AUX EXTI hardware pending bit at the snapshot. |
| `rtc_irq=1` | RTC alarm callback has run. |
| `uart_rx=N` | Bytes currently buffered in the LoRa UART RX ring. |
| `reason=UART_DATA_BEFORE_STOP` / `UART_DATA_AFTER_STOP` | Buffered UART input caused a receive-window exit. Bytes remain available to the parser. |
| `reason=AUX_ACTIVITY_AT_ARM` | AUX was LOW at the receive boundary/recheck; Stop was skipped. |
| `WOR RTC heartbeat` | RTC maintenance path; no forced sensor sample/report before the report deadline. |
| `reason=AUX_LOW_BEFORE_STOP` | LOW AUX caused a receive-window exit before this iteration called Stop. |
| `reason=AUX_EDGE_BEFORE_STOP` | A latched AUX edge caused a receive-window exit before this iteration called Stop. Earlier iterations may have called Stop. |
| `reason=AUX_EDGE_AFTER_STOP` | AUX edge was detected after a Stop call; validate the following command separately. |
| `reason=AUX_LOW_AFTER_STOP` | AUX was LOW after a Stop call. |
| `reason=REPORT_DEADLINE` | Scheduled report deadline was reached. Radio restoration can still fail afterward. |
| `reason=RTC_ALARM_SETUP_FAILED` | Alarm could not be enabled. |
| `reason=UNEXPECTED_WAKE` | Stop returned before the expected alarm without the expected AUX/RTC evidence. |
| `E32 Mode 0 restore failed` | Radio restoration failed after the reported exit; active recovery follows. |

Do not infer a confirmed server command from an AUX event. The real module can
signal busy/initialisation as well as received data. GPIO snapshots and RTC
elapsed time do not replace current traces or interrupt timing measurements.

## Software verification

`tests/wor_stop/run_tests.ps1` compiles the actual production PowerManager.cpp
with deterministic GPIO/RTC/HAL fakes and runs fresh-process scenarios covering
stale AUX pending state, neighbouring EXTI preservation, fresh short pulses,
arming/WFI races, heartbeat-boundary edges, LOW AUX, alarm/prepare/restore errors,
unexpected wake, trusted RTC, successful delivery, busy transport and WAKE leases.
The expanded suite has 26 scenarios, including atomic interrupt routing,
pre-arm idle-history clearing, preservation of LOW AUX and buffered RX during
preparation, new edges after the baseline clear, UART input during alarm setup,
retained RTC pin-function cleanup,
preservation of the internal alarm/format and unrelated TAFCR fields, and handle
failure. This guard does not prove that retained RTC configuration caused the
reported board symptom; the new pre-release ownership log supplies that evidence.
The suite is included in Validate-Release.ps1. ARM profile builds verify real HAL
and STM32duino compatibility; only the bench retest validates this radio/board.

RTC pin ownership reference: ST RM0368, section 8.3.15,
[Selection of RTC functions](https://www.st.com/resource/en/reference_manual/DM00096844.pdf).

Stop clock gating reference: [ST RM0368, section 5.3.4](https://www.st.com/resource/en/reference_manual/DM00096844.pdf).
