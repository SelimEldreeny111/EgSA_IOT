/** @file TufSensor.cpp @brief TUF Modbus polling, register decoding, and reading validation. */
#include <stdint.h>
#include "TufSensor.h"

#include "../config/AppConfig.h"
#include "../platform/Watchdog.h"
#include "Rs485Bus.h"

#include <math.h>
#include <string.h>

ModbusMaster tufSensor;

extern HardwareSerial SerialMon;

namespace
{
constexpr uint16_t kFlowRateRegister = 0x0000U;
constexpr uint16_t kVelocityRegisterOffset = 4U;
constexpr uint16_t kErrorCodeRegister = 0x0047U;
constexpr uint16_t kDayAndMonthTotalsRegister = 0x007CU;
constexpr uint16_t kYearTotalRegister = 0x0090U;
constexpr uint32_t kInterRequestDelayMs = 100UL;
constexpr uint8_t kMaxReadAttempts = 2U;

/** @brief Reinterpret a 32-bit TUF register pair as an IEEE-754 float. */
float u32ToFloat(uint32_t value)
{
    float result;
    memcpy(&result, &value, sizeof(result));
    return result;
}

/** @brief Combine TUF response words in the meter's low-word-first order. */
static uint32_t responseU32LowWordFirst(uint8_t lowWordIndex)
{
    return
        (static_cast<uint32_t>(tufSensor.getResponseBuffer(lowWordIndex + 1U)) << 16) |
        tufSensor.getResponseBuffer(lowWordIndex);
}

/** @brief Decode a low-word-first TUF floating-point response. */
static float responseFloat(uint8_t lowWordIndex)
{
    return u32ToFloat(responseU32LowWordFirst(lowWordIndex));
}

/** @brief Report an optional register-read failure without invalidating core data. */
static void logOptionalReadFailed(const char* name, uint8_t result)
{
    SerialMon.print("Optional TUF ");
    SerialMon.print(name);
    SerialMon.print(" read skipped, code=");
    SerialMon.println(result);
}

/** @brief Poll a TUF holding-register block with bounded retries. */
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

    tufSensor.begin(AppConfig::kTufModbusAddress, Serial1);

    tufSensor.preTransmission(rs485PreTransmission);
    tufSensor.postTransmission(rs485PostTransmission);

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

    data.flowRate = responseFloat(0U);
    data.velocity = responseFloat(kVelocityRegisterOffset);
    data.liveValid = isfinite(data.flowRate) && isfinite(data.velocity);

    tufSensor.clearResponseBuffer();
    data.isValid = data.liveValid;
    if (!data.liveValid)
    {
        SerialMon.println("TUF live-data reply contains an invalid float");
        return data;
    }

    res = readHoldingRegistersWithRetry(kDayAndMonthTotalsRegister, 4U);

    if (res == tufSensor.ku8MBSuccess)
    {
        data.flowPerDay = responseFloat(0U);
        data.flowPerMonth = responseFloat(2U);
        data.dayMonthTotalsValid =
            isfinite(data.flowPerDay) && isfinite(data.flowPerMonth);
        if (!data.dayMonthTotalsValid)
        {
            SerialMon.println("TUF day/month totalizer contains an invalid float");
        }
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
        data.yearTotalValid = isfinite(yearFraction) && isfinite(data.flowPerYear);
        if (!data.yearTotalValid)
        {
            SerialMon.println("TUF year totalizer contains an invalid float");
        }
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
        data.errorCodeValid = true;
    }
    else
    {
        logOptionalReadFailed("error-code", res);
    }
    tufSensor.clearResponseBuffer();
    data.periodTotalsValid =
        data.dayMonthTotalsValid && data.yearTotalValid;

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

    if (data.dayMonthTotalsValid)
    {
        SerialMon.print("Volume today      : ");
        SerialMon.print(data.flowPerDay);
        SerialMon.println(" m3");

        SerialMon.print("Volume this month : ");
        SerialMon.print(data.flowPerMonth);
        SerialMon.println(" m3");
    }
    else
    {
        SerialMon.println("Daily/monthly totals: unavailable");
    }

    if (data.yearTotalValid)
    {
        SerialMon.print("Volume this year  : ");
        SerialMon.print(data.flowPerYear);
        SerialMon.println(" m3");
    }
    else
    {
        SerialMon.println("Yearly total: unavailable");
    }

    SerialMon.print("TUF error code     : ");
    if (data.errorCodeValid)
    {
        SerialMon.print("0x");
        SerialMon.println(data.errorCode, HEX);
    }
    else
    {
        SerialMon.println("unavailable");
    }
    SerialMon.println("====================================================\n");

}
