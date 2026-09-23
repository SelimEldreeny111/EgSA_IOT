#ifndef APP_STATE_H
#define APP_STATE_H

#include <stdint.h>

#include "../devices/HndaSensor.h"
#include "../devices/SondasSensor.h"
#include "../devices/TufSensor.h"

struct TufMetrics
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
    TufMetrics tuf;
    HndaSensorData hnda;
    SondasSensorData sondas;
};

AppRuntimeState& appState();
void updateTufMetrics(const TufSensorData& data);
void updateHndaMetrics(const HndaSensorData& data);
void updateSondasMetrics(const SondasSensorData& data);
void refreshBatteryVoltage();
void refreshEnabledSensorSummary();

#endif
