/**
 * @file SupmeaSensor.h
 * @brief SUP-FMC240 electromagnetic flow-meter Modbus driver.
 */
#ifndef SUPMEA_SENSOR_H
#define SUPMEA_SENSOR_H

#include <stdint.h>

#include "../third_party/ModbusMaster/ModbusMaster.h"

/**
 * @brief Raw Supmea totalizer, flow rate, and velocity readings.
 *
 * FlowMeterManager converts the configured flow-rate unit to cubic metres
 * per hour and derives calendar consumption from the forward totalizer.
 */
struct SupmeaSensorData
{
    float forwardTotalM3;         ///< Cumulative forward volume in cubic metres.
    float reverseTotalM3;         ///< Cumulative reverse volume in cubic metres.
    float netTotalM3;             ///< Signed net volume in cubic metres.
    float flowRate;               ///< Instantaneous flow in the configured meter unit.
    float velocityMps;            ///< Fluid velocity in metres per second.
    uint8_t totalsResult;         ///< Modbus result for cumulative registers.
    uint8_t liveResult;           ///< Modbus result for live registers.
    bool totalsValid;             ///< Cumulative block passed transport/value checks.
    bool liveValid;               ///< Live block passed transport/value checks.
    bool isValid;                 ///< Overall sample validity reported by the driver.
};

extern ModbusMaster supmeaSensor;

/** @brief Bind the configured SUP-FMC240 slave and probe its live-flow block. */
void initializeSupmeaSensor();
/** @brief Read totalizer and live blocks with bounded retries. @return Raw values and independent validity flags. */
SupmeaSensorData readSupmeaSensor();
/** @brief Print the selected meter values and validity. @param data Sample to display. */
void printSupmeaSensorData(const SupmeaSensorData& data);

#endif
