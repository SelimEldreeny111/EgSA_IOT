/**
 * @file TufSensor.h
 * @brief TUF ultrasonic flow-meter Modbus driver and period-total reads.
 */
#ifndef TUF_SENSOR_H
#define TUF_SENSOR_H

#include <stdint.h>

#include "../third_party/ModbusMaster/ModbusMaster.h"

/**
 * @brief TUF live flow and meter-native calendar totals.
 *
 * The meter reports 32-bit values as low 16-bit word followed by high word;
 * the driver decodes that ordering before exposing these fields.
 */
struct TufSensorData
{
    float flowRate;              ///< Instantaneous cubic metres per hour.
    float velocity;              ///< Fluid velocity in metres per second.
    float flowPerDay;            ///< Meter-native volume today, cubic metres.
    float flowPerMonth;          ///< Meter-native volume this month, cubic metres.
    float flowPerYear;           ///< Meter-native volume this year, cubic metres.
    uint16_t errorCode;          ///< Meter diagnostic register when valid.
    bool liveValid;              ///< Flow and velocity read succeeded.
    bool dayMonthTotalsValid;    ///< Today/month read succeeded.
    bool yearTotalValid;         ///< Year total read succeeded.
    bool periodTotalsValid;      ///< All requested period totals are valid.
    bool errorCodeValid;         ///< Diagnostic register read succeeded.
    bool isValid;                ///< Overall required sample validity.
};

extern ModbusMaster tufSensor;

/** @brief Bind the configured TUF slave and probe its diagnostic register. */
void initializeTufSensor();
/** @brief Read live and calendar registers with bounded retries. @return Decoded sample with per-block validity flags. */
TufSensorData readTufSensor();
/** @brief Print decoded measurements and acquisition status. @param data Sample to display. */
void printTufSensorData(const TufSensorData& data);

#endif
