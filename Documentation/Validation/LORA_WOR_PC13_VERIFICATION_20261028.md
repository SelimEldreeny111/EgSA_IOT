# WOR PC13 RTC ownership follow-up

28 October 2026 | Branch feature/2026-10-28-lora-wor-pc13-rtc-ownership

## Observed bench result

After commit 83f321f, the supplied node screenshot reports armed AUX HIGH,
aux_irq=0, followed by AUX_EDGE_BEFORE_STOP with stop_calls=0, rtc_elapsed_s=0,
AUX HIGH, aux_irq=1, aux_pending=0, rtc_irq=0 and M0=0/M1=1. UART counters stay
unchanged. This establishes skipped Stop entry due to a latched AUX callback;
it does not establish where the physical pulse came from. The former diagnostic
hardening did not make this bench test pass.

## Follow-up and rationale

ST RM0368 section 8.3.15 documents RTC alarm/calibration outputs and timestamp/
tamper functions taking ownership of PC13. The installed STM32duino RTC source
sets desired output-disable parameters, but can skip HAL_RTC_Init when the backup
domain is already initialized. Reset-retained ownership therefore needs explicit
readback when this board reserves PC13 for LoRa AUX.

In WOR only, before radio arming, reserveWorAuxGpio() logs and clears CR.OSEL,
CR.COE, CR.TSE and TAFCR.TAMP1E under RTC write-protection handling. It preserves
FMT, ALRAE, ALRAIE, all other control fields and TAFCR fields. It never resets the
backup domain, calendar, clock source or consumption snapshots. Readback/handle
failure leaves the node awake. A zero ownership log is evidence that this
potential conflict was not present; no claim is made that it was the board's cause.

The ISR also records only a small phase enum, never logs or services the WDT.
Foreground logs report callback delivery phase. They preserve all fresh AUX
edges; no pulse debounce or arbitrary post-arm edge suppression was introduced.

## Validation

- 19 production PowerManager WOR scenarios pass, including retained RTC external
  ownership and preservation of the internal alarm/format and unrelated fields.
- Existing remote scheduling/command/reset-counter scenarios, 45 real AppConfig
  policy cases and the 16 RTC/SUPMEA scenarios pass.
- Real STM32 ARM builds cover WOR LoRa and timed-deep-sleep LoRa, all four sensor
  drivers compiled; output is under Documentation/FirmwareBuildWorPc13_20261028.
  Both pass: WOR flash load ends at 0x08016BA4, timed deep sleep at 0x080163C4;
  both remain below the reserved EEPROM sector at 0x08020000.
- Doxygen is regenerated. Source/guide/test files are copied into the existing
  final working folder without replacing the user's AppConfig.h or secrets.
  The final Doxygen warnings.log is empty; the 19-scenario WOR suite also passes
  from the final working folder.
- Previous full-release regression evidence remains recorded in
  LORA_WOR_DIAGNOSTICS_VERIFICATION_20261028.md. Python/server/protobuf code is
  unchanged in this follow-up; the relevant native/ARM tests were rerun.

## Required next bench evidence

Keep the existing node/gateway WOR test configuration. Flash the updated node,
send STIME once and obtain one successful report. Capture the PC13 ownership line,
WOR armed/Stop requested/exit snapshots and current trace. If the log still exits
before Stop with a zero ownership mask, capture aux_edge_phase and inspect actual
radio AUX/PC13 pulse timing. Do not report WOR fixed until measured Stop residence,
scheduled reporting and gateway command/reply tests pass.

Reference: [ST RM0368](https://www.st.com/resource/en/reference_manual/DM00096844.pdf).
