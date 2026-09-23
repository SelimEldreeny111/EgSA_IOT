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
    {
        1.2f,
        0.8f,
        10.0f,
        200.0f,
        1500.0f,
    },
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

void updateTufMetrics(const TufSensorData& data)
{
    AppRuntimeState& state = appState();

    if (!data.isValid) 
    {
        state.tuf.flowRate     = 0.0f;
        state.tuf.velocity     = 0.0f;
        state.tuf.flowPerDay   = 0.0f;
        state.tuf.flowPerMonth = 0.0f;
        state.tuf.flowPerYear  = 0.0f;
        return;
    }

    state.tuf.flowRate     = data.flowRate;
    state.tuf.velocity     = data.velocity;
    state.tuf.flowPerDay   = data.flowPerDay;
    state.tuf.flowPerMonth = data.flowPerMonth;
    state.tuf.flowPerYear  = data.flowPerYear;


    
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
