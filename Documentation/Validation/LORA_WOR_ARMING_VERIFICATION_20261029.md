# LoRa WOR receive-arming correction

29 October 2026 | feature/2026-10-29-lora-wor-arming-boundary

## Evidence and diagnosis

The node's latest log reports PC13 RTC ownership `before=0x0 tamper1=0`, so
the previous retained-ownership hypothesis was not observed. It still reports
`AUX_EDGE_BEFORE_STOP`, `stop_calls=0` and `aux_edge_phase=RADIO_ARMING`, with
unchanged received-byte counters. This localizes callback delivery to arming;
it does not identify the electrical source or prove a received command.

The installed STM32 2.12.0 core's attachInterrupt/HAL_GPIO_Init configures GPIO
routing, edge detection, IMR and the callback without clearing EXTI pending
history. The previous application cleared history before Mode-2 preparation,
leaving a gap before interrupt attachment. Replaying an edge from that gap
could repeatedly cancel Stop and return the radio to Mode 0. Tests now model
IRQ masking and pending delivery at attachment, instead of assuming attachment
always means a fresh receive event.

## Implementation

- Establish the final receive baseline after Mode 2 is ready, with IRQ delivery
  briefly masked around GPIO attachment and the baseline operation.
- Clear only earlier AUX EXTI history when AUX is HIGH and UART RX is empty;
  retain LOW AUX and buffered input, recheck after clearing, and preserve every
  edge after that boundary. Never clear the shared NVIC IRQ or adjacent EXTI lines.
- Keep the UART initialized through WOR and resume. The installed core's end()
  discards the RX ring, while begin() resets its indices; neither should erase
  data received during preparation. F401 Stop gates peripheral clocks while
  retaining registers/RAM. UART reception during Stop itself is not promised.
- Check UART RX as well as AUX before/after Stop. Buffered bytes trigger the
  existing receive window and remain available to the frame parser.
- Add RECEIVE_ARMED callback phase, uart_rx snapshots, UART_DATA_BEFORE_STOP,
  UART_DATA_AFTER_STOP and AUX_ACTIVITY_AT_ARM exit diagnostics.

An edge fully completed before the baseline, with HIGH AUX and no buffered
input, is treated as pre-arm history. No timed debounce or repeated clearing
after arming is used. The gateway's probe-plus-command exchange is still needed;
the first probe may be missed while MCU clocks are stopped. Timer and remote
command/reply tests on the real boards remain required.

## Verification

- 26 production PowerManager WOR scenarios pass in development and the final
  working folder, including idle preparation/attachment history, retained LOW
  AUX and RX bytes, fresh edges after the clear/arming boundary, heartbeat gaps,
  WFI races, alarm/preparation/restoration errors, PC13 ownership and WDT leases.
- Remote scheduling/command/reset-counter regressions, 45 real configuration
  policy cases and 16 RTC/SUPMEA scenarios pass.
- ARM build results are recorded in
  Documentation/FirmwareBuildWorArming_20261029/build-matrix.log.
  All three profiles pass with all four sensor drivers compiled:

  | Profile | Sketch bytes | Global RAM bytes | Flash load end |
  |---|---:|---:|---|
  | wor-lora | 92756 | 26492 | 0x08016C60 |
  | rtc-lora | 90552 | 26476 | 0x080163C4 |
  | gateway-wor | 58192 | 25760 | 0x0800E55C |

  All load sections remain below the EEPROM sector at 0x08020000.
- Doxygen regenerated in development and final copies; both warnings.log files
  are empty. Python/server/protobuf code is unchanged and its test suite was
  not rerun for this follow-up.
- Changed public files were compared with their previous committed baseline
  before copying to WIOT_Final_PowerModes_20261001. User AppConfig.h and private
  configuration/secrets were preserved. ESP32 and CubeIDE are unchanged.

## Required bench retest

1. Rebuild/flash the updated node only; keep the gateway NORMAL with WOR TX enabled.
2. Isolate the other node/transmitters, send STIME, then allow a successful report.
3. Observe WOR idle-baseline/armed/Stop-requested/heartbeat/exit lines and current.
   In a quiet interval, expect Stop attempts and RTC heartbeats, followed by a
   report at APP_POWER_SLEEP_SECONDS. A Stop-call count alone does not establish
   low-power residence; measure current as well.
4. After the timer/current test passes, send one gateway/server command before
   the report deadline. Confirm the decoded command and matching server reply.
5. If the loop persists, provide the complete new WOR sequence including
   aux_edge_phase and uart_rx. The update is not claimed bench-verified yet.

Reference: [ST RM0368, Stop mode section 5.3.4](https://www.st.com/resource/en/reference_manual/DM00096844.pdf).
