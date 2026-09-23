#ifndef SONDAS_SENSOR_H
#define SONDAS_SENSOR_H

#include <stdint.h>

#include "../third_party/ModbusMaster/ModbusMaster.h"

struct SondasSensorData
{
    float temperatureC;
    float moisturePercent;
    float electricalConductivity;
    bool isValid;
};

extern ModbusMaster sondasSensor;

void initializeSondasSensor();
SondasSensorData readSondasSensor();
void printSondasSensorData(const SondasSensorData& data);

#endif
