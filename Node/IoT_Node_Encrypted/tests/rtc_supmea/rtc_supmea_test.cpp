// Host regression harness: actual production calculation/persistence code,
// with strict mocks for RTC registers, protected writes and flash emulation.
#include "../../src/devices/RTC.h"
#include "../../src/devices/BackupDomainAccess.h"
#include "../../src/app/SupmeaPeriodAccumulator.h"
#include "../../src/platform/Watchdog.h"
#include "fakes/EEPROM.h"

#include <algorithm>
#include <array>
#include <iostream>
#include <stdexcept>
#include <vector>

namespace AppConfig
{
uint8_t kCalendarTimezone = APP_CALENDAR_TIMEZONE_UTC;
float kSupmeaMaxExpectedFlowM3h = 0.0f;
uint32_t kFlowFlashCheckpointSeconds = 86400U;
bool kResetSupmeaPeriodState = false;
}

HardwareSerial SerialMon;
extern STM32RTC& rtc;
PWR_TypeDef g_power;
RTC_TypeDef g_rtc;
PWR_TypeDef* PWR = &g_power;
RTC_TypeDef* RTC = &g_rtc;
std::array<uint32_t, 20> g_backup = {};
std::array<uint8_t, E2END + 1U> g_flash, g_buffer;
std::vector<uint32_t> g_backupWrites;
std::vector<WatchdogStage> g_stages;
WatchdogStage g_stage = WatchdogStage::Unknown;
unsigned g_flashCommits = 0U;
uint32_t g_ticks = 0U;
bool g_ignoreFlashWrites = false;
bool g_ignoreTrustWrites = false;
bool g_inFlashOperation = false;

void require(bool condition, const char* message)
{
    if (!condition) { throw std::runtime_error(message); }
}

void HAL_PWR_EnableBkUpAccess() { PWR->CR |= PWR_CR_DBP; }
void HAL_PWR_DisableBkUpAccess() { PWR->CR &= ~PWR_CR_DBP; }
uint32_t HAL_RTCEx_BKUPRead(RTC_HandleTypeDef*, uint32_t index)
{
    require(index < g_backup.size(), "OUT-OF-RANGE RTC BACKUP READ");
    return g_backup[index];
}
void HAL_RTCEx_BKUPWrite(RTC_HandleTypeDef*, uint32_t index, uint32_t value)
{
    require(index < g_backup.size(), "OUT-OF-RANGE RTC BACKUP WRITE");
    require((PWR->CR & PWR_CR_DBP) != 0U, "Unprotected RTC backup write");
    g_backupWrites.push_back(index);
    if (!(g_ignoreTrustWrites && index == RTC_BKP_DR14)) { g_backup[index] = value; }
}
uint32_t millis() { return g_ticks; }
void markHardwareWatchdogStage(WatchdogStage stage)
{
    g_stage = stage;
    g_stages.push_back(stage);
}
void serviceHardwareWatchdog()
{
    require(!g_inFlashOperation, "Watchdog was fed inside blocking flash operation");
}
void serviceHardwareWatchdog(WatchdogStage stage)
{
    markHardwareWatchdogStage(stage);
    serviceHardwareWatchdog();
}

STM32RTC& STM32RTC::getInstance() { static STM32RTC instance; return instance; }
void STM32RTC::begin() { HAL_PWR_EnableBkUpAccess(); }
void STM32RTC::setEpoch(uint32_t epoch)
{
    const std::time_t timestamp = epoch;
    const std::tm* calendar = std::gmtime(&timestamp);
    require(calendar != nullptr, "Host epoch conversion failed");
    setDate(calendar->tm_wday == 0 ? 7 : calendar->tm_wday,
        calendar->tm_mday, calendar->tm_mon + 1, calendar->tm_year - 100);
    setTime(calendar->tm_hour, calendar->tm_min, calendar->tm_sec);
}
void STM32RTC::setDate(uint8_t wd, uint8_t d, uint8_t m, uint8_t y)
{
    ++dateWrites;
    timeSet = true; // Mirrors the library, even when the HAL write did not land.
    require((PWR->CR & PWR_CR_DBP) != 0U, "RTC date write while DBP disabled");
    if (!ignoreClockWrites) { weekDay = wd; day = d; month = m; year = y; }
}
void STM32RTC::setTime(uint8_t h, uint8_t m, uint8_t s)
{
    ++timeWrites;
    timeSet = true;
    require((PWR->CR & PWR_CR_DBP) != 0U, "RTC time write while DBP disabled");
    if (!ignoreClockWrites) { hour = h; minute = m; second = s; }
}
void STM32RTC::disableAlarm(int)
{
    require((PWR->CR & PWR_CR_DBP) != 0U, "Alarm write while DBP disabled");
    RTC->CR &= ~RTC_CR_ALRAE;
}
void STM32RTC::setAlarmEpoch(std::time_t, int, int)
{
    require((PWR->CR & PWR_CR_DBP) != 0U, "Alarm write while DBP disabled");
    RTC->CR |= RTC_CR_ALRAE;
}
RTC_HandleTypeDef* STM32RTC::getHandle()
{
    static RTC_HandleTypeDef handle;
    handle.Instance = RTC;
    return &handle;
}

void eeprom_buffer_fill() { g_buffer = g_flash; }
uint8_t eeprom_buffered_read_byte(uint32_t address)
{
    require(address < g_buffer.size(), "EEPROM read outside buffer");
    return g_buffer[address];
}
void eeprom_buffered_write_byte(uint32_t address, uint8_t value)
{
    require(address < g_buffer.size(), "EEPROM write outside buffer");
    g_buffer[address] = value;
}
void eeprom_buffer_flush()
{
    require(g_stage == WatchdogStage::SupmeaFlashStorage, "Missing flash watchdog stage");
    g_inFlashOperation = true;
    ++g_flashCommits;
    g_ticks += 900U; // A bounded erase/program cycle; no fake in-operation feeding.
    if (!g_ignoreFlashWrites) { g_flash = g_buffer; }
    g_inFlashOperation = false;
}

constexpr uint32_t kEpoch = 1790686800U; // A valid 2026 UTC timestamp.
void setupPersistence()
{
    initializeRtc();
    require(syncRTCFromEpoch(kEpoch), "STIME setup failed");
    for (size_t index = 15U; index < g_backup.size(); ++index)
    {
        g_backup[index] = 0x12340000U + index;
    }
    initializeSupmeaPeriodAccumulator();
    g_backupWrites.clear();
}

void checkOtherStorage(const std::array<uint8_t, E2END + 1U>& before)
{
    for (size_t index = 0U; index < before.size(); ++index)
    {
        if (index < 128U || index >= 184U)
        {
            require(g_flash[index] == before[index], "Unrelated EEPROM record changed");
        }
    }
    for (size_t index = 15U; index < g_backup.size(); ++index)
    {
        require(g_backup[index] == 0x12340000U + index, "Power-down backup record changed");
    }
    require(isRtcTrusted(), "Supmea snapshot damaged RTC trust marker");
    require(std::all_of(g_backupWrites.begin(), g_backupWrites.end(),
        [](uint32_t index) { return index <= RTC_BKP_DR13; }),
        "Supmea wrote outside DR0..DR13");
}

void testBackupAccess()
{
    PWR->CR = 0U;
    {
        const BackupDomainAccess outer;
        require(PWR->CR & PWR_CR_DBP, "Guard did not enable writes");
        { const BackupDomainAccess nested; }
        require(PWR->CR & PWR_CR_DBP, "Nested guard revoked outer access");
    }
    require(!(PWR->CR & PWR_CR_DBP), "Guard did not restore disabled state");
    HAL_PWR_EnableBkUpAccess();
    { const BackupDomainAccess access; }
    require(PWR->CR & PWR_CR_DBP, "Guard revoked library-owned access");
}

void testStimeLocked()
{
    initializeRtc();
    HAL_PWR_DisableBkUpAccess();
    require(syncRTCFromEpoch(kEpoch), "STIME failed with initially disabled DBP");
    require(getEpochTime() == kEpoch && isRtcTrusted(), "Clock/trust mismatch");
    require(!(PWR->CR & PWR_CR_DBP), "STIME did not restore entry DBP state");
    require(rtc.dateWrites == 1U && rtc.timeWrites == 1U, "STIME used partial writes");
    require(SerialMon.output.str().find("(verified)") != std::string::npos,
        "Verified STIME log missing");
}

void testStimeRejected()
{
    require(!syncRTCFromEpoch(0U), "Accepted zero timestamp");
    require(!syncRTCFromEpoch(AppConfig::kPowerMinimumValidRtcEpoch - 1U),
        "Accepted placeholder-range timestamp");
    require(!syncRTCFromEpoch(4102444800UL), "Accepted year 2100");
    require(rtc.dateWrites == 0U && rtc.timeWrites == 0U, "Invalid STIME modified RTC");
}

void testStimeClockFailure()
{
    initializeRtc();
    rtc.ignoreClockWrites = true;
    require(!syncRTCFromEpoch(kEpoch), "Ignored RTC writes reported success");
    require(!isRtcTrusted(), "Failed STIME marked the clock trusted");
    require(SerialMon.output.str().find("RTC synced from epoch") == std::string::npos,
        "Failed STIME printed a success message");
}

void testStimeMarkerFailure()
{
    g_ignoreTrustWrites = true;
    require(!syncRTCFromEpoch(kEpoch), "Failed trust-marker write reported success");
    require(!isRtcTrusted(), "Missing trust marker accepted");
}

void testStimeStaleMarker()
{
    require(syncRTCFromEpoch(kEpoch), "Initial clock synchronization failed");
    const unsigned previousDateWrites = rtc.dateWrites;
    const unsigned previousTimeWrites = rtc.timeWrites;
    g_ignoreTrustWrites = true;
    require(!syncRTCFromEpoch(kEpoch + 600U), "Uncleared old marker was accepted");
    require(getEpochTime() == kEpoch && rtc.dateWrites == previousDateWrites &&
        rtc.timeWrites == previousTimeWrites, "Failed invalidation partially changed RTC");
}

void testUntrusted()
{
    initializeRtc();
    initializeSupmeaPeriodAccumulator();
    g_backupWrites.clear();
    const auto result = updateSupmeaPeriodAccumulator(1000000ULL, kEpoch, false);
    require(!result.valid && result.quality == FlowPeriodQuality::TimeUncertain,
        "Untrusted clock produced valid consumption");
    require(g_flashCommits == 0U && g_backupWrites.empty(),
        "Untrusted clock wrote consumption state");
}

void testBaselineAndRecovery()
{
    // Fill unrelated records with non-erased data, including stored WiFi bytes.
    for (size_t index = 0U; index < g_flash.size(); ++index)
    {
        g_flash[index] = static_cast<uint8_t>(index * 17U + 3U);
    }
    const auto before = g_flash;
    setupPersistence();
    auto result = updateSupmeaPeriodAccumulator(1000000ULL, kEpoch, true);
    require(result.valid && result.quality == FlowPeriodQuality::Partial &&
        result.volumeTodayLiters == 0U, "First sample did not establish a partial baseline");
    require(g_flashCommits == 1U, "Baseline did not use exactly ONE flash commit");
    require(!g_backupWrites.empty() && g_backupWrites.front() == RTC_BKP_DR0 &&
        g_backupWrites.back() == RTC_BKP_DR0, "Backup magic was not published last");
    result = updateSupmeaPeriodAccumulator(1001000ULL, kEpoch + 60U, true);
    require(result.volumeTodayLiters == 1000U && result.volumeThisMonthLiters == 1000U &&
        result.volumeThisYearLiters == 1000U, "Forward delta was not accumulated");
    require(g_flashCommits == 1U, "Normal sample unnecessarily rewrote flash");
    initializeSupmeaPeriodAccumulator(); // Reset recovery restores the newer backup.
    result = updateSupmeaPeriodAccumulator(1002000ULL, kEpoch + 120U, true);
    require(result.volumeTodayLiters == 2000U, "Backup recovery lost or double-counted volume");
    checkOtherStorage(before);
}

void testCounterReset()
{
    setupPersistence();
    updateSupmeaPeriodAccumulator(1000000ULL, kEpoch, true);
    updateSupmeaPeriodAccumulator(1001000ULL, kEpoch + 60U, true);
    const auto result = updateSupmeaPeriodAccumulator(500000ULL, kEpoch + 120U, true);
    require(result.valid && result.quality == FlowPeriodQuality::CounterReset &&
        result.volumeTodayLiters == 1000U, "Counter reset lost existing consumption");
    require(g_flashCommits == 2U, "Counter-reset checkpoint used multiple commits");
}

void testFlashFailureRetry()
{
    setupPersistence();
    g_ignoreFlashWrites = true;
    updateSupmeaPeriodAccumulator(1000000ULL, kEpoch, true);
    require(SerialMon.output.str().find("EEPROM verification failed") != std::string::npos,
        "Flash failure was not reported");
    g_ignoreFlashWrites = false;
    const auto result = updateSupmeaPeriodAccumulator(1001000ULL, kEpoch + 60U, true);
    require(g_flashCommits == 2U && result.volumeTodayLiters == 1000U,
        "Failed flash checkpoint was not retried without losing volume");
}

void testFlashFallback()
{
    setupPersistence();
    AppConfig::kFlowFlashCheckpointSeconds = 1U;
    updateSupmeaPeriodAccumulator(1000000ULL, kEpoch, true);
    updateSupmeaPeriodAccumulator(1001000ULL, kEpoch + 60U, true);
    std::fill(g_backup.begin(), g_backup.begin() + 14, 0U);
    initializeSupmeaPeriodAccumulator();
    const auto result = updateSupmeaPeriodAccumulator(1002000ULL, kEpoch + 120U, true);
    require(result.volumeTodayLiters == 2000U &&
        SerialMon.output.str().find("restored from EEPROM") != std::string::npos,
        "Flash fallback lost calendar state");
}

void testBoundary(bool yearBoundary)
{
    setupPersistence();
    const uint32_t from = yearBoundary
        ? dateToEpoch(2026U, 12U, 31U, 23U, 59U, 50U)
        : dateToEpoch(2026U, 9U, 29U, 23U, 59U, 50U);
    updateSupmeaPeriodAccumulator(1000000ULL, from, true);
    const auto result = updateSupmeaPeriodAccumulator(1001000ULL, from + 20U, true);
    require(result.volumeTodayLiters == 500U, "Midnight split was incorrect");
    require(result.volumeThisMonthLiters == (yearBoundary ? 500U : 1000U) &&
        result.volumeThisYearLiters == (yearBoundary ? 500U : 1000U),
        "Month/year boundary split was incorrect");
    require(g_flashCommits == 2U, "Boundary checkpoint used multiple commits");
}

void testCairoMidnight()
{
    setupPersistence();
    AppConfig::kCalendarTimezone = APP_CALENDAR_TIMEZONE_AFRICA_CAIRO;
    // September is UTC+3 under the configured offline Cairo calendar policy.
    const uint32_t from = dateToEpoch(2026U, 9U, 29U, 20U, 59U, 50U);
    CalendarPeriodKeys before = {}, after = {};
    require(getCalendarPeriodKeys(from, before) && before.day == 20260929U &&
        before.utcOffsetMinutes == 180, "Cairo calendar offset/key mismatch");
    require(getCalendarPeriodKeys(from + 20U, after) && after.day == 20260930U,
        "Cairo local midnight did not advance day key");
    updateSupmeaPeriodAccumulator(1000000ULL, from, true);
    const auto result = updateSupmeaPeriodAccumulator(1001000ULL, from + 20U, true);
    require(result.volumeTodayLiters == 500U && result.volumeThisMonthLiters == 1000U,
        "Cairo midnight consumption split was incorrect");
}

void testExplicitReset()
{
    setupPersistence();
    updateSupmeaPeriodAccumulator(1000000ULL, kEpoch, true);
    const auto before = g_flash;
    g_backupWrites.clear();
    AppConfig::kResetSupmeaPeriodState = true;
    initializeSupmeaPeriodAccumulator();
    require(g_flashCommits == 2U, "Explicit reset did not use one commit");
    initializeSupmeaPeriodAccumulator();
    require(g_flashCommits == 2U, "Unchanged empty checkpoint wore flash again");
    checkOtherStorage(before);
    AppConfig::kResetSupmeaPeriodState = false;
    initializeSupmeaPeriodAccumulator();
    const auto result = updateSupmeaPeriodAccumulator(1000000ULL, kEpoch, true);
    require(result.valid && result.volumeTodayLiters == 0U, "Reset did not allow a new baseline");
}

void testAlarmAccess()
{
    initializeRtc();
    HAL_PWR_DisableBkUpAccess();
    require(scheduleRtcWakeAlarm(kEpoch), "RTC wake alarm failed with locked DBP");
    require(!(PWR->CR & PWR_CR_DBP), "Alarm guard failed to restore DBP");
    cancelRtcWakeAlarm();
    require(!(RTC->CR & RTC_CR_ALRAE) && !(PWR->CR & PWR_CR_DBP),
        "Alarm cancellation/access restoration failed");
}

int main(int argc, char** argv)
{
    try
    {
        require(argc == 2, "Pass one test scenario (fresh process per scenario)");
        g_flash.fill(0xFFU);
        g_buffer.fill(0xFFU);
        const std::string scenario = argv[1];
        if (scenario == "backup_access") { testBackupAccess(); }
        else if (scenario == "stime_locked") { testStimeLocked(); }
        else if (scenario == "stime_invalid") { testStimeRejected(); }
        else if (scenario == "stime_clock_failure") { testStimeClockFailure(); }
        else if (scenario == "stime_marker_failure") { testStimeMarkerFailure(); }
        else if (scenario == "stime_stale_marker") { testStimeStaleMarker(); }
        else if (scenario == "untrusted_clock") { testUntrusted(); }
        else if (scenario == "baseline_and_backup_recovery") { testBaselineAndRecovery(); }
        else if (scenario == "counter_reset") { testCounterReset(); }
        else if (scenario == "flash_failure_retry") { testFlashFailureRetry(); }
        else if (scenario == "flash_fallback") { testFlashFallback(); }
        else if (scenario == "midnight") { testBoundary(false); }
        else if (scenario == "new_year") { testBoundary(true); }
        else if (scenario == "cairo_midnight") { testCairoMidnight(); }
        else if (scenario == "explicit_reset") { testExplicitReset(); }
        else if (scenario == "alarm_access") { testAlarmAccess(); }
        else { throw std::runtime_error("Unknown scenario"); }
        std::cout << "PASS " << scenario << '\n';
        return 0;
    }
    catch (const std::exception& error)
    {
        std::cerr << "FAIL: " << error.what() << '\n';
        return 1;
    }
}
