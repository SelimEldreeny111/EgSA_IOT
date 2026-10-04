#pragma once
#define APP_CONFIG_H
#define APP_STATE_H
#include <cstdint>
struct AppRuntimeState { uint8_t nodeStatus = 2U; };
AppRuntimeState& appState();
namespace AppConfig {
constexpr uint32_t kOpenCloseNodeGpio = 13, kValveAin1Pin = 9, kValveAin2Pin = 15;
constexpr uint32_t kValveEepromAddress = 212, kWatchdogCounterEepromAddress = 192;
constexpr uint32_t kFlowAccumulatorEepromAddress = 128;
extern bool kEnableOpenCloseNodeOutput, kValvePolarityConfirmed, kValveOpenAin1High;
extern uint32_t kValveOpenPulseMs, kValveClosePulseMs, kValveMinIntervalMs;
}
