#include "devices/BatteryMonitor.hpp"

#include "config/AppConfig.hpp"
#include "main.h"
#include "platform/Stm32Platform.hpp"

namespace
{
uint16_t readAdcSample()
{
  if (HAL_ADC_Start(&hadc1) != HAL_OK) return 0U;
  if (HAL_ADC_PollForConversion(&hadc1, 10U) != HAL_OK)
  {
    HAL_ADC_Stop(&hadc1);
    return 0U;
  }
  const uint16_t value = static_cast<uint16_t>(HAL_ADC_GetValue(&hadc1));
  HAL_ADC_Stop(&hadc1);
  return value;
}
}

void initializeBatteryMonitor()
{
  if (!AppConfig::kEnableBatteryMonitor) return;
  (void)readAdcSample();
  SerialMon.println("Battery monitor: ADC1_IN0, 21.6k/9.8k divider");
}

float readBatteryVoltage()
{
  if (!AppConfig::kEnableBatteryMonitor) return 0.0F;
  uint32_t sum = 0U;
  for (uint8_t sample = 0U; sample < AppConfig::kBatterySampleCount; ++sample)
  {
    sum += readAdcSample();
    Platform::delayUs(100U);
  }
  const float average = static_cast<float>(sum) / AppConfig::kBatterySampleCount;
  const float adcVoltage = average * AppConfig::kBatteryAdcReferenceVolts /
                           AppConfig::kBatteryAdcMaximumCount;
  const float divider = (AppConfig::kBatteryDividerHighOhms +
                         AppConfig::kBatteryDividerLowOhms) /
                        AppConfig::kBatteryDividerLowOhms;
  return adcVoltage * divider * AppConfig::kBatteryCalibrationFactor;
}
