#ifndef APP_STATE_H
#define APP_STATE_H

#include <stdint.h>

#include "devices/FlowMeter.hpp"
#include "devices/SoilMoistureTemperatureSensor.hpp"
#include "devices/SoilMoistureTemperatureEcSensor.hpp"

struct FlowMetrics 
{
    float flowRate;
    float velocity;
    float flowPerDay;
    float flowPerMonth;
    float flowPerYear;
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
    FlowMetrics metrics;
    SoilMoistureTemperatureData soilMoistureTemperature;
    SoilMoistureTemperatureEcData soilMoistureTemperatureEc;
};

AppRuntimeState& appState();
void updateFlowMetrics(const FlowData& data);
void updateSoilMoistureTemperatureMetrics(const SoilMoistureTemperatureData& data);
void updateSoilMoistureTemperatureEcMetrics(const SoilMoistureTemperatureEcData& data);
void refreshBatteryVoltage();
void refreshEnabledSensorSummary();

#endif
