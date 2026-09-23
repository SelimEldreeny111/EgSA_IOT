#ifndef APP_STATE_H
#define APP_STATE_H

#include <stdint.h>

#include "../devices/HndaSensor.h"
#include "../devices/SondasSensor.h"
enum class FlowMeterType : uint8_t
{
    None = 0,
    Tuf = 1,
    Supmea = 2,
};

enum class FlowPeriodSource : uint8_t
{
    Unknown = 0,
    MeterNative = 1,
    NodeRtcCalculated = 2,
};

enum class FlowPeriodQuality : uint8_t
{
    Invalid = 0,
    Valid = 1,
    Partial = 2,
    Estimated = 3,
    CounterReset = 4,
    Anomaly = 5,
    TimeUncertain = 6,
};

struct FlowMeterMetrics
{
    float flowRateM3h;
    float velocityMps;
    float volumeTodayM3;
    float volumeThisMonthM3;
    float volumeThisYearM3;
    uint64_t forwardTotalLiters;
    uint64_t reverseTotalLiters;
    int64_t netTotalLiters;
    uint32_t alarmFlags;
    FlowMeterType type;
    FlowPeriodSource periodSource;
    FlowPeriodQuality periodQuality;
    bool liveDataValid;
    bool cumulativeTotalsValid;
    bool periodTotalsValid;
    bool rtcValid;
};

struct AppRuntimeState 
{
    uint32_t samplingPeriodMs;
    uint32_t transmissionPeriodMs;
    uint32_t lastReadMs;
    uint32_t lastSendMs;
    uint32_t lastTimestamp;
    float batteryVoltage;
    uint8_t nodeStatus;
    uint16_t sensorMask;
    uint8_t activeSensorCount;
    FlowMeterMetrics tufFlow;
    FlowMeterMetrics supmeaFlow;
    HndaSensorData hnda;
    SondasSensorData sondas;
};

AppRuntimeState& appState();
void updateTufFlowMetrics(const FlowMeterMetrics& metrics);
void updateSupmeaFlowMetrics(const FlowMeterMetrics& metrics);
void updateHndaMetrics(const HndaSensorData& data);
void updateSondasMetrics(const SondasSensorData& data);
void refreshBatteryVoltage();
void refreshEnabledSensorSummary();

#endif
