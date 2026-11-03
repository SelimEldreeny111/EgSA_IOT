/** @file SondasSensor.cpp @brief Sondas probe Modbus polling and measurement decoding. */
#define APP_LOG_MODULE "SONDAS"
#include "../platform/DebugLog.h"
#include "SondasSensor.h"

#include <Arduino.h>

#include "../config/AppConfig.h"
#include "Rs485Bus.h"

extern HardwareSerial SerialMon;

ModbusMaster sondasSensor;

namespace {
/** @brief Interpret a Modbus register as signed fixed-point data. */
float scaledSignedRegister(uint16_t value, float scale)
{
    return static_cast<float>(static_cast<int16_t>(value)) / scale;
}

/** @brief Interpret a Modbus register as unsigned fixed-point data. */
float scaledUnsignedRegister(uint16_t value, float scale)
{
    return static_cast<float>(value) / scale;
}

/** @brief Bind the shared RS485 driver-enable callbacks to this Modbus client. */
void attachRs485DirectionCallbacks(ModbusMaster& sensor)
{
    sensor.preTransmission(rs485PreTransmission);
    sensor.postTransmission(rs485PostTransmission);
    sensor.idle(rs485ServiceCommands);
}
}

void initializeSondasSensor()
{
    APP_DEBUG_PRINTLN("Initializing Sondas moisture/temperature/EC sensor...");

    sondasSensor.begin(
        AppConfig::kSondasModbusAddress,
        Serial1);
    attachRs485DirectionCallbacks(sondasSensor);

    const uint8_t result = sondasSensor.readHoldingRegisters(
        AppConfig::kSondasTemperatureRegister,
        3);

    if (result == sondasSensor.ku8MBSuccess)
    {
        APP_DEBUG_PRINTLN("Sondas sensor OK");
    }
    else
    {
        APP_DEBUG_PRINT("Sondas sensor not found, code=");
        APP_DEBUG_PRINTLN(result);
    }

    sondasSensor.clearResponseBuffer();
}

SondasSensorData readSondasSensor()
{
    SondasSensorData data{};
    data.isValid = false;

    const uint8_t result = sondasSensor.readHoldingRegisters(
        AppConfig::kSondasTemperatureRegister,
        3);

    if (result != sondasSensor.ku8MBSuccess)
    {
        sondasSensor.clearResponseBuffer();
        APP_DEBUG_PRINT("Sondas sensor read failed, code=");
        APP_DEBUG_PRINTLN(result);
        return data;
    }

    data.temperatureC = scaledSignedRegister(
        sondasSensor.getResponseBuffer(0),
        AppConfig::kSondasTemperatureScale);
    data.moisturePercent = scaledUnsignedRegister(
        sondasSensor.getResponseBuffer(1),
        AppConfig::kSondasMoistureScale);
    data.electricalConductivity = scaledUnsignedRegister(
        sondasSensor.getResponseBuffer(2),
        AppConfig::kSondasElectricalConductivityScale);
    data.isValid = true;

    sondasSensor.clearResponseBuffer();
    return data;
}

void printSondasSensorData(const SondasSensorData& data)
{
    if (!data.isValid)
    {
        APP_LOG_ERROR("ERROR: Sondas sensor read failed");
        return;
    }

    APP_DEBUG_PRINT("Sondas temperature: ");
    APP_DEBUG_PRINT(data.temperatureC);
    APP_DEBUG_PRINTLN(" C");

    APP_DEBUG_PRINT("Sondas moisture: ");
    APP_DEBUG_PRINT(data.moisturePercent);
    APP_DEBUG_PRINTLN(" %");

    APP_DEBUG_PRINT("Sondas electrical conductivity: ");
    APP_DEBUG_PRINT(data.electricalConductivity);
    APP_DEBUG_PRINTLN(" EC");
}
