/** @file BatteryMonitor.cpp @brief Battery ADC configuration and divider-scaled voltage reading. */
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

    SerialMon.print("Battery monitor ready: ADC pin=");
    SerialMon.print(AppConfig::kBatteryAdcPin);
    SerialMon.print(" divider=");
    SerialMon.print(AppConfig::kBatteryDividerHighOhms, 0);
    SerialMon.print("/");
    SerialMon.print(AppConfig::kBatteryDividerLowOhms, 0);
    SerialMon.println(" ohm");
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
