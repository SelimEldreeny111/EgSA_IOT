#ifndef HNDA_SENSOR_H
#define HNDA_SENSOR_H

#include <stdint.h>

#include "../third_party/ModbusMaster/ModbusMaster.h"

struct HndaSensorData
{
    float temperatureC;
    float moisturePercent;
    bool isValid;
};

extern ModbusMaster hndaSensor;

void initializeHndaSensor();
HndaSensorData readHndaSensor();
void printHndaSensorData(const HndaSensorData& data);

#endif
