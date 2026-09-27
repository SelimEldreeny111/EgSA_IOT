/** @file SupmeaPeriodAccumulator.cpp @brief RTC-bucketed Supmea totals and persistence. */
#include "SupmeaPeriodAccumulator.h"

#include "../config/AppConfig.h"
#include "../devices/RTC.h"
#include "../platform/Watchdog.h"

#include <Arduino.h>
#include <EEPROM.h>
#include <string.h>

extern HardwareSerial SerialMon;

namespace
{
constexpr uint32_t kStateMagic = 0x464C4F57UL; // "FLOW"
constexpr uint8_t kStateVersion = 1U;
constexpr uint8_t kInitializedFlag = 0x01U;
constexpr uint32_t kFirstBackupRegister = RTC_BKP_DR0;
constexpr size_t kBackupRegisterCount = 14U;

/** @brief Checksummed, versioned flow state laid out for RTC backup registers. */
struct StoredFlowState
{
    uint32_t magic;
    uint32_t header;
    uint32_t lastEpoch;
    uint32_t lastForwardLow;
    uint32_t lastForwardHigh;
    uint32_t dayVolumeLow;
    uint32_t dayVolumeHigh;
    uint32_t monthVolumeLow;
    uint32_t monthVolumeHigh;
    uint32_t yearVolumeLow;
    uint32_t yearVolumeHigh;
    uint32_t dayKey;
    uint32_t reserved;
    uint32_t checksum;
};

static_assert(
    sizeof(StoredFlowState) == kBackupRegisterCount * sizeof(uint32_t),
    "Supmea accumulator must fit RTC backup registers DR0-DR13");

/** @brief In-memory cumulative reference and active calendar buckets. */
struct RuntimeFlowState
{
    bool initialized;
    uint32_t lastEpoch;
    uint64_t lastForwardLiters;
    uint64_t dayVolumeLiters;
    uint64_t monthVolumeLiters;
    uint64_t yearVolumeLiters;
    uint32_t dayKey;
    FlowPeriodQuality quality;
};

RuntimeFlowState g_state = {};
uint32_t g_lastFlashSaveEpoch = 0U;

/** @brief Reassemble a 64-bit counter from two persisted words. */
uint64_t joinU64(uint32_t low, uint32_t high)
{
    return static_cast<uint64_t>(low) |
        (static_cast<uint64_t>(high) << 32U);
}

/** @brief Split a 64-bit counter for the 32-bit backup-register layout. */
void splitU64(uint64_t value, uint32_t& low, uint32_t& high)
{
    low = static_cast<uint32_t>(value);
    high = static_cast<uint32_t>(value >> 32U);
}

/** @brief Checksum persisted bytes other than the checksum field. */
uint32_t stateChecksum(const StoredFlowState& stored)
{
    const uint8_t* bytes = reinterpret_cast<const uint8_t*>(&stored);
    const size_t length = sizeof(stored) - sizeof(stored.checksum);
    uint32_t hash = 2166136261UL;
    for (size_t index = 0U; index < length; ++index)
    {
        hash ^= bytes[index];
        hash *= 16777619UL;
    }
    return hash;
}

/** @brief Pack version, meter type, quality, and initialization flag. */
uint32_t buildHeader(const RuntimeFlowState& state)
{
    const uint8_t flags = state.initialized ? kInitializedFlag : 0U;
    return static_cast<uint32_t>(kStateVersion) |
        (static_cast<uint32_t>(FlowMeterType::Supmea) << 8U) |
        (static_cast<uint32_t>(state.quality) << 16U) |
        (static_cast<uint32_t>(flags) << 24U);
}

/** @brief Serialize runtime counters into a checksummed persistent record. */
StoredFlowState encodeState(const RuntimeFlowState& state)
{
    StoredFlowState stored = {};
    stored.magic = kStateMagic;
    stored.header = buildHeader(state);
    stored.lastEpoch = state.lastEpoch;
    splitU64(
        state.lastForwardLiters,
        stored.lastForwardLow,
        stored.lastForwardHigh);
    splitU64(
        state.dayVolumeLiters,
        stored.dayVolumeLow,
        stored.dayVolumeHigh);
    splitU64(
        state.monthVolumeLiters,
        stored.monthVolumeLow,
        stored.monthVolumeHigh);
    splitU64(
        state.yearVolumeLiters,
        stored.yearVolumeLow,
        stored.yearVolumeHigh);
    stored.dayKey = state.dayKey;
    stored.checksum = stateChecksum(stored);
    return stored;
}

/** @brief Validate a persistent record before restoring flow counters. */
bool decodeState(const StoredFlowState& stored, RuntimeFlowState& state)
{
    const uint8_t version = static_cast<uint8_t>(stored.header);
    const FlowMeterType meterType =
        static_cast<FlowMeterType>((stored.header >> 8U) & 0xFFU);
    const uint8_t flags = static_cast<uint8_t>(stored.header >> 24U);
    const uint8_t qualityValue =
        static_cast<uint8_t>((stored.header >> 16U) & 0xFFU);

    if (stored.magic != kStateMagic ||
        version != kStateVersion ||
        meterType != FlowMeterType::Supmea ||
        (flags & kInitializedFlag) == 0U ||
        qualityValue > static_cast<uint8_t>(FlowPeriodQuality::TimeUncertain) ||
        stored.lastEpoch < AppConfig::kPowerMinimumValidRtcEpoch ||
        stored.dayKey < 20000101UL || stored.dayKey > 20991231UL ||
        stored.checksum != stateChecksum(stored))
    {
        return false;
    }

    state.initialized = true;
    state.lastEpoch = stored.lastEpoch;
    state.lastForwardLiters =
        joinU64(stored.lastForwardLow, stored.lastForwardHigh);
    state.dayVolumeLiters =
        joinU64(stored.dayVolumeLow, stored.dayVolumeHigh);
    state.monthVolumeLiters =
        joinU64(stored.monthVolumeLow, stored.monthVolumeHigh);
    state.yearVolumeLiters =
        joinU64(stored.yearVolumeLow, stored.yearVolumeHigh);
    state.dayKey = stored.dayKey;
    state.quality = static_cast<FlowPeriodQuality>(qualityValue);
    return true;
}

/** @brief Create the HAL RTC handle used by backup-register operations. */
RTC_HandleTypeDef makeBackupHandle()
{
    RTC_HandleTypeDef handle = {};
    handle.Instance = RTC;
    return handle;
}

/** @brief Read the complete accumulator record from RTC backup registers. */
StoredFlowState readBackupState()
{
    StoredFlowState stored = {};
    uint32_t* words = reinterpret_cast<uint32_t*>(&stored);
    __HAL_RCC_PWR_CLK_ENABLE();
    HAL_PWR_EnableBkUpAccess();
    __HAL_RCC_RTC_ENABLE();
    RTC_HandleTypeDef handle = makeBackupHandle();
    for (size_t index = 0U; index < kBackupRegisterCount; ++index)
    {
        words[index] = HAL_RTCEx_BKUPRead(
            &handle,
            kFirstBackupRegister + static_cast<uint32_t>(index) * 4U);
    }
    HAL_PWR_DisableBkUpAccess();
    return stored;
}

/** @brief Copy the accumulator record to RTC backup registers. */
void writeBackupState(const StoredFlowState& stored)
{
    const uint32_t* words = reinterpret_cast<const uint32_t*>(&stored);
    __HAL_RCC_PWR_CLK_ENABLE();
    HAL_PWR_EnableBkUpAccess();
    __HAL_RCC_RTC_ENABLE();
    RTC_HandleTypeDef handle = makeBackupHandle();
    for (size_t index = 0U; index < kBackupRegisterCount; ++index)
    {
        HAL_RTCEx_BKUPWrite(
            &handle,
            kFirstBackupRegister + static_cast<uint32_t>(index) * 4U,
            words[index]);
    }
    HAL_PWR_DisableBkUpAccess();
}

/** @brief Clear both backup and EEPROM copies when explicit reset is configured. */
void clearStoredState()
{
    const StoredFlowState empty = {};
    writeBackupState(empty);
    EEPROM.put(AppConfig::kFlowAccumulatorEepromAddress, empty);
}

/** @brief Load and validate the EEPROM fallback copy. */
bool readFlashState(RuntimeFlowState& state)
{
    StoredFlowState stored = {};
    EEPROM.get(AppConfig::kFlowAccumulatorEepromAddress, stored);
    return decodeState(stored, state);
}

/** @brief Save a durable EEPROM copy and verify it by readback. */
bool writeFlashState(const RuntimeFlowState& state)
{
    const StoredFlowState stored = encodeState(state);
    EEPROM.put(AppConfig::kFlowAccumulatorEepromAddress, stored);
    StoredFlowState verified = {};
    EEPROM.get(AppConfig::kFlowAccumulatorEepromAddress, verified);
    return memcmp(&stored, &verified, sizeof(stored)) == 0;
}

/** @brief Refresh the low-wear backup-register working copy. */
void persistWorkingState()
{
    if (g_state.initialized)
    {
        writeBackupState(encodeState(g_state));
    }
}

/** @brief Save an EEPROM checkpoint with a serial-log reason. */
void persistDurableState(const char* reason)
{
    serviceHardwareWatchdog();
    if (writeFlashState(g_state))
    {
        g_lastFlashSaveEpoch = g_state.lastEpoch;
        SerialMon.print("Supmea period state saved to EEPROM: ");
        SerialMon.println(reason);
    }
    else
    {
        SerialMon.println("ERROR: Supmea period state EEPROM verification failed");
    }
    serviceHardwareWatchdog();
}

/** @brief Derive YYYYMM from a YYYYMMDD calendar key. */
uint32_t monthKeyFromDay(uint32_t dayKey)
{
    return dayKey / 100UL;
}

/** @brief Derive YYYY from a YYYYMMDD calendar key. */
uint16_t yearKeyFromDay(uint32_t dayKey)
{
    return static_cast<uint16_t>(dayKey / 10000UL);
}

/** @brief Reset crossed day, month, or year buckets without adding volume. */
void rollPeriodsWithoutVolume(const CalendarPeriodKeys& currentKeys)
{
    if (currentKeys.day == g_state.dayKey)
    {
        return;
    }
    const uint32_t previousMonth = monthKeyFromDay(g_state.dayKey);
    const uint16_t previousYear = yearKeyFromDay(g_state.dayKey);
    g_state.dayVolumeLiters = 0U;
    if (currentKeys.month != previousMonth)
    {
        g_state.monthVolumeLiters = 0U;
    }
    if (currentKeys.year != previousYear)
    {
        g_state.yearVolumeLiters = 0U;
    }
    g_state.dayKey = currentKeys.day;
}

enum class KeyPart : uint8_t
{
    Day,
    Month,
    Year,
};

/** @brief Select the requested day, month, or year calendar key. */
uint32_t selectKey(const CalendarPeriodKeys& keys, KeyPart part)
{
    if (part == KeyPart::Day)
    {
        return keys.day;
    }
    if (part == KeyPart::Month)
    {
        return keys.month;
    }
    return keys.year;
}

/** @brief Binary-search the first second of the current calendar bucket. */
uint32_t findCurrentPeriodStart(
    uint32_t fromEpoch,
    uint32_t toEpoch,
    uint32_t currentKey,
    KeyPart part)
{
    uint32_t low = fromEpoch + 1U;
    uint32_t high = toEpoch;
    while (low < high)
    {
        const uint32_t middle = low + (high - low) / 2U;
        CalendarPeriodKeys keys = {};
        if (!getCalendarPeriodKeys(middle, keys) ||
            selectKey(keys, part) == currentKey)
        {
            high = middle;
        }
        else
        {
            low = middle + 1U;
        }
    }
    return low;
}

/** @brief Allocate an interval's liters in proportion to elapsed seconds. */
uint64_t proportionalVolume(
    uint64_t volumeLiters,
    uint32_t numeratorSeconds,
    uint32_t denominatorSeconds)
{
    if (denominatorSeconds == 0U || numeratorSeconds >= denominatorSeconds)
    {
        return volumeLiters;
    }
    const uint64_t quotient = volumeLiters / denominatorSeconds;
    const uint64_t remainder = volumeLiters % denominatorSeconds;
    return quotient * numeratorSeconds +
        (remainder * numeratorSeconds) / denominatorSeconds;
}

/** @brief Estimate the part of a meter delta belonging to the current bucket. */
uint64_t volumeInCurrentPeriod(
    uint64_t deltaLiters,
    uint32_t previousEpoch,
    uint32_t currentEpoch,
    uint32_t currentKey,
    KeyPart part)
{
    const uint32_t periodStart = findCurrentPeriodStart(
        previousEpoch,
        currentEpoch,
        currentKey,
        part);
    return proportionalVolume(
        deltaLiters,
        currentEpoch - periodStart,
        currentEpoch - previousEpoch);
}

/** @brief Flag deltas above the configured maximum-flow safety envelope. */
bool jumpIsPhysicallyImpossible(uint64_t deltaLiters, uint32_t elapsedSeconds)
{
    if (AppConfig::kSupmeaMaxExpectedFlowM3h <= 0.0f)
    {
        return false;
    }
    if (elapsedSeconds == 0U)
    {
        return deltaLiters > AppConfig::kSupmeaCounterNoiseLiters;
    }
    const double maximumLiters =
        static_cast<double>(AppConfig::kSupmeaMaxExpectedFlowM3h) * 1000.0 *
        static_cast<double>(elapsedSeconds) / 3600.0 *
        static_cast<double>(AppConfig::kSupmeaMaxFlowSafetyFactor) +
        static_cast<double>(AppConfig::kSupmeaCounterNoiseLiters);
    return static_cast<double>(deltaLiters) > maximumLiters;
}

/** @brief Package active bucket values with their validity and quality state. */
SupmeaPeriodResult currentResult(bool valid)
{
    SupmeaPeriodResult result = {};
    result.volumeTodayLiters = g_state.dayVolumeLiters;
    result.volumeThisMonthLiters = g_state.monthVolumeLiters;
    result.volumeThisYearLiters = g_state.yearVolumeLiters;
    result.quality = valid ? g_state.quality : FlowPeriodQuality::TimeUncertain;
    result.valid = valid;
    return result;
}
}

void initializeSupmeaPeriodAccumulator()
{
    if (AppConfig::kResetSupmeaPeriodState)
    {
        clearStoredState();
        g_state = {};
        SerialMon.println(
            "Supmea period state RESET; set APP_RESET_SUPMEA_PERIOD_STATE back to 0");
        return;
    }

    RuntimeFlowState backupState = {};
    RuntimeFlowState flashState = {};
    const bool backupValid = decodeState(readBackupState(), backupState);
    const bool flashValid = readFlashState(flashState);

    if (backupValid && (!flashValid || backupState.lastEpoch >= flashState.lastEpoch))
    {
        g_state = backupState;
        g_lastFlashSaveEpoch = flashValid ? flashState.lastEpoch : 0U;
        SerialMon.println("Supmea period state restored from RTC backup domain");
    }
    else if (flashValid)
    {
        g_state = flashState;
        g_lastFlashSaveEpoch = flashState.lastEpoch;
        persistWorkingState();
        SerialMon.println("Supmea period state restored from EEPROM");
    }
    else
    {
        g_state = {};
        SerialMon.println("Supmea period state has no valid snapshot; waiting for baseline");
    }
}

SupmeaPeriodResult updateSupmeaPeriodAccumulator(
    uint64_t forwardTotalLiters,
    uint32_t sampleEpoch,
    bool rtcTrusted)
{
    CalendarPeriodKeys currentKeys = {};
    if (!rtcTrusted ||
        sampleEpoch < AppConfig::kPowerMinimumValidRtcEpoch ||
        !getCalendarPeriodKeys(sampleEpoch, currentKeys))
    {
        return currentResult(false);
    }

    if (!g_state.initialized)
    {
        g_state.initialized = true;
        g_state.lastEpoch = sampleEpoch;
        g_state.lastForwardLiters = forwardTotalLiters;
        g_state.dayKey = currentKeys.day;
        g_state.quality = FlowPeriodQuality::Partial;
        persistWorkingState();
        persistDurableState("initial baseline");
        return currentResult(true);
    }

    CalendarPeriodKeys previousKeys = {};
    if (sampleEpoch < g_state.lastEpoch ||
        !getCalendarPeriodKeys(g_state.lastEpoch, previousKeys))
    {
        g_state.lastEpoch = sampleEpoch;
        g_state.lastForwardLiters = forwardTotalLiters;
        if (currentKeys.day != g_state.dayKey)
        {
            g_state.dayVolumeLiters = 0U;
            if (currentKeys.month != monthKeyFromDay(g_state.dayKey))
            {
                g_state.monthVolumeLiters = 0U;
            }
            if (currentKeys.year != yearKeyFromDay(g_state.dayKey))
            {
                g_state.yearVolumeLiters = 0U;
            }
            g_state.dayKey = currentKeys.day;
        }
        // Keep future results conservatively partial after a backward clock
        // correction. A repeated second is allowed through the normal path
        // because sampling can legitimately occur near an RTC tick.
        g_state.quality = FlowPeriodQuality::Partial;
        persistWorkingState();
        persistDurableState("RTC moved backward");
        return currentResult(false);
    }

    const uint32_t elapsedSeconds = sampleEpoch - g_state.lastEpoch;
    uint64_t acceptedForwardLiters = forwardTotalLiters;
    if (acceptedForwardLiters < g_state.lastForwardLiters)
    {
        const uint64_t backwardsLiters =
            g_state.lastForwardLiters - acceptedForwardLiters;
        if (backwardsLiters <= AppConfig::kSupmeaCounterNoiseLiters)
        {
            // Keep the previous high-water mark so float quantization cannot
            // be counted again on the following sample.
            acceptedForwardLiters = g_state.lastForwardLiters;
        }
        else
        {
            rollPeriodsWithoutVolume(currentKeys);
            g_state.lastEpoch = sampleEpoch;
            g_state.lastForwardLiters = acceptedForwardLiters;
            g_state.quality = FlowPeriodQuality::CounterReset;
            persistWorkingState();
            persistDurableState("meter counter reset detected");
            return currentResult(true);
        }
    }

    const uint64_t deltaLiters =
        acceptedForwardLiters - g_state.lastForwardLiters;
    if (jumpIsPhysicallyImpossible(deltaLiters, elapsedSeconds))
    {
        rollPeriodsWithoutVolume(currentKeys);
        g_state.lastEpoch = sampleEpoch;
        g_state.lastForwardLiters = acceptedForwardLiters;
        g_state.quality = FlowPeriodQuality::Anomaly;
        persistWorkingState();
        persistDurableState("physically impossible counter jump");
        return currentResult(true);
    }

    const bool dayChanged = currentKeys.day != previousKeys.day;
    const bool monthChanged = currentKeys.month != previousKeys.month;
    const bool yearChanged = currentKeys.year != previousKeys.year;

    if (dayChanged)
    {
        g_state.dayVolumeLiters = volumeInCurrentPeriod(
            deltaLiters,
            g_state.lastEpoch,
            sampleEpoch,
            currentKeys.day,
            KeyPart::Day);
    }
    else
    {
        g_state.dayVolumeLiters += deltaLiters;
    }

    if (monthChanged)
    {
        g_state.monthVolumeLiters = volumeInCurrentPeriod(
            deltaLiters,
            g_state.lastEpoch,
            sampleEpoch,
            currentKeys.month,
            KeyPart::Month);
    }
    else
    {
        g_state.monthVolumeLiters += deltaLiters;
    }

    if (yearChanged)
    {
        g_state.yearVolumeLiters = volumeInCurrentPeriod(
            deltaLiters,
            g_state.lastEpoch,
            sampleEpoch,
            currentKeys.year,
            KeyPart::Year);
    }
    else
    {
        g_state.yearVolumeLiters += deltaLiters;
    }

    g_state.lastEpoch = sampleEpoch;
    g_state.lastForwardLiters = acceptedForwardLiters;
    g_state.dayKey = currentKeys.day;
    if (g_state.quality != FlowPeriodQuality::Partial || yearChanged)
    {
        g_state.quality = dayChanged || monthChanged || yearChanged
            ? FlowPeriodQuality::Estimated
            : FlowPeriodQuality::Valid;
    }

    persistWorkingState();
    const bool checkpointDue =
        AppConfig::kFlowFlashCheckpointSeconds > 0U &&
        (g_lastFlashSaveEpoch == 0U ||
         sampleEpoch - g_lastFlashSaveEpoch >=
             AppConfig::kFlowFlashCheckpointSeconds);
    if (dayChanged || monthChanged || yearChanged || checkpointDue)
    {
        persistDurableState(
            dayChanged || monthChanged || yearChanged
                ? "calendar boundary"
                : "periodic checkpoint");
    }
    return currentResult(true);
}
