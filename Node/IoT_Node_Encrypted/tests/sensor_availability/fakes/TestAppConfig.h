#ifndef TEST_AVAILABILITY_CONFIG_H
#define TEST_AVAILABILITY_CONFIG_H
#include "Arduino.h"
#define APP_CONFIG_H
#define ModbusMaster_h
class ModbusMaster {};
#define RTC_HELPERS_H
bool isRtcTrusted();
uint32_t getEpochTime();
#define HARDWARE_WATCHDOG_H
enum class WatchdogStage { SupmeaPeriodCalculation };
void serviceHardwareWatchdog(WatchdogStage);
uint32_t hardwareWatchdogResetCount();
#ifndef TEST_FLOW_CONFIG
#define TEST_FLOW_CONFIG 0
#endif
namespace AppConfig {
constexpr uint32_t kDefaultSamplingPeriodMs=5000, kDefaultTransmissionPeriodMs=5000;
constexpr bool kEnableTufSensor=TEST_FLOW_CONFIG==0 || TEST_FLOW_CONFIG==1;
constexpr bool kEnableSupmeaSensor=TEST_FLOW_CONFIG==0 || TEST_FLOW_CONFIG==2;
constexpr bool kEnableHndaSensor=true, kEnableSondasSensor=true;
constexpr uint16_t kSensorMaskTuf=1, kSensorMaskHnda=2, kSensorMaskSondas=4, kSensorMaskSupmea=8;
constexpr uint16_t kSensorId=1;
}
#endif
