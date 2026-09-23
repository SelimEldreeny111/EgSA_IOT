#ifndef WIOT_FLOW_METER_HPP
#define WIOT_FLOW_METER_HPP

#include <cstdint>

struct FlowData
{
  float flowRate;
  float velocity;
  float flowRate_per_day;
  float flowRate_per_month;
  float flowRate_per_year;
  uint16_t errorCode;
  bool isValid;
};

void initFlowMeter();
FlowData readAllParameters();
void printFlowData(const FlowData &data);

#endif
