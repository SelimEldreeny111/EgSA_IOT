/**
 * @file RTC.h
 * @brief RTC trust, UTC conversion, calendar keys, and standby wake alarms.
 */
#ifndef RTC_HELPERS_H
#define RTC_HELPERS_H

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

#include <Arduino.h>
#include <STM32RTC.h>

/** @brief Local calendar identifiers derived from a UTC sample timestamp. */
struct CalendarPeriodKeys
{
  uint32_t day;              ///< YYYYMMDD in the configured calendar zone.
  uint32_t month;            ///< YYYYMM in the configured calendar zone.
  uint16_t year;             ///< Calendar year in the configured zone.
  int16_t utcOffsetMinutes;  ///< Offset applied to the UTC sample timestamp.
};

/** @brief Initialize the STM32 RTC once per boot. */
void initializeRtc();
/** @brief Check whether the RTC library has a date/time value. @return True if the RTC is set, even if it is not trusted. */
bool isRtcTimeSet();
/** @brief Check synchronized-time magic and the minimum valid epoch. @return True only for trusted calendar time. */
bool isRtcTrusted();
/** @brief Set an untrusted placeholder UTC epoch. @param epoch Unix seconds; clears the synchronized-time marker. */
void setRtcEpoch(uint32_t epoch);
/** @brief Print the RTC calendar fields to the diagnostic serial port. */
void printRtcDateTime();
/** @brief Synchronize UTC from an approved command and mark valid time trusted. @param epoch Unix seconds to apply. */
void syncRTCFromEpoch(uint32_t epoch);
/** @brief Arm RTC Alarm A for a standby wakeup. @param epoch Target UTC Unix second. @return True if the alarm is enabled in hardware. */
bool scheduleRtcWakeAlarm(uint32_t epoch);
/** @brief Disable Alarm A and clear its pending flags. */
void cancelRtcWakeAlarm();
/**
 * @brief Convert a UTC calendar date to Unix seconds.
 * @param year Full calendar year.
 * @param month Month, 1 through 12.
 * @param day Day of the month.
 * @param hour Hour, 0 through 23.
 * @param minute Minute, 0 through 59.
 * @param second Second, 0 through 59.
 * @return UTC Unix timestamp, within the uint32_t representable range.
 */
uint32_t dateToEpoch(
    uint16_t year,
    uint8_t month,
    uint8_t day,
    uint8_t hour,
    uint8_t minute,
    uint8_t second);
/** @brief Read the RTC fields as a UTC Unix timestamp. @return Seconds since 1970-01-01 UTC. */
uint32_t getEpochTime();
/** @brief Select UTC, fixed offset, or Cairo DST offset for a sample. @param epoch UTC Unix seconds. @return Offset east of UTC in minutes. */
int16_t getCalendarUtcOffsetMinutes(uint32_t epoch);
/** @brief Derive day/month/year period keys from a UTC sample. @param epoch UTC Unix seconds. @param keys Receives local calendar identifiers on success. @return False if offset adjustment overflows the supported epoch range. */
bool getCalendarPeriodKeys(uint32_t epoch, CalendarPeriodKeys& keys);

#endif
