/** @file Rs485Bus.cpp @brief Shared half-duplex RS485 UART and driver-enable timing. */
#define APP_LOG_MODULE "RS485"
#include "../platform/DebugLog.h"
#include "Rs485Bus.h"

#include <Arduino.h>

#include "../config/AppConfig.h"
#include "../platform/Watchdog.h"
#include "../third_party/ModbusMaster/ModbusMaster.h"

extern HardwareSerial SerialMon;

namespace
{
bool g_rs485Initialized = false;
uint32_t g_lastTransmitReleaseUs = 0U;
constexpr uint32_t kMinimumSilentIntervalUs = 4000U;
void (*g_commandService)() = nullptr;
uint32_t g_lastCommandServiceMs = 0U;
constexpr uint32_t kCommandServiceIntervalMs = 100U;

#if APP_ENABLE_DEBUG && APP_DEBUG_RS485_RX
/** @brief Log the received ADU in wire order, including incomplete or invalid replies. */
void logModbusResponse(uint8_t unit, uint8_t function, uint8_t result,
                       const uint8_t* bytes, uint8_t length)
{
    char label[68];
    snprintf(label, sizeof(label), "modbus_rx unit=%u function=0x%02X result=0x%02X",
             static_cast<unsigned>(unit), static_cast<unsigned>(function), static_cast<unsigned>(result));
    WiotDebug::hex(APP_LOG_MODULE, label, bytes, length);
}
#endif
}

void configureRs485Modbus(ModbusMaster& sensor, uint8_t address)
{
    sensor.begin(address, Serial1);
    sensor.preTransmission(rs485PreTransmission);
    sensor.postTransmission(rs485PostTransmission);
    sensor.idle(rs485ServiceCommands);
#if APP_ENABLE_DEBUG && APP_DEBUG_RS485_RX
    sensor.onResponse(logModbusResponse);
#endif
}

void setRs485CommandService(void (*service)())
{
    g_commandService = service;
}

void rs485ServiceCommands()
{
    if (!g_commandService || millis() - g_lastCommandServiceMs < kCommandServiceIntervalMs) return;
    // The parent Modbus read is bounded. A broken read must not stay alive
    // indefinitely by reaching an idle hook that reloads the watchdog.
    const HardwareWatchdogServicePause pause;
    g_commandService();
    g_lastCommandServiceMs = millis();
}

void rs485PreTransmission()
{
    initializeRs485Bus();
    const uint32_t elapsedUs = micros() - g_lastTransmitReleaseUs;
    if (g_lastTransmitReleaseUs != 0U &&
        elapsedUs < kMinimumSilentIntervalUs)
    {
        delayMicroseconds(kMinimumSilentIntervalUs - elapsedUs);
    }
    digitalWrite(AppConfig::kRs485TxEnablePin, HIGH);
    delayMicroseconds(50);
}

void rs485PostTransmission()
{
    delayMicroseconds(50);
    digitalWrite(AppConfig::kRs485TxEnablePin, LOW);
    g_lastTransmitReleaseUs = micros();
}

void initializeRs485Bus()
{
    if (g_rs485Initialized)
    {
        return;
    }

    Serial1.begin(AppConfig::kRs485BaudRate, SERIAL_8N1);
    pinMode(AppConfig::kRs485TxEnablePin, OUTPUT);
    digitalWrite(AppConfig::kRs485TxEnablePin, LOW);
    delay(50);
    g_rs485Initialized = true;

    APP_DEBUG_PRINT("RS485 bus ready: ");
    APP_DEBUG_PRINT(AppConfig::kRs485BaudRate);
    APP_DEBUG_PRINTLN(" baud, 8N1");
}
