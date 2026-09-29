#ifndef TEST_STM32RTC_H
#define TEST_STM32RTC_H

#include "Arduino.h"
#include <ctime>

/** Mock failed writes just like STM32RTC: setters return void and set timeSet. */
class STM32RTC
{
public:
    enum { ALARM_A = 0, MATCH_DHHMMSS = 1 };
    static STM32RTC& getInstance();
    void begin();
    bool isTimeSet() const { return timeSet; }
    void setEpoch(uint32_t epoch);
    void setDate(uint8_t weekday, uint8_t day, uint8_t month, uint8_t year);
    void setTime(uint8_t hour, uint8_t minute, uint8_t second);
    uint8_t getYear() const { return year; }
    uint8_t getMonth() const { return month; }
    uint8_t getDay() const { return day; }
    uint8_t getHours() const { return hour; }
    uint8_t getMinutes() const { return minute; }
    uint8_t getSeconds() const { return second; }
    void disableAlarm(int);
    void setAlarmEpoch(std::time_t, int, int);
    RTC_HandleTypeDef* getHandle();

    bool ignoreClockWrites = false;
    bool timeSet = false;
    unsigned dateWrites = 0U;
    unsigned timeWrites = 0U;
    uint8_t weekDay = 1U;
    uint8_t year = 24U, month = 1U, day = 1U;
    uint8_t hour = 0U, minute = 0U, second = 0U;
};

#endif
