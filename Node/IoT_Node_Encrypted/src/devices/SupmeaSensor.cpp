/** @file SupmeaSensor.cpp @brief Supmea Modbus block reads and flow-quality decoding. */
#define APP_LOG_MODULE "SUPMEA"
#include "../platform/DebugLog.h"
#include "SupmeaSensor.h"

#include <Arduino.h>
#include <math.h>
#include <string.h>

#include "../config/AppConfig.h"
#include "../platform/Watchdog.h"
#include "Rs485Bus.h"

extern HardwareSerial SerialMon;

ModbusMaster supmeaSensor;

namespace
{
// SUP-FMC240 user manual, Chapter 9.4.1 (zero-based Modbus addresses).
constexpr uint16_t kForwardTotalRegister = 90U;
constexpr uint16_t kFlowRateRegister = 98U;
constexpr uint16_t kTotalsRegisterCount = 6U; // 90-95
constexpr uint16_t kLiveRegisterCount = 10U;  // 98-107
constexpr uint32_t kInterRequestDelayMs = 100UL;
constexpr uint8_t kMaxReadAttempts = 2U;

/** @brief Bind half-duplex direction callbacks to the Supmea Modbus client. */
void attachRs485DirectionCallbacks(ModbusMaster& sensor)
{
    sensor.preTransmission(rs485PreTransmission);
    sensor.postTransmission(rs485PostTransmission);
    sensor.idle(rs485ServiceCommands);
}

/** @brief Read a register block with configured retry count and watchdog service. */
uint8_t readHoldingRegistersWithRetry(uint16_t address, uint16_t count)
{
    uint8_t result = supmeaSensor.ku8MBResponseTimedOut;

    for (uint8_t attempt = 0U; attempt < kMaxReadAttempts; ++attempt)
    {
        serviceHardwareWatchdog();
        delay(kInterRequestDelayMs);
        result = supmeaSensor.readHoldingRegisters(address, count);
        serviceHardwareWatchdog();

        if (result == supmeaSensor.ku8MBSuccess)
        {
            return result;
        }

        supmeaSensor.clearResponseBuffer();

        // Modbus exception responses are complete replies; retry only transport
        // failures such as a timeout, truncated frame, or CRC error.
        if (result < supmeaSensor.ku8MBInvalidSlaveID ||
            attempt + 1U >= kMaxReadAttempts)
        {
            break;
        }

        APP_DEBUG_PRINT("SUP-FMC240 transient Modbus error ");
        APP_DEBUG_PRINT(result);
        APP_DEBUG_PRINTLN(", retrying...");
    }

    return result;
}

/** @brief Decode a Supmea IEEE-754 response from high-word-first registers. */
float responseFloat(uint8_t highWordIndex)
{
    // The FMC240 manual defines Register 1 as BYTE1/BYTE2 and Register 2 as
    // BYTE3/BYTE4, i.e. normal big-endian IEEE-754 byte and word order.
    const uint32_t bits =
        (static_cast<uint32_t>(supmeaSensor.getResponseBuffer(highWordIndex)) << 16) |
        supmeaSensor.getResponseBuffer(highWordIndex + 1U);

    float value = 0.0f;
    memcpy(&value, &bits, sizeof(value));
    return value;
}

/** @brief Reject NaN and infinite meter readings before publication. */
bool isFiniteMeasurement(float value)
{
    return isfinite(value);
}
}

void initializeSupmeaSensor()
{
    APP_DEBUG_PRINTLN("Initializing Supmea SUP-FMC240 Modbus interface...");
    APP_DEBUG_PRINT("SUP-FMC240 slave address: ");
    APP_DEBUG_PRINTLN(AppConfig::kSupmeaSensorModbusAddress);

    supmeaSensor.begin(
        AppConfig::kSupmeaSensorModbusAddress,
        Serial1);
    attachRs485DirectionCallbacks(supmeaSensor);

    const uint8_t result = readHoldingRegistersWithRetry(
        kFlowRateRegister,
        2U);

    if (result == supmeaSensor.ku8MBSuccess)
    {
        const float flowRate = responseFloat(0U);
        if (isFiniteMeasurement(flowRate))
        {
            APP_DEBUG_PRINT("SUP-FMC240 interface OK, flow rate=");
            APP_DEBUG_PRINTLN(flowRate, 3);
        }
        else
        {
            APP_DEBUG_PRINTLN("SUP-FMC240 replied, but flow-rate float is invalid");
        }
    }
    else
    {
        APP_DEBUG_PRINT("SUP-FMC240 not found, Modbus code=");
        APP_DEBUG_PRINTLN(result);
    }

    supmeaSensor.clearResponseBuffer();
}

SupmeaSensorData readSupmeaSensor()
{
    SupmeaSensorData data{};
    data.totalsResult = supmeaSensor.ku8MBResponseTimedOut;
    data.liveResult = supmeaSensor.ku8MBResponseTimedOut;

    data.totalsResult = readHoldingRegistersWithRetry(
        kForwardTotalRegister,
        kTotalsRegisterCount);
    if (data.totalsResult == supmeaSensor.ku8MBSuccess)
    {
        data.forwardTotalM3 = responseFloat(0U);
        data.reverseTotalM3 = responseFloat(2U);
        data.netTotalM3 = responseFloat(4U);
        data.totalsValid =
            isFiniteMeasurement(data.forwardTotalM3) &&
            isFiniteMeasurement(data.reverseTotalM3) &&
            isFiniteMeasurement(data.netTotalM3);
    }
    supmeaSensor.clearResponseBuffer();

    data.liveResult = readHoldingRegistersWithRetry(
        kFlowRateRegister,
        kLiveRegisterCount);
    if (data.liveResult == supmeaSensor.ku8MBSuccess)
    {
        data.flowRate = responseFloat(0U);
        data.velocityMps = responseFloat(2U);
        data.flowRatioPercent = responseFloat(4U);
        data.epdPercent = supmeaSensor.getResponseBuffer(6U);
        data.flowRateUnitCode = supmeaSensor.getResponseBuffer(7U);
        data.epdAlarm = supmeaSensor.getResponseBuffer(8U);
        data.excitationCurrentAlarm =
            supmeaSensor.getResponseBuffer(9U);
        data.liveValid =
            isFiniteMeasurement(data.flowRate) &&
            isFiniteMeasurement(data.velocityMps) &&
            isFiniteMeasurement(data.flowRatioPercent) &&
            data.flowRateUnitCode <= 11U;
    }
    supmeaSensor.clearResponseBuffer();

    data.isValid = data.totalsValid && data.liveValid;
    return data;
}

const char* supmeaFlowUnitName(uint16_t unitCode)
{
    static const char* const kUnits[] =
    {
        "L/h", "L/min", "L/s", "m3/h", "m3/min", "m3/s",
        "kg/h", "kg/min", "kg/s", "t/h", "t/min", "t/s"
    };

    return unitCode < (sizeof(kUnits) / sizeof(kUnits[0]))
        ? kUnits[unitCode]
        : "unknown";
}

void printSupmeaSensorData(const SupmeaSensorData& data)
{
    APP_DEBUG_PRINTLN();
    APP_DEBUG_PRINTLN("=========== SUP-FMC240 READINGS =============");

    if (data.totalsValid)
    {
        APP_DEBUG_PRINT("Forward total : ");
        APP_DEBUG_PRINT(data.forwardTotalM3, 3);
        APP_DEBUG_PRINTLN(" m3");
        APP_DEBUG_PRINT("Reverse total : ");
        APP_DEBUG_PRINT(data.reverseTotalM3, 3);
        APP_DEBUG_PRINTLN(" m3");
        APP_DEBUG_PRINT("Net total     : ");
        APP_DEBUG_PRINT(data.netTotalM3, 3);
        APP_DEBUG_PRINTLN(" m3");
    }
    else
    {
        APP_DEBUG_PRINT("Totals read failed/invalid, Modbus code=");
        APP_DEBUG_PRINTLN(data.totalsResult);
    }

    if (data.liveValid)
    {
        APP_DEBUG_PRINT("Flow rate     : ");
        APP_DEBUG_PRINT(data.flowRate, 3);
        APP_DEBUG_PRINT(' ');
        APP_DEBUG_PRINTLN(supmeaFlowUnitName(data.flowRateUnitCode));
        APP_DEBUG_PRINT("Velocity      : ");
        APP_DEBUG_PRINT(data.velocityMps, 3);
        APP_DEBUG_PRINTLN(" m/s");
        APP_DEBUG_PRINT("Flow ratio    : ");
        APP_DEBUG_PRINT(data.flowRatioPercent, 2);
        APP_DEBUG_PRINTLN(" %");
        APP_DEBUG_PRINT("EPD value     : ");
        APP_DEBUG_PRINT(data.epdPercent);
        APP_DEBUG_PRINTLN(" %");
        APP_DEBUG_PRINT("EPD alarm     : ");
        APP_DEBUG_PRINTLN(data.epdAlarm);
        APP_DEBUG_PRINT("Excitation alarm: ");
        APP_DEBUG_PRINTLN(data.excitationCurrentAlarm);
    }
    else
    {
        APP_DEBUG_PRINT("Live-data read failed/invalid, Modbus code=");
        APP_DEBUG_PRINTLN(data.liveResult);
    }

    APP_DEBUG_PRINT("Overall result: ");
    APP_DEBUG_PRINTLN(data.isValid ? "VALID" : "INVALID");
    APP_DEBUG_PRINTLN("==============================================");
}
