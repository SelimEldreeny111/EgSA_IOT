# IoT Node Encrypted

25 October update: [separate power/WDT counters, clear commands and independent
SUPMEA simulator comparison](RESET_COUNTERS_AND_SUPMEA_REFERENCE_GUIDE.md).
Counter clears are direct-node commands 7/8 with data=0 and a nonzero request ID.

An IoT monitoring system with application-layer encrypted communication for industrial flow measurement and telemetry.
For the new PB9/PB15/PC13 TB6612FNG latching-valve control, safe commissioning,
ON/OFF telemetry, reset retention and tests, see the
[Latching Valve User Guide](LATCHING_VALVE_USER_GUIDE.md). Actuation defaults to
inhibited until supplier pulse durations and opening polarity are confirmed.
See the [Valve Verification Report](LATCHING_VALVE_VERIFICATION.md) for software
test results and the remaining physical acceptance checks.
This guide supersedes the earlier static-PC13 valve and RAM-state descriptions
in historical power-mode documentation; modem/controller power policies are unchanged.
The generated firmware API and architecture reference is described in
[Doxygen documentation](DOXYGEN_MAINPAGE.md).
For current radio configuration, role-specific UART wiring, unsupported RSSI
behavior and battery-voltage tests, see [Radio and Voltage Guide](RADIO_AND_VOLTAGE_GUIDE.md).

For independent sensor selection, protobuf fields, Supmea calendar consumption, RTC
setup, persistence, and commissioning, see [STM32 Four-Sensor RS485 and
Consumption Guide](FLOW_METER_PROFILES_AND_CONSUMPTION_GUIDE.md).

## Power mode selection

For the consolidated mode descriptions, all supported/rejected combinations,
configuration recipes, wake behavior and acceptance tests, see the
[Power Modes Reference](../../Documentation/PowerModes/WIOT_Power_Modes_Reference.md)
and its [printable PDF](../../Documentation/PowerModes/output/pdf/WIOT_Power_Modes_Reference.pdf).
This reference reflects the current 30-second watchdog and 10 + 10 network
recovery release without changing firmware settings.

Failed sensor replies now send zero readings with false validity flags rather
than previous readings. See [Unavailable Sensor Behavior and Tests](SENSOR_UNAVAILABLE_ZERO_GUIDE.md).

For server-command wake-up, select controller `APP_COMPONENT_MODE_REMOTE_WAKE`
and keep the selected radio `APP_COMPONENT_MODE_NORMAL`. This uses lighter CPU
Sleep, not Standby, and preserves MQTT/LoRa reception and watchdog coverage.
The server Commands tab provides **WAKE** (active seconds, 0=node default).
See [Remote Wake Configuration and Bench Tests](REMOTE_WAKE_USER_GUIDE.md).
REMOTE_WAKE now defaults to independent sampling/transmission deadlines, not
APP_POWER_SLEEP_SECONDS. See [schedule-driven remote idle](REMOTE_WAKE_APP_SCHEDULE_GUIDE.md)
for the true/false switch and separate SRATE/STRAN tests. Explicit WAKE still
requests an active lease; brief MQTT/tick/watchdog maintenance continues.

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

The additional opt-in **LORA_WOR_STOP** and **RTC_QUEUED** profiles, gateway
configuration, server command mailbox, and commissioning sequence are in
[Additional Power Modes User Guide](NEW_POWER_MODES_USER_GUIDE.md). The three
earlier profiles remain selectable.

See [STM32 Global Watchdog Recovery and Test Guide](WATCHDOG_RECOVERY_AND_TEST_GUIDE.md)
for the blocking-path timing audit, selected global deadline, reset-stage
diagnostics, controlled fault injection, and acceptance procedure.

See [Watchdog Reset Counter Guide](WDT_RESET_COUNTER_GUIDE.md) for the persistent
`wdt_reset_count` protobuf field, server display, storage limits and bench tests.

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
| STM32 modem RX | PA11 | Connect to SIM800/ESP8266 TX |
| STM32 modem TX | PA12 | Connect to SIM800/ESP8266 RX |

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
  → Receive commands / maintain MQTT → Send priority replies
  → Check sampling period → Read one enabled sensor per pass
  → Service commands in Modbus receive gaps (without feeding WDT)
  → Complete sensor cycle → Queue/send periodic Status
  → Advance power policy and verified watchdog checkpoints
```

## Functional Description

### Data Acquisition

- **Sampling**: Periodic flow parameter reading based on `samplingPeriodMs`
- **Data Types**: `TufSensorData`, `SupmeaSensorData`, `HndaSensorData`, and `SondasSensorData`
- **Metrics**: separate TUF/Supmea flow state, HNDA
  state via `updateHndaMetrics()`, and Sondas state via
  `updateSondasMetrics()`

### Sensor selection

Set each sensor independently to `true` or `false` in the four-switch block
of `src/config/AppConfig.h`:

```cpp
#define APP_ENABLE_TUF_SENSOR true
#define APP_ENABLE_HNDA_SENSOR true
#define APP_ENABLE_SUPMEA_SENSOR true
#define APP_ENABLE_SONDAS_SENSOR true
```

`true` initializes and polls that sensor. `false` sends no Modbus request to
it, excludes it from `active_sensor_count`, and clears its sensor-mask bit.
Set the four `APP_*_SENSOR_MODBUS_ADDRESS` macros to match the addresses
programmed in your meters. Defaults are TUF 1, Supmea 2, HNDA 3, Sondas 4.
The compiler rejects duplicate enabled-device addresses. At startup, the
serial monitor prints `ENABLED` or `DISABLED` for all four sensors so the
flashed configuration can be confirmed immediately.

The original flow protobuf fields report TUF when both flow meters are enabled
(or Supmea when it is the only flow meter). An optional second record reports
Supmea in the dual-meter case. HNDA and Sondas retain separate fields and
validity flags.

### Communication

The latest SIM800/ESP8266 path uses TinyGSM exclusively for AT transactions.
Queued command replies precede periodic Status; local write acceptance is
checked but does not confirm server delivery. See
[SIM MQTT Recovery and Priority Tests](SIM_MQTT_COMMAND_PRIORITY_FIX_GUIDE.md).

- **MQTT Protocol**: Connection management via `ensureMqttConnection()`;
  application payloads use the existing AES envelope, not authenticated TLS.
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
with a nominal 30-second global deadline. The watchdog is refreshed only at
verified progress boundaries. Therefore a stuck sensor, LoRa, MQTT, GSM,
Wi-Fi, or library call automatically resets the microcontroller even if the
main loop is no longer running.

Expected long operations report progress only between attempts. For example,
the 12-second LoRa ACK window is allowed to finish, but a single call that does
not return within 30 seconds cannot hide the fault by feeding the watchdog.
Ten failed GSM/Wi-Fi connection attempts pulse the active modem's RST pin.
Ten more failures pulse that modem's RST and request a fast IWDG controller
reset. Network success clears both stages. Broker-only failures do not count.

The serial boot log reports whether the previous boot was caused by the IWDG
and the last active subsystem stage. The behavior and controlled self-test can
be adjusted in `src/config/AppConfig.h`:

```cpp
#define APP_ENABLE_HARDWARE_WATCHDOG 1
#define APP_WATCHDOG_TIMEOUT_US 30000000UL
#define APP_NETWORK_RETRIES_PER_STAGE 10U
#define APP_WATCHDOG_SELF_TEST_MODE APP_WATCHDOG_SELF_TEST_DISABLED
```

The STM32duino `IWatchdog` library expects microseconds. Keep the configured
timeout within the supported IWDG range for the selected STM32 board. When
debugging with breakpoints, remember that the production watchdog continues
running and resets the board if execution remains paused past its deadline.
The complete timing rationale and test procedure are in
`WATCHDOG_RECOVERY_AND_TEST_GUIDE.md`. For reset-pin wiring, retry counting and
independent bench tests, see [Network Recovery Guide](NETWORK_RECOVERY_USER_GUIDE.md).

## Supmea SUP-FMC240 production integration

The Supmea driver reads the FMC240 cumulative and live register blocks at the
configured slave address. Live volumetric flow is normalized to m3/h. Day, month, and year
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

## Regional MQTT topics (26 October 2026)

The active STM32/web release uses `wiot/{company}/{region}/{node}/data|status|cmd` and `wiot/{company}/{region}/broadcast`. See [configuration, migration and tests](REGIONAL_MQTT_TOPICS_GUIDE.md).
