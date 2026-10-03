/**
 * @file HndaSensor.h
 * @brief HNDA soil temperature and moisture Modbus driver.
 */
#ifndef HNDA_SENSOR_H
#define HNDA_SENSOR_H

#include <stdint.h>

#include "../third_party/ModbusMaster/ModbusMaster.h"

/** @brief One HNDA sample with a separate communication/validation result. */
struct HndaSensorData
{
    float temperatureC;     ///< Soil temperature in degrees Celsius.
    float moisturePercent;  ///< Volumetric moisture reading in percent.
    bool isValid;           ///< True only when the latest Modbus sample passed validation.
};

extern ModbusMaster hndaSensor;

/** @brief Bind the configured HNDA slave to the shared RS485 bus. */
void initializeHndaSensor();
/** @brief Acquire and validate one HNDA register set. @return Measurements with isValid indicating success. */
HndaSensorData readHndaSensor();
/** @brief Print one sample and validity to the diagnostic serial port. @param data Sample to display. */
void printHndaSensorData(const HndaSensorData& data);

#endif
