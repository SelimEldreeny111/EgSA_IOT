#include "Rs485Bus.h"

#include <Arduino.h>

#include "../config/AppConfig.h"
#include "../platform/Watchdog.h"

extern HardwareSerial SerialMon;

namespace
{
bool g_rs485Initialized = false;
uint32_t g_lastTransmitReleaseUs = 0U;
constexpr uint32_t kMinimumSilentIntervalUs = 4000U;
void (*g_commandService)() = nullptr;
uint32_t g_lastCommandServiceMs = 0U;
constexpr uint32_t kCommandServiceIntervalMs = 100U;
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

    SerialMon.print("RS485 bus ready: ");
    SerialMon.print(AppConfig::kRs485BaudRate);
    SerialMon.println(" baud, 8N1");
}
