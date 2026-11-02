#ifndef WOR_TEST_CONFIG_H
#define WOR_TEST_CONFIG_H
#include "Arduino.h"
#define APP_CONFIG_H
#define WIOT_TELEMETRY_ARCHIVE_H
namespace TelemetryArchive {
bool blocking(); bool transferring(); bool maintenanceDue(uint32_t); uint32_t expiry();
bool prepareSleep(); void resume();
}
#define APP_COMPONENT_MODE_NORMAL 0
#define APP_COMPONENT_MODE_POWER_DOWN 1
#define APP_COMPONENT_MODE_REMOTE_WAKE 2
#define APP_COMPONENT_MODE_LORA_WOR 3
#define APP_COMPONENT_MODE_QUEUED 4
#define APP_LORA_WOR_WAKE_SOURCE_AUX 0
#define APP_LORA_WOR_WAKE_SOURCE_UART_RX 1
#ifndef APP_LORA_WOR_WAKE_SOURCE
#define APP_LORA_WOR_WAKE_SOURCE APP_LORA_WOR_WAKE_SOURCE_UART_RX
#endif
#define APP_CONTROLLER_USES_STANDBY 0
#define APP_CONTROLLER_POWER_MODE 3
#ifndef APP_LORA_WOR_USE_APP_SCHEDULE
#define APP_LORA_WOR_USE_APP_SCHEDULE false
#endif
#define APP_HAS_IP_UPLINK 0
#define APP_HAS_LORA 1
#define USE_SIM800
#define MQTT_NODE_H
#define LORA_LINK_H
bool isLoraIdleForPowerDown();
bool prepareLoraForWakeOnRadio(uint32_t);
bool resumeLoraFromWakeOnRadio(uint32_t);
void initializeLoraLink();
#define RTC_HELPERS_H
uint32_t getEpochTime();
bool isRtcTrusted();
void initializeRtc();
bool scheduleRtcWakeAlarm(uint32_t);
void cancelRtcWakeAlarm();
class STM32RTC {
public:
  enum { ALARM_A=0 };
  void (*callback)(void*)=nullptr;
  void attachInterrupt(void (*fn)(void*), int) { callback=fn; }
  void detachInterrupt(int) { callback=nullptr; }
  RTC_HandleTypeDef* getHandle();
  uint32_t getEpoch(uint32_t* fraction);
};
#define HARDWARE_WATCHDOG_H
enum class WatchdogStage { PowerTransition };
void serviceHardwareWatchdog(WatchdogStage);
#define APP_STATE_H
struct AppRuntimeState {
  uint32_t samplingPeriodMs=10000U, transmissionPeriodMs=15000U;
  uint32_t lastReadMs=0U, lastSendMs=0U;
};
AppRuntimeState& appState();
namespace AppConfig {
constexpr bool kLoraPowerDown=false, kWifiPowerDown=false, kSimPowerDown=false;
constexpr uint32_t kLoraAuxPin=13U, kLoraMd0Pin=2U, kLoraMd1Pin=1U;
constexpr uint32_t kLoraRxPin=12U;
constexpr uint32_t kPowerSleepSeconds=60U, kLoraWorWatchdogWakeSeconds=15U;
constexpr uint32_t kPowerMinimumValidRtcEpoch=1704067200U;
constexpr uint32_t kPowerSleepEntryTimeoutMs=1000U, kLoraTxCompleteTimeoutMs=10000U;
constexpr uint32_t kLoraWorCommandWindowMs=5000U;
constexpr uint32_t kRemoteWakeDefaultSeconds=60U, kRemoteWakeMaximumSeconds=86400U;
}
#endif
