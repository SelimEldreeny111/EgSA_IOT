#include "HndaSensor.h"

#include <Arduino.h>

#include "../config/AppConfig.h"

extern HardwareSerial& SerialMon;
extern HardwareSerial& SerialRs485;

ModbusMaster hndaSensor;

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
    sensor.preTransmission([]()
    {
        digitalWrite(AppConfig::kRs485TxEnablePin, HIGH);
        delayMicroseconds(50);
    });

    sensor.postTransmission([]()
    {
        delayMicroseconds(50);
        digitalWrite(AppConfig::kRs485TxEnablePin, LOW);
    });
}
}

void initializeHndaSensor()
{
    SerialMon.println("Initializing HNDA moisture/temperature sensor...");

    hndaSensor.begin(
        AppConfig::kHndaModbusAddress,
        SerialRs485);
    attachRs485DirectionCallbacks(hndaSensor);

    const uint8_t result = hndaSensor.readHoldingRegisters(
        AppConfig::kHndaTemperatureRegister,
        2);

    if (result == hndaSensor.ku8MBSuccess)
    {
        SerialMon.println("HNDA sensor OK");
    }
    else
    {
        SerialMon.print("HNDA sensor not found, code=");
        SerialMon.println(result);
    }

    hndaSensor.clearResponseBuffer();
}

HndaSensorData readHndaSensor()
{
    HndaSensorData data{};
    data.isValid = false;

    const uint8_t result = hndaSensor.readHoldingRegisters(
        AppConfig::kHndaTemperatureRegister,
        2);

    if (result != hndaSensor.ku8MBSuccess)
    {
        hndaSensor.clearResponseBuffer();
        SerialMon.print("HNDA sensor read failed, code=");
        SerialMon.println(result);
        return data;
    }

    data.temperatureC = scaledSignedRegister(
        hndaSensor.getResponseBuffer(0),
        AppConfig::kHndaRegisterScale);
    data.moisturePercent = scaledUnsignedRegister(
        hndaSensor.getResponseBuffer(1),
        AppConfig::kHndaRegisterScale);
    data.isValid = true;

    hndaSensor.clearResponseBuffer();
    return data;
}

void printHndaSensorData(const HndaSensorData& data)
{
    if (!data.isValid)
    {
        SerialMon.println("ERROR: HNDA sensor read failed");
        return;
    }

    SerialMon.print("HNDA temperature: ");
    SerialMon.print(data.temperatureC);
    SerialMon.println(" C");

    SerialMon.print("HNDA moisture: ");
    SerialMon.print(data.moisturePercent);
    SerialMon.println(" %");
}
