#include "RTC.h"

#include "../config/AppConfig.h"

#include <esp_sleep.h>
#include <limits.h>
#include <sys/time.h>
#include <time.h>

extern HardwareSerial& SerialMon;

namespace
{
bool g_rtcInitializedThisBoot = false;

bool isLeapYear(uint16_t year)
{
  return ((year % 4U == 0U && year % 100U != 0U) ||
          (year % 400U == 0U));
}
}

void initializeRtc()
{
  // Arduino-ESP32 keeps POSIX system time from the RTC slow clock across
  // deep sleep. No external RTC library is required for timer wakeup.
  g_rtcInitializedThisBoot = true;
}

bool isRtcTimeSet()
{
  return getEpochTime() >= AppConfig::kPowerMinimumValidRtcEpoch;
}

void setRtcEpoch(uint32_t epoch)
{
  const timeval value = {static_cast<time_t>(epoch), 0};
  settimeofday(&value, nullptr);
  g_rtcInitializedThisBoot = true;
}

void printRtcDateTime()
{
  const time_t epoch = static_cast<time_t>(getEpochTime());
  tm utcTime = {};
  gmtime_r(&epoch, &utcTime);

  SerialMon.print("Current RTC time is : ");
  SerialMon.printf(
      "%04d-%02d-%02d %02d:%02d:%02d UTC\n",
      utcTime.tm_year + 1900,
      utcTime.tm_mon + 1,
      utcTime.tm_mday,
      utcTime.tm_hour,
      utcTime.tm_min,
      utcTime.tm_sec);
}

uint32_t getEpochTime()
{
  const time_t epoch = time(nullptr);
  if (epoch <= 0)
  {
    return 0U;
  }

  const uint64_t value = static_cast<uint64_t>(epoch);
  return value > UINT32_MAX ? UINT32_MAX : static_cast<uint32_t>(value);
}

bool scheduleRtcWakeAlarm(uint32_t epoch)
{
  if (!g_rtcInitializedThisBoot)
  {
    initializeRtc();
  }

  const uint32_t nowEpoch = getEpochTime();
  if (epoch <= nowEpoch)
  {
    return false;
  }

  const uint64_t sleepUs =
      static_cast<uint64_t>(epoch - nowEpoch) * 1000000ULL;
  return esp_sleep_enable_timer_wakeup(sleepUs) == ESP_OK;
}

void cancelRtcWakeAlarm()
{
  (void)esp_sleep_disable_wakeup_source(ESP_SLEEP_WAKEUP_TIMER);
}

uint32_t dateToEpoch(
    uint16_t year,
    uint8_t month,
    uint8_t day,
    uint8_t hour,
    uint8_t minute,
    uint8_t second)
{
  const uint8_t monthDays[] = { 31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31 };

  uint32_t days = 0;
  for (uint16_t y = 1970; y < year; y++)
  {
    days += isLeapYear(y) ? 366UL : 365UL;
  }

  for (uint8_t m = 1; m < month; m++)
  {
    days += monthDays[m - 1];
    if (m == 2 && isLeapYear(year))
    {
      days++;
    }
  }

  days += (day - 1);

  return days * 86400UL + hour * 3600UL + minute * 60UL + second;
}

void syncRTCFromEpoch(uint32_t epoch)
{
  setRtcEpoch(epoch);
  SerialMon.println("RTC synced from epoch");
}
