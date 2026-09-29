# Arduino Node Power-Down Configuration and Test Guide

## 1. Scope

This guide applies only to the Arduino IDE firmware in `Node`. The
`WIOT_STM32CubeIDE` project is intentionally unchanged.

The firmware provides a separate NORMAL/POWER_DOWN policy for:

- the STM32F401RCT6 controller;
- the E32/AS32 LoRa module;
- the ESP8266 module;
- the SIM800L module.

NORMAL is the default for every device. The compiler rejects unsafe or
unsupported combinations before a firmware image is produced.

The controller also supports **REMOTE_WAKE** (value 2): CPU Sleep with the
selected radio kept NORMAL/connected. It is a separate, lighter-power profile
that accepts server WAKE commands without waiting for the RTC interval.
See [Remote Wake Configuration and Bench Tests](REMOTE_WAKE_USER_GUIDE.md).
The Standby/deep-sleep sequences below remain RTC_PERIODIC only.

## 2. Configuration block

Open `src/config/AppConfig.h`. The first block contains:

```cpp
#define APP_COMPONENT_MODE_NORMAL 0
#define APP_COMPONENT_MODE_POWER_DOWN 1
#define APP_COMPONENT_MODE_REMOTE_WAKE 2 // controller only; selected radio NORMAL

#define APP_CONTROLLER_POWER_MODE APP_COMPONENT_MODE_NORMAL
#define APP_LORA_POWER_MODE       APP_COMPONENT_MODE_NORMAL
#define APP_WIFI_POWER_MODE       APP_COMPONENT_MODE_NORMAL
#define APP_SIM_POWER_MODE        APP_COMPONENT_MODE_NORMAL
```

These selections are compile-time policies. The transport selected by
`APP_UPLINK` must use the same active/sleep policy as the controller:

- NORMAL controller + NORMAL active radio: continuous operation;
- POWER_DOWN controller + POWER_DOWN active radio: scheduled RTC cycle.
- REMOTE_WAKE controller + NORMAL active radio: reachable application idle.

An unselected radio is not initialized. A configuration value alone is not a
replacement for removing its supply or adding a load switch.

The meaning of each value is:

- `NORMAL`: the selected device remains available continuously and the STM32
  never enters this feature's RTC Standby cycle.
- `POWER_DOWN`: after one successful telemetry delivery and the command window,
  the selected radio is put into its supported deep state and the STM32 enters
  Standby.

Do not set every line to POWER_DOWN automatically. Set the controller and only
the active communication path to POWER_DOWN. Leave unused policies NORMAL; if
an unused module is physically populated, disable or power-gate it in hardware.

Exactly one IP modem must be selected in the transport block, even in a LoRa
sensor build because the same codebase also builds the gateway:

```cpp
//#define USE_SIM800
#define USE_ESP8266
```

For SIM800L, uncomment `USE_SIM800` and comment out `USE_ESP8266`. Selecting
both—or neither—now gives a clear compiler error.

The cycle timing is configured immediately below the device policies:

```cpp
#define APP_POWER_SLEEP_SECONDS 300UL
#define APP_POWER_COMMAND_WINDOW_MS 5000UL
#define APP_POWER_SLEEP_ENTRY_TIMEOUT_MS 1000UL
```

- `APP_POWER_SLEEP_SECONDS`: Standby interval, 5 seconds through 7 days.
- `APP_POWER_COMMAND_WINDOW_MS`: time kept awake after successful telemetry so
  commands can arrive.
- `APP_POWER_SLEEP_ENTRY_TIMEOUT_MS`: maximum radio-idle preparation check.

Use 30 seconds during initial bench testing, then restore the intended field
interval.

## 3. Supported combinations

| Product profile | Controller | Active communication module | Status |
|---|---|---|---|
| LoRa sensor, continuous | NORMAL | LoRa NORMAL | Supported |
| LoRa sensor, periodic | POWER_DOWN | LoRa POWER_DOWN | Supported |
| Direct Wi-Fi sensor, continuous | NORMAL | Wi-Fi NORMAL | Supported |
| Direct Wi-Fi sensor, periodic | POWER_DOWN | Wi-Fi POWER_DOWN | Supported |
| Direct SIM800L sensor, continuous | NORMAL | SIM NORMAL | Supported |
| Direct SIM800L sensor, periodic | POWER_DOWN | SIM POWER_DOWN | Blocked by present PCB |
| LoRa / Wi-Fi / SIM800 sensor, remote wake | REMOTE_WAKE | Selected radio NORMAL | Supported; less saving than deep sleep |
| LoRa/IP gateway | NORMAL | Active modules NORMAL | Supported and required |
| Gateway controller Standby | POWER_DOWN | Any | Rejected; gateway would become unreachable |

The active controller and radio are paired deliberately. This release does not
power an active radio down between transactions while leaving the STM32 running
continuously.

## 4. Ready-to-use examples

### 4.1 Existing normal LoRa node

```cpp
#define APP_CONTROLLER_POWER_MODE APP_COMPONENT_MODE_NORMAL
#define APP_LORA_POWER_MODE       APP_COMPONENT_MODE_NORMAL
#define APP_WIFI_POWER_MODE       APP_COMPONENT_MODE_NORMAL
#define APP_SIM_POWER_MODE        APP_COMPONENT_MODE_NORMAL

#define APP_ROLE   APP_ROLE_SENSOR_NODE
#define APP_UPLINK APP_UPLINK_LORA_TO_GATEWAY
```

### 4.2 Normal direct Wi-Fi node

```cpp
#define APP_CONTROLLER_POWER_MODE APP_COMPONENT_MODE_NORMAL
#define APP_LORA_POWER_MODE       APP_COMPONENT_MODE_NORMAL
#define APP_WIFI_POWER_MODE       APP_COMPONENT_MODE_NORMAL
#define APP_SIM_POWER_MODE        APP_COMPONENT_MODE_NORMAL

#define APP_ROLE   APP_ROLE_SENSOR_NODE
#define APP_UPLINK APP_UPLINK_MQTT_DIRECT
```

Keep `USE_ESP8266` selected. This profile stays connected and does not enter
STM32 Standby.

### 4.3 Periodic LoRa node

```cpp
#define APP_CONTROLLER_POWER_MODE APP_COMPONENT_MODE_POWER_DOWN
#define APP_LORA_POWER_MODE       APP_COMPONENT_MODE_POWER_DOWN
#define APP_WIFI_POWER_MODE       APP_COMPONENT_MODE_NORMAL
#define APP_SIM_POWER_MODE        APP_COMPONENT_MODE_NORMAL

#define APP_ROLE   APP_ROLE_SENSOR_NODE
#define APP_UPLINK APP_UPLINK_LORA_TO_GATEWAY

#define APP_POWER_SLEEP_SECONDS 30UL
```

After bench acceptance, change the last value to the desired interval, for
example `300UL` for five minutes.

### 4.4 Periodic direct Wi-Fi node

Keep `USE_ESP8266` selected and use:

```cpp
#define APP_CONTROLLER_POWER_MODE APP_COMPONENT_MODE_POWER_DOWN
#define APP_LORA_POWER_MODE       APP_COMPONENT_MODE_NORMAL
#define APP_WIFI_POWER_MODE       APP_COMPONENT_MODE_POWER_DOWN
#define APP_SIM_POWER_MODE        APP_COMPONENT_MODE_NORMAL

#define APP_ROLE   APP_ROLE_SENSOR_NODE
#define APP_UPLINK APP_UPLINK_MQTT_DIRECT

#define APP_POWER_SLEEP_SECONDS 30UL
```

The ESP8266 publishes telemetry, keeps MQTT command processing active for the
command window, closes MQTT/TCP, and enters indefinite ESP-AT deep sleep with
`AT+GSLP=0`. The STM32 then enters Standby. On RTC wake, PB8 pulses ESP_RST,
Wi-Fi reconnects, and MQTT is restored.

### 4.5 SIM800L normal node

Use:

```cpp
#define USE_SIM800
//#define USE_ESP8266

#define APP_CONTROLLER_POWER_MODE APP_COMPONENT_MODE_NORMAL
#define APP_LORA_POWER_MODE       APP_COMPONENT_MODE_NORMAL
#define APP_WIFI_POWER_MODE       APP_COMPONENT_MODE_NORMAL
#define APP_SIM_POWER_MODE        APP_COMPONENT_MODE_NORMAL

#define APP_ROLE   APP_ROLE_SENSOR_NODE
#define APP_UPLINK APP_UPLINK_MQTT_DIRECT
```

Do not select SIM POWER_DOWN on this PCB.

### 4.6 Gateway

The gateway must use controller NORMAL, LoRa NORMAL, and NORMAL for its selected
ESP8266 or SIM800L modem. A gateway must listen for LoRa packets and server
commands continuously; the compiler rejects gateway Standby.

## 5. Schematic-derived control map

The supplied schematic gives the following relevant signals:

| Device/function | STM32 pin | Schematic net | Firmware use |
|---|---:|---|---|
| LoRa mode M0 | PB2 | S_nRF_RST | Driven HIGH for E32 Mode 3 |
| LoRa mode M1 | PB1 | S_nRF_EN | Driven HIGH for E32 Mode 3 |
| LoRa AUX | PC13 | GPIO6 | Idle/busy validation before sleep |
| ESP8266 enable | PB7 | ESP_EN | Held enabled during the active cycle |
| ESP8266 reset | PB8 | ESP_RST | Pulsed after every wake/reset |
| SIM800L reset | PB0 | GSM_RST | Reset only; not a power-on control |
| Modem UART | PA11/PA12 | GSM/4G/WiFi RX/TX | ESP8266 or SIM800L transport |
| RS485 driver enable | PA8 | RDE1 | Forced LOW before Standby |

The SIM800L `DTR`, `RING/RI`, and especially `PWRKEY` are not routed to the
STM32 in this schematic. Therefore:

- `AT+CPOWD=1` could turn the SIM800L off;
- the STM32 could not use the documented PWRKEY sequence to turn it back on;
- GSM_RST must not be treated as a substitute for PWRKEY;
- the firmware rejects the SIM800L POWER_DOWN profile.

A future PCB revision should route PWRKEY through a transistor/open-drain
driver, route DTR and RI, and preferably provide a modem load switch.

## 6. Required LoRa sleep hardware

STM32 Standby does not retain ordinary GPIO output levels. Before enabling the
LoRa periodic profile, verify:

| Signal | Required hardware state during Standby |
|---|---|
| E32 M0/PB2 | External pull-up, typically 10 kOhm |
| E32 M1/PB1 | External pull-up, typically 10 kOhm |
| E32 AUX/PC13 | Stable and connected |
| RS485 DE/PA8 | External pull-down, typically 10 kOhm |
| RTC/VBAT domain | Powered for the whole sleep interval |

M0=HIGH and M1=HIGH select E32 Mode 3. Mode 3 cannot receive radio data, so a
LoRa command cannot wake the node. Commands must be queued at the gateway and
sent in the active command window after the node publishes.

## 7. Runtime sequences

### LoRa periodic cycle

```text
RTC/cold boot -> initialize -> sample sensors -> encrypted LoRa telemetry
-> require gateway transport ACK -> LoRa command window
-> wait for UART/AUX/reassembly idle -> E32 Mode 3 -> RS485 DE low
-> checksummed RTC handoff -> software reset -> STM32 Standby -> RTC wake
```

### Wi-Fi periodic cycle

```text
RTC/cold boot -> pulse PB8 ESP_RST -> connect Wi-Fi/MQTT -> sample sensors
-> encrypted MQTT publish -> require SEND OK -> MQTT command window
-> disconnect MQTT/TCP -> AT+GSLP=0 -> close UART -> RS485 DE low
-> checksummed RTC handoff -> software reset -> STM32 Standby -> RTC wake
```

If telemetry fails, the node remains awake and retries. If a transport is busy,
sleep is postponed. If the RTC handoff fails validation, the firmware cancels
sleep and resumes active scheduling.

### Wake and retained-state behavior

RTC Alarm A is the normal wake source. Reset and power cycling also start the
firmware, but neither a LoRa packet nor an MQTT server packet can wake this
Standby profile:

- LoRa is in Mode 3, so its receiver is off.
- ESP8266 deep sleep has no Wi-Fi/MQTT connection.
- the server or gateway must queue commands until the next active window.

STM32 Standby is a reset-style wake. SRAM, local variables, UART state, LoRa
parser state, and network sessions are not retained. RTC calendar/backup-domain
state survives; the firmware validates a checksummed sleep request, then fully
initializes sensors and communication again. Meter totalizers remain the
responsibility of the externally powered meters—the firmware does not switch
their supply.

## 8. Boot log

Every build prints all four policies:

```text
Power configuration:
  STM32 controller: POWER_DOWN [ACTIVE]
  LoRa module: POWER_DOWN [ACTIVE]
  ESP8266: NORMAL [NOT SELECTED]
  SIM800L: NORMAL [NOT SELECTED]
Power cycle: RTC_PERIODIC, sleep=30 s, command window=5000 ms
```

In normal mode the final line is:

```text
Power mode: NORMAL (continuous operation; Standby disabled)
```

`ACTIVE` means the module participates in this compiled firmware. `NOT SELECTED`
means its policy is displayed for audit purposes but the firmware does not
initialize or power-control that module.

## 9. Arduino IDE build and upload

Use these settings for the existing STM32F401RCT6 board:

| Arduino IDE item | Selection |
|---|---|
| Board | Generic STM32F4 series |
| Board part number | Core board F401RCT6 |
| U(S)ART support | Enabled (generic Serial) |
| USB support | None |
| USB speed | Low/Full Speed |
| Optimize | Smallest (`-Os`, default) |
| C runtime | Newlib Nano |
| Upload method | STM32CubeProgrammer (SWD) |

Open `Node/IoT_Node_Encrypted.ino`, make the profile changes in
`src/config/AppConfig.h`, compile, and upload. SerialMon is 115200 baud on the
project debug UART PA2/PA3. Keep `build_opt.h` with the sketch because the LoRa
transport requires its 512-byte UART buffers.

The reviewed environment successfully built with STM32 core 2.12.0,
TinyGSM 0.12.0, PubSubClient 2.8, STM32duino RTC 1.9.0, IWatchdog 1.0.0, and
AESLib 2.3.6.

### Software validation status

The final v1.12.1 review compiles these independent profiles for `Core board
F401RCT6`:

- normal LoRa sensor node;
- periodic LoRa sensor node;
- periodic direct ESP8266 sensor node;
- normal LoRa/ESP8266 gateway;
- normal direct SIM800L sensor node.

It also verifies that the compiler deliberately rejects both-modems-selected
and SIM800L periodic-power-down builds. Compilation proves configuration and
link integrity; it does not replace the physical wake-cycle and current tests
below.

## 10. Step-by-step acceptance test

### Stage A — compile and normal-operation regression

1. Select the `Core board F401RCT6` Arduino target.
2. Set all four policies to NORMAL.
3. Compile and upload.
4. Confirm the boot log reports four NORMAL values.
5. Confirm sensor reads, LoRa or MQTT telemetry, commands, and watchdog recovery
   still work as before.

Pass condition: no sleep/reset cycle occurs and all existing functions behave
normally.

### Stage B — 30-second LoRa power-down test

1. Apply the required M0/M1 and RS485 DE hardware resistors.
2. Select the periodic LoRa example and set 30 seconds.
3. Upload and keep SerialMon connected.
4. Confirm a fresh sensor sample and acknowledged LoRa telemetry occur.
5. Send a gateway command during the five-second window and confirm it runs.
6. Confirm the log commits a sleep deadline.
7. Confirm the node wakes approximately 30 seconds later and repeats.
8. Remove the gateway ACK temporarily; confirm the node stays awake.
9. Restore the ACK and confirm the next successful cycle sleeps.

### Stage C — 30-second Wi-Fi power-down test

1. Select the periodic Wi-Fi example and set 30 seconds.
2. Confirm PB7/PB8 are physically connected as shown in the schematic.
3. Upload and confirm Wi-Fi/MQTT connect normally.
4. Confirm MQTT telemetry ends with `Telemetry Published Successfully`.
5. Send a server command during the five-second command window.
6. Confirm the log shows MQTT close and ESP8266 deep sleep.
7. Confirm the RTC wakes the STM32, PB8 resets the ESP, and MQTT reconnects.
8. Disable the access point temporarily; confirm the unit stays awake/retries or
   is recovered by the hardware watchdog instead of entering sleep blindly.

### Stage D — current measurements

1. Measure current in normal receive/idle operation.
2. Measure current after the log says the STM32 entered Standby.
3. Measure at least ten wake cycles.
4. Test at minimum and maximum supply voltage and expected temperature.
5. Calculate battery life from measured active time, active current, sleep time,
   and sleep current—not module datasheet current alone.

Disconnect the debugger/USB adapters when taking the final sleep-current
measurement; they can power the board through signal pins or change the value.
Measure the complete PCB supply, then isolate module and sensor rails if the
result is higher than expected. Repeat at least ten wake/sleep cycles.

The battery divider, regulators, LEDs, sensors, and RS485 transceiver remain
possible dominant loads. See `../POWER_DOWN_MODE_STUDY.md` for the detailed
current budget.

## 11. Recovery and troubleshooting

To recover a unit immediately, set the controller and active radio back to
NORMAL, rebuild, and upload. Normal-mode boot clears this feature's stale RTC
backup sleep request.

| Symptom | Check |
|---|---|
| Compile-time rejection | Read the complete error; active controller/radio policies must match |
| LoRa node never sleeps | Gateway ACK, AUX state, incomplete fragments, command activity |
| Wi-Fi node never sleeps | MQTT SEND OK, ESP-AT support for `AT+GSLP=0`, PB8 reset wiring |
| Wakes immediately | RTC alarm/wake flags and accidental PA0 wake input |
| Does not wake | RTC/VBAT power and RTC clock operation |
| LoRa sleep current stays high | External M0/M1 pull-ups and actual E32 Mode 3 |
| Total sleep current stays high | Regulators, LEDs, battery divider, sensors, RS485, back-power paths |
| SIM POWER_DOWN compile error | This is intentional; add PWRKEY/DTR/RI hardware first |

For emergency recovery, connect SWD, set the controller and active transport to
NORMAL, rebuild, and flash. Normal boot clears only this feature's tagged RTC
sleep record, so an old request cannot immediately return the unit to Standby.

## 12. Implementation files

- `src/config/AppConfig.h`: policies, timing, schematic pins, safety checks.
- `src/power/PowerManager.cpp`: RTC handoff and common periodic state machine.
- `src/radio/LoraLink.cpp`: LoRa idle validation and Mode 3 entry.
- `src/comm/MQTT.cpp`: ESP reset/wake, deep sleep, and publish-result handoff.
- `IoT_Node_Encrypted.ino`: main-loop integration.
