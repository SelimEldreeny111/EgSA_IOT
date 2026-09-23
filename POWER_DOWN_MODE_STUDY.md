# WIOT Power-Down Mode Engineering Study

> The Arduino implementation now provides per-device power policies and
> scheduled RTC Standby for LoRa and ESP8266 sensor nodes. Its commissioning procedure is documented in
> `Node/POWER_DOWN_MODE_USER_GUIDE.md`. The STM32CubeIDE project is intentionally
> unchanged.

**Project:** STM32F401RCT6 IoT sensor node and LoRa/IP gateway  
**Study date:** 2026-09-01  
**Status:** Architecture study; Arduino LoRa-node and ESP8266-node periodic phases are implemented

## 1. Executive decision

The project should support two distinct power profiles. A single sleep strategy cannot provide both the lowest current and immediate reception of remote commands.

1. **Periodic ultra-low-power sensor node**
   - Wakes by RTC or a local alarm.
   - Measures, transmits, opens a short command window, and sleeps again.
   - Can reach tens or hundreds of microamps between wake windows, before board-level leakage is included.
   - Cannot receive an arbitrary server command while its radio is deeply asleep. The server/gateway must queue the command until the next node wake window.

2. **Always-reachable node or gateway**
   - Keeps a low-power receiver/network connection alive.
   - Uses E32 Mode 2, ESP8266 Light-sleep, or SIM800L network sleep and wakes the STM32 on an interrupt.
   - Consumes more power than periodic deep sleep, but can receive data with bounded latency.

The recommended deployment is:

- **LoRa sensor nodes:** periodic deep sleep when immediate commands are not mandatory; otherwise E32 Mode 2 plus STM32 Stop and AUX wake.
- **Direct ESP8266 sensor nodes:** periodic deep sleep and server-side command queue; use connected Light-sleep only if immediate downlink is mandatory.
- **Direct SIM800L sensor nodes:** power down between scheduled uploads for the lowest average current; use network sleep only when cellular reachability is required and proven with the operator/firmware.
- **Gateways:** remain logically online. Use connected/light sleep and CPU idle, not full system power-down.

## 2. Important measurement boundary

All currents below are typical chip or module values, generally at room temperature. They are not guaranteed whole-PCB currents. The real unit also includes:

- regulator quiescent current and conversion loss;
- power LEDs and module-breakout LEDs;
- sensor and RS485 transceiver current;
- pull-ups, level shifters, USB/UART adapters, and leakage through powered-off signal pins;
- the battery ADC divider;
- radio reconnect and transmit energy.

Consequently, the final design target must be verified with a current profiler or ammeter on the complete production PCB.

## 3. Per-device power study

### 3.1 STM32F401RCT6

At 3.3 V and 84 MHz, the STM32F401 datasheet gives approximately 22.5 mA typical in Run mode with peripherals enabled. The useful low-power modes are:

| STM32 mode | Typical MCU current | State retained | Wake sources | Approximate saving from 22.5 mA |
|---|---:|---|---|---:|
| Run | 22.5 mA | All | N/A | 0 mA |
| Sleep, 84 MHz | 5.2-16.2 mA | SRAM/registers/peripherals | Any enabled peripheral interrupt | 6.3-17.3 mA |
| Stop, low-power regulator and Flash deep power-down | about 0.012 mA | SRAM and registers | Any configured EXTI line or RTC event | about 22.49 mA |
| Standby, RTC + LSE on | about 0.0028 mA | Backup domain only | PA0/WKUP, RTC, NRST, or IWDG reset | about 22.50 mA |

Sources: [STM32F401xB/xC datasheet](https://www.st.com/resource/en/datasheet/stm32f401vc.pdf) and [STM32F401 reference manual RM0368](https://www.st.com/resource/en/reference_manual/rm0368-stm32f401xb-c-d-e-mb-reference-manual-stmicroelectronics.pdf).

Engineering consequences:

- **Sleep mode** is safest for a continuously connected gateway because UARTs and other clocks can continue and wake the CPU. It is not the lowest-current mode.
- **Stop mode** is the preferred node mode when RAM must be retained. After wake, HSI is selected as the system clock, so the firmware must restore the 84 MHz clock tree, UARTs, SysTick/timebase, and any affected peripherals before resuming communications.
- **Standby mode** is effectively a restart. SRAM and normal registers are lost. The boot path must detect the Standby flag and restore application state from RTC backup registers or nonvolatile storage.
- On this MCU, Standby external wake is restricted to **PA0/WKUP**. The current LoRa AUX signal is on PC13, so it can wake Stop mode through EXTI but cannot wake Standby without a hardware reroute.
- Floating GPIOs and externally driven pins cause leakage. Before Stop/Standby, unused pins should be put in analog mode and powered-off peripheral pins must not be driven.

### 3.2 Ebyte E32-TTL-100 / E32 T20-family LoRa module

The exact label/revision must be recorded before implementation. E32-TTL-100 and later E32-433T20D manuals differ slightly, but the relevant values are approximately:

| E32 mode | M1 | M0 | Radio behavior | Typical current | Can receive over air? |
|---|---:|---:|---|---:|---|
| Mode 0 - normal | 0 | 0 | UART and receiver continuously active | about 14-15 mA RX; about 110 mA at 20 dBm TX | Yes |
| Mode 1 - wake-up transmit | 0 | 1 | Adds wake preamble before transmitted packet | similar active current | Yes; also wakes Mode 2 receivers |
| Mode 2 - power saving/WOR | 1 | 0 | Periodically checks for wake preamble; UART input disabled | as low as about 0.030 mA average | Yes, receive only |
| Mode 3 - deep sleep/config | 1 | 1 | RF receive/transmit disabled | about 0.002-0.004 mA | No |

The official T20-family manual specifies 15 mA receive, 110 mA transmit, 3 microamps deep sleep, and a minimum Mode 2 average near 30 microamps. It also states that Mode 2 latency can reach about two seconds depending on the configured wake interval. Source: [Ebyte E32 T20-family manual](https://www.ebyte.com/Uploadfiles/Files/2024-4-3/2024431610567020.pdf) and [E32-433T20D product page](https://www.ebyte.com/product/5.html).

The existing board is well positioned for LoRa wake-up:

- M0 is PB2.
- M1 is PB1.
- AUX is PC13.
- AUX can be configured as a PC13 EXTI wake source for STM32 Stop mode.

For an incoming Mode 2 packet, the E32 drives AUX low and waits about 5 ms before sending the received bytes on TXD. STM32 Stop wake-up is much faster than this, so AUX can wake the MCU before UART data begins. The sender must use Mode 1 so that the wake preamble covers the receiver's configured WOR interval.

Required receive sequence:

1. E32 receiver rests in Mode 2 and STM32 rests in Stop.
2. Gateway transmits using E32 Mode 1.
3. Receiver recognizes the wake preamble and drives AUX low.
4. PC13 EXTI wakes the STM32.
5. STM32 restores clocks/UART and reads the LoRa frame.
6. STM32 waits for AUX high, waits at least 2 ms, switches E32 to Mode 0, and sends the ACK/response.
7. After all frames and ACKs are complete, it returns the E32 to Mode 2 and the MCU to Stop.

Mode 3 is suitable only for scheduled wake-up. It cannot receive a LoRa packet and therefore cannot wake the node from a remote LoRa command.

### 3.3 ESP8266

The ESP8266EX datasheet gives these typical chip values:

| ESP8266 state | Typical current | Wi-Fi/server connection | Wake method | Approximate saving from 80 mA active average |
|---|---:|---|---|---:|
| Active average | about 80 mA | Yes | N/A | 0 mA |
| Modem-sleep | about 15 mA | Retained through DTIM | Automatic Wi-Fi activity | about 65 mA |
| Light-sleep | about 0.9 mA at DTIM3 | Retained in automatic connected mode | Wi-Fi/MAC, host or configured GPIO | about 79.1 mA |
| Deep-sleep | about 0.020 mA | No | RTC timer through GPIO16-to-RST or external RST pulse | about 79.98 mA |
| CHIP_EN low/shutdown | about 0.0005 mA chip-only | No | CHIP_EN/high plus reset/boot | about 80.0 mA |

Sources: [ESP8266EX datasheet](https://documentation.espressif.com/0a-esp8266ex_datasheet_en.html), [ESP8266 Low-Power Solutions](https://www.espressif.com/sites/default/files/documentation/9b-esp8266-low_power_solutions__en.pdf), and [ESP8266 ESP-AT sleep commands](https://docs.espressif.com/projects/esp-at/en/release-v2.3.0.0_esp8266/AT_Command_Set/Basic_AT_Commands.html).

For ESP-AT firmware:

- `AT+SLEEP=1` selects DTIM modem sleep.
- `AT+SLEEP=2` selects Light-sleep on current ESP-AT releases.
- `AT+GSLP=<milliseconds>` enters Deep-sleep.
- Support and numeric meaning must be verified using `AT+GMR`, `AT+CMD`, and `AT+SLEEP?`, because older NONOS-AT firmware used different conventions.

Recommended behavior:

- **Immediate MQTT downlink:** ESP8266 Light-sleep plus STM32 Sleep. The Wi-Fi/TCP path stays connected, and UART activity wakes the STM32 CPU.
- **Lowest-power periodic node:** gracefully close MQTT/TCP, then use ESP deep sleep, drive CHIP_EN low, or remove power with a load switch. Wake by RTC/external control, restart the ESP, reconnect Wi-Fi/MQTT, publish, collect queued commands, then sleep.
- ESP deep sleep cannot receive a server message. A server-side pending-command queue is mandatory.

The 20 microamp and 0.5 microamp figures are for the ESP8266 chip. An ESP-01 or other breakout can consume much more because of its regulator, LED, flash, and pull resistors. Measure the exact fitted module.

### 3.4 SIM800L

SIM800L current varies by silicon and hardware-document revision. Published SIMCom hardware-design revisions show approximately:

| SIM800L state | Typical module current | Cellular reachability | Wake method |
|---|---:|---|---|
| GSM idle/registered | about 13.4-18.7 mA | Yes | Already awake |
| Network sleep | about 1.0-1.94 mA | Paging/SMS/call retained | DTR low or network/hardware event |
| Power down | about 0.05-0.20 mA | No | PWRKEY or power cycle |
| GPRS transfer | often 150-530 mA average depending on band/slots/power | Active data | N/A |
| GSM TX burst | up to about 2 A peak | Active data | N/A |

Sources: the manufacturer-authored [SIM800L MT6261 Hardware Design](https://simcom.ee/documents/SIM800L/SIM800L%28MT6261%29_Hardware%20Design_V1.01.pdf), [SIMCom SIM800-series official document listing](https://cn.simcom.com/technical_files-p166.html?filetype=0&pro_cat=0&pro_li=0&time=0), and [SIM800 Series AT Command Manual listing](https://www.simcom.com/technical_files-p140.html?filetype=0&pro_cat=0&pro_li=0&time=0).

Control options:

- `AT+CSCLK=1`, then DTR high: the module can enter network sleep when idle. Pull DTR low and wait about 50 ms before sending AT commands.
- `AT+CSCLK=2`: automatic sleep based on inactivity. On the documented variant, the first UART character used to wake it can be lost, so the host must use a deliberate wake/synchronization sequence.
- `AT+CPOWD=1`: normal power down. The baseband and UART stop; only RTC-related circuitry remains. It cannot receive a server command.
- `AT+CFUN=0`: minimum functionality; RF/SIM operation is disabled but UART remains available. It is not an always-reachable mode.

For MQTT, registered GSM sleep does not automatically guarantee reliable always-on TCP delivery on every SIM800 firmware/operator combination. Before selecting it for an always-reachable gateway, test TCP/MQTT socket survival, broker keepalive, incoming packet behavior, UART URCs, and recovery over several hours. The current design exposes only the modem UART; production hardware should also expose/control DTR, RI, PWRKEY, and preferably RESET.

## 4. Theoretical whole-system idle budgets

These comparisons add only the STM32 and communication modules. They exclude sensors, regulators, LEDs, and PCB leakage. They compare an active/listening state to the proposed resting state, so they are useful design estimates, not battery-life guarantees.

| Product profile | Active/listening reference | Proposed resting state | Estimated resting current | Approximate current saved | Immediate remote downlink? |
|---|---:|---|---:|---:|---|
| LoRa sensor, remotely reachable | STM32 Run + E32 RX = about 37.5 mA | STM32 Stop + E32 Mode 2 | about 0.042 mA | about 37.46 mA | Yes, with Mode 1 sender and AUX wake |
| LoRa sensor, scheduled only | about 37.5 mA | STM32 Standby + E32 Mode 3 | about 0.006 mA | about 37.49 mA | No; commands wait for next wake window |
| ESP direct node, connected | STM32 Run + ESP active = about 102.5 mA | STM32 Sleep + ESP Light-sleep | about 6.1-17.1 mA | about 85-96 mA | Yes, subject to MQTT keepalive/latency |
| ESP direct node, scheduled only | about 102.5 mA | STM32 Standby + ESP Deep-sleep | about 0.023 mA | about 102.48 mA | No; reconnect and poll after wake |
| SIM direct node, connected | STM32 Run + SIM idle = about 35.9-41.2 mA | STM32 Sleep + SIM network sleep | about 6.2-18.1 mA | about 18-35 mA | Conditional; must be proven with MQTT/operator |
| SIM direct node, scheduled only | about 35.9-41.2 mA | STM32 Standby + SIM power down | about 0.053-0.203 mA | about 35.7-41.1 mA | No; cellular re-registration required |
| LoRa + ESP gateway | STM32 Run + E32 RX + ESP active = about 117.5 mA | STM32 Sleep + E32 Mode 2 + ESP Light-sleep | about 6.1-17.1 mA | about 100-111 mA | Yes, if all wake paths are reliable |
| LoRa + SIM gateway | STM32 Run + E32 RX + SIM idle = about 50.9-56.2 mA | STM32 Sleep + E32 Mode 2 + SIM network sleep | about 6.2-18.2 mA | about 33-50 mA | Conditional; MQTT socket test required |

Transmit energy is not represented by the resting-current table. The E32 may draw about 110 mA during TX, the ESP8266 has RF peaks above its average, and SIM800L can draw two-amp bursts. Battery life must be calculated from duty cycle:

```text
I_average = (I_active * t_active + I_sleep * t_sleep) / total_period
battery_life_hours = usable_battery_capacity_mAh / I_average_mA
```

For SIM800L especially, reconnect time can dominate energy. A short sleep interval may consume less total energy by preserving registration rather than powering down and registering again.

## 5. Board-level currents that can defeat deep sleep

### 5.1 Existing battery divider

The current configuration uses 21.6 kOhm and 9.8 kOhm continuously across the battery. Its permanent drain is:

| Battery voltage | Divider current |
|---:|---:|
| 6.0 V | 0.191 mA |
| 7.4 V | 0.236 mA |
| 8.4 V | 0.268 mA |

This divider alone consumes roughly 32-46 times the theoretical STM32-Standby plus E32-Mode-3 current. For true deep sleep, switch the divider's high side with a low-leakage MOSFET/analog switch, or redesign it with higher resistance and validate ADC settling/source impedance. The existing 100 nF ADC capacitor can help settling but must be included in the calculation.

### 5.2 Required production-hardware controls

- A low-leakage load switch for sensor rails and, where appropriate, ESP8266/SIM800L rails.
- ESP8266 CHIP_EN and RESET routed to STM32 GPIOs.
- SIM800L DTR, RI, PWRKEY, and RESET routed to STM32 GPIO/EXTI pins.
- E32 AUX routed to an EXTI-capable pin; PC13 already satisfies Stop-mode wake.
- A regulator whose quiescent current is well below the sleep budget.
- No permanent power LED in the battery path, or a removable/controlled LED.
- RS485 transceiver shutdown control and sensor power switching.
- Series resistance or isolation on UART/IO lines to prevent back-powering a disabled module through protection diodes.
- Adequate SIM800L bulk/ceramic decoupling and a supply capable of the two-amp TX burst. Never power it from an STM32 GPIO.

## 6. Wake-up and remote-command strategy

### 6.1 LoRa node

Two valid designs are available:

**A. Always LoRa-reachable**

- Node E32 rests in Mode 2.
- Node STM32 rests in Stop.
- Gateway E32 sends commands in Mode 1 with a wake preamble matching the node's WOR interval.
- E32 AUX falling edge on PC13 wakes the node.
- Expected radio response latency is the configured WOR latency, potentially up to about two seconds, plus application processing.

**B. Scheduled receive window**

- Node E32 rests in Mode 3 or is power-gated.
- STM32 wakes by RTC, reads sensors, sends an uplink, then listens for a short command window.
- Gateway stores commands until it sees the node's `AWAKE`/telemetry frame.
- Gateway sends pending commands; node returns an ACK with command ID and result.
- Node sends a `SLEEPING_UNTIL` indication and sleeps.

Design B gives the lowest current and scales well for battery nodes. It requires command queuing, expiry, deduplication, and acknowledgements.

### 6.2 ESP8266 direct node

- **Connected behavior:** ESP Light-sleep, STM32 Sleep, UART interrupt wakes the STM32, and MQTT remains serviced within the 45-second keepalive requirement.
- **Deep behavior:** disconnect MQTT/Wi-Fi, enter ESP deep sleep or disable CHIP_EN, then STM32 Stop/Standby. Server commands remain queued until the scheduled reconnect.
- Do not rely on UART reception to wake STM32 Stop mode without a dedicated external wake/handshake design; the first bytes can be lost while clocks/UART are restored.

### 6.3 SIM800L direct node

- **Connected behavior:** use `AT+CSCLK=1` with DTR control. STM32 can use CPU Sleep and wake on UART/RI. Validate MQTT socket survival and incoming delivery on the exact firmware and mobile network.
- **Deep behavior:** close the socket/PDP context, issue `AT+CPOWD=1`, confirm `NORMAL POWER DOWN`, then STM32 Stop/Standby. Wake by RTC, pulse PWRKEY, wait for registration, reconnect, and collect queued commands.
- RI is useful for call/SMS wake but must not be assumed to signal every MQTT/TCP packet without test evidence.

### 6.4 Gateway

A gateway should not enter a state that breaks both LoRa reception and server connectivity. Recommended idle behavior:

- STM32 uses CPU Sleep/WFI between events, not Standby.
- E32 uses Mode 2 only if all nodes transmit to it with Mode 1 wake preambles. On reception the gateway wakes, changes to Mode 0 when it needs to ACK/transmit, then returns to Mode 2.
- ESP8266 uses connected Light-sleep; SIM800L uses proven registered sleep or remains in GPRS standby.
- UART RX, LoRa AUX, MQTT timers, and health timers are wake sources.
- A mains/solar-powered gateway may prioritize availability over the last few milliamps.

## 7. Required software architecture

Introduce one power-management layer instead of placing sleep calls throughout sensor, LoRa, and MQTT modules.

```text
ACTIVE
  -> PREPARE_SLEEP
       stop new publishes and commands
       finish ACK/fragment transactions
       flush UARTs and wait for E32 AUX ready
       disconnect or place modem in selected sleep state
       power down sensors/transceivers
       persist required state and compute RTC deadline
  -> ARM_WAKE_SOURCES
  -> LOW_POWER
  -> WAKE_CAPTURE
       record RTC / LoRa AUX / modem RI-UART / local GPIO reason
  -> RESTORE
       restore clock tree, timebase, UARTs, GPIOs and module state
  -> ACTIVE
```

Suggested modules:

- `PowerManager`: owns system state and the only entry into MCU sleep.
- `WakeManager`: configures RTC/EXTI and records wake reason.
- `RadioPowerAdapter`: E32 Mode 0/1/2/3 transitions and AUX-ready rules.
- `IpModemPowerAdapter`: separate ESP8266 and SIM800L strategies.
- `SensorPowerManager`: controls sensor rails, RS485 shutdown, warm-up and sampling.
- `PersistentState`: stores only state that must survive Standby/reset, such as node ID, message sequence, pending ACK state, next schedule, and reset counters.
- `CommandQueueProtocol`: command ID, creation time, expiry, retry count, ACK/result, and deduplication.

### State-retention rules

- Stop mode retains SRAM, but timestamps must still be based on RTC rather than assuming `millis()` advanced normally.
- Standby loses SRAM and restarts the application. Use RTC backup registers for small frequently updated values. Avoid writing internal Flash/EEPROM every sleep cycle because of endurance limits.
- MQTT session and socket state are lost in modem deep sleep/power-off. Reconnection must be treated as a normal state transition, not an error.
- LoRa fragment and ACK transactions must complete or be explicitly cancelled before sleep.

## 8. Conflicts with the current Arduino implementation

### 8.1 Independent watchdog

The current sketch starts a 25-second STM32 independent watchdog at the beginning of `setup()`. On STM32F401, once IWDG is started it cannot be stopped except by reset, and it continues in Stop/Standby. Therefore:

- sleep shorter than the watchdog window can work only with a safe timing margin;
- a node sleeping for minutes would reset after roughly the watchdog interval;
- the low-power architecture must decide the sleep profile **before** starting IWDG.

Professional options are:

1. Use IWDG only in always-awake/short-sleep profiles.
2. Replace it with WWDG or another active-phase watchdog that naturally stops with its clock, after verifying fault coverage.
3. Use an external watchdog/supervisor with a sleep/enable input.
4. Use a reset-to-sleep handshake: store a `sleep_pending` flag in the backup domain, reset, enter long sleep before starting IWDG, then start IWDG only for the active phase after the real wake.

The fourth option preserves the present strong active-phase watchdog without allowing it to terminate a long sleep.

### 8.2 `millis()` scheduling

The current sampling and transmission scheduler compares `millis()` with `lastReadMs` and `lastSendMs`. Stop/Standby halts or restarts the Arduino timebase, so the future implementation must use absolute RTC deadlines and restore/rebase the software timebase after wake.

### 8.3 Current loop behavior

The current sensor loop continuously polls LoRa, MQTT, sensor schedules, and the asynchronous publish state machine. The new design should preserve these modules but place a `PowerManager` above them. It may enter sleep only when all modules report `readyToSleep()` and no LoRa fragment, MQTT publish, command, UART transfer, or sensor transaction is active.

## 9. Recommended implementation plan

### Phase 1 - measure the current hardware

Measure each configuration in Run, radio receive, radio transmit, proposed sleep, and wake/reconnect states. Record current versus time, not only one multimeter number.

1. STM32 board alone.
2. STM32 + E32.
3. STM32 + ESP8266.
4. STM32 + SIM800L.
5. Complete node with every sensor and regulator.
6. Complete gateway.

### Phase 2 - hardware enable/wake controls

Add or confirm E32 AUX EXTI, ESP EN/RST, SIM DTR/RI/PWRKEY/RST, sensor/load-switch controls, low-Iq regulation, and a switchable battery divider.

### Phase 3 - RTC and power manager

Implement RTC absolute scheduling, wake-reason capture, clock/UART restoration, pin-leakage configuration, and the `readyToSleep()` contract. First validate STM32 Stop with all external modules held awake; then integrate one module at a time.

### Phase 4 - LoRa low power

Implement E32 Mode 2/AUX wake and Mode 1 gateway transmission. Then add the alternative scheduled receive-window protocol for the lowest-power nodes.

### Phase 5 - IP modem low power

Implement ESP Light-sleep and deep-sleep profiles. Implement SIM DTR sleep and normal power-down profiles. Add reconnection backoff and server-side command queuing.

### Phase 6 - gateway optimization

Use STM32 CPU Sleep/WFI, connected modem sleep, E32 Mode 2 where compatible, and event-driven wake. Do not use deep sleep until end-to-end command and telemetry availability has been proven.

## 10. Acceptance tests

- Measure complete-board sleep current at battery minimum, nominal, and maximum voltage.
- Run at room, minimum, and maximum intended temperature.
- Verify 1,000 RTC sleep/wake cycles without lockup.
- Verify LoRa AUX wake at every configured WOR interval and at weak-signal limits.
- Verify no first-byte loss after every UART/module wake.
- Verify ESP Wi-Fi/MQTT reconnect and queued-command delivery after deep sleep.
- Verify SIM800 registration, PDP, MQTT reconnect, and two-amp supply transient margin.
- Verify SIM800 connected sleep for several hours with repeated broker downlinks.
- Verify command expiry, deduplication, ACK retry, and reset during every protocol phase.
- Verify watchdog behavior separately in active and low-power profiles.
- Confirm no back-power current when each external module is disabled.

## 11. Final recommendation

Start implementation with the **LoRa sensor-node periodic profile**, because it offers the largest reliable battery improvement and the current E32 M0/M1/AUX wiring already supports it. Keep the gateway always reachable using CPU Sleep and connected modem sleep. After current profiling, decide whether direct ESP/SIM sensor nodes need immediate commands; if not, use scheduled wake plus a server-side command queue.

Before writing low-power firmware, confirm three hardware facts:

1. the exact E32 model/revision printed on the module;
2. whether the STM32 board has a populated 32.768 kHz LSE crystal;
3. whether ESP EN/RST and SIM DTR/RI/PWRKEY/RST are physically accessible.

Those answers determine which wake paths can be implemented without a PCB revision.
