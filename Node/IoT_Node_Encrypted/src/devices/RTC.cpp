/** @file RTC.cpp @brief RTC initialization, trust state, time conversion, and backup registers. */
#include "RTC.h"
#include "BackupDomainAccess.h"

#include "../config/AppConfig.h"
#include "../platform/Watchdog.h"

STM32RTC& rtc = STM32RTC::getInstance();

extern HardwareSerial SerialMon;

namespace
{
bool g_rtcInitializedThisBoot = false;
constexpr uint32_t kRtcTrustedMagic = 0x52544332UL; // "RTC2"
constexpr uint32_t kRtcTrustedBackupRegister = RTC_BKP_DR14;

/** @brief Apply Gregorian leap-year rules to a calendar year. */
bool isLeapYear(uint16_t year)
{
  return (year % 4U == 0U && year % 100U != 0U) || year % 400U == 0U;
}

/** @brief Return the number of days in a valid month, including leap February. */
uint8_t daysInMonth(uint16_t year, uint8_t month)
{
  static const uint8_t kMonthDays[] =
      {31U, 28U, 31U, 30U, 31U, 30U, 31U, 31U, 30U, 31U, 30U, 31U};
  return month == 2U && isLeapYear(year)
      ? 29U
      : kMonthDays[month - 1U];
}

/** @brief Create a HAL handle for RTC backup-register access. */
RTC_HandleTypeDef makeBackupHandle()
{
  RTC_HandleTypeDef handle = {};
  handle.Instance = RTC;
  return handle;
}

/** @brief Read a backup register with temporary backup-domain access. */
uint32_t readBackupRegister(uint32_t backupRegister)
{
  const BackupDomainAccess access;
  RTC_HandleTypeDef handle = makeBackupHandle();
  const uint32_t value = HAL_RTCEx_BKUPRead(&handle, backupRegister);
  return value;
}

/** @brief Write a backup register with temporary backup-domain access. */
void writeBackupRegister(uint32_t backupRegister, uint32_t value)
{
  const BackupDomainAccess access;
  RTC_HandleTypeDef handle = makeBackupHandle();
  HAL_RTCEx_BKUPWrite(&handle, backupRegister, value);
}

/** @brief Derive the UTC calendar year from Unix seconds. */
uint16_t yearFromEpoch(uint32_t epoch)
{
  uint32_t days = epoch / 86400UL;
  uint16_t year = 1970U;
  while (true)
  {
    const uint16_t yearDays = isLeapYear(year) ? 366U : 365U;
    if (days < yearDays)
    {
      return year;
    }
    days -= yearDays;
    ++year;
  }
}

/** @brief Split Unix seconds into UTC year, month, and day. */
void epochToDate(
    uint32_t epoch,
    uint16_t& year,
    uint8_t& month,
    uint8_t& day)
{
  uint32_t days = epoch / 86400UL;
  year = 1970U;
  while (true)
  {
    const uint16_t yearDays = isLeapYear(year) ? 366U : 365U;
    if (days < yearDays)
    {
      break;
    }
    days -= yearDays;
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

/** @brief Return weekday as Sunday=0 through Saturday=6. */
uint8_t weekday(uint16_t year, uint8_t month, uint8_t day)
{
  // 1970-01-01 was Thursday. Return 0=Sunday through 6=Saturday.
  return static_cast<uint8_t>(
      ((dateToEpoch(year, month, day, 0U, 0U, 0U) / 86400UL) + 4UL) % 7UL);
}

/** @brief Find the final occurrence of a weekday in a valid month. */
uint8_t lastWeekdayOfMonth(
    uint16_t year,
    uint8_t month,
    uint8_t targetWeekday)
{
  uint8_t day = daysInMonth(year, month);
  while (weekday(year, month, day) != targetWeekday)
  {
    --day;
  }
  return day;
}

/** @brief Apply the firmware's offline Cairo DST rule to a UTC epoch. */
bool isCairoDst(uint32_t epoch)
{
  const uint16_t year = yearFromEpoch(epoch);
  const uint8_t lastFridayApril = lastWeekdayOfMonth(year, 4U, 5U);
  const uint8_t lastThursdayOctober = lastWeekdayOfMonth(year, 10U, 4U);

  // Offline-capable Africa/Cairo policy matching the IANA rule used since
  // 2023: EET-2EEST,M4.5.5/0,M10.5.4/24. RTC/transmitted timestamps stay UTC;
  // this conversion is used only for local calendar period keys.
  const uint32_t startUtc =
      dateToEpoch(year, 4U, lastFridayApril, 0U, 0U, 0U) - 2UL * 3600UL;
  const uint32_t endUtc =
      dateToEpoch(year, 10U, lastThursdayOctober, 0U, 0U, 0U) +
      24UL * 3600UL - 3UL * 3600UL;
  return epoch >= startUtc && epoch < endUtc;
}
}

void initializeRtc()
{
  if (g_rtcInitializedThisBoot)
  {
    return;
  }

  rtc.begin();
  g_rtcInitializedThisBoot = true;
}

bool isRtcTimeSet()
{
  return rtc.isTimeSet();
}

bool isRtcTrusted()
{
  if (!g_rtcInitializedThisBoot)
  {
    initializeRtc();
  }
  return rtc.isTimeSet() &&
      getEpochTime() >= AppConfig::kPowerMinimumValidRtcEpoch &&
      readBackupRegister(kRtcTrustedBackupRegister) == kRtcTrustedMagic;
}

void setRtcEpoch(uint32_t epoch)
{
  const BackupDomainAccess access;
  rtc.setEpoch(epoch);
  // Placeholder dates must never drive calendar consumption. Only STIME
  // synchronization marks the backup-domain clock as trusted.
  writeBackupRegister(kRtcTrustedBackupRegister, 0U);
}

void printRtcDateTime()
{
  SerialMon.print("Current RTC time is : ");
  SerialMon.printf("%04d-%02d-%02d %02d:%02d:%02d\n",
                   2000 + rtc.getYear(),
                   rtc.getMonth(),
                   rtc.getDay(),
                   rtc.getHours(),
                   rtc.getMinutes(),
                   rtc.getSeconds());
}

uint32_t getEpochTime()
{
  const uint16_t year = 2000 + rtc.getYear();
  const uint8_t month = rtc.getMonth();
  const uint8_t day = rtc.getDay();
  const uint8_t hour = rtc.getHours();
  const uint8_t minute = rtc.getMinutes();
  const uint8_t second = rtc.getSeconds();

  return dateToEpoch(year, month, day, hour, minute, second);
}

bool scheduleRtcWakeAlarm(uint32_t epoch)
{
  if (!g_rtcInitializedThisBoot)
  {
    initializeRtc();
  }

  const BackupDomainAccess access;
  rtc.disableAlarm(STM32RTC::ALARM_A);
  rtc.setAlarmEpoch(
      static_cast<time_t>(epoch),
      STM32RTC::MATCH_DHHMMSS,
      STM32RTC::ALARM_A);

  RTC_HandleTypeDef* handle = rtc.getHandle();
  return handle != nullptr &&
      handle->Instance != nullptr &&
      (handle->Instance->CR & RTC_CR_ALRAE) != 0U;
}

void cancelRtcWakeAlarm()
{
  if (!g_rtcInitializedThisBoot)
  {
    initializeRtc();
  }

  const BackupDomainAccess access;
  rtc.disableAlarm(STM32RTC::ALARM_A);
  RTC_HandleTypeDef* handle = rtc.getHandle();
  if (handle == nullptr || handle->Instance == nullptr)
  {
    return;
  }

  __HAL_RTC_ALARM_CLEAR_FLAG(handle, RTC_FLAG_ALRAF);
  __HAL_RTC_ALARM_EXTI_CLEAR_FLAG();
}

uint32_t dateToEpoch(
    uint16_t year,
    uint8_t month,
    uint8_t day,
    uint8_t hour,
    uint8_t minute,
    uint8_t second)
{
  uint32_t days = 0U;
  for (uint16_t y = 1970U; y < year; ++y)
  {
    days += isLeapYear(y) ? 366UL : 365UL;
  }

  for (uint8_t m = 1U; m < month; ++m)
  {
    days += daysInMonth(year, m);
  }

  days += day - 1U;
  return days * 86400UL +
      static_cast<uint32_t>(hour) * 3600UL +
      static_cast<uint32_t>(minute) * 60UL + second;
}

bool syncRTCFromEpoch(uint32_t epoch)
{
  // STM32RTC's calendar stores two-digit years in the range 2000..2099.
  constexpr uint32_t kFirstUnsupportedEpoch = 4102444800UL; // 2100-01-01 UTC
  if (epoch < AppConfig::kPowerMinimumValidRtcEpoch ||
      epoch >= kFirstUnsupportedEpoch)
  {
    SerialMon.println("ERROR: STIME epoch outside supported RTC range");
    return false;
  }

  serviceHardwareWatchdog(WatchdogStage::RtcSynchronization);
  if (!g_rtcInitializedThisBoot)
  {
    initializeRtc();
  }

  const uint32_t secondsInDay = epoch % 86400UL;

  const uint8_t hour = secondsInDay / 3600UL;
  const uint8_t minute = (secondsInDay % 3600UL) / 60UL;
  const uint8_t second = secondsInDay % 60UL;

  uint16_t year = 0U;
  uint8_t month = 0U;
  uint8_t day = 0U;
  epochToDate(epoch, year, month, day);

  const BackupDomainAccess access;
  writeBackupRegister(kRtcTrustedBackupRegister, 0U);
  if (readBackupRegister(kRtcTrustedBackupRegister) != 0U)
  {
    // Do not partially replace an already trusted clock if invalidation failed.
    SerialMon.println("ERROR: RTC trust marker could not be cleared");
    serviceHardwareWatchdog();
    return false;
  }
  const uint8_t rtcWeekday = static_cast<uint8_t>(
      (weekday(year, month, day) + 6U) % 7U + 1U); // Monday=1, Sunday=7
  // Two complete writes avoid intermediate invalid dates (e.g. Jan 31 -> Feb).
  rtc.setDate(rtcWeekday, day, month, static_cast<uint8_t>(year - 2000U));
  rtc.setTime(hour, minute, second);

  const uint32_t actualEpoch = getEpochTime();
  if (!rtc.isTimeSet() || actualEpoch < epoch || actualEpoch - epoch > 2U)
  {
    SerialMon.print("ERROR: RTC sync verification failed; requested=");
    SerialMon.print(epoch);
    SerialMon.print(" actual=");
    SerialMon.println(actualEpoch);
    serviceHardwareWatchdog();
    return false;
  }

  writeBackupRegister(kRtcTrustedBackupRegister, kRtcTrustedMagic);
  if (readBackupRegister(kRtcTrustedBackupRegister) != kRtcTrustedMagic)
  {
    SerialMon.println("ERROR: RTC trust marker write failed");
    serviceHardwareWatchdog();
    return false;
  }

  SerialMon.println("RTC synced from epoch (verified)");
  printRtcDateTime();
  serviceHardwareWatchdog();
  return true;
}

int16_t getCalendarUtcOffsetMinutes(uint32_t epoch)
{
  if (AppConfig::kCalendarTimezone == APP_CALENDAR_TIMEZONE_UTC)
  {
    return 0;
  }
  if (AppConfig::kCalendarTimezone == APP_CALENDAR_TIMEZONE_FIXED_OFFSET)
  {
    return AppConfig::kCalendarFixedUtcOffsetMinutes;
  }
  return static_cast<int16_t>(isCairoDst(epoch) ? 180 : 120);
}

bool getCalendarPeriodKeys(uint32_t epoch, CalendarPeriodKeys& keys)
{
  const int16_t offsetMinutes = getCalendarUtcOffsetMinutes(epoch);
  const int64_t adjustedEpoch =
      static_cast<int64_t>(epoch) + static_cast<int64_t>(offsetMinutes) * 60LL;
  if (adjustedEpoch < 0LL || adjustedEpoch > UINT32_MAX)
  {
    return false;
  }

  uint16_t year = 0U;
  uint8_t month = 0U;
  uint8_t day = 0U;
  epochToDate(static_cast<uint32_t>(adjustedEpoch), year, month, day);
  keys.day =
      static_cast<uint32_t>(year) * 10000UL +
      static_cast<uint32_t>(month) * 100UL + day;
  keys.month = static_cast<uint32_t>(year) * 100UL + month;
  keys.year = year;
  keys.utcOffsetMinutes = offsetMinutes;
  return true;
}
