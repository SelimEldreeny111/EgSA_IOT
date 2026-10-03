/** @file AppState.cpp @brief Shared runtime measurements and validity-state updates. */
#include "AppState.h"

#include "../config/AppConfig.h"
#include "../devices/BatteryMonitor.h"

namespace {
AppRuntimeState g_appState = {
    AppConfig::kDefaultSamplingPeriodMs,
    AppConfig::kDefaultTransmissionPeriodMs,
    0,
    0,
    0,
    0.0f,
    0,
    0,
    0,
    {},
    {},
    {
        0.0f,
        0.0f,
        false,
    },
    {
        0.0f,
        0.0f,
        0.0f,
        false,
    },
};
}

AppRuntimeState& appState()
{
    return g_appState;
}

void updateTufFlowMetrics(const FlowMeterMetrics& metrics)
{
    appState().tufFlow = metrics;
}

void updateSupmeaFlowMetrics(const FlowMeterMetrics& metrics)
{
    appState().supmeaFlow = metrics;
}

void updateHndaMetrics(const HndaSensorData& data)
{
    appState().hnda = data.isValid ? data : HndaSensorData{};
}

void updateSondasMetrics(const SondasSensorData& data)
{
    appState().sondas = data.isValid ? data : SondasSensorData{};
}

void refreshBatteryVoltage()
{
    appState().batteryVoltage = readBatteryVoltage();
}

void refreshEnabledSensorSummary()
{
    AppRuntimeState& state = appState();
    state.sensorMask = 0;
    state.activeSensorCount = 0;

    if (AppConfig::kEnableTufSensor)
    {
        state.sensorMask |= AppConfig::kSensorMaskTuf;
        ++state.activeSensorCount;
    }

    if (AppConfig::kEnableSupmeaSensor)
    {
        state.sensorMask |= AppConfig::kSensorMaskSupmea;
        ++state.activeSensorCount;
    }

    if (AppConfig::kEnableHndaSensor)
    {
        state.sensorMask |= AppConfig::kSensorMaskHnda;
        ++state.activeSensorCount;
    }

    if (AppConfig::kEnableSondasSensor)
    {
        state.sensorMask |= AppConfig::kSensorMaskSondas;
        ++state.activeSensorCount;
    }
}
