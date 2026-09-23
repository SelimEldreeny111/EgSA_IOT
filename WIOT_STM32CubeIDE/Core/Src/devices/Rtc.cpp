#include "devices/Rtc.hpp"

#include "main.h"
#include "platform/Stm32Platform.hpp"

namespace
{
constexpr uint32_t kRtcMagic = 0x57494F54UL;

bool leapYear(uint16_t year)
{
  return (year % 4U == 0U && year % 100U != 0U) || year % 400U == 0U;
}

uint8_t daysInMonth(uint16_t year, uint8_t month)
{
  static const uint8_t days[] = {31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31};
  return month == 2U && leapYear(year) ? 29U : days[month - 1U];
}

void epochToDate(
    uint32_t epoch,
    uint16_t &year,
    uint8_t &month,
    uint8_t &day,
    uint8_t &hour,
    uint8_t &minute,
    uint8_t &second,
    uint8_t &weekday)
{
  uint32_t days = epoch / 86400UL;
  uint32_t seconds = epoch % 86400UL;
  hour = static_cast<uint8_t>(seconds / 3600UL);
  minute = static_cast<uint8_t>((seconds % 3600UL) / 60UL);
  second = static_cast<uint8_t>(seconds % 60UL);
  weekday = static_cast<uint8_t>(((days + 3U) % 7U) + 1U); // Monday=1

  year = 1970U;
  while (days >= (leapYear(year) ? 366U : 365U))
  {
    days -= leapYear(year) ? 366U : 365U;
    ++year;
  }
  month = 1U;
  while (days >= daysInMonth(year, month))
  {
    days -= daysInMonth(year, month);
    ++month;
  }
  day = static_cast<uint8_t>(days + 1U);
}
}

void initializeRtc()
{
  HAL_PWR_EnableBkUpAccess();
}

bool isRtcTimeSet()
{
  return HAL_RTCEx_BKUPRead(&hrtc, RTC_BKP_DR0) == kRtcMagic;
}

void setRtcEpoch(uint32_t epoch)
{
  uint16_t year;
  uint8_t month, day, hour, minute, second, weekday;
  epochToDate(epoch, year, month, day, hour, minute, second, weekday);

  RTC_TimeTypeDef time{};
  time.Hours = hour;
  time.Minutes = minute;
  time.Seconds = second;
  time.DayLightSaving = RTC_DAYLIGHTSAVING_NONE;
  time.StoreOperation = RTC_STOREOPERATION_RESET;
  RTC_DateTypeDef date{};
  date.WeekDay = weekday;
  date.Month = month;
  date.Date = day;
  date.Year = static_cast<uint8_t>(year - 2000U);
  (void)HAL_RTC_SetTime(&hrtc, &time, RTC_FORMAT_BIN);
  (void)HAL_RTC_SetDate(&hrtc, &date, RTC_FORMAT_BIN);
  HAL_RTCEx_BKUPWrite(&hrtc, RTC_BKP_DR0, kRtcMagic);
}

void syncRTCFromEpoch(uint32_t epoch)
{
  setRtcEpoch(epoch);
  SerialMon.println("RTC synchronized from epoch");
}

uint32_t getEpochTime()
{
  RTC_TimeTypeDef time{};
  RTC_DateTypeDef date{};
  if (HAL_RTC_GetTime(&hrtc, &time, RTC_FORMAT_BIN) != HAL_OK ||
      HAL_RTC_GetDate(&hrtc, &date, RTC_FORMAT_BIN) != HAL_OK)
  {
    return 0U;
  }
  const uint16_t year = 2000U + date.Year;
  uint32_t days = 0U;
  for (uint16_t current = 1970U; current < year; ++current)
    days += leapYear(current) ? 366U : 365U;
  for (uint8_t month = 1U; month < date.Month; ++month)
    days += daysInMonth(year, month);
  days += date.Date - 1U;
  return days * 86400UL + time.Hours * 3600UL + time.Minutes * 60UL + time.Seconds;
}

void printRtcDateTime()
{
  RTC_TimeTypeDef time{};
  RTC_DateTypeDef date{};
  (void)HAL_RTC_GetTime(&hrtc, &time, RTC_FORMAT_BIN);
  (void)HAL_RTC_GetDate(&hrtc, &date, RTC_FORMAT_BIN);
  SerialMon.printf("RTC %04u-%02u-%02u %02u:%02u:%02u\r\n",
                   2000U + date.Year, date.Month, date.Date,
                   time.Hours, time.Minutes, time.Seconds);
}
