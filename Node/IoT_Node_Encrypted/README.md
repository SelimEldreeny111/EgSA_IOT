# IoT Node Encrypted

> RSSI diagnostics, battery-divider wiring, protobuf field numbers, and web
> migration details are documented in
> `../Documentation/AS32_RSSI_AND_BATTERY_TELEMETRY.md`.

A secure IoT monitoring system with encrypted communication capabilities for industrial flow measurement and telemetry.
For the restored AS32 private-LoRa V1 build, module settings, reflashing sequence, diagnostics, and Wi-Fi flash-persistence test, see [AS32 Private-LoRa V1 Recovery and Acceptance Test](../Documentation/AS32_V1_RECOVERY_TEST.md).

For product selection, protobuf fields, Supmea calendar consumption, RTC
setup, persistence, and commissioning, see [STM32 Flow-Meter Profiles and
Consumption Guide](FLOW_METER_PROFILES_AND_CONSUMPTION_GUIDE.md).

## Power mode selection

The Arduino firmware has a separate, safe policy for each main device at the
beginning of `src/config/AppConfig.h`:

```cpp
#define APP_CONTROLLER_POWER_MODE APP_COMPONENT_MODE_NORMAL
#define APP_LORA_POWER_MODE       APP_COMPONENT_MODE_NORMAL
#define APP_WIFI_POWER_MODE       APP_COMPONENT_MODE_NORMAL
#define APP_SIM_POWER_MODE        APP_COMPONENT_MODE_NORMAL
```

Keep all four values NORMAL for the existing continuously awake behavior.
Periodic RTC Standby is supported for LoRa sensor nodes and direct ESP8266
sensor nodes when both the controller and their active radio are POWER_DOWN.
The compiler rejects unsafe pairings, gateway Standby, and SIM800L power-down
on the present schematic because SIM800L PWRKEY/DTR/RI are not routed to the
STM32.

See [Arduino Node Power-Down Configuration and Test Guide](POWER_DOWN_MODE_USER_GUIDE.md)
for ready-to-use profiles, schematic pin mapping, required M0/M1 and RS485
hardware pulls, ESP reset behavior, expected logs, and the complete test plan.

## Overview

This project implements an IoT node that reads the TUF, Supmea, HNDA, and
Sondas RS485 sensors and transmits encrypted telemetry over LoRa or MQTT.

## Hardware Components

- **Microcontroller**: STM32F401RCT6 using the Arduino STM32 core
- **TUF sensor**: TUF-2000 series ultrasonic flow meter
- **Supmea sensor**: SUP-FMC240 electromagnetic flow meter
- **HNDA sensor**: RD-SMT-P-O soil moisture and temperature probe
- **Sondas sensor**: soil moisture, temperature, and EC probe
- **Communication modules**: E32/AS32 LoRa, ESP8266 Wi-Fi, or SIM800L GSM
- **Debug interface**: hardware serial monitor via PA3/PA2

## Pin Configuration

| Function | Pin | Purpose |
|----------|-----|----------|
| Debug TX | PA2 | Serial debug output |
| Debug RX | PA3 | Serial debug input |
| SIM800 TX | PA11 | Cellular modem receive |
| SIM800 RX | PA12 | Cellular modem transmit |

## Architecture

### Core Components

1. **IoT_Node.h**: Main application framework and state management
2. **TufSensor.h**: TUF flow-meter driver and data acquisition
3. **SupmeaSensor.h**: Supmea FMC240 production Modbus driver
4. **HndaSensor.h**: HNDA moisture/temperature driver
5. **SondasSensor.h**: Sondas moisture/temperature/EC driver
6. **State Management**: Runtime state tracking with sampling and transmission periods

### System Flow

```
Setup Phase:
  → Initialize hardware serial interfaces
  → Configure IoT node state
  → Establish MQTT connection

Main Loop:
  → Check sampling period → Read sensor data → Process flow metrics
  → Check transmission period → Publish telemetry data
  → Maintain MQTT connection
```

## Functional Description

### Data Acquisition

- **Sampling**: Periodic flow parameter reading based on `samplingPeriodMs`
- **Data Types**: `TufSensorData`, `SupmeaSensorData`, `HndaSensorData`, and `SondasSensorData`
- **Metrics**: common TUF/Supmea flow state via `updateFlowMetrics()`, HNDA
  state via `updateHndaMetrics()`, and Sondas state via
  `updateSondasMetrics()`

### Sensor selection

First select the product family in `src/config/AppConfig.h`:

```cpp
#define APP_SENSOR_PROJECT APP_SENSOR_PROJECT_SUPMEA_SONDAS
```

The alternatives are `APP_SENSOR_PROJECT_TUF_HNDA` and
`APP_SENSOR_PROJECT_SUPMEA_SONDAS`. Then set each sensor in the selected
profile independently to `true` or `false` in the **INDIVIDUAL SENSOR
SWITCHES** block:

```cpp
#define APP_ENABLE_TUF_SENSOR true
#define APP_ENABLE_HNDA_SENSOR true
#define APP_ENABLE_SUPMEA_SENSOR false
#define APP_ENABLE_SONDAS_SENSOR false
```

`true` initializes and polls that sensor. `false` sends no Modbus request to
it, excludes it from `active_sensor_count`, and clears its sensor-mask bit.
The non-selected product family's switches must remain `false`; the compiler
rejects mixed products. The Supmea + Sondas image uses addresses 1 and 3. The
default TUF + HNDA image uses addresses 2 and 1. The compiler also rejects
invalid profiles and duplicate enabled-device addresses. At startup, the
serial monitor prints `ENABLED` or `DISABLED` for all four sensors so the
flashed configuration can be confirmed immediately.

Both profiles use the common flow protobuf block. The original HNDA and Sondas
fields remain present, with separate validity flags for their latest reads.

### Communication

- **MQTT Protocol**: Secure message transmission via `ensureMqttConnection()`
- **Telemetry**: Periodic data publishing via `publishTelemetry()`
- **Debug Interface**: Real-time monitoring through hardware serial

### Wi-Fi credential priority

For ESP8266 builds, the node always tries the SSID and password compiled in
`src/config/AppConfig.cpp` first. If that network is unavailable, it tries the
fallback credentials retained in STM32 EEPROM/flash. If both fail, the serial
monitor offers one operator-provisioning attempt for that boot; credentials
entered there are saved only after a successful connection.

A successful connection to the firmware-configured Wi-Fi does not overwrite
the saved fallback. If the two credential sets are identical, the duplicate
fallback attempt is skipped. Therefore changing `kWifiSsid` or
`kWifiPassword`, recompiling, and flashing is enough to make the new firmware
network the primary choice while retaining the old stored network as backup.

Expected boot-log order:

```text
WiFi priority: configured firmware -> saved flash fallback -> operator fallback.
Connecting to configured firmware WiFi SSID: ...
```

### State Management

The system maintains runtime state including:
- Last sensor read timestamp
- Last transmission timestamp
- Sampling period configuration
- Transmission period configuration

## Usage

### Setup

1. Connect TUF2000B sensor to designated analog/digital pins
2. Connect SIM800 modem to hardware serial interface (PA11/PA12)
3. Configure MQTT broker settings in IoT_Node.h
4. Set sampling and transmission periods according to requirements

### Configuration

Modify the following parameters in your application configuration:

```cpp
// Timing intervals (milliseconds)
state.samplingPeriodMs = 1000;      // Sensor sampling rate
state.transmissionPeriodMs = 5000;  // Data transmission rate

// MQTT configuration (in IoT_Node.h)
mqtt_server = "your.mqtt.broker";
mqtt_port = 1883;
mqtt_topic = "iot/telemetry";
```

### Monitoring

Use the debug serial interface (SerialMon) to monitor system status:
- Sensor readings
- Connection status
- Transmission confirmations
- Error messages

## Dependencies

- Arduino core framework
- HardwareSerial library (built-in)
- MQTT client library
- TUF2000B sensor driver

## Security Features

- Encrypted communication support via MQTT TLS/SSL
- Hardware serial isolation for debug and cellular modem
- Secure state management with timestamp validation

## Troubleshooting

### Connection Issues
- Verify SIM800 modem power and antenna connection
- Check serial communication (PA11/PA12)
- Validate MQTT broker credentials and network connectivity

### Data Reading Problems
- Confirm TUF2000B sensor connections
- Check sampling period configuration
- Monitor debug serial output for error messages

### Telemetry Not Publishing
- Verify MQTT connection status
- Check transmission period settings
- Ensure cellular network coverage

## Hardware Watchdog Recovery

The Arduino firmware uses the STM32F401 independent hardware watchdog (IWDG),
not a software timer. It is armed before application, LoRa, and modem setup
with a 25-second deadline. The watchdog is refreshed only after a bounded
operation returns or a complete superloop checkpoint is reached. Therefore a
stuck sensor, LoRa, MQTT, GSM, Wi-Fi, or library call automatically resets the
microcontroller even if the main loop is no longer running.

Expected long operations report progress only between attempts. For example,
the 12-second LoRa ACK window is allowed to finish, but a single call that does
not return within 25 seconds cannot hide the fault by feeding the watchdog.
Two complete failed GSM/Wi-Fi recovery cycles request a fast IWDG reset so the
MCU and modem initialization sequence starts cleanly.

The serial boot log reports whether the previous boot was caused by the IWDG.
The behavior can be adjusted in `src/config/AppConfig.h`:

```cpp
#define APP_ENABLE_HARDWARE_WATCHDOG 1
#define APP_WATCHDOG_TIMEOUT_US 25000000UL
#define APP_NETWORK_FAILURES_BEFORE_RESET 2U
```

The STM32duino `IWatchdog` library expects microseconds. Keep the configured
timeout within the supported IWDG range for the selected STM32 board. When
debugging with breakpoints, remember that the production watchdog continues
running and resets the board if execution remains paused past its deadline.

## Supmea SUP-FMC240 production integration

The Supmea profile reads the FMC240 cumulative and live register blocks at
address 1. Live volumetric flow is normalized to m3/h. Day, month, and year
consumption is calculated from changes in the cumulative forward total using
the trusted STM32 RTC; instantaneous flow is not integrated for these totals.

The calculated state is checksummed in RTC backup registers and periodically
checkpointed to EEPROM. Appended protobuf fields carry meter identity, source,
validity, cumulative litres, quality, and alarms to the server. See the
flow-meter guide above for setup, first-baseline behavior, STIME, reset and
anomaly handling, and the complete test sequence. The matching PC simulator is
documented in `../../SENSORS/Supmea Flow meter/simulator/README.md`.

## License

This project is provided as-is for educational and commercial use.

## Version History

- **v1.0**: Initial release with basic MQTT telemetry functionality
- **v1.10**: Enhanced security features and state management
- **v1.11**: Optional RTC-scheduled LoRa sensor-node Standby mode with a watchdog-safe reset handoff
- **v1.12**: Per-device controller/LoRa/Wi-Fi/SIM power policies and RTC-scheduled ESP8266 sensor-node support
- **v1.12.1**: Final power review: active-module boot labels, exclusive modem selection, single-pass ESP TCP shutdown, and expanded commissioning documentation
- **v1.12.2**: Arduino sensor drivers and internal state renamed consistently to TUF, Supmea, HNDA, and Sondas without changing the telemetry wire schema
- **v1.13**: Added fixed TUF + HNDA and Supmea + Sondas profiles, common flow
  schema v2, persistent Supmea calendar consumption, and matching server
  support
