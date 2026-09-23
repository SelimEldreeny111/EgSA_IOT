#include <stdint.h>
#include "TufSensor.h"

#include "../config/AppConfig.h"
#include "../platform/SerialPorts.h"
#include "../platform/Watchdog.h"

#include <string.h>

ModbusMaster tufSensor;

extern HardwareSerial& SerialMon;
extern HardwareSerial& SerialRs485;

namespace
{
constexpr uint16_t kFlowRateRegister = 0x0000U;
constexpr uint16_t kVelocityRegisterOffset = 4U;
constexpr uint16_t kErrorCodeRegister = 0x0047U;
constexpr uint16_t kDayAndMonthTotalsRegister = 0x007CU;
constexpr uint16_t kYearTotalRegister = 0x0090U;
constexpr uint32_t kInterRequestDelayMs = 100UL;
constexpr uint8_t kMaxReadAttempts = 2U;

float u32ToFloat(uint32_t value)
{
    float result;
    memcpy(&result, &value, sizeof(result));
    return result;
}

static uint32_t responseU32LowWordFirst(uint8_t lowWordIndex)
{
    return
        (static_cast<uint32_t>(tufSensor.getResponseBuffer(lowWordIndex + 1U)) << 16) |
        tufSensor.getResponseBuffer(lowWordIndex);
}

static float responseFloat(uint8_t lowWordIndex)
{
    return u32ToFloat(responseU32LowWordFirst(lowWordIndex));
}

static void logOptionalReadFailed(const char* name, uint8_t result)
{
    SerialMon.print("Optional TUF ");
    SerialMon.print(name);
    SerialMon.print(" read skipped, code=");
    SerialMon.println(result);
}

static uint8_t readHoldingRegistersWithRetry(uint16_t address, uint16_t count)
{
    static uint32_t lastTransactionMs = 0;
    uint8_t result = tufSensor.ku8MBResponseTimedOut;

    for (uint8_t attempt = 0U; attempt < kMaxReadAttempts; ++attempt)
    {
        serviceHardwareWatchdog();
        const uint32_t elapsedMs = millis() - lastTransactionMs;
        if (elapsedMs < kInterRequestDelayMs)
        {
            delay(kInterRequestDelayMs - elapsedMs);
        }

        result = tufSensor.readHoldingRegisters(address, count);
        lastTransactionMs = millis();
        serviceHardwareWatchdog();

        if (result == tufSensor.ku8MBSuccess)
        {
            return result;
        }

        tufSensor.clearResponseBuffer();

        // Modbus exception responses are valid frames and should not be retried.
        if (result < tufSensor.ku8MBInvalidSlaveID ||
            attempt + 1U >= kMaxReadAttempts)
        {
            break;
        }

        SerialMon.print("TUF transient read error ");
        SerialMon.print(result);
        SerialMon.println(", retrying...");
    }

    return result;
}
}

void initializeTufSensor()
{
    SerialMon.println("Initializing TUF RS485 Modbus sensor...");

    beginRs485Serial(AppConfig::kRs485BaudRate, SERIAL_8N1);
    delay(50);

    pinMode(AppConfig::kRs485TxEnablePin, OUTPUT);
    digitalWrite(AppConfig::kRs485TxEnablePin, LOW);

    tufSensor.begin(AppConfig::kTufModbusAddress, SerialRs485);

    tufSensor.preTransmission([]()
    {
        digitalWrite(AppConfig::kRs485TxEnablePin, HIGH);
        delayMicroseconds(50);
    });

    tufSensor.postTransmission([]()
    {
        delayMicroseconds(50);
        digitalWrite(AppConfig::kRs485TxEnablePin, LOW);
    });

    SerialMon.print("Modbus test... ");
    const uint8_t res = readHoldingRegistersWithRetry(kErrorCodeRegister, 1U);

    if (res == tufSensor.ku8MBSuccess)
    {
        SerialMon.println("OK");
    }
    else
    {
        SerialMon.print("FAIL (");
        SerialMon.print(res);
        SerialMon.println(") , no sensor found");
    }

    tufSensor.clearResponseBuffer();
}

TufSensorData readTufSensor()
{
    SerialMon.println("\n================ TUF SENSOR READINGS ================");
    TufSensorData data{};
    data.isValid = false;

    uint8_t res = readHoldingRegistersWithRetry(kFlowRateRegister, 6U);
    if (res != tufSensor.ku8MBSuccess)
    {
        tufSensor.clearResponseBuffer();
        SerialMon.print("TUF live-data read failed, code=");
        SerialMon.println(res);
        return data;
    }

    data.flowRate = responseFloat(0);
    data.velocity = responseFloat(kVelocityRegisterOffset);

    tufSensor.clearResponseBuffer();
    data.isValid = true;

    res = readHoldingRegistersWithRetry(kDayAndMonthTotalsRegister, 4U);

    if (res == tufSensor.ku8MBSuccess)
    {
        data.flowPerDay = responseFloat(0U);
        data.flowPerMonth = responseFloat(2U);
    }
    else
    {
        logOptionalReadFailed("day/month totalizer", res);
    }

    tufSensor.clearResponseBuffer();

    res = readHoldingRegistersWithRetry(kYearTotalRegister, 4U);

    if (res == tufSensor.ku8MBSuccess)
    {
        const int32_t yearInteger =
            static_cast<int32_t>(responseU32LowWordFirst(0));
        const float yearFraction = responseFloat(2);
        data.flowPerYear = static_cast<float>(yearInteger) + yearFraction;
    }
    else
    {
        logOptionalReadFailed("year totalizer", res);
    }
    tufSensor.clearResponseBuffer();

    res = readHoldingRegistersWithRetry(kErrorCodeRegister, 1U);
    if (res == tufSensor.ku8MBSuccess)
    {
        data.errorCode = tufSensor.getResponseBuffer(0U);
    }
    else
    {
        logOptionalReadFailed("error-code", res);
    }
    tufSensor.clearResponseBuffer();

    return data;
}

void printTufSensorData(const TufSensorData& data)
{
    if (!data.isValid)
    {
        SerialMon.println("ERROR: Modbus read failed");
        return;
    }

    SerialMon.print("Flow Rate : ");
    SerialMon.print(data.flowRate);
    SerialMon.println(" m3/h");

    SerialMon.print("velocity  : ");
    SerialMon.print(data.velocity);
    SerialMon.println(" m/s");

    SerialMon.print("Flow per day   : ");
    SerialMon.print(data.flowPerDay);
    SerialMon.println(" m3");

    SerialMon.print("Flow per month : ");
    SerialMon.print(data.flowPerMonth);
    SerialMon.println(" m3");

    SerialMon.print("Flow per year  : ");
    SerialMon.print(data.flowPerYear);
    SerialMon.println(" m3");

    SerialMon.print("TUF error code     : 0x");
    SerialMon.println(data.errorCode, HEX);
    SerialMon.println("====================================================\n");

}
