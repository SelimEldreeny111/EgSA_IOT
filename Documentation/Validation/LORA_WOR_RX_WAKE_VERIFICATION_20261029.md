# LoRa WOR UART RX wake verification

29 October 2026 | feature/2026-10-29-lora-wor-rx-wake

## Requested behavior and scope

Keep APP_CONTROLLER_POWER_MODE=APP_COMPONENT_MODE_LORA_WOR and
APP_LORA_POWER_MODE=APP_COMPONENT_MODE_WAKE_ON_RADIO, but use the existing
LoRa TXD -> STM32 UART RX wire to wake Stop instead of AUX. The supplied AUX
logs repeatedly showed stop_calls=0, fresh callbacks and unchanged UART counts.
Their electrical origin remains unconfirmed; this update does not claim the
original AUX problem was diagnosed or physically fixed.

APP_LORA_WOR_WAKE_SOURCE now defaults to APP_LORA_WOR_WAKE_SOURCE_UART_RX.
APP_LORA_WOR_WAKE_SOURCE_AUX retains the old selectable implementation.
Other power profiles and their numeric values are unchanged. AUX remains wired
for radio-ready/busy checks; it is not an interrupt source in UART_RX mode.

## Implementation review

- The sensor node uses PA12 as the selected wake input (LoRa TXD), with falling
  GPIO EXTI and UART reception using the same existing pad.
- WorWakeInput.h verifies UART alternate-function mode before radio preparation.
  With IRQ delivery masked, it registers the EXTI callback through STM32duino,
  then restores this pin's MODER and OSPEEDR bits. This is necessary because
  core 2.12.0 attachInterrupt changes MODER to input. AFR, PUPDR and neighbouring
  GPIO bits remain intact; detachInterrupt disables EXTI without changing UART mode.
- Initial-mode failure leaves the node awake. Attachment readback failure takes
  the existing radio-restoration/active-recovery path.
- Selected-input activity and buffered UART input prevent Stop; AUX activity
  alone does not do so after successful preparation in RX mode. Existing
  readiness errors still keep the node awake rather than bypassing the driver.
- UART RX buffering is preserved. Clocks are restored before pending handlers
  run. The first probe bytes may be lost/corrupted during Stop wake; the existing
  gateway Mode-1 probe, guard and separate command remain required.
- RTC heartbeat, combined report/sample deadline, trusted-time requirement,
  command window, WAKE leases and watchdog reset behavior are preserved.
- Diagnostics identify wake_source, wake_level, wake_irq, wake_edge_phase and
  wake_pending, with WAKE_EDGE/LOW reason names and explicit arm failures.

## Validation results

- 57 production PowerManager host scenarios pass across AUX and UART_RX in both
  development and final-folder copies. New checks cover pin mode/speed/pull/AFR
  preservation, AUX-only activity ignored by RX wake, and invalid UART-mode
  rejection. Existing race, UART-buffer, neighbour-EXTI, RTC and failure tests remain.
- Remote scheduling, command/reset-counter tests, 47 real AppConfig policy cases
  and 16 RTC/SUPMEA scenarios pass. Production-default checks include UART_RX.
- Real STM32 ARM builds compile all four sensor drivers:

  | Profile | Sketch bytes | Global RAM bytes | Flash load end |
  |---|---:|---:|---|
  | wor-lora (UART_RX default) | 93372 | 26492 | 0x08016EC8 |
  | wor-lora-aux | 92940 | 26492 | 0x08016D18 |
  | rtc-lora | 90552 | 26476 | 0x080163C4 |
  | gateway-wor | 58192 | 25760 | 0x0800E55C |

  All remain below the EEPROM sector at 0x08020000. Build transcript:
  Documentation/FirmwareBuildWorRx_20261029/build-matrix.log.
- Doxygen includes the new RX guide and helper. Both development and final
  warnings.log files are empty after regeneration.
- Changed public files are copied into WIOT_Final_PowerModes_20261001. Its
  AppConfig gains only the wake-source selector and validation; the existing
  node ID 2, WOR modes, 120-second interval, 15-second heartbeat, sensor settings,
  private AppConfig.cpp and AppSecrets.h are preserved.
- Server, protobuf, simulators, ESP32 and CubeIDE are unchanged. Their test suites
  were not rerun for this focused firmware update.

## Initial bench current result recorded

After testing firmware b60388b, the user confirmed current dropped to approximately
9 mA. The supplied log shows wake_source=UART_RX and reaches WOR Stop requested
with RX HIGH and no pending wake interrupt or buffered UART data. Compared with
the earlier approximately 42-mA unsuccessful sleep attempt, the reported decrease
is approximately 33 mA (79%). Measurement location and averaging were not supplied;
this is not an MCU-only current specification or a whole-cycle average.

See [the dated bench record](LORA_WOR_9MA_BENCH_RESULT_20261029.md) for the exact
log, configuration, interpretation and remaining acceptance checks. This confirms
the initial current-reduction observation; a server command/reply and multiple
RTC/report cycles have not yet been reported.

## Remaining bench qualification

Rebuild/flash the node from the final folder, keeping AUX connected. Confirm
wake_source=UART_RX, send STIME, then obtain a successful report. Test quiet
current/RTC heartbeats first, periodic reports next, and immediate server
command/reply during Stop last. Add the second node and exercise fragmentation
only after the single-node path passes. Confirm normal Stop wakes do not increase
reset counters. Existing gateway timing must be measured on the actual modules;
host tests and ARM compilation do not prove current consumption or RF wake timing.

Use Node/IoT_Node_Encrypted/LORA_WOR_RX_WAKE_GUIDE.md for detailed configuration,
wiring, rollback to AUX and step-by-step tests.

Reference: [ST RM0368, GPIO and Stop mode](https://www.st.com/resource/en/reference_manual/DM00096844.pdf).
