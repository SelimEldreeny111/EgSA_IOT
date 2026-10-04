# Uflow latching valve / TB6612FNG — wiring, commissioning and tests

Release: 4 October 2026. Scope: FINAL Arduino STM32 node and its Python server.
ESP32 and STM32CubeIDE ports are unchanged. This replaces the old static valve
GPIO behavior; do not use that older firmware with this new driver wiring.

## 1. What the hardware does

The supplied coil photo is marked Uflow, **12 V DC, 06 W, LATCH, H class**.
This identifies a latching coil, not an ordinary continuously energized valve.
The exact valve model, supplier pulse durations, minimum interval/duty cycle,
operating pressure and opening wire polarity are not established by the photo.
Do not infer normally-open/normally-closed behavior from its appearance.

A bipolar latching coil receives a brief DC pulse to move one way and an
opposite-polarity pulse to move back. The coil is unpowered between commands,
including when the valve is open. A controller reset does not itself close it.
The label implies approximately `6 W / 12 V = 0.5 A` nominal current; this is
an estimate, not a measured pulse current or guarantee of successful actuation.

TB6612FNG is the confirmed H-bridge. Its STBY input LOW makes its outputs
high-impedance. PWM LOW is a braking mode in some input combinations, so this
implementation uses STBY for the actual off state. See the manufacturer's
[TB6612FNG datasheet](https://toshiba.semicon-storage.com/info/TB6612FNG_datasheet_en_20141001.pdf?did=10660&prodName=TB6612FNG).
Uflow's [coil catalogue](https://www.uflowvalve.com/Assets/Product/Catalogue/solenoid-valve/solenoid_coil.pdf)
describes pulsed latching operation but is not a pulse-time specification for
the exact photographed assembly. Obtain those values from the supplier.

## 2. Wiring — driver channel A

Disconnect power while wiring. The GPIOs drive logic inputs, NEVER the coil.

| STM32 / supply | TB6612FNG | Purpose |
| --- | --- | --- |
| PB9 | AIN1 | Polarity input 1 |
| PB15 | AIN2 | Polarity input 2 |
| PC13 (existing valve pin) | STBY | HIGH only during a pulse; LOW otherwise |
| Regulated 3.3 V | VCC and PWMA | Logic supply and channel-A enable |
| Regulated external 12 V | VM | Coil power, not the MCU 3.3/5 V rail |
| Common ground | GND / PGND | STM32, driver and 12 V supply reference |
| Coil wire 1 | AO1 / A01 | First end of the two-wire coil |
| Coil wire 2 | AO2 / A02 | Second end; opposite polarity for the other command |

Use the actual module labels; AO1/AO2 must not be confused with AIN1/AIN2.
The wire colors are not a verified opening-polarity convention. Record the
AO1/AO2 assignment before commissioning. Tie unused BIN1/BIN2/PWMB LOW and
leave BO1/BO2 unconnected. Do not parallel the two channels.

Fit an external STBY-to-GND pull-down (for example 10 kOhm), and verify that
the breakout has no conflicting pull-up. It must hold the bridge OFF while
the MCU is reset, unpowered, booting, or in Standby. Internal IC pull-downs do
not replace system-level startup verification. Never tie STBY permanently HIGH.

Use VCC=3.3 V for the STM32's 3.3 V logic. Provide the driver's supply bypass
capacitors close to it (the datasheet circuit uses 10 uF plus 0.1 uF per rail),
appropriate supply energy absorption/transient protection and a fuse/current
limit. Check voltage overshoot at VM when a pulse ends. The datasheet's
operating VM ceiling is 13.5 V; 15 V is an absolute maximum, not an operating
target. Check pulse current and board heating. A single diode directly across
the bipolar coil would short one commanded polarity; do not use that ordinary
one-way solenoid arrangement here. Have the actual protection circuit reviewed.

PB9/PB15 are unused by the active application's buses. They are dedicated to
this valve in this release; do not also enable alternate I2C/SPI uses on them.
TIM10 is reserved for valve cutoff; do not use it for PWM/tone/another library.
PC13 can also drive a board LED. With an active-low LED, STBY LOW can leave
the LED lit between pulses and affect the power budget. The LED circuit can
also bias a floating PC13 during reset/Standby: measure STBY and confirm it
stays below the driver's LOW-input limit (0.3 x VCC). Do not assume a 10 kOhm
pull-down is sufficient for every breakout/LED circuit. Review any LED removal,
buffering or pull-down change electrically before use; no PCB change is made here.

**Existing LoRa limitation:** PC13 is AS32 AUX on the current LoRa wiring.
All builds with that conflict inhibit valve control and leave these valve
GPIOs untouched, including gateway builds. No pin was silently reassigned.
To add valve control to that LoRa wiring, a separate approved wiring/pin change
is required. SIM and ESP8266/Wi-Fi sensor-node builds can use this pin set.

## 3. Configuration in src/config/AppConfig.h

The delivered defaults are deliberately NOT commissioned:

```cpp
#define APP_ENABLE_LATCHING_VALVE true
#define APP_VALVE_OPEN_PULSE_MS 0UL
#define APP_VALVE_CLOSE_PULSE_MS 0UL
#define APP_VALVE_POLARITY_CONFIRMED false
#define APP_VALVE_OPEN_AIN1_HIGH true
#define APP_VALVE_MIN_INTERVAL_MS 1000UL
```

The definitions already exist under `#ifndef`; edit the existing definitions,
not duplicate copies. Build flags may override them, so also check any flags.

| Setting | Exact effect |
| --- | --- |
| APP_ENABLE_LATCHING_VALVE | false: no valve GPIO operations and valve commands rejected; true still requires commissioning and a non-conflicting sensor-node pin set. |
| APP_VALVE_OPEN_PULSE_MS | Supplier-approved opening pulse length. Zero inhibits BOTH directions. |
| APP_VALVE_CLOSE_PULSE_MS | Supplier-approved closing pulse length. Zero inhibits BOTH directions. |
| APP_VALVE_POLARITY_CONFIRMED | Must be true only after the opening polarity has been established. false rejects actuation. |
| APP_VALVE_OPEN_AIN1_HIGH | true: opening drives AO1 positive relative to AO2; false reverses opening polarity. Closing always uses the opposite combination. |
| APP_VALVE_MIN_INTERVAL_MS | Minimum OFF time before another opposite-direction pulse. Range 1000..60000 ms; use a supplier-approved value no shorter than the software floor. |

Pulse settings accept zero (inhibited) or 1..1000 ms. **1000 ms is a software
ceiling, NOT the permitted coil duration.** Do not choose it merely because it
compiles. The 1000 ms switching-interval floor is likewise not a coil thermal
rating. If the supplier requires longer pulse times or intervals outside the
supported limits, do not work around the guards: review the driver/coil design.
No guessed pulse duration is supplied in this release. The 60/80 ms values in
automated tests are compile/simulation fixtures only, never commissioning data.

To commission: obtain the two specified durations and duty/cooling limits,
record wire assignment and confirm polarity, then replace both zero values
with the approved times and set polarity confirmation true. Rebuild/flash the
node with those choices. The server has no command to set these safety values.

## 4. Command, cutoff, telemetry and reset behavior

Server VALVE remains command ID 5: data 1 = open/ON, data 0 = close/OFF.
Other data is rejected. The node validates the target ID before actuation.
Both SIM and Wi-Fi use the same command handler and priority reply queue.

For a change of state, the driver:

1. Holds STBY LOW and saves a checksummed Unknown record BEFORE powering the coil.
2. Programs direction with STBY LOW and arms the TIM10 interrupt.
3. Raises STBY for the selected pulse, waits for cutoff, and leaves all three
   inputs LOW. No direction change occurs while the bridge is enabled.
4. After cutoff, saves the completed command and returns a telemetry ACK.

Repeated commands for an already recorded completed target are idempotent:
successful ACK, no extra pulse/flash erase. They do not prove that the physical
valve has not been moved manually. A deliberately different command after the
minimum interval is required to establish another commanded state.

The interrupt turns the bridge off even if foreground execution stalls while
interrupts still run. No logging, EEPROM or MQTT work occurs in that interrupt.
A missing cutoff callback makes the foreground disable the bridge at its next
configured-deadline check (1 ms yield granularity) and report a fault; it does
not intentionally extend the pulse with an energized grace period.
The command does not feed the global **30-second IWDG** and never recursively
calls MQTT. The bounded pulse blocks command dispatch for its duration; it does
not interrupt an existing modem/library call. Flash commits happen with the
bridge OFF and remain covered by the global WDT, not the pulse deadline.

**Safety limit:** a disabled/stalled interrupt system or failed CPU can defeat
GPIO-based cutoff. The 30-second watchdog is too slow to protect a short-pulse
coil. Use an independent hardware pulse limiter for that failure case. This is
not a safety-certified actuator or a guaranteed fail-closed water system.

The unchanged protobuf field `node_status` carries these values in BOTH
periodic Status (tag 9) and command Telemetry (tag 15):

| Value | Server label | Meaning |
| --- | --- | --- |
| 0 | Closed / OFF (commanded) | A completed closing pulse or restored completed closing command. |
| 1 | Open / ON (commanded) | A completed opening pulse or restored completed opening command. |
| 2 | Unknown — not confirmed | No valid saved command or an interrupted pulse. |
| 3 | Fault — position unknown | A storage/cutoff failure prevented reliable completion. |

There is NO position/limit-switch feedback. Successful ACK means the firmware
completed the electrical pulse (or an idempotent command), not verified valve
movement or verified water flow. Failed sensor reads do not erase valve state.
If a successfully completed pulse cannot be saved, its RAM state and ACK remain
successful with a log warning; reset may restore Unknown instead.

The server gives every VALVE command a nonzero request ID and initially reports
publication/waiting, not success of movement. After the node replies, existing
`command_ack_request_id`, `command_ack_cmd_id=5`, and `command_ack_success` carry
the correlated result. A rejected command returns false with the unchanged or
fault/unknown state. Legacy commands with request ID 0 still get telemetry but
cannot be correlated. Reply-queue or transport failure is logged; no reply does
not mean no actuation. Review telemetry/physical position before retrying.

Queued VALVE commands are claimed for publication at most once, like WAKE.
They remain Dispatched until a matching ACK or expiry; the server does not
automatically send an old valve request again after a missing ACK. Otherwise
an earlier opening command could reopen a valve after a newer closing command.
Rate/time commands retain their existing retry behavior. If the first valve
publication/delivery is lost, inspect the latest state and deliberately issue
another command if appropriate. MQTT itself still has its normal QoS delivery
semantics; this safeguard is not a system-wide exactly-once guarantee.

`node_status` already used uint32, so tags, message sizes, generated descriptors,
AES framing and databases do not change. The new server labels are needed for
Unknown/Fault. Historical old firmware rows lack this new boot certainty; they
must not be reinterpreted as proof of physical position.

After reset/RTC Standby: the early boot hook keeps the bridge OFF before any
network or sleep handoff. A valid flash record restores the last completed
command without another pulse. Missing/corrupt/interrupted records restore
Unknown. Disabled/LoRa-conflicting builds report Unknown rather than a fabricated
Closed state. Hardware latching retains its own position across controller sleep;
actual retention on total power loss must be checked on the supplied assembly.

The record uses EEPROM-emulation bytes 212..231, after Wi-Fi 0..111, Supmea
128..183 and WDT 192..211. Buffered commits preserve the other records in normal
operation. No RTC backup registers are taken: all 20 are already allocated.
Two flash-sector commits are needed per actual state change. The shared sector
is NOT power-fail atomic or wear-levelled; power loss during erase can invalidate
other records too. Frequent switching needs a separately reviewed endurance
design/external durable memory; do not use this journal for rapid cycling.

Power modes, four-sensor behavior, RTC consumption, modem retry recovery and
WDT settings are otherwise unchanged. Deep sleeping nodes cannot receive
immediate commands; use the existing next-wake queue. Reachable-controller
profiles dispatch the valve after their normal command reception/wake handling.
The old static-PC13/RAM-only valve descriptions in earlier guides are superseded
by this guide. Coil power is OFF between pulses in every supported controller
mode, independent of whether the last commanded valve position is open or closed.

## 5. Step-by-step bench acceptance

Use a safe test rig, current-limited supply and physical/manual shutoff. Start
with the coil DISCONNECTED. Do not test on an unattended live water installation.

| Step | Action | Required result |
| --- | --- | --- |
| 1 | Flash delivered zero/false defaults; send VALVE 1 then 0. | Actuation inhibited; negative correlated ACK; no STBY pulse; first-boot state Unknown. |
| 2 | Observe STBY during power-on, reset and controller Standby. | LOW throughout reset/startup/idle; external pull-down effective before firmware runs. |
| 3 | Obtain supplier times/polarity; configure them. Keep coil disconnected; scope STBY/AIN1/AIN2/AO1/AO2. | Opening/closing polarity opposite; pulse lengths match approved settings; STBY LOW and outputs disabled between pulses. |
| 4 | Send VALVE 1, wait approved interval, then VALVE 0 on SIM. | Pulse-completion ACK IDs match; ON/1 and OFF/0 appear in command telemetry and following Status. |
| 5 | Repeat step 4 with ESP8266/Wi-Fi. | Same pulse/state/ACK behavior; no transport-specific valve implementation. |
| 6 | Repeat same-state command; send invalid data 2; send an opposite command too quickly. | Same-state produces no new pulse; invalid/too-fast command rejected without false state update. |
| 7 | Connect coil only after electrical checks. Test operation at approved voltage/pressure and interval; measure current/VM overshoot/temperature. | Actual valve moves correctly, supply/driver safe, no continuous coil current. Telemetry remains explicitly commanded state. |
| 8 | Reset after a completed open/close command. | No startup pulse; last completed command restored; physical latch position independently checked. |
| 9 | In a controlled rig, reset DURING a pulse. | Pull-down disables bridge; boot reports Unknown, not stale Open/Closed; no automatic recovery pulse. |
| 10 | Disconnect sensors while valve is commanded open/closed. | Failed sensor values zero/invalid; valve state remains independent. |
| 11 | Exercise supported REMOTE_WAKE and Wi-Fi RTC/queued modes. | Driver idle OFF; restored last command after Standby; queued commands execute only after node wakes. |
| 12 | Build/run a LoRa/gateway profile using PC13 AUX. | Valve command rejected; no driver GPIO writes; radio AUX operation unchanged. Do not wire STBY to shared AUX. |

The existing packet encryption is AES-CBC without authenticated commands.
Before real actuator deployment, use a reviewed authenticated command/channel
design and secure broker access. A public/shared broker plus encryption alone
does not establish sender authenticity. This release does not silently change
the application's security protocol.

## 6. Reproducible software checks

- `tests/valve/run_tests.ps1`: actual driver with fake GPIO/TIM10/EEPROM;
  inhibited/disabled paths, both polarities, idempotence, minimum interval,
  reset/flash corruption, pre/post-write failures, missing/premature interrupts,
  foreground stall cutoff, shared-record preservation, millis wrap.
- `tests/mqtt_priority/run_tests.ps1`: priority correlated replies plus legacy
  valve telemetry, including the existing SIM and Wi-Fi compile fixtures.
- `tests/remote_wake/test_config.ps1`: actual-header pulse/interval guards plus
  prior power/network-policy checks.
- `tests/remote_wake/run_build_matrix.ps1`: 11 original profiles plus two
  **compile-only** commissioned-valve fixtures. It never uploads hardware.
- Server `tests/test_remote_wake.py`: VALVE API correlation, invalid input,
  database/live telemetry codes 0..3; `tests/test_valve_display.js`: real labels.
- Root `Validate-Release.ps1`: all host/server/simulator/schema checks;
  optional `-BuildFirmware` and `-BuildDocumentation`.

Automated tests are not approval of the unknown coil timings, not a proof of
hydraulic operation and not a measured current-saving test. Physical acceptance
and supplier commissioning remain mandatory.
