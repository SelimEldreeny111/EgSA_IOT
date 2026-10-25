#pragma once
#include "Arduino.h"
#define APP_CONFIG_H
extern bool testWatchdogEnabled;
namespace AppConfig {
constexpr int kFlowAccumulatorEepromAddress = 128;
constexpr int kWatchdogCounterEepromAddress = 192;
constexpr int kPowerCounterEepromAddress = 232;
constexpr uint32_t kValveEepromAddress = 212U;
static const bool& kEnableHardwareWatchdog = testWatchdogEnabled;
constexpr uint32_t kWatchdogTimeoutUs=30000000U, kWatchdogForcedResetTimeoutUs=250000U;
constexpr uint8_t kWatchdogSelfTestMode=0;
}
