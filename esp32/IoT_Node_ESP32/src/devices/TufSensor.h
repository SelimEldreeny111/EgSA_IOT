#ifndef TUF_SENSOR_H
#define TUF_SENSOR_H

#include <stdint.h>

#include "../third_party/ModbusMaster/ModbusMaster.h"

struct TufSensorData
{
    float flowRate;
    float velocity;
    float flowPerDay;
    float flowPerMonth;
    float flowPerYear;
    uint16_t errorCode;
    bool isValid;
};

extern ModbusMaster tufSensor;

void initializeTufSensor();
TufSensorData readTufSensor();
void printTufSensorData(const TufSensorData& data);

#endif
