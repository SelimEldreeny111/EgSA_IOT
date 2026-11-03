#pragma once
#include "Arduino.h"
#define APP_CONFIG_H
#define APP_ENABLE_COMMAND_ACK_REPLIES true
constexpr const char kMqttCompanyTopicPrefix[]="wiot/Test/Region";
#if defined(TEST_ESP8266)
#define USE_ESP8266
#else
#define USE_SIM800
#endif
#define APP_HAS_IP_UPLINK 1
#define APP_HAS_LORA 0
#define LORA_LINK_H
#define RTC_HELPERS_H
void initializeRtc(); bool isRtcTimeSet(); void setRtcEpoch(uint32_t); void printRtcDateTime();
#define HARDWARE_WATCHDOG_H
enum class WatchdogStage { Setup, WifiJoin, OperatorInput, GsmRegistration, GprsAttach };
void serviceHardwareWatchdog(); void serviceHardwareWatchdog(WatchdogStage);
void watchdogDelay(uint32_t); void reportHardwareWatchdogStatus();
#define APP_STATE_H
struct AppRuntimeState { uint8_t nodeStatus=0; float batteryVoltage=0; uint32_t lastReadMs=0,lastSendMs=0; };
AppRuntimeState& appState(); void refreshEnabledSensorSummary(); void refreshBatteryVoltage();
#define HNDA_SENSOR_H
#define SONDAS_SENSOR_H
void initializeHndaSensor(); void initializeSondasSensor();
namespace AppConfig {
constexpr uint16_t kNodeId=2;
constexpr uint8_t kNetworkRetriesPerStage=10;
constexpr bool kEnableWifiCredentialStore=true, kEnableOpenCloseNodeOutput=false, kOpenCloseNodeActiveLow=false;
constexpr bool kEnableTufSensor=false,kEnableSupmeaSensor=false,kEnableHndaSensor=false,kEnableSondasSensor=false;
constexpr uint8_t kTufModbusAddress=1,kSupmeaSensorModbusAddress=2,kHndaModbusAddress=3,kSondasModbusAddress=4;
constexpr uint32_t kOpenCloseNodeGpio=13,kDefaultRtcEpoch=1704067200;
}
extern const char kApn[], kNetworkUser[], kNetworkPassword[], kWifiSsid[], kWifiPassword[];
