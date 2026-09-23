#ifndef RTC_HELPERS_H
#define RTC_HELPERS_H

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

#include <Arduino.h>

void initializeRtc();
bool isRtcTimeSet();
void setRtcEpoch(uint32_t epoch);
void printRtcDateTime();
void syncRTCFromEpoch(uint32_t epoch);
bool scheduleRtcWakeAlarm(uint32_t epoch);
void cancelRtcWakeAlarm();
uint32_t dateToEpoch(
    uint16_t year,
    uint8_t month,
    uint8_t day,
    uint8_t hour,
    uint8_t minute,
    uint8_t second);
uint32_t getEpochTime();

#endif
