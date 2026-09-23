#include "app/AppState.hpp"

#include "config/AppConfig.hpp"
#include "devices/BatteryMonitor.hpp"

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

void updateFlowMetrics(const FlowData& data)
{
    AppRuntimeState& state = appState();

    if (!data.isValid) 
    {
        state.metrics.flowRate     = 0.0f;
        state.metrics.velocity     = 0.0f;
        state.metrics.flowPerDay   = 0.0f;
        state.metrics.flowPerMonth = 0.0f;
        state.metrics.flowPerYear  = 0.0f;
        return;
    }

    state.metrics.flowRate     = data.flowRate;
    state.metrics.velocity     = data.velocity;
    state.metrics.flowPerDay   = data.flowRate_per_day;
    state.metrics.flowPerMonth = data.flowRate_per_month;
    state.metrics.flowPerYear  = data.flowRate_per_year;


    
}

void updateSoilMoistureTemperatureMetrics(const SoilMoistureTemperatureData& data)
{
    appState().soilMoistureTemperature = data;
}

void updateSoilMoistureTemperatureEcMetrics(const SoilMoistureTemperatureEcData& data)
{
    appState().soilMoistureTemperatureEc = data;
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

    if (AppConfig::kEnableFlowMeter)
    {
        state.sensorMask |= AppConfig::kSensorMaskFlowMeter;
        ++state.activeSensorCount;
    }

    if (AppConfig::kEnableSoilMoistureTemperatureSensor)
    {
        state.sensorMask |= AppConfig::kSensorMaskSoilMoistureTemperature;
        ++state.activeSensorCount;
    }

    if (AppConfig::kEnableSoilMoistureTemperatureEcSensor)
    {
        state.sensorMask |= AppConfig::kSensorMaskSoilMoistureTemperatureEc;
        ++state.activeSensorCount;
    }
}
