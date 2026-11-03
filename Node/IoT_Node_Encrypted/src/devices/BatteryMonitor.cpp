/** @file BatteryMonitor.cpp @brief Battery ADC configuration and divider-scaled voltage reading. */
#define APP_LOG_MODULE "BATTERY"
#include "../platform/DebugLog.h"
#include "BatteryMonitor.h"

#include "../config/AppConfig.h"

#include <Arduino.h>

extern HardwareSerial SerialMon;

void initializeBatteryMonitor()
{
    if (!AppConfig::kEnableBatteryMonitor)
    {
        return;
    }

#if defined(INPUT_ANALOG)
    pinMode(AppConfig::kBatteryAdcPin, INPUT_ANALOG);
#else
    pinMode(AppConfig::kBatteryAdcPin, INPUT);
#endif
    analogReadResolution(AppConfig::kBatteryAdcResolutionBits);

    // The first conversion after configuring an ADC channel can contain the
    // previous sample-and-hold value. Discard it before normal measurements.
    (void)analogRead(AppConfig::kBatteryAdcPin);

    APP_DEBUG_PRINT("Battery monitor ready: ADC pin=");
    APP_DEBUG_PRINT(AppConfig::kBatteryAdcPin);
    APP_DEBUG_PRINT(" divider=");
    APP_DEBUG_PRINT(AppConfig::kBatteryDividerHighOhms, 0);
    APP_DEBUG_PRINT("/");
    APP_DEBUG_PRINT(AppConfig::kBatteryDividerLowOhms, 0);
    APP_DEBUG_PRINTLN(" ohm");
}

float readBatteryVoltage()
{
    if (!AppConfig::kEnableBatteryMonitor ||
        AppConfig::kBatteryDividerLowOhms <= 0.0f)
    {
        return 0.0f;
    }

    uint32_t sum = 0U;
    for (uint8_t i = 0U; i < AppConfig::kBatterySampleCount; ++i)
    {
        sum += static_cast<uint32_t>(analogRead(AppConfig::kBatteryAdcPin));
        delayMicroseconds(100U);
    }

    const float averageCount =
        static_cast<float>(sum) / AppConfig::kBatterySampleCount;
    const float adcVoltage =
        averageCount * AppConfig::kBatteryAdcReferenceVolts /
        AppConfig::kBatteryAdcMaximumCount;
    const float dividerRatio =
        (AppConfig::kBatteryDividerHighOhms +
         AppConfig::kBatteryDividerLowOhms) /
        AppConfig::kBatteryDividerLowOhms;

    return adcVoltage * dividerRatio * AppConfig::kBatteryCalibrationFactor;
}
