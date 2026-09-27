/**
 * @file SupmeaPeriodAccumulator.h
 * @brief RTC-keyed consumption totals derived from Supmea forward totalizer.
 */
#ifndef SUPMEA_PERIOD_ACCUMULATOR_H
#define SUPMEA_PERIOD_ACCUMULATOR_H

#include <stdint.h>

#include "AppState.h"

/** @brief Calculated calendar totals and their trust classification. */
struct SupmeaPeriodResult
{
    uint64_t volumeTodayLiters;
    uint64_t volumeThisMonthLiters;
    uint64_t volumeThisYearLiters;
    FlowPeriodQuality quality;
    bool valid;
};

/**
 * @brief Restore a validated accumulator snapshot from backup registers or EEPROM.
 *
 * Invalid persisted state is discarded; the first trusted sample then becomes
 * the baseline rather than inventing consumption before boot.
 */
void initializeSupmeaPeriodAccumulator();
/**
 * @brief Advance day, month, and year totals from a cumulative meter sample.
 * @param forwardTotalLiters Meter's nondecreasing forward totalizer in litres.
 * @param sampleEpoch UTC timestamp associated with this meter sample.
 * @param rtcTrusted Whether the RTC is synchronized and valid for calendar keys.
 * @return Updated totals with validity and quality flags.
 */
SupmeaPeriodResult updateSupmeaPeriodAccumulator(
    uint64_t forwardTotalLiters,
    uint32_t sampleEpoch,
    bool rtcTrusted);

#endif
