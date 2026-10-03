/**
 * @file SondasSensor.h
 * @brief Sondas soil temperature, moisture, and conductivity Modbus driver.
 */
#ifndef SONDAS_SENSOR_H
#define SONDAS_SENSOR_H

#include <stdint.h>

#include "../third_party/ModbusMaster/ModbusMaster.h"

/** @brief One Sondas sample and its acquisition validity. */
struct SondasSensorData
{
    float temperatureC;          ///< Soil temperature in degrees Celsius.
    float moisturePercent;       ///< Soil moisture in percent.
    float electricalConductivity;///< Conductivity in the meter's configured unit.
    bool isValid;                ///< True only when the latest Modbus sample passed validation.
};

extern ModbusMaster sondasSensor;

/** @brief Bind the configured Sondas slave to the shared RS485 bus. */
void initializeSondasSensor();
/** @brief Acquire and validate one Sondas register set. @return Measurements with isValid indicating success. */
SondasSensorData readSondasSensor();
/** @brief Print one sample and validity to the diagnostic serial port. @param data Sample to display. */
void printSondasSensorData(const SondasSensorData& data);

#endif
