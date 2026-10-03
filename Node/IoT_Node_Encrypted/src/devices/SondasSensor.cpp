#include "SondasSensor.h"

#include <Arduino.h>

#include "../config/AppConfig.h"
#include "Rs485Bus.h"

extern HardwareSerial SerialMon;

ModbusMaster sondasSensor;

namespace {
float scaledSignedRegister(uint16_t value, float scale)
{
    return static_cast<float>(static_cast<int16_t>(value)) / scale;
}

float scaledUnsignedRegister(uint16_t value, float scale)
{
    return static_cast<float>(value) / scale;
}

void attachRs485DirectionCallbacks(ModbusMaster& sensor)
{
    sensor.preTransmission(rs485PreTransmission);
    sensor.postTransmission(rs485PostTransmission);
    sensor.idle(rs485ServiceCommands);
}
}

void initializeSondasSensor()
{
    SerialMon.println("Initializing Sondas moisture/temperature/EC sensor...");

    sondasSensor.begin(
        AppConfig::kSondasModbusAddress,
        Serial1);
    attachRs485DirectionCallbacks(sondasSensor);

    const uint8_t result = sondasSensor.readHoldingRegisters(
        AppConfig::kSondasTemperatureRegister,
        3);

    if (result == sondasSensor.ku8MBSuccess)
    {
        SerialMon.println("Sondas sensor OK");
    }
    else
    {
        SerialMon.print("Sondas sensor not found, code=");
        SerialMon.println(result);
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
        SerialMon.print("Sondas sensor read failed, code=");
        SerialMon.println(result);
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
        SerialMon.println("ERROR: Sondas sensor read failed");
        return;
    }

    SerialMon.print("Sondas temperature: ");
    SerialMon.print(data.temperatureC);
    SerialMon.println(" C");

    SerialMon.print("Sondas moisture: ");
    SerialMon.print(data.moisturePercent);
    SerialMon.println(" %");

    SerialMon.print("Sondas electrical conductivity: ");
    SerialMon.print(data.electricalConductivity);
    SerialMon.println(" EC");
}
