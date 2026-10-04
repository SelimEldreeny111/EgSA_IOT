# TB6612FNG latching valve — software verification

Release date: 4 October 2026. Branch: `feature/2026-10-04-tb6612-latching-valve`.
Scope: Arduino STM32 node and Python web server in the final working copy.
ESP32 and STM32CubeIDE ports are unchanged.

## Delivered configuration and limits

PB9 drives AIN1, PB15 drives AIN2, and the existing PC13 valve output drives
STBY. The bridge is disabled between opposite-polarity, timed pulses.
Delivered opening/closing durations are both zero and polarity confirmation
is false: **no valve actuation is permitted until commissioning**. No supplier
pulse duration or opening polarity has been assumed. Test values are not
approved coil settings.

Telemetry distinguishes commanded Closed/OFF (0), commanded Open/ON (1),
Unknown (2), and Fault/unknown physical position (3). There is no position
sensor; an ACK proves software pulse completion, not hydraulic movement.
Existing protobuf tags and generated descriptors are unchanged.

## Automated checks

| Check | Result / coverage |
| --- | --- |
| Actual driver host suite | 14 scenarios passed: inhibited/disabled, both polarities, same-target idempotence and minimum interval, restored state, interrupted pulse, corrupt storage, pre/post-write failure, missing/premature timer, timer-arm latency, foreground stall and millis wrap. |
| Actual valve configuration | 8 checks passed: SIM/Wi-Fi defaults, disabled valve, LoRa conflict, gateway and invalid Boolean guards. |
| Combined configuration guards | 39 checks passed, including pulse/interval bounds and existing watchdog/network/power policies. |
| Power combination preprocessing | 155 combinations checked: 15 accepted, 140 intentionally rejected. |
| Python web server | 51 tests passed, including valve request correlation, state codes and lost-ACK queue ordering. |
| Sensor simulators | 54 tests passed across multi-sensor, TUF and Supmea simulators. |
| Release contract audit | 6 tests passed. |
| Dashboard JavaScript | Existing dashboard/WAKE suites and new valve display suite passed. |
| Existing node host suites | MQTT/transport priority, Modbus, network recovery, watchdog counter, RTC/Supmea, unavailable sensors and remote wake passed through `Validate-Release.ps1`. |

The queue does not automatically republish dispatched VALVE requests: a lost
ACK for an old opening request cannot cause a later automatic reopening after
a newer close request. This is not a system-wide exactly-once guarantee.

Tests use actual application source with simulated peripherals where stated.
Existing third-party ModbusMaster/PubSubClient compiler warnings remain; the
new valve host suite builds with warnings treated as errors.

## Actual STM32 firmware builds

All 13 profiles compiled using STM32 Arduino core 2.12.0 and STM32RTC 1.9.0,
with all four sensor drivers enabled. Every flash load ends below the reserved
EEPROM-emulation sector beginning at `0x08020000`.

| Profile | Flash load end |
| --- | --- |
| normal-sim | 0x08015014 |
| remote-sim | 0x08015440 |
| remote-wifi | 0x08014DD4 |
| remote-lora | 0x080152D4 |
| rtc-wifi | 0x08015920 |
| rtc-lora | 0x08015D24 |
| queued-wifi | 0x08015A18 |
| queued-lora | 0x08015E1C |
| wor-lora | 0x08015E58 |
| gateway-wifi | 0x0800E13C |
| gateway-wor | 0x0800E1AC |
| valve-test-sim — compile only | 0x08015C48 |
| valve-test-wifi — compile only | 0x080155DC |

The final two profiles use synthetic 60/80 ms settings to compile the enabled
timer path. **Never upload those fixture binaries to the supplied coil.**
The local evidence is `Documentation/FirmwareBuild_20261004/build-matrix.log`
at the final-copy root. Build outputs may embed private configuration and are
not publication artifacts. No firmware was uploaded during verification.

## Unverified hardware and mandatory acceptance

- Confirm supplier pulse duration, polarity, pressure range and switching duty.
- Measure STBY LOW during reset/Standby: PC13 board LED/pull-ups can defeat an
  inadequately sized external pull-down. Review wiring before powering the coil.
- Scope both polarities and cutoff with the coil disconnected first; then
  verify movement, supply transients, current and temperature on a safe rig.
- TIM10 cuts power during a foreground stall only while interrupts continue.
  Use an independent hardware pulse limiter if strict coil protection is required.
- LoRa AUX currently shares PC13. LoRa/gateway builds inhibit valve output;
  simultaneous operation requires a separately approved pin/wiring change.
- EEPROM bytes 212..231 preserve neighbouring records during normal writes,
  but shared-sector emulation is neither power-fail atomic nor wear-levelled.
  Two sector commits per change require an endurance review for frequent use.
- Existing AES-CBC/public-broker operation does not authenticate actuator
  commands. Review secure command delivery before physical deployment.

The existing node ID, four-sensor selections/addresses, normal SIM profile,
30-second watchdog, 10 + 10 recovery settings and private local configuration
in the final folder were preserved. Software verification is not hardware
commissioning, a measured power-saving result, or proof of physical position.

See [Latching Valve User Guide](LATCHING_VALVE_USER_GUIDE.md) for wiring,
configuration, command use and the step-by-step physical acceptance checklist.
