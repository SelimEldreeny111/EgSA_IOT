#ifndef SUPMEA_SENSOR_H
#define SUPMEA_SENSOR_H

#include <stdint.h>

#include "../third_party/ModbusMaster/ModbusMaster.h"

// One coherent production sample from the Supmea SUP-FMC240 electromagnetic
// flow meter. FlowMeterManager validates and maps these raw meter values into
// the common application/protobuf flow block.
struct SupmeaSensorData
{
    float forwardTotalM3;
    float reverseTotalM3;
    float netTotalM3;
    float flowRate;
    float velocityMps;
    float flowRatioPercent;
    uint16_t epdPercent;
    uint16_t flowRateUnitCode;
    uint16_t epdAlarm;
    uint16_t excitationCurrentAlarm;
    uint8_t totalsResult;
    uint8_t liveResult;
    bool totalsValid;
    bool liveValid;
    bool isValid;
};

extern ModbusMaster supmeaSensor;

void initializeSupmeaSensor();
SupmeaSensorData readSupmeaSensor();
void printSupmeaSensorData(const SupmeaSensorData& data);
const char* supmeaFlowUnitName(uint16_t unitCode);

#endif
