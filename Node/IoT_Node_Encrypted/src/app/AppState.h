/**
 * @file AppState.h
 * @brief Shared acquisition, timing, and telemetry state for the STM32 node.
 */
#ifndef APP_STATE_H
#define APP_STATE_H

#include <stdint.h>

#include "../devices/HndaSensor.h"
#include "../devices/SondasSensor.h"
/** @brief Flow-meter implementation represented by a common metrics record. */
enum class FlowMeterType : uint8_t
{
    None = 0,
    Tuf = 1,
    Supmea = 2,
};

/** @brief Origin of the day, month, and year consumption figures. */
enum class FlowPeriodSource : uint8_t
{
    Unknown = 0,
    MeterNative = 1,
    NodeRtcCalculated = 2,
};

/** @brief Quality classification for calendar consumption totals. */
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

/**
 * @brief Normalized flow telemetry shared by TUF and Supmea profiles.
 *
 * Volume fields use cubic metres, cumulative counters use integer litres,
 * and validity flags distinguish a configured meter from a successful sample.
 */
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

/**
 * @brief Mutable node snapshot consumed by samplers and telemetry builders.
 *
 * The sketch owns scheduling; sensor modules update only their corresponding
 * measurement blocks. Failed measurement groups are zeroed and marked invalid;
 * Supmea's separate persisted consumption baseline is retained for recovery.
 */
struct AppRuntimeState 
{
    uint32_t samplingPeriodMs;
    uint32_t transmissionPeriodMs;
    uint32_t lastReadMs;
    uint32_t lastSendMs;
    uint32_t lastTimestamp;
    float batteryVoltage;
    uint8_t nodeStatus; ///< Valve: 0=commanded closed, 1=commanded open, 2=unknown, 3=fault.
    uint16_t sensorMask;
    uint8_t activeSensorCount;
    FlowMeterMetrics tufFlow;
    FlowMeterMetrics supmeaFlow;
    HndaSensorData hnda;
    SondasSensorData sondas;
};

/** @brief Access the single node state instance. @return Mutable runtime state. */
AppRuntimeState& appState();
/** @brief Replace the TUF metrics block. @param metrics Latest TUF acquisition. */
void updateTufFlowMetrics(const FlowMeterMetrics& metrics);
/** @brief Replace the Supmea metrics block. @param metrics Latest Supmea acquisition. */
void updateSupmeaFlowMetrics(const FlowMeterMetrics& metrics);
/** @brief Replace HNDA metrics, zeroing invalid reads. @param data Latest acquisition. */
void updateHndaMetrics(const HndaSensorData& data);
/** @brief Replace Sondas soil readings. @param data Latest Sondas acquisition result. */
void updateSondasMetrics(const SondasSensorData& data);
/** @brief Read the battery ADC and update the cached voltage in node state. */
void refreshBatteryVoltage();
/** @brief Recompute the configured-sensor bit mask and active-sensor count. */
void refreshEnabledSensorSummary();

#endif
