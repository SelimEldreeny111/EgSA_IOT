#ifndef RTC_HELPERS_H
#define RTC_HELPERS_H

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

#include <Arduino.h>
#include <STM32RTC.h>

struct CalendarPeriodKeys
{
  uint32_t day;
  uint32_t month;
  uint16_t year;
  int16_t utcOffsetMinutes;
};

void initializeRtc();
bool isRtcTimeSet();
bool isRtcTrusted();
void setRtcEpoch(uint32_t epoch);
void printRtcDateTime();
/** @brief Set UTC time; return true only after verifying clock and trust marker. */
bool syncRTCFromEpoch(uint32_t epoch);
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
int16_t getCalendarUtcOffsetMinutes(uint32_t epoch);
bool getCalendarPeriodKeys(uint32_t epoch, CalendarPeriodKeys& keys);

#endif
