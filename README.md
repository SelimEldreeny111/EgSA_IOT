# EgSA WIOT

EgSA WIOT is an industrial IoT platform for flow and soil sensing. This
repository contains the production STM32 Arduino node, its native
STM32CubeIDE/HAL port, an independent ESP32 port, the Python server, sensor
simulators, documentation, and software requirement specifications.

## Repository layout

| Path | Purpose |
| --- | --- |
| `Node/IoT_Node_Encrypted` | Main STM32F401 Arduino firmware |
| `WIOT_STM32CubeIDE` | Native STM32CubeIDE/HAL firmware port |
| `esp32/IoT_Node_ESP32` | Independent ESP32 Arduino firmware port |
| `Server/WIOT-Server-Web v1.31 - Fixed Sensor Readings in Dashboard` | MQTT/web server and telemetry storage |
| `SENSORS` | Sensor manuals, individual simulators, and the multi-sensor RS485 lab |
| `Node SW Specs` and `outputs` | Requirements and test documentation |

The STM32 Arduino node supports TUF + HNDA and Supmea + Sondas product
profiles, SIM800L, ESP8266 and E32/AS32 LoRa communication, encrypted nanopb
telemetry, voltage measurement, watchdog recovery, and configurable power
modes. See the README inside each firmware directory for its build, pinout,
and commissioning details.

## First-time private configuration

Deployment credentials and AES keys are deliberately excluded from Git. The
working files already present on an existing development computer remain
untouched. On a fresh clone, create the private files from the supplied
templates:

1. Copy each firmware `AppConfig.cpp.example` file to `AppConfig.cpp` in the
   same directory, then enter the required network, broker, client and topic
   values.
2. Copy each `AppSecrets.example.h` or `AppSecrets.example.hpp` file to the
   matching `AppSecrets.h` or `AppSecrets.hpp`, then enter the common 16-byte
   AES key used by the node, gateway and server.
3. In the server directory, copy `node_config.example.json` to
   `node_config.json` and configure the node records without committing that
   file.
4. Copy `.env.example` to `.env`, set strong account/session secrets, and load
   those variables before starting the server.

Never commit the generated private files. The root `.gitignore` protects the
standard local locations, but every release should still be reviewed before
it is pushed.

## Build entry points

- STM32 Arduino: open `Node/IoT_Node_Encrypted/IoT_Node_Encrypted.ino` and use
  the STM32F4 board configuration documented by the node project.
- ESP32 Arduino: open `esp32/IoT_Node_ESP32/IoT_Node_ESP32.ino` and follow
  `esp32/IoT_Node_ESP32/ESP32_USER_GUIDE.md`.
- STM32CubeIDE: import `WIOT_STM32CubeIDE` as an existing project and select
  either the SensorNode or LoRaGateway build configuration.
- Server: create a Python virtual environment, install the appropriate
  `requirements_*.txt`, configure the environment, and start `server_web.py`.

## Test assets

The sensor simulator directories include their own usage instructions. The
`SENSORS/Multi Sensor RS485 Simulator` application emulates any mix of HNDA,
TUF, Supmea, and Sondas devices at unique addresses on one Modbus RTU bus. Use
the individual TUF and Supmea tools for focused register tests, and the fleet
simulator for multi-address, dynamic-value, timeout, CRC, and scale testing.
Hardware acceptance and power-mode test procedures are documented alongside
the STM32 node. The node's `WATCHDOG_RECOVERY_AND_TEST_GUIDE.md` contains the
global WDT timing audit, configuration, diagnostic stages, and fault-injection
acceptance tests.
