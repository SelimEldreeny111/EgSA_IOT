# LoRa WOR arming and wake diagnostics

28 October 2026 | Active Arduino STM32 node only

The bench log repeatedly reported `LoRa AUX woke STM32` while UART counters did
not change. An AUX reading of 3.3 V rules out a continuous LOW at the instant
measured, but does not exclude a short pulse or an already pending interrupt.
The previous message also covered a LOW/edge before Stop was called. It could
not establish either sustained Stop residence or reception of a command.

## Change and scope

- Clear only the AUX GPIO EXTI pending bit, while the line is HIGH, before
  switching the radio into Mode 2. Do not clear the shared NVIC interrupt vector
  or any neighbouring GPIO pending bit. A LOW line preserves its pending bit.
- Initialize the AUX software flag before radio preparation. Preserve a new
  edge during preparation, interrupt attachment, alarm programming and the
  heartbeat-to-next-Stop interval; do not erase it at each loop iteration.
- Flush debug UART transmission before Stop and restore system clocks only
  when the Stop HAL call was actually made.
- Report arming, every Stop request, RTC heartbeat and exit reason in foreground.
  AUX opens a receive window; it is never reported as a decoded command ACK.

This is an interrupt-arming hardening and diagnostic update. It does not prove
the electrical cause of the bench symptom. It does not debounce, mask or ignore
new AUX edges. Node/gateway roles, radio pin assignments, command payloads,
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
5. In a quiet interval, expect RTC heartbeats near the configured heartbeat
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
| `WOR cleared pre-arm stale AUX pending flag while line HIGH` | An old AUX EXTI pending bit was observed and cleared before Mode 2; not proof that it caused the prior symptom. |
| `WOR pre-arm AUX LOW; pending flag preserved` | AUX was LOW at pre-arm sampling; no potentially live edge was cleared. |
| `WOR armed ...` | Mode-2 preparation and callback attachment completed. |
| `WOR Stop requested; alarm_epoch=...` | Foreground is about to attempt Stop; pending activity may still skip/immediately end it. |
| `stop_calls=N` | Number of HAL Stop invocations in this run, not proof of low-power duration. |
| `rtc_elapsed_s=N` | RTC seconds elapsed since arming, including foreground work; coarse, not an exact Stop timer. |
| `AUX=HIGH/LOW` | GPIO level sampled while logging. |
| `aux_irq=1` | A falling-edge callback has been latched. AUX may already be HIGH again. |
| `aux_pending=1` | AUX EXTI hardware pending bit at the snapshot. |
| `rtc_irq=1` | RTC alarm callback has run. |
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
The suite is included in Validate-Release.ps1. ARM profile builds verify real HAL
and STM32duino compatibility; only the bench retest validates this radio/board.
