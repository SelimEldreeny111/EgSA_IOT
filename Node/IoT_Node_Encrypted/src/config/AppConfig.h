/**
 * @file AppConfig.h
 * @brief Compile-time role, transport, sensor, timing, pin, watchdog, and power policies.
 *
 * Select the role, transport and each sensor's enable/address before building.
 * Invalid role/transport/power combinations are rejected by compile-time checks.
 * Values in this file describe firmware policy; external modules that are not
 * selected may still require hardware power isolation.
 */
#ifndef APP_CONFIG_H
#define APP_CONFIG_H

#include <stddef.h>
#include <stdint.h>
#include <Arduino.h>

/**************** COMMAND REPLY CONFIGURATION ****************/
// true: action commands return success/rejection Telemetry ACKs.
// false: apply/validate commands silently; periodic Status is unchanged.
// GOSTM always replies: telemetry is its requested action, not an optional ACK.
// Without ACKs, the server cannot confirm execution (timeline may show unknown).
#ifndef APP_ENABLE_COMMAND_ACK_REPLIES
#define APP_ENABLE_COMMAND_ACK_REPLIES true
#endif
#if APP_ENABLE_COMMAND_ACK_REPLIES != 0 && APP_ENABLE_COMMAND_ACK_REPLIES != 1
#error "APP_ENABLE_COMMAND_ACK_REPLIES must be true or false"
#endif
static_assert(APP_ENABLE_COMMAND_ACK_REPLIES == true || APP_ENABLE_COMMAND_ACK_REPLIES == false,
    "APP_ENABLE_COMMAND_ACK_REPLIES must be true or false");
/*************************************************************/

/**************** POWER CONFIGURATION - START HERE ****************/
// Each device has an explicit policy. NORMAL is the safe factory default.
// POWER_DOWN means that the device participates in the scheduled low-power
// cycle. The compile-time checks below reject combinations that the selected
// role, transport, or present PCB cannot wake safely.
// Only the active transport is controlled; an unselected module must be
// removed, disabled, or power-gated by hardware if it is physically fitted.
#define APP_COMPONENT_MODE_NORMAL 0
#define APP_COMPONENT_MODE_POWER_DOWN 1
#define APP_COMPONENT_MODE_WAKE_ON_RADIO 2
#define APP_COMPONENT_MODE_LORA_WOR 3
#define APP_COMPONENT_MODE_QUEUED 4
// Controller-only mode: CPU Sleep while the selected radio stays NORMAL.
// This permits server WAKE commands; it is not RTC-only Standby/deep sleep.
#define APP_COMPONENT_MODE_REMOTE_WAKE 2

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
// this command window open, prepares its selected radio, and enters STM32
// Standby until the RTC alarm. See POWER_DOWN_MODE_USER_GUIDE.md before use.

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
#ifndef APP_QUEUED_COMMAND_WINDOW_MS
#define APP_QUEUED_COMMAND_WINDOW_MS 20000UL
#endif
// Stop mode retains RAM but the IWDG still runs. Wake on the RTC this often
// to check application progress and feed the watchdog in foreground code.
#ifndef APP_LORA_WOR_WATCHDOG_WAKE_SECONDS
#define APP_LORA_WOR_WATCHDOG_WAKE_SECONDS 8UL
#endif
#ifndef APP_LORA_WOR_COMMAND_WINDOW_MS
#define APP_LORA_WOR_COMMAND_WINDOW_MS 5000UL
#endif
// Set to 1 on a separately built LoRa gateway when its nodes use LORA_WOR.
// It sends a Mode-1 wake probe before forwarding each command.
#ifndef APP_LORA_GATEWAY_WOR_TX
#define APP_LORA_GATEWAY_WOR_TX 0
#endif

// REMOTE_WAKE: automatic measurement/report cycle while otherwise reachable.
// WAKE data is active seconds; 0 selects the configured default below.
#ifndef APP_REMOTE_WAKE_DEFAULT_SECONDS
#define APP_REMOTE_WAKE_DEFAULT_SECONDS 60UL
#endif
#ifndef APP_REMOTE_WAKE_POLL_INTERVAL_MS
#define APP_REMOTE_WAKE_POLL_INTERVAL_MS 100UL
#endif
/*********************************************************/

/**************** TRANSPORT SELECT ****************/
#if !defined(USE_SIM800) && !defined(USE_ESP8266)
#define USE_SIM800
//#define USE_ESP8266
#endif
/*************************************************/

#if defined(USE_SIM800) && defined(USE_ESP8266)
#error "Select only one IP modem: USE_SIM800 or USE_ESP8266, not both"
#elif !defined(USE_SIM800) && !defined(USE_ESP8266)
#error "Select one IP modem: USE_SIM800 or USE_ESP8266"
#endif

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
#define APP_UPLINK APP_UPLINK_MQTT_DIRECT
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
     APP_CONTROLLER_POWER_MODE != APP_COMPONENT_MODE_POWER_DOWN && \
     APP_CONTROLLER_POWER_MODE != APP_COMPONENT_MODE_REMOTE_WAKE && \
     APP_CONTROLLER_POWER_MODE != APP_COMPONENT_MODE_LORA_WOR && \
     APP_CONTROLLER_POWER_MODE != APP_COMPONENT_MODE_QUEUED) || \
    (APP_LORA_POWER_MODE != APP_COMPONENT_MODE_NORMAL && \
     APP_LORA_POWER_MODE != APP_COMPONENT_MODE_POWER_DOWN && \
     APP_LORA_POWER_MODE != APP_COMPONENT_MODE_WAKE_ON_RADIO) || \
    (APP_WIFI_POWER_MODE != APP_COMPONENT_MODE_NORMAL && \
     APP_WIFI_POWER_MODE != APP_COMPONENT_MODE_POWER_DOWN) || \
    (APP_SIM_POWER_MODE != APP_COMPONENT_MODE_NORMAL && \
     APP_SIM_POWER_MODE != APP_COMPONENT_MODE_POWER_DOWN)
#error "Invalid controller or radio power mode"
#endif

#define APP_CONTROLLER_USES_STANDBY \
    (APP_CONTROLLER_POWER_MODE == APP_COMPONENT_MODE_POWER_DOWN || \
     APP_CONTROLLER_POWER_MODE == APP_COMPONENT_MODE_QUEUED)

#if APP_CONTROLLER_POWER_MODE != APP_COMPONENT_MODE_NORMAL && \
    APP_ROLE == APP_ROLE_LORA_GATEWAY
#error "A gateway must remain NORMAL; low-power application cycles are supported only on a sensor node"
#endif

#if APP_HAS_LORA && APP_CONTROLLER_POWER_MODE == APP_COMPONENT_MODE_LORA_WOR && \
    APP_LORA_POWER_MODE != APP_COMPONENT_MODE_WAKE_ON_RADIO
#error "LORA_WOR requires APP_LORA_POWER_MODE=APP_COMPONENT_MODE_WAKE_ON_RADIO"
#endif

#if APP_HAS_LORA && APP_CONTROLLER_POWER_MODE != APP_COMPONENT_MODE_LORA_WOR && \
    APP_LORA_POWER_MODE == APP_COMPONENT_MODE_WAKE_ON_RADIO
#error "WAKE_ON_RADIO is supported only by the LORA_WOR controller profile"
#endif

#if APP_HAS_LORA && APP_CONTROLLER_POWER_MODE != APP_COMPONENT_MODE_REMOTE_WAKE && \
    APP_CONTROLLER_POWER_MODE != APP_COMPONENT_MODE_LORA_WOR && \
    ((APP_CONTROLLER_USES_STANDBY && APP_LORA_POWER_MODE != APP_COMPONENT_MODE_POWER_DOWN) || \
     (!APP_CONTROLLER_USES_STANDBY && APP_LORA_POWER_MODE != APP_COMPONENT_MODE_NORMAL))
#error "LoRa NORMAL/Standby profiles require the matching LoRa power policy"
#endif

#if APP_HAS_IP_UPLINK && defined(USE_ESP8266) && \
    APP_CONTROLLER_POWER_MODE != APP_COMPONENT_MODE_REMOTE_WAKE && \
    ((APP_CONTROLLER_USES_STANDBY && APP_WIFI_POWER_MODE != APP_COMPONENT_MODE_POWER_DOWN) || \
     (!APP_CONTROLLER_USES_STANDBY && APP_WIFI_POWER_MODE != APP_COMPONENT_MODE_NORMAL))
#error "ESP8266 NORMAL/Standby profiles require the matching ESP power policy"
#endif

#if APP_CONTROLLER_POWER_MODE == APP_COMPONENT_MODE_LORA_WOR && !APP_HAS_LORA
#error "LORA_WOR requires a LoRa sensor node; direct SIM/WiFi cannot wake this PCB"
#endif

#if APP_LORA_GATEWAY_WOR_TX && APP_ROLE != APP_ROLE_LORA_GATEWAY
#error "APP_LORA_GATEWAY_WOR_TX is only valid on a LoRa gateway build"
#endif

#if APP_CONTROLLER_POWER_MODE == APP_COMPONENT_MODE_REMOTE_WAKE && \
    ((APP_HAS_LORA && APP_LORA_POWER_MODE != APP_COMPONENT_MODE_NORMAL) || \
     (APP_HAS_IP_UPLINK && defined(USE_ESP8266) && APP_WIFI_POWER_MODE != APP_COMPONENT_MODE_NORMAL) || \
     (APP_HAS_IP_UPLINK && defined(USE_SIM800) && APP_SIM_POWER_MODE != APP_COMPONENT_MODE_NORMAL))
#error "REMOTE_WAKE requires the selected radio to remain NORMAL/connected; a deep-sleep radio cannot receive WAKE"
#endif

#if APP_HAS_IP_UPLINK && defined(USE_SIM800) && \
    (APP_CONTROLLER_USES_STANDBY || \
     APP_SIM_POWER_MODE == APP_COMPONENT_MODE_POWER_DOWN)
#error "SIM800L periodic POWER_DOWN is unsafe on this PCB: route MCU-controlled PWRKEY (and preferably DTR/RI) before enabling it; GSM_RST alone cannot power the modem back on"
#endif

#if APP_POWER_SLEEP_SECONDS < 5UL || APP_POWER_SLEEP_SECONDS > 604800UL
#error "APP_POWER_SLEEP_SECONDS must be between 5 seconds and 7 days"
#endif

#if APP_POWER_COMMAND_WINDOW_MS > 60000UL
#error "APP_POWER_COMMAND_WINDOW_MS must not exceed 60000 milliseconds"
#endif
#if APP_QUEUED_COMMAND_WINDOW_MS < 5000UL || APP_QUEUED_COMMAND_WINDOW_MS > 60000UL
#error "APP_QUEUED_COMMAND_WINDOW_MS must be 5000..60000 milliseconds"
#endif
#if APP_LORA_WOR_COMMAND_WINDOW_MS < 1000UL || APP_LORA_WOR_COMMAND_WINDOW_MS > 60000UL
#error "APP_LORA_WOR_COMMAND_WINDOW_MS must be 1000..60000 milliseconds"
#endif
#if APP_LORA_WOR_WATCHDOG_WAKE_SECONDS < 2UL || APP_LORA_WOR_WATCHDOG_WAKE_SECONDS > 15UL
#error "APP_LORA_WOR_WATCHDOG_WAKE_SECONDS must be 2..15 seconds"
#endif

#if APP_POWER_SLEEP_ENTRY_TIMEOUT_MS < 100UL || \
    APP_POWER_SLEEP_ENTRY_TIMEOUT_MS > 5000UL
#error "APP_POWER_SLEEP_ENTRY_TIMEOUT_MS must be between 100 and 5000 milliseconds"
#endif

#if APP_REMOTE_WAKE_DEFAULT_SECONDS < 1UL || APP_REMOTE_WAKE_DEFAULT_SECONDS > 86400UL
#error "APP_REMOTE_WAKE_DEFAULT_SECONDS must be between 1 and 86400 seconds"
#endif
#if APP_REMOTE_WAKE_POLL_INTERVAL_MS < 10UL || APP_REMOTE_WAKE_POLL_INTERVAL_MS > 1000UL
#error "APP_REMOTE_WAKE_POLL_INTERVAL_MS must be between 10 and 1000 milliseconds"
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
#define MQTT_MAX_PACKET_SIZE 512

namespace AppConfig 
{
constexpr bool kPowerDownEnabled =
    APP_CONTROLLER_POWER_MODE != APP_COMPONENT_MODE_NORMAL;
constexpr bool kRemoteWakeEnabled =
    APP_CONTROLLER_POWER_MODE == APP_COMPONENT_MODE_REMOTE_WAKE;
constexpr bool kControllerPowerDown =
    APP_CONTROLLER_USES_STANDBY;
constexpr bool kQueuedCommands =
    APP_CONTROLLER_POWER_MODE == APP_COMPONENT_MODE_QUEUED;
constexpr bool kLoraWakeOnRadio =
    APP_CONTROLLER_POWER_MODE == APP_COMPONENT_MODE_LORA_WOR;
constexpr bool kLoraPowerDown =
    APP_LORA_POWER_MODE == APP_COMPONENT_MODE_POWER_DOWN;
constexpr bool kWifiPowerDown =
    APP_WIFI_POWER_MODE == APP_COMPONENT_MODE_POWER_DOWN;
constexpr bool kSimPowerDown =
    APP_SIM_POWER_MODE == APP_COMPONENT_MODE_POWER_DOWN;
constexpr uint32_t kPowerSleepSeconds = APP_POWER_SLEEP_SECONDS;
constexpr uint32_t kPowerCommandWindowMs = APP_POWER_COMMAND_WINDOW_MS;
constexpr uint32_t kQueuedCommandWindowMs = APP_QUEUED_COMMAND_WINDOW_MS;
constexpr uint32_t kLoraWorCommandWindowMs = APP_LORA_WOR_COMMAND_WINDOW_MS;
constexpr uint32_t kLoraWorWatchdogWakeSeconds = APP_LORA_WOR_WATCHDOG_WAKE_SECONDS;
constexpr uint32_t kPowerSleepEntryTimeoutMs =
    APP_POWER_SLEEP_ENTRY_TIMEOUT_MS;
constexpr uint32_t kPowerMinimumValidRtcEpoch = 1704067200UL;
constexpr uint32_t kPowerMaximumSleepSeconds = 604800UL;
constexpr uint32_t kRemoteWakeDefaultSeconds = APP_REMOTE_WAKE_DEFAULT_SECONDS;
constexpr uint32_t kRemoteWakeMaximumSeconds = 86400UL;
constexpr uint32_t kRemoteWakePollIntervalMs = APP_REMOTE_WAKE_POLL_INTERVAL_MS;

#ifndef APP_NODE_ID
#define APP_NODE_ID 1
#endif

#ifndef APP_SENSOR_ID
#define APP_SENSOR_ID 1
#endif

constexpr uint16_t kNodeId = APP_NODE_ID;
constexpr uint16_t kGatewayNodeId = 0;
constexpr uint16_t kSensorId = APP_SENSOR_ID;

constexpr uint16_t kLoraNetworkId = 0x4547; // this is for the  "EG"
constexpr uint32_t kLoraMd0Pin = PB2;
constexpr uint32_t kLoraMd1Pin = PB1;
constexpr uint32_t kLoraAuxPin = PC13;

// Control lines verified against the supplied PCB schematic.
constexpr uint32_t kEspEnablePin = PB7;
constexpr uint32_t kEspResetPin = PB8;
constexpr bool kEspEnableActiveHigh = true;
constexpr bool kEspResetActiveLow = true;
constexpr uint32_t kEspResetPulseMs = 100UL;
constexpr uint32_t kEspBootDelayMs = 3000UL;
constexpr uint32_t kSimResetPin = PB0;
// SIM800L RESET has an internal low-voltage pull-up: pull low, then release.
// Do not drive it high at 3.3 V. This is emergency reset, not power switching.
constexpr uint32_t kSimResetPulseMs = 250UL;
constexpr uint32_t kSimBootDelayMs = 3000UL;

#if APP_ROLE == APP_ROLE_LORA_GATEWAY
// Gateway needs two UARTs at the same time: one for IP modem and one for AS32.
// PA9/PA10 are free on the gateway because RS485 sensors are disabled there.
constexpr uint32_t kLoraRxPin = PA10;
constexpr uint32_t kLoraTxPin = PA9;
#else
// Sensor node uses the same AS32 pins proven by the standalone Ping/Pong test.
// Do not enable MQTT direct and LoRa on PA11/PA12 at the same time.
constexpr uint32_t kLoraRxPin = PA12;
constexpr uint32_t kLoraTxPin = PA11;
#endif

// Four independent RS485 switches. A disabled sensor is neither initialized
// nor polled. Keep the deployed TUF-only default; enable any combination by
// changing these values (or overriding them with build flags).
#ifndef APP_ENABLE_TUF_SENSOR
#define APP_ENABLE_TUF_SENSOR true
#endif
#ifndef APP_ENABLE_HNDA_SENSOR
#define APP_ENABLE_HNDA_SENSOR false
#endif
#ifndef APP_ENABLE_SUPMEA_SENSOR
#define APP_ENABLE_SUPMEA_SENSOR false
#endif
#ifndef APP_ENABLE_SONDAS_SENSOR
#define APP_ENABLE_SONDAS_SENSOR false
#endif

// These are the addresses programmed in the physical meters, not commands to
// change them. All enabled devices on this RS485 bus need unique addresses.
#ifndef APP_TUF_SENSOR_MODBUS_ADDRESS
#define APP_TUF_SENSOR_MODBUS_ADDRESS 1
#endif
#ifndef APP_SUPMEA_SENSOR_MODBUS_ADDRESS
#define APP_SUPMEA_SENSOR_MODBUS_ADDRESS 2
#endif
#ifndef APP_HNDA_SENSOR_MODBUS_ADDRESS
#define APP_HNDA_SENSOR_MODBUS_ADDRESS 3
#endif
#ifndef APP_SONDAS_SENSOR_MODBUS_ADDRESS
#define APP_SONDAS_SENSOR_MODBUS_ADDRESS 4
#endif

#if APP_TUF_SENSOR_MODBUS_ADDRESS < 1 || \
    APP_TUF_SENSOR_MODBUS_ADDRESS > 247 || \
    APP_SUPMEA_SENSOR_MODBUS_ADDRESS < 1 || \
    APP_SUPMEA_SENSOR_MODBUS_ADDRESS > 247 || \
    APP_HNDA_SENSOR_MODBUS_ADDRESS < 1 || \
    APP_HNDA_SENSOR_MODBUS_ADDRESS > 247 || \
    APP_SONDAS_SENSOR_MODBUS_ADDRESS < 1 || \
    APP_SONDAS_SENSOR_MODBUS_ADDRESS > 247
#error "Every Modbus address must be in the unicast range 1..247"
#endif

static_assert(
    APP_ENABLE_TUF_SENSOR == true || APP_ENABLE_TUF_SENSOR == false,
    "APP_ENABLE_TUF_SENSOR must be true or false");
static_assert(
    APP_ENABLE_HNDA_SENSOR == true || APP_ENABLE_HNDA_SENSOR == false,
    "APP_ENABLE_HNDA_SENSOR must be true or false");
static_assert(
    APP_ENABLE_SUPMEA_SENSOR == true || APP_ENABLE_SUPMEA_SENSOR == false,
    "APP_ENABLE_SUPMEA_SENSOR must be true or false");
static_assert(
    APP_ENABLE_SONDAS_SENSOR == true || APP_ENABLE_SONDAS_SENSOR == false,
    "APP_ENABLE_SONDAS_SENSOR must be true or false");

constexpr bool kTufSensorRequested = APP_ENABLE_TUF_SENSOR;
constexpr bool kHndaSensorRequested = APP_ENABLE_HNDA_SENSOR;
constexpr bool kSupmeaSensorRequested = APP_ENABLE_SUPMEA_SENSOR;
constexpr bool kSondasSensorRequested = APP_ENABLE_SONDAS_SENSOR;

constexpr bool kEnableTufSensor = APP_HAS_SENSORS && kTufSensorRequested;
constexpr bool kEnableSupmeaSensor = APP_HAS_SENSORS && kSupmeaSensorRequested;
constexpr bool kEnableHndaSensor = APP_HAS_SENSORS && kHndaSensorRequested;
constexpr bool kEnableSondasSensor = APP_HAS_SENSORS && kSondasSensorRequested;

constexpr uint8_t kTufModbusAddress = APP_TUF_SENSOR_MODBUS_ADDRESS;
constexpr uint8_t kSupmeaSensorModbusAddress =
    APP_SUPMEA_SENSOR_MODBUS_ADDRESS;
constexpr uint8_t kHndaModbusAddress = APP_HNDA_SENSOR_MODBUS_ADDRESS;
constexpr uint8_t kSondasModbusAddress = APP_SONDAS_SENSOR_MODBUS_ADDRESS;

static_assert(
    !(kEnableTufSensor && kEnableSupmeaSensor &&
      kTufModbusAddress == kSupmeaSensorModbusAddress),
    "TUF and Supmea must use different Modbus addresses");
static_assert(
    !(kEnableTufSensor && kEnableHndaSensor &&
      kTufModbusAddress == kHndaModbusAddress),
    "TUF and HNDA must use different Modbus addresses");
static_assert(
    !(kEnableTufSensor && kEnableSondasSensor &&
      kTufModbusAddress == kSondasModbusAddress),
    "TUF and Sondas must use different Modbus addresses");
static_assert(
    !(kEnableSupmeaSensor && kEnableHndaSensor &&
      kSupmeaSensorModbusAddress == kHndaModbusAddress),
    "Supmea and HNDA must use different Modbus addresses");
static_assert(
    !(kEnableSupmeaSensor && kEnableSondasSensor &&
      kSupmeaSensorModbusAddress == kSondasModbusAddress),
    "Supmea and Sondas must use different Modbus addresses");
static_assert(
    !(kEnableHndaSensor && kEnableSondasSensor &&
      kHndaModbusAddress == kSondasModbusAddress),
    "HNDA and Sondas must use different Modbus addresses");

constexpr uint16_t kSensorMaskTuf = 0x0001;
constexpr uint16_t kSensorMaskHnda = 0x0002;
constexpr uint16_t kSensorMaskSondas = 0x0004;
constexpr uint16_t kSensorMaskSupmea = 0x0008;

constexpr uint32_t kRs485BaudRate = 9600UL;
constexpr uint32_t kRs485TxEnablePin = PA8;

// Supmea calendar consumption uses the meter's cumulative forward total and
// the trusted STM32 RTC. The RTC itself remains UTC; the calendar converter
// applies the selected business-time policy only when deriving period keys.
#define APP_CALENDAR_TIMEZONE_UTC 0
#define APP_CALENDAR_TIMEZONE_FIXED_OFFSET 1
#define APP_CALENDAR_TIMEZONE_AFRICA_CAIRO 2
#ifndef APP_CALENDAR_TIMEZONE
#define APP_CALENDAR_TIMEZONE APP_CALENDAR_TIMEZONE_AFRICA_CAIRO
#endif
#if APP_CALENDAR_TIMEZONE != APP_CALENDAR_TIMEZONE_UTC && \
    APP_CALENDAR_TIMEZONE != APP_CALENDAR_TIMEZONE_FIXED_OFFSET && \
    APP_CALENDAR_TIMEZONE != APP_CALENDAR_TIMEZONE_AFRICA_CAIRO
#error "APP_CALENDAR_TIMEZONE must be UTC, FIXED_OFFSET, or AFRICA_CAIRO"
#endif
#ifndef APP_CALENDAR_FIXED_UTC_OFFSET_MINUTES
#define APP_CALENDAR_FIXED_UTC_OFFSET_MINUTES 120
#endif
#ifndef APP_SUPMEA_COUNTER_NOISE_LITERS
#define APP_SUPMEA_COUNTER_NOISE_LITERS 2ULL
#endif
#ifndef APP_SUPMEA_MAX_EXPECTED_FLOW_M3H
// Zero disables physical jump rejection until the installed pipe/meter range
// is known. Commissioning documentation requires setting the real limit.
#define APP_SUPMEA_MAX_EXPECTED_FLOW_M3H 0.0f
#endif
#ifndef APP_SUPMEA_MAX_FLOW_SAFETY_FACTOR
#define APP_SUPMEA_MAX_FLOW_SAFETY_FACTOR 1.5f
#endif
#ifndef APP_FLOW_FLASH_CHECKPOINT_SECONDS
#define APP_FLOW_FLASH_CHECKPOINT_SECONDS 86400UL
#endif
#ifndef APP_RESET_SUPMEA_PERIOD_STATE
#define APP_RESET_SUPMEA_PERIOD_STATE 0
#endif

constexpr uint8_t kCalendarTimezone = APP_CALENDAR_TIMEZONE;
constexpr int16_t kCalendarFixedUtcOffsetMinutes =
    APP_CALENDAR_FIXED_UTC_OFFSET_MINUTES;
constexpr uint64_t kSupmeaCounterNoiseLiters =
    APP_SUPMEA_COUNTER_NOISE_LITERS;
constexpr float kSupmeaMaxExpectedFlowM3h =
    APP_SUPMEA_MAX_EXPECTED_FLOW_M3H;
constexpr float kSupmeaMaxFlowSafetyFactor =
    APP_SUPMEA_MAX_FLOW_SAFETY_FACTOR;
constexpr uint32_t kFlowFlashCheckpointSeconds =
    APP_FLOW_FLASH_CHECKPOINT_SECONDS;
constexpr bool kResetSupmeaPeriodState =
    APP_RESET_SUPMEA_PERIOD_STATE != 0;
constexpr int kFlowAccumulatorEepromAddress = 128;
// 20-byte versioned IWDG counter; do not overlap WiFi [0,112) or flow [128,184).
constexpr int kWatchdogCounterEepromAddress = 192;
static_assert(
    kCalendarFixedUtcOffsetMinutes >= -720 &&
    kCalendarFixedUtcOffsetMinutes <= 840,
    "Calendar UTC offset must be between -12:00 and +14:00");
static_assert(
    kSupmeaMaxExpectedFlowM3h >= 0.0f,
    "Supmea maximum expected flow cannot be negative");
static_assert(
    kSupmeaMaxFlowSafetyFactor >= 1.0f,
    "Supmea maximum-flow safety factor must be at least 1.0");

// Measured hardware: battery+ -- 21.6 kOhm -- PA0 -- 9.8 kOhm -- GND, with a
// 100 nF capacitor from PA0 to GND. At 8.4 V, PA0 is approximately 2.622 V.
  // The theoretical input limit is approximately 10.57 V at the 3.3 V ADC
// limit. Values below are the measured resistances, not their nominal markings.
// Never connect the battery directly to PA0; battery- and STM32 GND must be
// connected together.
// Override these APP_BATTERY_* definitions at build time if the production
// PCB uses a different ADC pin, divider, reference, or calibration factor.
#ifndef APP_ENABLE_BATTERY_MONITOR
#define APP_ENABLE_BATTERY_MONITOR 1
#endif
#ifndef APP_BATTERY_ADC_PIN
#define APP_BATTERY_ADC_PIN PA0
#endif
#ifndef APP_BATTERY_DIVIDER_HIGH_OHMS
#define APP_BATTERY_DIVIDER_HIGH_OHMS 21600.0f
#endif
#ifndef APP_BATTERY_DIVIDER_LOW_OHMS
#define APP_BATTERY_DIVIDER_LOW_OHMS 9800.0f
#endif
#ifndef APP_BATTERY_ADC_REFERENCE_VOLTS
#define APP_BATTERY_ADC_REFERENCE_VOLTS 3.3f
#endif
#ifndef APP_BATTERY_CALIBRATION_FACTOR
#define APP_BATTERY_CALIBRATION_FACTOR 1.0f
#endif

constexpr bool kEnableBatteryMonitor =
    APP_HAS_SENSORS && (APP_ENABLE_BATTERY_MONITOR != 0);
constexpr uint32_t kBatteryAdcPin = APP_BATTERY_ADC_PIN;
constexpr uint8_t kBatteryAdcResolutionBits = 12U;
constexpr uint16_t kBatteryAdcMaximumCount = 4095U;
constexpr uint8_t kBatterySampleCount = 16U;
constexpr float kBatteryDividerHighOhms = APP_BATTERY_DIVIDER_HIGH_OHMS;
constexpr float kBatteryDividerLowOhms = APP_BATTERY_DIVIDER_LOW_OHMS;
constexpr float kBatteryAdcReferenceVolts = APP_BATTERY_ADC_REFERENCE_VOLTS;
constexpr float kBatteryCalibrationFactor = APP_BATTERY_CALIBRATION_FACTOR;

// HNDA (Honde RD-SMT-P-O) Modbus map from the supplied PDF:
// 0x0000 = signed soil temperature * 10, 0x0001 = soil moisture * 10.
// The factory default slave address is 0x01; use a unique address when the
// flow meter is on the same RS485 bus.
constexpr uint16_t kHndaTemperatureRegister = 0x0000;
constexpr uint16_t kHndaMoistureRegister = 0x0001;
constexpr float kHndaRegisterScale = 10.0f;

// The supplied Sondas HP/Nutricontrol document identifies the EC-capable sensor
// family but does not provide a Modbus register table. Keep this common
// contiguous Modbus layout configurable here so it can be aligned with the
// exact purchased probe without changing application code.
constexpr uint16_t kSondasTemperatureRegister = 0x0000;
constexpr uint16_t kSondasMoistureRegister = 0x0001;
constexpr uint16_t kSondasElectricalConductivityRegister = 0x0002;
constexpr float kSondasTemperatureScale = 10.0f;
constexpr float kSondasMoistureScale = 10.0f;
constexpr float kSondasElectricalConductivityScale = 1.0f;

// TB6612FNG channel A commissioning. NEVER guess a latching-coil pulse time.
// Keep zero/false until the coil supplier specifies both pulse durations and
// the opening polarity has been verified. PWMA is wired HIGH, not a GPIO.
#ifndef APP_ENABLE_LATCHING_VALVE
#define APP_ENABLE_LATCHING_VALVE true
#endif
#ifndef APP_VALVE_OPEN_PULSE_MS
#define APP_VALVE_OPEN_PULSE_MS 0UL
#endif
#ifndef APP_VALVE_CLOSE_PULSE_MS
#define APP_VALVE_CLOSE_PULSE_MS 0UL
#endif
#ifndef APP_VALVE_POLARITY_CONFIRMED
#define APP_VALVE_POLARITY_CONFIRMED false
#endif
#ifndef APP_VALVE_OPEN_AIN1_HIGH
#define APP_VALVE_OPEN_AIN1_HIGH true
#endif
#ifndef APP_VALVE_MIN_INTERVAL_MS
#define APP_VALVE_MIN_INTERVAL_MS 1000UL
#endif
#if APP_VALVE_OPEN_PULSE_MS < 0 || APP_VALVE_OPEN_PULSE_MS > 1000 || \
    APP_VALVE_CLOSE_PULSE_MS < 0 || APP_VALVE_CLOSE_PULSE_MS > 1000
#error "Valve pulse must be 0 (inhibited) or 1..1000 ms; 1000 is a software ceiling, not a coil rating"
#endif
#if APP_VALVE_MIN_INTERVAL_MS < 1000 || APP_VALVE_MIN_INTERVAL_MS > 60000
#error "APP_VALVE_MIN_INTERVAL_MS must be 1000..60000 ms"
#endif
static_assert(APP_ENABLE_LATCHING_VALVE == true || APP_ENABLE_LATCHING_VALVE == false,
    "APP_ENABLE_LATCHING_VALVE must be true or false");
static_assert(APP_VALVE_POLARITY_CONFIRMED == true || APP_VALVE_POLARITY_CONFIRMED == false,
    "APP_VALVE_POLARITY_CONFIRMED must be true or false");
static_assert(APP_VALVE_OPEN_AIN1_HIGH == true || APP_VALVE_OPEN_AIN1_HIGH == false,
    "APP_VALVE_OPEN_AIN1_HIGH must be true or false");
constexpr uint32_t kValveAin1Pin = PB9;
constexpr uint32_t kValveAin2Pin = PB15;
constexpr uint32_t kValveOpenPulseMs = APP_VALVE_OPEN_PULSE_MS;
constexpr uint32_t kValveClosePulseMs = APP_VALVE_CLOSE_PULSE_MS;
constexpr uint32_t kValveMinIntervalMs = APP_VALVE_MIN_INTERVAL_MS;
constexpr bool kValvePolarityConfirmed = APP_VALVE_POLARITY_CONFIRMED;
constexpr bool kValveOpenAin1High = APP_VALVE_OPEN_AIN1_HIGH;
// Wi-Fi 0..111; Supmea 128..183; WDT 192..211; valve 212..231.
constexpr uint32_t kValveEepromAddress = 212U;
#if defined(PC13)
constexpr uint32_t kOpenCloseNodeGpio = PC13;
#elif defined(LED_BUILTIN)
constexpr uint32_t kOpenCloseNodeGpio = LED_BUILTIN;
#else
constexpr uint32_t kOpenCloseNodeGpio = 13;
#endif
// Existing valve pin is retained, now STBY: HIGH only DURING a pulse.
constexpr bool kOpenCloseNodeActiveLow = false;
constexpr bool kOpenCloseNodeGpioConflictsWithLora =
    APP_HAS_LORA && (kOpenCloseNodeGpio == kLoraAuxPin);
constexpr bool kEnableOpenCloseNodeOutput = APP_HAS_SENSORS &&
    APP_ENABLE_LATCHING_VALVE && !kOpenCloseNodeGpioConflictsWithLora;
static_assert(kValveAin1Pin != kValveAin2Pin &&
    kValveAin1Pin != kOpenCloseNodeGpio && kValveAin2Pin != kOpenCloseNodeGpio,
    "TB6612FNG pins must be distinct");

constexpr size_t kAesBlockSize = 16;
constexpr size_t kIvLength = 16;
// Worst-case Telemetry protobuf is 365 bytes; AES-CBC framing needs 385.
constexpr size_t kCodecBufferSize = 416;
// PubSubClient's buffer contains the MQTT header and topic as well as the
// encrypted payload. The dual-flow/power envelope can reach 385 bytes, so the
// 512-byte whole-packet buffer still has room for the MQTT topic and header.
constexpr size_t kMqttPacketBufferSize = MQTT_MAX_PACKET_SIZE;
constexpr uint8_t kProtocolVersion = 1;

constexpr uint32_t kDefaultSamplingPeriodMs = 10000UL;
constexpr uint32_t kDefaultTransmissionPeriodMs = 15000UL;

constexpr uint32_t kDefaultRtcEpoch = 1704067200UL;
constexpr uint16_t kMqttPort = 1883;
constexpr uint16_t kMqttKeepAliveSeconds = 45;
constexpr uint16_t kMqttSocketTimeoutSeconds = 8;
constexpr bool kEnableCommandAckReplies = APP_ENABLE_COMMAND_ACK_REPLIES;
constexpr uint32_t kMqttReconnectIntervalMs = 3000UL;

constexpr uint32_t kMinimumRateSeconds = 10UL;
// When enabled, a successfully provisioned operator network is retained as a
// fallback. The SSID/password compiled in AppConfig.cpp are always attempted
// first and do not overwrite this saved fallback when they connect.
constexpr bool kEnableWifiCredentialStore = true;
constexpr bool kEnableGatewayHeartbeatLogs = true;
constexpr bool kEnableVerboseMqttLogs = true;//false  or  true 
constexpr bool kEnablePublishTimingLogs = true;//false  or  true 

// STM32F401 independent hardware watchdog. This is a GLOBAL controller safety
// deadline, not only a GSM/WiFi retry timer. The timeout is in microseconds as
// required by STM32duino IWatchdog. Application-owned bounded phases reach an
// explicit progress checkpoint within 12 seconds; an opaque modem call that
// does not return before the nominal 30-second deadline is intentionally
// treated as stuck. Network retry exhaustion remains an additional recovery
// policy for calls that do return.
#ifndef APP_ENABLE_HARDWARE_WATCHDOG
#define APP_ENABLE_HARDWARE_WATCHDOG 1
#endif
#ifndef APP_WATCHDOG_TIMEOUT_US
#define APP_WATCHDOG_TIMEOUT_US 30000000UL
#endif
#ifndef APP_NETWORK_RETRIES_PER_STAGE
#define APP_NETWORK_RETRIES_PER_STAGE 10U
#endif
#if APP_NETWORK_RETRIES_PER_STAGE < 1U || APP_NETWORK_RETRIES_PER_STAGE > 100U
#error "APP_NETWORK_RETRIES_PER_STAGE must be within 1..100"
#endif

// Controlled fault injection. Leave DISABLED in every production image.
// AFTER_SETUP proves boot/application coverage; MAIN_LOOP proves runtime
// coverage. The test resets by IWDG, reports PASS on the immediately following
// boot, and then permits normal execution so the result can be read.
#define APP_WATCHDOG_SELF_TEST_DISABLED 0
#define APP_WATCHDOG_SELF_TEST_AFTER_SETUP 1
#define APP_WATCHDOG_SELF_TEST_MAIN_LOOP 2
#ifndef APP_WATCHDOG_SELF_TEST_MODE
#define APP_WATCHDOG_SELF_TEST_MODE APP_WATCHDOG_SELF_TEST_DISABLED
#endif

constexpr bool kEnableHardwareWatchdog =
    APP_ENABLE_HARDWARE_WATCHDOG != 0;
constexpr uint32_t kWatchdogTimeoutUs = APP_WATCHDOG_TIMEOUT_US;
#if APP_CONTROLLER_POWER_MODE == APP_COMPONENT_MODE_LORA_WOR && \
    APP_ENABLE_HARDWARE_WATCHDOG && \
    APP_WATCHDOG_TIMEOUT_US <= (APP_LORA_WOR_WATCHDOG_WAKE_SECONDS + 2UL) * 1000000UL
#error "LORA_WOR RTC heartbeat must be at least 2 seconds shorter than IWDG timeout"
#endif
constexpr uint32_t kWatchdogForcedResetTimeoutUs = 250000UL;
// First budget resets the active modem; second budget resets modem + MCU.
// Network success clears both budgets. MQTT broker failures do not count here.
constexpr uint8_t kNetworkRetriesPerStage = APP_NETWORK_RETRIES_PER_STAGE;
constexpr uint8_t kWatchdogSelfTestMode = APP_WATCHDOG_SELF_TEST_MODE;

// STM32duino 2.12.0 calculates this limit from a typical 32 kHz LSI clock.
// IWDG timing is approximate because the physical LSI oscillator is not a
// precision time base.
static_assert(
    APP_WATCHDOG_TIMEOUT_US >= 1000000UL &&
    APP_WATCHDOG_TIMEOUT_US <= 32760000UL,
    "APP_WATCHDOG_TIMEOUT_US must be within 1,000,000..32,760,000 us");
static_assert(
    APP_WATCHDOG_SELF_TEST_MODE >= APP_WATCHDOG_SELF_TEST_DISABLED &&
    APP_WATCHDOG_SELF_TEST_MODE <= APP_WATCHDOG_SELF_TEST_MAIN_LOOP,
    "APP_WATCHDOG_SELF_TEST_MODE is invalid");

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
