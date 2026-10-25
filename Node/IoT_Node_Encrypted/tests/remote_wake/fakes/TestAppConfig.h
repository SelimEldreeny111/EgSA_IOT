#ifndef REMOTE_TEST_APP_CONFIG_H
#define REMOTE_TEST_APP_CONFIG_H
#include "Arduino.h"
#define APP_CONFIG_H
#define APP_COMPONENT_MODE_NORMAL 0
#define APP_COMPONENT_MODE_POWER_DOWN 1
#define APP_COMPONENT_MODE_REMOTE_WAKE 2
#define APP_COMPONENT_MODE_LORA_WOR 3
#define APP_COMPONENT_MODE_QUEUED 4
#define APP_CONTROLLER_USES_STANDBY 0
#define APP_CONTROLLER_POWER_MODE 2
#define USE_SIM800
#define APP_HAS_IP_UPLINK 1
#define APP_HAS_LORA 0
#define MQTT_NODE_H
bool isAsyncPublishBusy();
#define LORA_LINK_H
#define RTC_HELPERS_H
uint32_t getEpochTime();
bool syncRTCFromEpoch(uint32_t);
#define HARDWARE_WATCHDOG_H
enum class WatchdogStage { MainLoop, PowerTransition, ResetCounterStorage };
void markHardwareWatchdogStage(WatchdogStage);
void serviceHardwareWatchdog(WatchdogStage = WatchdogStage::MainLoop);
#define APP_STATE_H
struct AppRuntimeState {
  uint32_t samplingPeriodMs=5000U, transmissionPeriodMs=5000U;
  uint32_t lastReadMs=0U, lastSendMs=0U, lastTimestamp=0U;
  uint8_t nodeStatus=0U;
};
AppRuntimeState& appState();
void refreshBatteryVoltage();
namespace AppConfig {
#ifndef TEST_REMOTE_APP_SCHEDULE
#define TEST_REMOTE_APP_SCHEDULE false
#endif
constexpr bool kRemoteWakeUsesAppSchedule=TEST_REMOTE_APP_SCHEDULE;
constexpr bool kControllerPowerDown=false, kRemoteWakeEnabled=true;
constexpr bool kLoraPowerDown=false, kWifiPowerDown=false, kSimPowerDown=false;
constexpr uint32_t kPowerSleepSeconds=30U, kPowerCommandWindowMs=5000U;
constexpr uint32_t kRemoteWakeDefaultSeconds=60U, kRemoteWakePollIntervalMs=100U;
constexpr uint32_t kNodeId=7U, kMinimumRateSeconds=10U;
constexpr bool kEnableOpenCloseNodeOutput=true, kOpenCloseNodeActiveLow=false;
constexpr uint32_t kOpenCloseNodeGpio=13U;
constexpr size_t kCodecBufferSize=384U;
}
#define PB_SENSOR_PB_H_INCLUDED
struct CMD_Message { uint32_t node_id, cmd_id; uint64_t cmd_data; uint32_t request_id; };
struct Telemetry {
  uint32_t node_id=0U, timestamp=0U, sampling_rate=0U, Transmission_rate=0U;
  uint32_t power_mode=0U, power_state=0U, wake_remaining_seconds=0U;
  bool wake_command_ack=false;
  uint32_t wake_request_id=0U;
  uint32_t command_ack_request_id=0U, command_ack_cmd_id=0U;
  bool command_ack_success=false;
};
#define Telemetry_init_zero {}
extern const void* Telemetry_fields;
#define PACKET_CODEC_H
bool encodeEncryptedMessage(const void*, const void*, uint8_t*, size_t, size_t&);
#define SENSOR_PAYLOAD_MAPPER_H
void populateSensorPayloadFields(Telemetry&, const AppRuntimeState&);
#endif
