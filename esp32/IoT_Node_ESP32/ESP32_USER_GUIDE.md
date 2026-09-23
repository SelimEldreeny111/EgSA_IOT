# ESP32 IoT Node/Gateway Port — User Guide

## 1. Scope

This is a separate Arduino project for the classic ESP32-WROOM 38-pin
development board shown in the supplied pinout image. It preserves the current
application architecture:

- sensor node and LoRa-to-MQTT gateway roles;
- TUF, Supmea, HNDA, and Sondas RS485 drivers;
- external ESP8266 or SIM800L through TinyGSM;
- E32/AS32 LoRa framing, fragmentation, acknowledgement, and diagnostics;
- MQTT topics, protobuf messages, AES payload encryption, and commands;
- watchdog recovery; and
- configurable normal/deep-sleep policies.

This compatibility port intentionally keeps the external ESP8266/SIM800L
architecture. The ESP32's internal Wi-Fi radio is not used. That avoids a
protocol and network-stack redesign and keeps behavior aligned with the STM32
project.

The STM32 Arduino and STM32CubeIDE projects remain separate and unchanged.

## 2. Supported toolchain

The verified configuration is:

| Item | Version/selection |
|---|---|
| Arduino board package | `esp32 by Espressif Systems` 3.3.8 |
| Board | `ESP32 Dev Module` |
| FQBN | `esp32:esp32:esp32` |
| Flash size | 4 MB default for the development board |
| Partition scheme | Default |
| Serial monitor | 115200 baud |
| TinyGSM | 0.12.0 |
| PubSubClient | 2.8 |
| AESLib | 2.3.6 |

`STM32duino RTC` and `IWatchdog` are not required by this ESP32 project. RTC
timer wake and the task watchdog are provided by the ESP32 core.

## 3. Electrical rules

1. Every ESP32 GPIO is a 3.3 V signal. Never apply 5 V to an ESP32 input.
2. Connect the grounds of the ESP32, RS485 transceiver, LoRa module, and active
   external modem.
3. Do not power the LoRa module, ESP8266, or SIM800L from the ESP32 development
   board's 3.3 V pin. Use properly sized supplies, especially for SIM800L burst
   current, and join their grounds.
4. GPIO6 through GPIO11 are connected to the ESP32 module's SPI flash. They are
   not available even though GPIO9/GPIO10 are sometimes labelled RX1/TX1 in
   generic pinout pictures. This port safely remaps UART1 to GPIO32/GPIO33.
5. Do not connect two peripheral TX outputs to a shared ESP32 RX pin. The table
   below assigns shared pins only to mutually exclusive firmware profiles. Use
   jumpers, a multiplexer, or guaranteed power isolation if one PCB carries all
   modules.

## 4. Pin map

### 4.1 Fixed control and measurement pins

| Function | ESP32 pin | Connection |
|---|---:|---|
| Debug TX0 | GPIO1 | On-board USB-UART RX |
| Debug RX0 | GPIO3 | On-board USB-UART TX |
| LoRa M0 | GPIO25 | E32/AS32 M0 |
| LoRa M1 | GPIO26 | E32/AS32 M1 |
| LoRa AUX | GPIO27 | E32/AS32 AUX |
| RS485 direction | GPIO4 | Tie transceiver DE and /RE together |
| Battery ADC | GPIO36 | Divider midpoint; input-only ADC1 pin |
| Node open/close output | GPIO18 | Active-low output |
| External ESP8266 EN | GPIO13 | ESP_EN |
| External ESP8266 reset | GPIO14 | ESP_RST, active low |
| SIM800 reset | GPIO19 | SIM reset line |

Recommended external bias resistors for deterministic sleep and reset behavior:

- 10 kΩ pull-up on LoRa M0 and M1;
- 10 kΩ pull-down on RS485 DE+/RE;
- 10 kΩ pull-ups on ESP8266 EN and RST.

The firmware also uses ESP32 GPIO hold during deep sleep, but external biasing
still protects the modules during power-up, reset, upload, and brownout.

### 4.2 UART ownership by build profile

| Profile | UART0 | UART1: GPIO32 RX / GPIO33 TX | UART2: GPIO16 RX / GPIO17 TX |
|---|---|---|---|
| Sensor node → LoRa gateway | Debug | RS485 sensors | LoRa |
| Sensor node → MQTT direct | Debug | ESP8266 or SIM800L | RS485 sensors |
| LoRa MQTT gateway | Debug | ESP8266 or SIM800L | LoRa |

Signal direction is from the ESP32's point of view:

- ESP32 RX connects to the peripheral TX/RO.
- ESP32 TX connects to the peripheral RX/DI.

RS485 wiring for the active sensor bus:

| ESP32/transceiver side | Connection |
|---|---|
| Selected UART RX | Transceiver RO |
| Selected UART TX | Transceiver DI |
| GPIO4 | Transceiver DE and /RE joined |
| Transceiver A/B | Sensor 485+/485- as required by its manual |
| GND | Sensor/transceiver reference ground |

Fit 120 Ω termination only at the two physical ends of a long RS485 bus. Do
not add 120 Ω at every sensor.

## 5. Open and upload

1. Open `IoT_Node_ESP32.ino` in Arduino IDE.
2. Install/select `esp32 by Espressif Systems` version 3.3.8.
3. Select **Tools → Board → esp32 → ESP32 Dev Module**.
4. Leave the default partition scheme and select the correct COM port.
5. Install TinyGSM, PubSubClient, and AESLib versions shown above.
6. Open `src/config/AppConfig.h` and select the required profile before upload.
7. Compile first, then upload.
8. Open Serial Monitor at 115200 baud and reset the board.

If upload cannot start, hold **BOOT**, press and release **EN/RESET**, begin the
upload, then release **BOOT** when writing starts.

## 6. Configuration profiles

All choices are near the beginning of `src/config/AppConfig.h`.

### 6.1 Default: sensor node through LoRa

```cpp
#define APP_IP_MODEM APP_IP_MODEM_ESP8266

#define APP_ROLE   APP_ROLE_SENSOR_NODE
#define APP_UPLINK APP_UPLINK_LORA_TO_GATEWAY

#define APP_CONTROLLER_POWER_MODE APP_COMPONENT_MODE_NORMAL
#define APP_LORA_POWER_MODE       APP_COMPONENT_MODE_NORMAL
#define APP_WIFI_POWER_MODE       APP_COMPONENT_MODE_NORMAL
#define APP_SIM_POWER_MODE        APP_COMPONENT_MODE_NORMAL
```

UART1 belongs to RS485 and UART2 belongs to LoRa. The selected external modem
is compiled for shared architecture compatibility but is not initialized.

### 6.2 Sensor node with direct MQTT through external ESP8266

```cpp
#define APP_IP_MODEM APP_IP_MODEM_ESP8266

#define APP_ROLE   APP_ROLE_SENSOR_NODE
#define APP_UPLINK APP_UPLINK_MQTT_DIRECT

#define APP_CONTROLLER_POWER_MODE APP_COMPONENT_MODE_NORMAL
#define APP_LORA_POWER_MODE       APP_COMPONENT_MODE_NORMAL
#define APP_WIFI_POWER_MODE       APP_COMPONENT_MODE_NORMAL
#define APP_SIM_POWER_MODE        APP_COMPONENT_MODE_NORMAL
```

UART1 belongs to ESP8266 and UART2 belongs to RS485. Do not leave a LoRa TXD
connected to GPIO16 in this profile unless it is electrically isolated.

### 6.3 LoRa-to-MQTT gateway

```cpp
#define APP_IP_MODEM APP_IP_MODEM_ESP8266

#define APP_ROLE   APP_ROLE_LORA_GATEWAY
#define APP_UPLINK APP_UPLINK_LORA_TO_GATEWAY

#define APP_CONTROLLER_POWER_MODE APP_COMPONENT_MODE_NORMAL
#define APP_LORA_POWER_MODE       APP_COMPONENT_MODE_NORMAL
#define APP_WIFI_POWER_MODE       APP_COMPONENT_MODE_NORMAL
#define APP_SIM_POWER_MODE        APP_COMPONENT_MODE_NORMAL
```

UART1 belongs to ESP8266 and UART2 belongs to LoRa. Local sensor drivers are
disabled by the gateway role. The gateway controller must remain in NORMAL
mode so it can receive LoRa traffic continuously.

### 6.4 Sensor node periodic LoRa deep sleep

Start with a 30-second test interval:

```cpp
#define APP_CONTROLLER_POWER_MODE APP_COMPONENT_MODE_POWER_DOWN
#define APP_LORA_POWER_MODE       APP_COMPONENT_MODE_POWER_DOWN
#define APP_WIFI_POWER_MODE       APP_COMPONENT_MODE_NORMAL
#define APP_SIM_POWER_MODE        APP_COMPONENT_MODE_NORMAL
#define APP_POWER_SLEEP_SECONDS   30UL
```

After one successful telemetry transmission and the command window, the LoRa
module enters mode 3 and the ESP32 enters timer deep sleep.

### 6.5 Sensor node periodic direct-ESP8266 deep sleep

Use `APP_UPLINK_MQTT_DIRECT`, then configure:

```cpp
#define APP_CONTROLLER_POWER_MODE APP_COMPONENT_MODE_POWER_DOWN
#define APP_LORA_POWER_MODE       APP_COMPONENT_MODE_NORMAL
#define APP_WIFI_POWER_MODE       APP_COMPONENT_MODE_POWER_DOWN
#define APP_SIM_POWER_MODE        APP_COMPONENT_MODE_NORMAL
#define APP_POWER_SLEEP_SECONDS   30UL
```

The firmware closes MQTT/TCP, sends the ESP8266 deep-sleep command, retains its
control-pin levels, and starts ESP32 timer deep sleep. GPIO14 resets/wakes the
ESP8266 after the controller wakes.

SIM800L periodic power-down remains intentionally blocked because a reset pin
alone cannot guarantee a controlled power-off and wake. Route PWRKEY (and
preferably DTR/RI) before adding that feature.

For an always-awake SIM800L direct node or gateway, select:

```cpp
#define APP_IP_MODEM APP_IP_MODEM_SIM800
```

Keep `APP_SIM_POWER_MODE` and `APP_CONTROLLER_POWER_MODE` set to NORMAL on the
present hardware.

## 7. Deep-sleep behavior and limitations

The periodic sequence is:

```text
sample sensors → send encrypted telemetry → command window
→ quiesce active transport → retain safe GPIO levels
→ ESP32 deep sleep → RTC timer wake → full setup/reconnect
```

The sleep duration and command window are configured by:

```cpp
#define APP_POWER_SLEEP_SECONDS      300UL
#define APP_POWER_COMMAND_WINDOW_MS  5000UL
```

Important: the current design wakes only from the ESP32 RTC timer. It cannot
receive a LoRa or server command while the controller and radio are sleeping.
Commands must arrive during the configured awake command window. Adding an
external wake line from LoRa AUX, ESP8266, or SIM800 RI requires separate
hardware qualification and firmware work.

The ESP32 internal clock survives deep sleep, but it does not provide
battery-backed time through complete power removal. On a cold boot the firmware
uses the configured default epoch until a valid command/server timestamp sets
the clock.

## 8. Watchdog behavior

The ESP32 loop task is registered with the Task Watchdog Timer. The default
timeout is 25 seconds:

```cpp
#define APP_ENABLE_HARDWARE_WATCHDOG 1
#define APP_WATCHDOG_TIMEOUT_MS      25000UL
#define APP_NETWORK_FAILURES_BEFORE_RESET 2U
```

Progress checkpoints service the watchdog only after bounded work returns. A
stuck sensor, modem, Wi-Fi/GSM search, or application loop therefore resets the
controller. Intentional delays use short watchdog-serviced slices. Do not add
watchdog service calls inside an operation that may hang forever.

## 9. Step-by-step hardware acceptance test

Test one interface at a time before assembling the full system.

1. **Bare ESP32** — Upload with all power modes NORMAL. Confirm 115200-baud
   startup logs and `ESP32 task watchdog: armed`.
2. **Battery input** — Apply a known safe divider voltage to GPIO36. Compare the
   printed battery voltage with a multimeter and adjust only
   `APP_BATTERY_CALIBRATION_FACTOR` if required.
3. **RS485 only** — Connect the 3.3 V RS485 transceiver, common ground, and one
   sensor. Verify GPIO4 is low while idle and pulses high during requests.
4. **Sensor addresses** — Enable one driver at a time. Confirm each physical
   Modbus address matches `AppConfig.h`; no two active sensors may share an
   address.
5. **LoRa only** — Use the LoRa-node profile, connect UART2 and M0/M1/AUX, and
   confirm AUX becomes high and frames are transmitted/acknowledged.
6. **External modem only** — Use direct MQTT, connect the modem to UART1, and
   verify AT firmware, network, MQTT connection, subscription, and one publish.
7. **Full node** — Add its second active interface according to the UART table.
   Confirm repeated sensor reads and encrypted telemetry without CRC, timeout,
   or reconnect loops.
8. **Gateway** — Build the gateway profile on a separate board. Confirm incoming
   LoRa frames are acknowledged and published to the source node's MQTT topic.
9. **Watchdog** — On a bench unit only, temporarily introduce a delay longer
   than 25 seconds without calling `watchdogDelay`. Confirm a watchdog reset and
   the next boot's watchdog reset-cause log, then remove the test.
10. **Deep sleep** — Use a 30-second interval. Confirm one delivery, the 5-second
    command window, the deep-sleep log, low current, timer wake, and a complete
    reconnect. Only then increase the production interval.

## 10. Compile validation completed

The following profiles were compiled with ESP32 Arduino core 3.3.8 on
2026-09-07:

| Profile | Result | Flash | Global RAM |
|---|---|---:|---:|
| LoRa sensor, NORMAL | Passed | 388,723 B (29%) | 29,644 B (9%) |
| LoRa sensor, POWER_DOWN | Passed | 410,251 B (31%) | 29,748 B (9%) |
| Direct MQTT sensor, NORMAL | Passed | 400,331 B (30%) | 26,412 B (8%) |
| Direct MQTT sensor, POWER_DOWN | Passed | 410,531 B (31%) | 26,532 B (8%) |
| LoRa MQTT gateway, NORMAL | Passed | 385,572 B (29%) | 29,804 B (9%) |
| SIM800 direct MQTT sensor, NORMAL | Passed | 400,091 B (30%) | 26,412 B (8%) |

Compilation verifies the source and every UART ownership profile. Final
acceptance still requires the staged hardware test above because supply
quality, signal levels, transceiver direction, and attached module firmware
cannot be verified by compilation.
