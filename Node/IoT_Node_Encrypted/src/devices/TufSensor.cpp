/** @file TufSensor.cpp @brief TUF Modbus polling, register decoding, and reading validation. */
#define APP_LOG_MODULE "TUF"
#include "../platform/DebugLog.h"
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
    APP_DEBUG_PRINT("Optional TUF ");
    APP_DEBUG_PRINT(name);
    APP_DEBUG_PRINT(" read skipped, code=");
    APP_DEBUG_PRINTLN(result);
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

        APP_DEBUG_PRINT("TUF transient read error ");
        APP_DEBUG_PRINT(result);
        APP_DEBUG_PRINTLN(", retrying...");
    }

    return result;
}
}

void initializeTufSensor()
{
    APP_DEBUG_PRINTLN("Initializing TUF RS485 Modbus sensor...");

    tufSensor.begin(AppConfig::kTufModbusAddress, Serial1);

    tufSensor.preTransmission(rs485PreTransmission);
    tufSensor.postTransmission(rs485PostTransmission);
    tufSensor.idle(rs485ServiceCommands);

    APP_DEBUG_PRINT("Modbus test... ");
    const uint8_t res = readHoldingRegistersWithRetry(kErrorCodeRegister, 1U);

    if (res == tufSensor.ku8MBSuccess)
    {
        APP_DEBUG_PRINTLN("OK");
    }
    else
    {
        APP_DEBUG_PRINT("FAIL (");
        APP_DEBUG_PRINT(res);
        APP_DEBUG_PRINTLN(") , no sensor found");
    }

    tufSensor.clearResponseBuffer();
}

TufSensorData readTufSensor()
{
    APP_DEBUG_PRINTLN("\n================ TUF SENSOR READINGS ================");
    TufSensorData data{};
    data.isValid = false;

    uint8_t res = readHoldingRegistersWithRetry(kFlowRateRegister, 6U);
    if (res != tufSensor.ku8MBSuccess)
    {
        tufSensor.clearResponseBuffer();
        APP_DEBUG_PRINT("TUF live-data read failed, code=");
        APP_DEBUG_PRINTLN(res);
        return data;
    }

    data.flowRate = responseFloat(0U);
    data.velocity = responseFloat(kVelocityRegisterOffset);
    data.liveValid = isfinite(data.flowRate) && isfinite(data.velocity);

    tufSensor.clearResponseBuffer();
    data.isValid = data.liveValid;
    if (!data.liveValid)
    {
        APP_DEBUG_PRINTLN("TUF live-data reply contains an invalid float");
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
            APP_DEBUG_PRINTLN("TUF day/month totalizer contains an invalid float");
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
            APP_DEBUG_PRINTLN("TUF year totalizer contains an invalid float");
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
        APP_LOG_ERROR("ERROR: Modbus read failed");
        return;
    }

    APP_DEBUG_PRINT("Flow Rate : ");
    APP_DEBUG_PRINT(data.flowRate);
    APP_DEBUG_PRINTLN(" m3/h");

    APP_DEBUG_PRINT("velocity  : ");
    APP_DEBUG_PRINT(data.velocity);
    APP_DEBUG_PRINTLN(" m/s");

    if (data.dayMonthTotalsValid)
    {
        APP_DEBUG_PRINT("Volume today      : ");
        APP_DEBUG_PRINT(data.flowPerDay);
        APP_DEBUG_PRINTLN(" m3");

        APP_DEBUG_PRINT("Volume this month : ");
        APP_DEBUG_PRINT(data.flowPerMonth);
        APP_DEBUG_PRINTLN(" m3");
    }
    else
    {
        APP_DEBUG_PRINTLN("Daily/monthly totals: unavailable");
    }

    if (data.yearTotalValid)
    {
        APP_DEBUG_PRINT("Volume this year  : ");
        APP_DEBUG_PRINT(data.flowPerYear);
        APP_DEBUG_PRINTLN(" m3");
    }
    else
    {
        APP_DEBUG_PRINTLN("Yearly total: unavailable");
    }

    APP_DEBUG_PRINT("TUF error code     : ");
    if (data.errorCodeValid)
    {
        APP_DEBUG_PRINT("0x");
        APP_DEBUG_PRINTLN(data.errorCode, HEX);
    }
    else
    {
        APP_DEBUG_PRINTLN("unavailable");
    }
    APP_DEBUG_PRINTLN("====================================================\n");

}
