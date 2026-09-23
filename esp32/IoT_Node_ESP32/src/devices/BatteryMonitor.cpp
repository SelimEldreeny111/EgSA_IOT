#include "BatteryMonitor.h"

#include "../config/AppConfig.h"

#include <Arduino.h>

extern HardwareSerial& SerialMon;

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
    analogSetPinAttenuation(AppConfig::kBatteryAdcPin, ADC_11db);

    // The first conversion after configuring an ADC channel can contain the
    // previous sample-and-hold value. Discard it before normal measurements.
    (void)analogReadMilliVolts(AppConfig::kBatteryAdcPin);

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

    uint32_t sumMillivolts = 0U;
    for (uint8_t i = 0U; i < AppConfig::kBatterySampleCount; ++i)
    {
        sumMillivolts += analogReadMilliVolts(AppConfig::kBatteryAdcPin);
        delayMicroseconds(100U);
    }

    // analogReadMilliVolts() uses the ESP32 eFuse calibration when available,
    // which is substantially more accurate than assuming an ideal 3.3 V ADC.
    const float adcVoltage =
        static_cast<float>(sumMillivolts) /
        (1000.0f * AppConfig::kBatterySampleCount);
    const float dividerRatio =
        (AppConfig::kBatteryDividerHighOhms +
         AppConfig::kBatteryDividerLowOhms) /
        AppConfig::kBatteryDividerLowOhms;

    return adcVoltage * dividerRatio * AppConfig::kBatteryCalibrationFactor;
}
