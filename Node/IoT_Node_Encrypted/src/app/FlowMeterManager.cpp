/** @file FlowMeterManager.cpp @brief Selected flow-meter startup and sampling orchestration. */
#include "FlowMeterManager.h"

#include "AppState.h"
#include "SupmeaPeriodAccumulator.h"
#include "../config/AppConfig.h"
#include "../devices/RTC.h"
#include "../devices/SupmeaSensor.h"
#include "../devices/TufSensor.h"
#include "../platform/Watchdog.h"

#include <Arduino.h>
#include <math.h>

extern HardwareSerial SerialMon;

namespace
{
/** @brief Convert a finite, nonnegative cumulative cubic-meter value to integer liters. */
bool unsignedM3ToLiters(float valueM3, uint64_t& liters)
{
    if (!isfinite(valueM3) || valueM3 < 0.0f)
    {
        return false;
    }
    const double scaled = static_cast<double>(valueM3) * 1000.0;
    if (scaled > static_cast<double>(UINT64_MAX))
    {
        return false;
    }
    liters = static_cast<uint64_t>(llround(scaled));
    return true;
}

/** @brief Convert a finite signed net cubic-meter value to integer liters. */
bool signedM3ToLiters(float valueM3, int64_t& liters)
{
    if (!isfinite(valueM3))
    {
        return false;
    }
    const double scaled = static_cast<double>(valueM3) * 1000.0;
    if (scaled < static_cast<double>(INT64_MIN) ||
        scaled > static_cast<double>(INT64_MAX))
    {
        return false;
    }
    liters = static_cast<int64_t>(llround(scaled));
    return true;
}

/** @brief Normalize Supmea volumetric rate units; reject unsupported mass-flow units. */
bool normalizeSupmeaFlowToM3h(
    float rawFlow,
    uint16_t unitCode,
    float& flowM3h)
{
    if (!isfinite(rawFlow))
    {
        return false;
    }

    switch (unitCode)
    {
        case 0U: // L/h
            flowM3h = rawFlow / 1000.0f;
            return true;
        case 1U: // L/min
            flowM3h = rawFlow * 60.0f / 1000.0f;
            return true;
        case 2U: // L/s
            flowM3h = rawFlow * 3600.0f / 1000.0f;
            return true;
        case 3U: // m3/h
            flowM3h = rawFlow;
            return true;
        case 4U: // m3/min
            flowM3h = rawFlow * 60.0f;
            return true;
        case 5U: // m3/s
            flowM3h = rawFlow * 3600.0f;
            return true;
        default:
            // Mass-flow units need a configured density and are deliberately
            // not presented as a volume rate.
            return false;
    }
}

/** @brief Give each period-validity state a readable serial diagnostic name. */
const char* qualityName(FlowPeriodQuality quality)
{
    switch (quality)
    {
        case FlowPeriodQuality::Valid: return "VALID";
        case FlowPeriodQuality::Partial: return "PARTIAL";
        case FlowPeriodQuality::Estimated: return "ESTIMATED";
        case FlowPeriodQuality::CounterReset: return "COUNTER_RESET";
        case FlowPeriodQuality::Anomaly: return "ANOMALY";
        case FlowPeriodQuality::TimeUncertain: return "TIME_UNCERTAIN";
        default: return "INVALID";
    }
}

/** @brief Read TUF native daily, monthly, and yearly totals into shared state. */
void sampleTuf()
{
    const TufSensorData data = readTufSensor();
    printTufSensorData(data);

    // Each poll replaces the published snapshot; failed groups stay zero.
    FlowMeterMetrics metrics = {};
    metrics.type = FlowMeterType::Tuf;
    metrics.periodSource = FlowPeriodSource::MeterNative;
    metrics.rtcValid = isRtcTrusted();
    metrics.liveDataValid = data.liveValid;
    metrics.periodTotalsValid = data.periodTotalsValid;
    metrics.cumulativeTotalsValid = false;
    metrics.periodQuality = data.periodTotalsValid
        ? FlowPeriodQuality::Valid
        : FlowPeriodQuality::Invalid;
    metrics.alarmFlags = data.errorCodeValid ? data.errorCode : 0U;

    if (data.liveValid)
    {
        metrics.flowRateM3h = data.flowRate;
        metrics.velocityMps = data.velocity;
    }
    if (data.periodTotalsValid)
    {
        metrics.volumeTodayM3 = data.flowPerDay;
        metrics.volumeThisMonthM3 = data.flowPerMonth;
        metrics.volumeThisYearM3 = data.flowPerYear;
    }
    updateTufFlowMetrics(metrics);
}

/** @brief Print RTC-derived Supmea totals and the associated quality flag. */
void printSupmeaCalculatedPeriods(const FlowMeterMetrics& metrics)
{
    SerialMon.println("---------- SUPMEA RTC CONSUMPTION ----------");
    SerialMon.print("Today's volume  : ");
    SerialMon.print(metrics.volumeTodayM3, 3);
    SerialMon.println(" m3");
    SerialMon.print("This month     : ");
    SerialMon.print(metrics.volumeThisMonthM3, 3);
    SerialMon.println(" m3");
    SerialMon.print("This year      : ");
    SerialMon.print(metrics.volumeThisYearM3, 3);
    SerialMon.println(" m3");
    SerialMon.print("RTC trusted    : ");
    SerialMon.println(metrics.rtcValid ? "YES" : "NO");
    SerialMon.print("Period quality : ");
    SerialMon.println(qualityName(metrics.periodQuality));
    SerialMon.println("--------------------------------------------");
}

/** @brief Read Supmea totals, normalize live flow, and update RTC-based periods. */
void sampleSupmea()
{
    const SupmeaSensorData data = readSupmeaSensor();
    printSupmeaSensorData(data);
    serviceHardwareWatchdog(WatchdogStage::SupmeaPeriodCalculation);

    // Do not retain old wire readings when the current Modbus poll fails.
    // The independent RTC accumulator keeps its baseline/history internally.
    FlowMeterMetrics metrics = {};
    metrics.type = FlowMeterType::Supmea;
    metrics.periodSource = FlowPeriodSource::NodeRtcCalculated;
    metrics.liveDataValid = false;
    metrics.cumulativeTotalsValid = false;
    metrics.periodTotalsValid = false;
    metrics.rtcValid = isRtcTrusted();
    metrics.alarmFlags =
        static_cast<uint32_t>(data.epdAlarm) |
        (static_cast<uint32_t>(data.excitationCurrentAlarm) << 16U);

    float normalizedFlowM3h = 0.0f;
    if (data.liveValid &&
        normalizeSupmeaFlowToM3h(
            data.flowRate,
            data.flowRateUnitCode,
            normalizedFlowM3h))
    {
        metrics.flowRateM3h = normalizedFlowM3h;
        metrics.velocityMps = data.velocityMps;
        metrics.liveDataValid = true;
    }
    else if (data.liveValid)
    {
        SerialMon.println(
            "SUP-FMC240 flow unit is a mass unit; configure a volumetric unit");
    }

    uint64_t forwardLiters = 0U;
    uint64_t reverseLiters = 0U;
    int64_t netLiters = 0;
    metrics.cumulativeTotalsValid = data.totalsValid &&
        unsignedM3ToLiters(data.forwardTotalM3, forwardLiters) &&
        unsignedM3ToLiters(data.reverseTotalM3, reverseLiters) &&
        signedM3ToLiters(data.netTotalM3, netLiters);

    if (metrics.cumulativeTotalsValid)
    {
        metrics.forwardTotalLiters = forwardLiters;
        metrics.reverseTotalLiters = reverseLiters;
        metrics.netTotalLiters = netLiters;

        const SupmeaPeriodResult period = updateSupmeaPeriodAccumulator(
            forwardLiters,
            getEpochTime(),
            metrics.rtcValid);
        metrics.volumeTodayM3 =
            static_cast<float>(period.volumeTodayLiters) / 1000.0f;
        metrics.volumeThisMonthM3 =
            static_cast<float>(period.volumeThisMonthLiters) / 1000.0f;
        metrics.volumeThisYearM3 =
            static_cast<float>(period.volumeThisYearLiters) / 1000.0f;
        metrics.periodQuality = period.quality;
        metrics.periodTotalsValid = period.valid;
    }
    else
    {
        metrics.periodQuality = metrics.rtcValid
            ? FlowPeriodQuality::Invalid
            : FlowPeriodQuality::TimeUncertain;
    }

    updateSupmeaFlowMetrics(metrics);
    printSupmeaCalculatedPeriods(metrics);
}
}

void initializeConfiguredFlowMeter()
{
    if (AppConfig::kEnableTufSensor)
    {
        SerialMon.println("Flow meter enabled: TUF");
        FlowMeterMetrics metrics = {};
        metrics.type = FlowMeterType::Tuf;
        metrics.periodSource = FlowPeriodSource::MeterNative;
        updateTufFlowMetrics(metrics);
        initializeTufSensor();
    }

    if (AppConfig::kEnableSupmeaSensor)
    {
        SerialMon.println("Flow meter enabled: Supmea");
        FlowMeterMetrics metrics = {};
        metrics.type = FlowMeterType::Supmea;
        metrics.periodSource = FlowPeriodSource::NodeRtcCalculated;
        updateSupmeaFlowMetrics(metrics);
        initializeSupmeaPeriodAccumulator();
        initializeSupmeaSensor();
    }

    if (!AppConfig::kEnableTufSensor && !AppConfig::kEnableSupmeaSensor)
    {
        SerialMon.println("No flow meter selected");
    }
}

void sampleConfiguredFlowMeter()
{
    sampleTufFlowMeter();
    sampleSupmeaFlowMeter();
}

void sampleTufFlowMeter()
{
    if (AppConfig::kEnableTufSensor)
    {
        sampleTuf();
    }
}

void sampleSupmeaFlowMeter()
{
    if (AppConfig::kEnableSupmeaSensor)
    {
        sampleSupmea();
    }
}
