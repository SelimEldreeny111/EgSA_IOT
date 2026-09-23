#ifndef SUPMEA_PERIOD_ACCUMULATOR_H
#define SUPMEA_PERIOD_ACCUMULATOR_H

#include <stdint.h>

#include "AppState.h"

struct SupmeaPeriodResult
{
    uint64_t volumeTodayLiters;
    uint64_t volumeThisMonthLiters;
    uint64_t volumeThisYearLiters;
    FlowPeriodQuality quality;
    bool valid;
};

void initializeSupmeaPeriodAccumulator();
SupmeaPeriodResult updateSupmeaPeriodAccumulator(
    uint64_t forwardTotalLiters,
    uint32_t sampleEpoch,
    bool rtcTrusted);

#endif
