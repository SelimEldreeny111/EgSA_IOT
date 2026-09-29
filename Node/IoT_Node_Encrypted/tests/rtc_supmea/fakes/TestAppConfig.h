#ifndef TEST_APP_CONFIG_H
#define TEST_APP_CONFIG_H

// Replace only hardware configuration and Modbus declarations. Production
// RTC.cpp, SupmeaPeriodAccumulator.cpp, AppState enums and Watchdog enums are
// compiled unchanged; no test-specific branches exist in firmware sources.
#define APP_CONFIG_H
#include <cstdint>
#define APP_CALENDAR_TIMEZONE_UTC 0
#define APP_CALENDAR_TIMEZONE_FIXED_OFFSET 1
#define APP_CALENDAR_TIMEZONE_AFRICA_CAIRO 2
namespace AppConfig
{
constexpr uint32_t kPowerMinimumValidRtcEpoch = 1704067200UL;
constexpr int kFlowAccumulatorEepromAddress = 128;
constexpr uint64_t kSupmeaCounterNoiseLiters = 2ULL;
constexpr float kSupmeaMaxFlowSafetyFactor = 1.5f;
constexpr int16_t kCalendarFixedUtcOffsetMinutes = 120;
extern uint8_t kCalendarTimezone;
extern float kSupmeaMaxExpectedFlowM3h;
extern uint32_t kFlowFlashCheckpointSeconds;
extern bool kResetSupmeaPeriodState;
}
#define HNDA_SENSOR_H
struct HndaSensorData { float temperatureC; float moisturePercent; bool isValid; };
#define SONDAS_SENSOR_H
struct SondasSensorData
{
    float temperatureC; float moisturePercent; float electricalConductivity;
    bool isValid;
};

#endif
