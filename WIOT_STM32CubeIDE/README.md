# WIOT STM32CubeIDE native port

This is the native STM32CubeIDE/HAL port of the working Arduino STM32F401RCT6 IoT firmware. The original `Node` and `Server` projects remain unchanged. The LoRa wire protocol, nanopb schema, AES-128-CBC envelope, node identities, sensor scaling, command handling, timings, and MQTT topic layout are preserved.

The project builds two firmware images from the same source tree:

- **SensorNode** (`APP_ROLE=1`) reads the Modbus sensors and battery ADC, sends encrypted telemetry over E32 LoRa, and receives commands.
- **LoRaGateway** (`APP_ROLE=2`) bridges encrypted LoRa packets to MQTT through an ESP8266 running ESP-AT and forwards MQTT commands back to LoRa.

## Open and build in STM32CubeIDE

1. Select **File > Import > General > Existing Projects into Workspace**.
2. Select this `WIOT_STM32CubeIDE` directory. Do not copy it into the workspace.
3. Select **Project > Build Configurations > Set Active**.
4. Choose either **SensorNode** or **LoRaGateway**, then build the project.
5. Flash the generated ELF, HEX, or BIN with STM32CubeIDE/ST-LINK.

The checked-in `WIOT_STM32F401RC.ioc` documents the shared STM32 pinout. `ProjectManager.NoMain=true` protects the hand-ported application and HAL initialization. The role-specific USART6 baud rate is selected in `Core/Src/main.cpp`: 9600 baud for the sensor node and 115200 baud for the ESP8266 gateway. If CubeMX generation is used later, review its generated diff instead of overwriting the custom Core files.

## Hardware mapping

| Function | SensorNode | LoRaGateway |
|---|---|---|
| Debug console | USART2: PA2 TX, PA3 RX, 115200 | USART2: PA2 TX, PA3 RX, 115200 |
| RS485 / Modbus | USART1: PA9 TX, PA10 RX, PA8 DE, 9600 | Not used |
| E32 LoRa UART | USART6: PA11 TX, PA12 RX, 9600 | USART1: PA9 TX, PA10 RX, 9600 |
| E32 mode/control | PB2 M0, PB1 M1, PC13 AUX | PB2 M0, PB1 M1, PC13 AUX |
| ESP8266 ESP-AT | Not used | USART6: PA11 TX, PA12 RX, 115200 |
| Battery input | ADC1_IN0: PA0 | Not used |

The E32 module is expected to be preconfigured exactly as in the deployed Arduino system: transparent transmission, UART 9600 baud, 2.4 kbps air rate, and the required 433 MHz channel. Automatic E32 configuration is disabled by default because the E32-TTL-100 protocol in the supplied datasheet does not provide the AS32 V3 command/RSSI interface. The firmware therefore does not invent a fixed dBm value; RSSI remains unavailable unless the hardware is replaced with a model that explicitly appends RSSI bytes.

## Source architecture

| Directory | Responsibility |
|---|---|
| `Core/Src/app` | Role orchestration, application state, sensor and gateway loops |
| `Core/Src/devices` | ADC battery monitor, RTC, Modbus RTU, flow and soil sensors |
| `Core/Src/radio` | Reliable E32 LoRa framing, fragmentation, ACK/retry, CRC and diagnostics |
| `Core/Src/comm` | nanopb telemetry, AES packet codec, command handler and ESP-AT/MQTT client |
| `Core/Src/platform` | STM32 HAL UART rings, timing, GPIO and diagnostic printing |
| `Core/Inc/config` | Node IDs, sensors, timings, AES key, Wi-Fi, broker and MQTT topics |
| `Middlewares/Third_Party` | nanopb runtime and AES implementation used by the original protocol |

Protocol compatibility is intentional: packets remain `[version][16-byte IV][AES-128-CBC(PKCS#7(nanopb))]`, so the existing server can consume data without migration. The gateway publishes the encrypted binary body, not decoded sensor JSON, matching the current server contract.

## Configuration

Deployment values are centralized in `Core/Inc/config/AppConfig.hpp` and `Core/Src/config/AppConfig.cpp`. Before production flashing, review the Wi-Fi credentials, MQTT host/port, company/topic names, node IDs, sensor table, periods, AES key, ADC-divider values, and battery calibration factor.

## Verification

Both roles are compiled with the STM32CubeIDE ARM GNU toolchain for `STM32F401RCTx`. The host-side AES test in `Tests/aes_cbc_vector_test.cpp` checks the implementation against the NIST AES-128-CBC vector. Release verification artifacts are placed under `Build/SensorNode` and `Build/LoRaGateway`.
