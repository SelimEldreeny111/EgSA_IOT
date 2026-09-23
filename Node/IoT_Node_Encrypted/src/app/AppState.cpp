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

void updateFlowMetrics(const FlowMeterMetrics& metrics)
{
    appState().flow = metrics;
}

void updateHndaMetrics(const HndaSensorData& data)
{
    appState().hnda = data;
}

void updateSondasMetrics(const SondasSensorData& data)
{
    appState().sondas = data;
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
