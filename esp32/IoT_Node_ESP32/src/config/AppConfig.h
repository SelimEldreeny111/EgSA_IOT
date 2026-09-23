#ifndef APP_CONFIG_H
#define APP_CONFIG_H

#include <stddef.h>
#include <stdint.h>
#include <Arduino.h>

#if !defined(ARDUINO_ARCH_ESP32) || !defined(CONFIG_IDF_TARGET_ESP32)
#error "IoT_Node_ESP32 targets the classic ESP32-WROOM 38-pin board only"
#endif

/**************** POWER CONFIGURATION - START HERE ****************/
// Each device has an explicit policy. NORMAL is the safe factory default.
// POWER_DOWN means that the device participates in the scheduled low-power
// cycle. The compile-time checks below reject combinations that the selected
// role, transport, or present PCB cannot wake safely.
// Only the active transport is controlled; an unselected module must be
// removed, disabled, or power-gated by hardware if it is physically fitted.
#define APP_COMPONENT_MODE_NORMAL 0
#define APP_COMPONENT_MODE_POWER_DOWN 1

#ifndef APP_CONTROLLER_POWER_MODE
#define APP_CONTROLLER_POWER_MODE APP_COMPONENT_MODE_NORMAL
#endif
#ifndef APP_LORA_POWER_MODE
#define APP_LORA_POWER_MODE APP_COMPONENT_MODE_NORMAL
#endif
#ifndef APP_WIFI_POWER_MODE
#define APP_WIFI_POWER_MODE APP_COMPONENT_MODE_NORMAL
#endif
#ifndef APP_SIM_POWER_MODE
#define APP_SIM_POWER_MODE APP_COMPONENT_MODE_NORMAL
#endif

// In controller POWER_DOWN mode, a sensor node samples and sends once, keeps
// this command window open, prepares its selected radio, and enters ESP32
// deep sleep until the RTC timer wakes it. See ESP32_USER_GUIDE.md before use.

// Periodic-mode timing. The first commissioning test should override the sleep
// interval to 30 seconds; use 300 seconds (5 minutes) for normal operation.
#ifndef APP_POWER_SLEEP_SECONDS
#define APP_POWER_SLEEP_SECONDS 300UL
#endif
#ifndef APP_POWER_COMMAND_WINDOW_MS
#define APP_POWER_COMMAND_WINDOW_MS 5000UL
#endif
#ifndef APP_POWER_SLEEP_ENTRY_TIMEOUT_MS
#define APP_POWER_SLEEP_ENTRY_TIMEOUT_MS 1000UL
#endif
/*********************************************************/

/**************** EXTERNAL IP MODEM SELECT ****************/
#define APP_IP_MODEM_SIM800 1
#define APP_IP_MODEM_ESP8266 2

#ifndef APP_IP_MODEM
#define APP_IP_MODEM APP_IP_MODEM_ESP8266
#endif

#if APP_IP_MODEM == APP_IP_MODEM_SIM800
#define USE_SIM800
#elif APP_IP_MODEM == APP_IP_MODEM_ESP8266
#define USE_ESP8266
#else
#error "APP_IP_MODEM must be APP_IP_MODEM_SIM800 or APP_IP_MODEM_ESP8266"
#endif
/**********************************************************/

/**************** APPLICATION ROLE + ROUTING ****************/
#define APP_ROLE_SENSOR_NODE 1
#define APP_ROLE_LORA_GATEWAY 2

#define APP_UPLINK_MQTT_DIRECT 1
#define APP_UPLINK_LORA_TO_GATEWAY 2

// Sensor-node firmware:
//   APP_ROLE_SENSOR_NODE + APP_UPLINK_MQTT_DIRECT       -> current behavior
//   APP_ROLE_SENSOR_NODE + APP_UPLINK_LORA_TO_GATEWAY   -> send encrypted telemetry by AS32 LoRa
//
// Gateway firmware:
//   APP_ROLE_LORA_GATEWAY -> receive AS32 LoRa telemetry and publish it to MQTT
#ifndef APP_ROLE
#define APP_ROLE APP_ROLE_SENSOR_NODE
#endif

#ifndef APP_UPLINK
#define APP_UPLINK APP_UPLINK_LORA_TO_GATEWAY
#endif

#if APP_UPLINK != APP_UPLINK_MQTT_DIRECT && \
    APP_UPLINK != APP_UPLINK_LORA_TO_GATEWAY
#error "APP_UPLINK must be APP_UPLINK_MQTT_DIRECT or APP_UPLINK_LORA_TO_GATEWAY"
#endif

#if APP_ROLE == APP_ROLE_LORA_GATEWAY
#define APP_HAS_SENSORS 0
#define APP_HAS_IP_UPLINK 1
#define APP_HAS_LORA 1
#elif APP_ROLE == APP_ROLE_SENSOR_NODE
#define APP_HAS_SENSORS 1
#if APP_UPLINK == APP_UPLINK_LORA_TO_GATEWAY
#define APP_HAS_IP_UPLINK 0
#define APP_HAS_LORA 1
#else
#define APP_HAS_IP_UPLINK 1
#define APP_HAS_LORA 0
#endif
#else
#error "APP_ROLE must be APP_ROLE_SENSOR_NODE or APP_ROLE_LORA_GATEWAY"
#endif

#if (APP_CONTROLLER_POWER_MODE != APP_COMPONENT_MODE_NORMAL && \
     APP_CONTROLLER_POWER_MODE != APP_COMPONENT_MODE_POWER_DOWN) || \
    (APP_LORA_POWER_MODE != APP_COMPONENT_MODE_NORMAL && \
     APP_LORA_POWER_MODE != APP_COMPONENT_MODE_POWER_DOWN) || \
    (APP_WIFI_POWER_MODE != APP_COMPONENT_MODE_NORMAL && \
     APP_WIFI_POWER_MODE != APP_COMPONENT_MODE_POWER_DOWN) || \
    (APP_SIM_POWER_MODE != APP_COMPONENT_MODE_NORMAL && \
     APP_SIM_POWER_MODE != APP_COMPONENT_MODE_POWER_DOWN)
#error "Every APP_*_POWER_MODE must be APP_COMPONENT_MODE_NORMAL or APP_COMPONENT_MODE_POWER_DOWN"
#endif

#if APP_CONTROLLER_POWER_MODE == APP_COMPONENT_MODE_POWER_DOWN && \
    APP_ROLE == APP_ROLE_LORA_GATEWAY
#error "A gateway must remain reachable; controller Standby is supported only on a sensor node"
#endif

#if APP_HAS_LORA && \
    APP_CONTROLLER_POWER_MODE != APP_LORA_POWER_MODE
#error "The active LoRa transport and controller must both be NORMAL or both be POWER_DOWN"
#endif

#if APP_HAS_IP_UPLINK && defined(USE_ESP8266) && \
    APP_CONTROLLER_POWER_MODE != APP_WIFI_POWER_MODE
#error "The active ESP8266 transport and controller must both be NORMAL or both be POWER_DOWN"
#endif

#if APP_HAS_IP_UPLINK && defined(USE_SIM800) && \
    (APP_CONTROLLER_POWER_MODE == APP_COMPONENT_MODE_POWER_DOWN || \
     APP_SIM_POWER_MODE == APP_COMPONENT_MODE_POWER_DOWN)
#error "SIM800L periodic POWER_DOWN is unsafe on this PCB: route MCU-controlled PWRKEY (and preferably DTR/RI) before enabling it; GSM_RST alone cannot power the modem back on"
#endif

#if APP_POWER_SLEEP_SECONDS < 5UL || APP_POWER_SLEEP_SECONDS > 604800UL
#error "APP_POWER_SLEEP_SECONDS must be between 5 seconds and 7 days"
#endif

#if APP_POWER_COMMAND_WINDOW_MS > 60000UL
#error "APP_POWER_COMMAND_WINDOW_MS must not exceed 60000 milliseconds"
#endif

#if APP_POWER_SLEEP_ENTRY_TIMEOUT_MS < 100UL || \
    APP_POWER_SLEEP_ENTRY_TIMEOUT_MS > 5000UL
#error "APP_POWER_SLEEP_ENTRY_TIMEOUT_MS must be between 100 and 5000 milliseconds"
#endif
/*************************************************************/

#if defined(USE_SIM800)
#define TINY_GSM_MODEM_SIM800
#define TINY_GSM_USE_GPRS true
#elif defined(USE_ESP8266)
#define TINY_GSM_MODEM_ESP8266
#else
#error "No modem selected!"
#endif

#if defined(USE_SIM800)
#define MODEM_BAUD 9600
#elif defined(USE_ESP8266)
#define MODEM_BAUD    115200 //115200
#endif

#define TINY_GSM_RX_BUFFER 1024
#define MQTT_MAX_PACKET_SIZE 256

namespace AppConfig 
{
constexpr bool kPowerDownEnabled =
    APP_CONTROLLER_POWER_MODE == APP_COMPONENT_MODE_POWER_DOWN;
constexpr bool kControllerPowerDown =
    APP_CONTROLLER_POWER_MODE == APP_COMPONENT_MODE_POWER_DOWN;
constexpr bool kLoraPowerDown =
    APP_LORA_POWER_MODE == APP_COMPONENT_MODE_POWER_DOWN;
constexpr bool kWifiPowerDown =
    APP_WIFI_POWER_MODE == APP_COMPONENT_MODE_POWER_DOWN;
constexpr bool kSimPowerDown =
    APP_SIM_POWER_MODE == APP_COMPONENT_MODE_POWER_DOWN;
constexpr uint32_t kPowerSleepSeconds = APP_POWER_SLEEP_SECONDS;
constexpr uint32_t kPowerCommandWindowMs = APP_POWER_COMMAND_WINDOW_MS;
constexpr uint32_t kPowerSleepEntryTimeoutMs =
    APP_POWER_SLEEP_ENTRY_TIMEOUT_MS;
constexpr uint32_t kPowerMinimumValidRtcEpoch = 1704067200UL;
constexpr uint32_t kPowerMaximumSleepSeconds = 604800UL;

#ifndef APP_NODE_ID
#define APP_NODE_ID 3
#endif

#ifndef APP_SENSOR_ID
#define APP_SENSOR_ID 1
#endif

constexpr uint16_t kNodeId = APP_NODE_ID;
constexpr uint16_t kGatewayNodeId = 0;
constexpr uint16_t kSensorId = APP_SENSOR_ID;

constexpr uint16_t kLoraNetworkId = 0x4547; // "EG"
// Safe classic ESP32-WROOM GPIO assignment for the supplied 38-pin board.
// GPIO6..GPIO11 are connected to module flash and must never be used.
// GPIO0, GPIO2, GPIO5, GPIO12, and GPIO15 are deliberately avoided here
// because attached hardware can disturb the ESP32 boot strapping levels.
constexpr int8_t kDebugRxPin = 3;   // UART0 RX0 / USB bridge TX
constexpr int8_t kDebugTxPin = 1;   // UART0 TX0 / USB bridge RX
constexpr int8_t kModemRxPin = 32;  // UART1 RX <- ESP8266/SIM800 TX
constexpr int8_t kModemTxPin = 33;  // UART1 TX -> ESP8266/SIM800 RX
constexpr int8_t kLoraRxPin = 16;   // UART2 RX <- E32/AS32 TXD
constexpr int8_t kLoraTxPin = 17;   // UART2 TX -> E32/AS32 RXD

// UART1 is free for sensors in a LoRa-only node. In direct-MQTT nodes UART1
// belongs to the modem and the sensor bus moves to UART2. A gateway has no
// local sensors, so its UART2 is exclusively the LoRa receiver.
#if APP_HAS_IP_UPLINK
constexpr int8_t kRs485RxPin = 16;  // UART2 RX <- MAX485 RO
constexpr int8_t kRs485TxPin = 17;  // UART2 TX -> MAX485 DI
#else
constexpr int8_t kRs485RxPin = 32;  // UART1 RX <- MAX485 RO
constexpr int8_t kRs485TxPin = 33;  // UART1 TX -> MAX485 DI
#endif

constexpr uint32_t kLoraMd0Pin = 25;
constexpr uint32_t kLoraMd1Pin = 26;
constexpr uint32_t kLoraAuxPin = 27;

// External ESP8266/SIM800 control lines. GPIO13/GPIO14 are retained through
// controller deep sleep by PowerManager when the ESP8266 transport is active.
constexpr uint32_t kEspEnablePin = 13;
constexpr uint32_t kEspResetPin = 14;
constexpr bool kEspEnableActiveHigh = true;
constexpr bool kEspResetActiveLow = true;
constexpr uint32_t kEspResetPulseMs = 100UL;
constexpr uint32_t kEspBootDelayMs = 3000UL;
constexpr uint32_t kSimResetPin = 19;

constexpr size_t kSerialRxBufferSize = 512U;
constexpr size_t kSerialTxBufferSize = 512U;

// RS485 sensor selection. These names match the four physical sensor folders:
// TUF, Supmea, HNDA, and Sondas. Supmea remains a commissioning-only reader,
// so it is intentionally not added to AppState or the network schema yet.
constexpr bool kEnableTufSensor = false;
constexpr bool kEnableHndaSensor = true;
constexpr bool kEnableSondasSensor = false;

// Supmea SUP-FMC240 commissioning interface. This is deliberately a serial-
// monitor-only test path: its values are not added to AppState, protobuf, or
// the server schema. Address 4 avoids the existing RS485 addresses 1-3.
// Change the meter's menu address to match, or override the value at build
// time with -DAPP_SUPMEA_SENSOR_MODBUS_ADDRESS=<address>.
#ifndef APP_ENABLE_SUPMEA_SENSOR_TEST
#define APP_ENABLE_SUPMEA_SENSOR_TEST 1
#endif
#ifndef APP_SUPMEA_SENSOR_MODBUS_ADDRESS
#define APP_SUPMEA_SENSOR_MODBUS_ADDRESS 4
#endif
constexpr bool kEnableSupmeaSensorTest =
    APP_HAS_SENSORS && (APP_ENABLE_SUPMEA_SENSOR_TEST != 0);
constexpr uint8_t kSupmeaSensorModbusAddress =
    APP_SUPMEA_SENSOR_MODBUS_ADDRESS;

constexpr uint16_t kSensorMaskTuf = 0x0001;
constexpr uint16_t kSensorMaskHnda = 0x0002;
constexpr uint16_t kSensorMaskSondas = 0x0004;

constexpr uint32_t kRs485BaudRate = 9600UL;
constexpr uint32_t kRs485TxEnablePin = 4;
constexpr uint8_t kTufModbusAddress = 0x02;

// Measured hardware: battery+ -- 21.6 kOhm -- GPIO36 -- 9.8 kOhm -- GND, with
// a 100 nF capacitor from GPIO36 to GND. At 8.4 V, the ADC pin is about 2.622 V.
// The theoretical input limit is approximately 10.57 V at the 3.3 V ADC
// limit. Values below are the measured resistances, not their nominal markings.
// theoretical input limit is approximately 10.35 V at the 3.3 V ADC limit.
// Never connect the battery directly to GPIO36; battery- and ESP32 GND must be
// connected together.
// Override these APP_BATTERY_* definitions at build time if the production
// PCB uses a different ADC pin, divider, reference, or calibration factor.
#ifndef APP_ENABLE_BATTERY_MONITOR
#define APP_ENABLE_BATTERY_MONITOR 1
#endif
#ifndef APP_BATTERY_ADC_PIN
#define APP_BATTERY_ADC_PIN 36
#endif
#ifndef APP_BATTERY_DIVIDER_HIGH_OHMS
#define APP_BATTERY_DIVIDER_HIGH_OHMS 21600.0f
#endif
#ifndef APP_BATTERY_DIVIDER_LOW_OHMS
#define APP_BATTERY_DIVIDER_LOW_OHMS 9800.0f
#endif
#ifndef APP_BATTERY_CALIBRATION_FACTOR
#define APP_BATTERY_CALIBRATION_FACTOR 1.0f
#endif

constexpr bool kEnableBatteryMonitor =
    APP_HAS_SENSORS && (APP_ENABLE_BATTERY_MONITOR != 0);
constexpr uint32_t kBatteryAdcPin = APP_BATTERY_ADC_PIN;
constexpr uint8_t kBatteryAdcResolutionBits = 12U;
constexpr uint8_t kBatterySampleCount = 16U;
constexpr float kBatteryDividerHighOhms = APP_BATTERY_DIVIDER_HIGH_OHMS;
constexpr float kBatteryDividerLowOhms = APP_BATTERY_DIVIDER_LOW_OHMS;
constexpr float kBatteryCalibrationFactor = APP_BATTERY_CALIBRATION_FACTOR;

// HNDA (Honde RD-SMT-P-O) Modbus map from the supplied PDF:
// 0x0000 = signed soil temperature * 10, 0x0001 = soil moisture * 10.
// The factory default slave address is 0x01; use a unique address when the
// flow meter is on the same RS485 bus.
constexpr uint8_t kHndaModbusAddress = 0x01;
constexpr uint16_t kHndaTemperatureRegister = 0x0000;
constexpr uint16_t kHndaMoistureRegister = 0x0001;
constexpr float kHndaRegisterScale = 10.0f;

// The supplied Sondas HP/Nutricontrol document identifies the EC-capable sensor
// family but does not provide a Modbus register table. Keep this common
// contiguous Modbus layout configurable here so it can be aligned with the
// exact purchased probe without changing application code.
constexpr uint8_t kSondasModbusAddress = 0x03;
constexpr uint16_t kSondasTemperatureRegister = 0x0000;
constexpr uint16_t kSondasMoistureRegister = 0x0001;
constexpr uint16_t kSondasElectricalConductivityRegister = 0x0002;
constexpr float kSondasTemperatureScale = 10.0f;
constexpr float kSondasMoistureScale = 10.0f;
constexpr float kSondasElectricalConductivityScale = 1.0f;

constexpr uint32_t kOpenCloseNodeGpio = 18;
constexpr bool kOpenCloseNodeActiveLow = true;
constexpr bool kOpenCloseNodeGpioConflictsWithLora = false;
constexpr bool kEnableOpenCloseNodeOutput = !kOpenCloseNodeGpioConflictsWithLora;

constexpr size_t kAesBlockSize = 16;
constexpr size_t kIvLength = 16;
constexpr size_t kCodecBufferSize = 256;
constexpr uint8_t kProtocolVersion = 1;

constexpr uint32_t kDefaultSamplingPeriodMs = 10000UL;
constexpr uint32_t kDefaultTransmissionPeriodMs = 15000UL;

constexpr uint32_t kDefaultRtcEpoch = 1704067200UL;
constexpr uint16_t kMqttPort = 1883;
constexpr uint16_t kMqttKeepAliveSeconds = 45;
constexpr uint16_t kMqttSocketTimeoutSeconds = 8;
constexpr uint32_t kMqttReconnectIntervalMs = 3000UL;

constexpr uint32_t kMinimumRateSeconds = 10UL;
constexpr bool kEnableWifiCredentialStore = true;
constexpr bool kEnableGatewayHeartbeatLogs = true;
constexpr bool kEnableVerboseMqttLogs = true;//false  or  true 
constexpr bool kEnablePublishTimingLogs = true;//false  or  true 

// ESP32 Task Watchdog Timer. A healthy Arduino loop task feeds it only after
// bounded operations return; a function that blocks for more than 25 seconds
// is reset by the ESP32 watchdog. Network recovery is also forced after two
// complete failed connection cycles.
#ifndef APP_ENABLE_HARDWARE_WATCHDOG
#define APP_ENABLE_HARDWARE_WATCHDOG 1
#endif
#ifndef APP_WATCHDOG_TIMEOUT_MS
#define APP_WATCHDOG_TIMEOUT_MS 25000UL
#endif
#ifndef APP_NETWORK_FAILURES_BEFORE_RESET
#define APP_NETWORK_FAILURES_BEFORE_RESET 2U
#endif
constexpr bool kEnableHardwareWatchdog =
    APP_ENABLE_HARDWARE_WATCHDOG != 0;
constexpr uint32_t kWatchdogTimeoutMs = APP_WATCHDOG_TIMEOUT_MS;
constexpr uint32_t kWatchdogForcedResetTimeoutMs = 250UL;
constexpr uint8_t kNetworkFailuresBeforeReset =
    APP_NETWORK_FAILURES_BEFORE_RESET;

// Keep these enabled during LoRa commissioning. Every transmitted/accepted
// application frame is printed in full, while rejected or incomplete streams
// get their own dump so the two ends can be compared byte-for-byte.
constexpr bool kEnableLoraFrameHexLogs = true;
constexpr bool kEnableLoraErrorHexLogs = true;
// The installed E32-TTL-100 does not expose RSSI over its UART interface
// (datasheet electrical-parameter table: "RSSI - No support"). The
// 0xAF/0x73 and 0xAF/0x74 diagnostic commands below belong to a different
// AS32-TTL-1W V3 firmware family and must not be sent to an E32-TTL-100.
// Override this only when the fitted radio is explicitly documented to
// support those AS32 V3 commands.
#ifndef APP_LORA_MODULE_SUPPORTS_AS32_V3_RSSI
#define APP_LORA_MODULE_SUPPORTS_AS32_V3_RSSI 0
#endif
constexpr bool kLoraModuleSupportsRssi =
    APP_LORA_MODULE_SUPPORTS_AS32_V3_RSSI != 0;
constexpr bool kEnableAs32RssiDiagnostics = kLoraModuleSupportsRssi;
constexpr uint32_t kLoraDiagnosticsPeriodMs = 5000UL;

// The tested AS32 path has a 63-byte transport boundary. Every physical wire
// frame is therefore independently framed and kept at or below 48 bytes.
// Larger logical messages are fragmented and reassembled by message ID.
constexpr size_t kLoraMaxWireFrameBytes = 48U;
constexpr uint32_t kLoraAuxBusyDetectTimeoutMs = 200UL;
constexpr uint32_t kLoraInterPacketGuardMs = 500UL;
constexpr uint32_t kLoraFinalPacketGuardMs = 200UL;

// The gateway acknowledges every node fragment. A lost fragment or ACK is
// retransmitted without combining bytes from different logical messages.
// ESP-AT/MQTT calls can occupy the gateway for up to the configured eight-
// second socket timeout. The first fragment therefore waits long enough for
// the gateway to return to the radio service before attempting a retry.
constexpr uint32_t kLoraFragmentAckTimeoutMs = 12000UL;
constexpr uint8_t kLoraFragmentMaxAttempts = 3U;
constexpr uint32_t kLoraFragmentRetryBackoffMs = 250UL;
constexpr uint32_t kLoraPostAckGuardMs = 500UL;

// Stream timeout applies to one physical frame. Fragment timeout applies to
// the complete logical message and supports interleaved multi-node traffic.
constexpr uint32_t kLoraRxAssemblyTimeoutMs = 4000UL;
constexpr uint32_t kLoraTransactionPriorityMs = 15000UL;
constexpr uint32_t kLoraFragmentAssemblyTimeoutMs = 60000UL;
constexpr size_t kLoraReassemblyContextCount = 8U;
constexpr size_t kLoraPendingFrameCount = 4U;
constexpr uint32_t kLoraUartWriteTimeoutMs = 3000UL;
constexpr uint32_t kLoraTxCompleteTimeoutMs = 10000UL;
}

#if defined(USE_SIM800)
extern const char kApn[];
extern const char kNetworkUser[];
extern const char kNetworkPassword[];
#elif defined(USE_ESP8266)
extern const char kWifiSsid[];
extern const char kWifiPassword[];
#endif

extern const char kMqttServer[];
extern const char kMqttClientId[];
extern const char kMqttPublishTopicStatus[];
extern const char kMqttPublishTopicTlm[];
extern const char kMqttCommandTopic[];
extern const char kMqttBroadcastTopic[];
extern const char kMqttCompanyTopicPrefix[];
extern const char kMqttGatewayCommandWildcardTopic[];

#endif
