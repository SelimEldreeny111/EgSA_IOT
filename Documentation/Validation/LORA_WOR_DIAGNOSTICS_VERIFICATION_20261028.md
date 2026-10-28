# LoRa WOR arming and diagnostics verification

28 October 2026 | Arduino STM32 node | Branch feature/2026-10-28-lora-wor-wake-diagnostics

## Bench evidence and limits

The user confirmed ordinary timed deep sleep works at approximately 6 mA.
That measurement is not a successful WOR test. In the WOR log, repeated AUX
receive-window messages appeared with unchanged UART/frame counters. The user
measured AUX at 3.3 V. This excludes a continuously LOW signal only at the
measurement instant; it does not identify pulse timing or a pending interrupt.
No hardware was flashed or operated by this software verification.

## Reviewed dependency behavior

The installed STM32duino 2.12.0 interrupt implementation enables/configures GPIO
EXTI in stm32_interrupt_enable() without explicitly clearing a pre-existing
pending GPIO flag. Detaching an interrupt can leave edge detection/pending state
behind. HAL_GPIO_EXTI_IRQHandler() clears the line's pending bit when dispatching.
This supports explicit idle-line stale-state cleanup before arming the new WOR
session. It does not prove this was the sole cause of the bench symptom.

The former PowerManager cleared its AUX callback flag at every Stop-loop pass,
after callback attachment. A real short edge during arming or the gap after a
heartbeat could be lost. The update initializes once before Mode 2 and preserves
newly latched events. The old single AUX-wake message also covered paths that
never invoked Stop; the new logs distinguish those paths.

## Changes

- AUX EXTI line-only stale-state cleanup while HIGH, before Mode 2. No shared
  NVIC pending-vector clearing, no clearing live LOW state or newly armed edges.
- Debug UART flush before WFI; no unnecessary PLL restoration when WFI is skipped.
- Foreground logs for pending state, arming, Stop attempts, RTC heartbeat, exit
  cause, AUX level/callback/pending state and mode GPIO levels.
- No packet/schema/server changes, GPIO reassignment or timing-default changes.
- Existing final-folder AppConfig.h and private files preserved. ESP32 and
  CubeIDE unchanged. Documentation explains an isolated node-2 retest.

## Automated evidence

- 17 fresh-process scenarios compiling production PowerManager.cpp with hardware
  fakes: report deadline; stale pending HIGH; unrelated EXTI preservation; AUX
  short edge after Stop; edge during Mode-2 preparation; edge during alarm setup;
  check-to-WFI race; edge after RTC heartbeat; AUX LOW before Stop; unexpected
  wake; alarm failure; untrusted RTC; radio preparation failure; pending LOW
  preservation; radio restoration failure; transport busy; active WAKE lease;
  unsuccessful delivery. Some checks share one scenario. All pass.
- Existing remote-mode tests and 45 actual AppConfig policy checks pass.
- Complete Validate-Release.ps1 passes with the new suite included: all eight
  native node suites, 184 Python tests (34 multi-sensor, 20 TUF, 11 SUPMEA,
  110 server, 9 release-contract/oracle) and existing browser regressions.
- The new WOR suite also passes from the final working release folder.
- Real ARM builds cover WOR node, WOR gateway, timed-deep-sleep LoRa node and
  remote-wake LoRa node, with all four sensor drivers compiled. Build evidence
  is retained under Documentation/FirmwareBuildWorDiagnostics_20261028.
- Doxygen regenerated from updated sources/guides. See its local warnings.log.

| ARM profile | Flash load end (reserved EEPROM sector starts at 0x08020000) |
|---|---|
| wor-lora | 0x08016938 |
| gateway-wor | 0x0800E55C |
| rtc-lora | 0x080163C4 |
| remote-lora | 0x08015A34 |

All four builds pass. Development and final-copy Doxygen warnings.log files are
both empty. The final working source, guide, test suite and validator match the
development copy; the user's current gateway/bench AppConfig.h was not replaced.

Local logs: Documentation/wor-development-regression-20261028.log,
Documentation/wor-doxygen-20261028.log and
Documentation/wor-final-doxygen-20261028.log. Compiler output and generated
Doxygen files are intentionally ignored by Git.

## Required physical acceptance

Rebuild/flash the updated node in LORA_WOR, send STIME once, obtain a successful
report, then capture the new logs through a quiet interval and a single immediate
GOSTM command. Confirm radio GPIO levels, actual Stop current, scheduled report
wake and decoded-command/reply correlation. A Stop call count or elapsed RTC
seconds alone does not prove sustained low-power residence. Do not call WOR
fixed until these board/radio tests pass.
