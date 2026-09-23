#ifndef WIOT_RTC_HPP
#define WIOT_RTC_HPP

#include <cstdint>

void initializeRtc();
bool isRtcTimeSet();
void setRtcEpoch(uint32_t epoch);
void syncRTCFromEpoch(uint32_t epoch);
uint32_t getEpochTime();
void printRtcDateTime();

#endif
