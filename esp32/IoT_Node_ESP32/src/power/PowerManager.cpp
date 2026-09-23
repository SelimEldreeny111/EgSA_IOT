#include "PowerManager.h"

#include "../app/AppState.h"
#include "../comm/MQTT.h"
#include "../config/AppConfig.h"
#include "../devices/RTC.h"
#include "../platform/SerialPorts.h"
#include "../platform/Watchdog.h"
#include "../radio/LoraLink.h"

#include <Arduino.h>
#include <driver/gpio.h>
#include <esp_attr.h>
#include <esp_sleep.h>

namespace
{
constexpr uint32_t kSleepStateMagic = 0x50444E32UL; // "PDN2"
constexpr uint32_t kSleepDelayLogPeriodMs = 5000UL;

struct PersistentSleepState
{
  uint32_t magic;
  uint32_t requestEpoch;
  uint32_t deadlineEpoch;
  uint32_t durationSeconds;
  uint32_t checksum;
};

// ESP32 RTC slow memory survives deep sleep and is validated before use.
RTC_DATA_ATTR PersistentSleepState g_persistentSleepState = {};

const char* componentModeName(bool powerDown)
{
  return powerDown ? "POWER_DOWN" : "NORMAL";
}

void printComponentMode(
    const char* component,
    bool powerDown,
    bool selected)
{
  SerialMon.print("  ");
  SerialMon.print(component);
  SerialMon.print(": ");
  SerialMon.print(componentModeName(powerDown));
  SerialMon.println(selected ? " [ACTIVE]" : " [NOT SELECTED]");
}

uint32_t addChecksumWord(uint32_t hash, uint32_t word)
{
  for (uint8_t byteIndex = 0U; byteIndex < 4U; ++byteIndex)
  {
    hash ^= static_cast<uint8_t>(word >> (byteIndex * 8U));
    hash *= 16777619UL;
  }
  return hash;
}

uint32_t calculateSleepStateChecksum(const PersistentSleepState& state)
{
  uint32_t hash = 2166136261UL;
  hash = addChecksumWord(hash, state.magic);
  hash = addChecksumWord(hash, state.requestEpoch);
  hash = addChecksumWord(hash, state.deadlineEpoch);
  hash = addChecksumWord(hash, state.durationSeconds);
  return hash;
}

bool sleepStateFieldsAreSane(const PersistentSleepState& state)
{
  if (state.magic != kSleepStateMagic ||
      state.requestEpoch < AppConfig::kPowerMinimumValidRtcEpoch ||
      state.durationSeconds < 5UL ||
      state.durationSeconds > AppConfig::kPowerMaximumSleepSeconds)
  {
    return false;
  }

  return state.deadlineEpoch > state.requestEpoch &&
      state.deadlineEpoch - state.requestEpoch == state.durationSeconds;
}

bool persistentSleepStateIsValid()
{
  return sleepStateFieldsAreSane(g_persistentSleepState) &&
      g_persistentSleepState.checksum ==
          calculateSleepStateChecksum(g_persistentSleepState);
}

bool persistentSleepStateIsEmpty()
{
  return g_persistentSleepState.magic == 0U &&
      g_persistentSleepState.checksum == 0U;
}

void clearPersistentSleepState()
{
  // Invalidate first so a reset during cleanup never leaves a valid record.
  g_persistentSleepState.checksum = 0U;
  g_persistentSleepState.magic = 0U;
  g_persistentSleepState.requestEpoch = 0U;
  g_persistentSleepState.deadlineEpoch = 0U;
  g_persistentSleepState.durationSeconds = 0U;
}

bool storePersistentSleepState(
    uint32_t requestEpoch,
    uint32_t deadlineEpoch,
    uint32_t durationSeconds)
{
  PersistentSleepState state = {
      kSleepStateMagic,
      requestEpoch,
      deadlineEpoch,
      durationSeconds,
      0U};
  state.checksum = calculateSleepStateChecksum(state);

  g_persistentSleepState.checksum = 0U;
  g_persistentSleepState.magic = state.magic;
  g_persistentSleepState.requestEpoch = state.requestEpoch;
  g_persistentSleepState.deadlineEpoch = state.deadlineEpoch;
  g_persistentSleepState.durationSeconds = state.durationSeconds;
  g_persistentSleepState.checksum = state.checksum;

  return persistentSleepStateIsValid();
}

void configureOutputBeforeUnhold(uint32_t pin, bool high)
{
  pinMode(pin, OUTPUT);
  digitalWrite(pin, high ? HIGH : LOW);
  (void)gpio_hold_dis(static_cast<gpio_num_t>(pin));
}

void releasePowerPinHolds()
{
  // An individual GPIO hold resumes after deep-sleep wake. Configure every
  // pad to a safe level before releasing it so attached modules see no pulse.
  gpio_deep_sleep_hold_dis();
  configureOutputBeforeUnhold(AppConfig::kRs485TxEnablePin, false);
  configureOutputBeforeUnhold(AppConfig::kLoraMd0Pin, true);
  configureOutputBeforeUnhold(AppConfig::kLoraMd1Pin, true);
#if APP_HAS_IP_UPLINK && defined(USE_ESP8266)
  configureOutputBeforeUnhold(
      AppConfig::kEspEnablePin,
      AppConfig::kEspEnableActiveHigh);
#else
  configureOutputBeforeUnhold(
      AppConfig::kEspEnablePin,
      !AppConfig::kEspEnableActiveHigh);
#endif
  configureOutputBeforeUnhold(
      AppConfig::kEspResetPin,
      AppConfig::kEspResetActiveLow);
  if (AppConfig::kEnableOpenCloseNodeOutput)
  {
    configureOutputBeforeUnhold(
        AppConfig::kOpenCloseNodeGpio,
        AppConfig::kOpenCloseNodeActiveLow);
  }
}

bool holdOutputForDeepSleep(uint32_t pin, bool high)
{
  (void)gpio_hold_dis(static_cast<gpio_num_t>(pin));
  pinMode(pin, OUTPUT);
  digitalWrite(pin, high ? HIGH : LOW);
  delayMicroseconds(20U);
  return gpio_hold_en(static_cast<gpio_num_t>(pin)) == ESP_OK;
}

bool holdPowerDownPins()
{
  bool held = holdOutputForDeepSleep(
      AppConfig::kRs485TxEnablePin,
      false);

  if (AppConfig::kEnableOpenCloseNodeOutput)
  {
    held = holdOutputForDeepSleep(
        AppConfig::kOpenCloseNodeGpio,
        AppConfig::kOpenCloseNodeActiveLow) && held;
  }

#if APP_HAS_LORA
  held = holdOutputForDeepSleep(AppConfig::kLoraMd0Pin, true) && held;
  held = holdOutputForDeepSleep(AppConfig::kLoraMd1Pin, true) && held;
#elif APP_HAS_IP_UPLINK && defined(USE_ESP8266)
  held = holdOutputForDeepSleep(
      AppConfig::kEspEnablePin,
      AppConfig::kEspEnableActiveHigh) && held;
  held = holdOutputForDeepSleep(
      AppConfig::kEspResetPin,
      AppConfig::kEspResetActiveLow) && held;
#endif

  if (held)
  {
    gpio_deep_sleep_hold_en();
  }
  return held;
}

void quiesceRs485Interface()
{
#if APP_HAS_SENSORS
  SerialRs485.flush();
  endRs485Serial();
#endif
  pinMode(AppConfig::kRs485TxEnablePin, OUTPUT);
  digitalWrite(AppConfig::kRs485TxEnablePin, LOW);
}

bool activeTransportIsIdleForPowerDown()
{
#if APP_HAS_LORA
  return isLoraIdleForPowerDown();
#elif APP_HAS_IP_UPLINK
  return !isAsyncPublishBusy();
#else
  return true;
#endif
}

void restoreActiveTransportAfterAbort()
{
  releasePowerPinHolds();
#if APP_HAS_LORA
  initializeLoraLink();
#elif APP_HAS_IP_UPLINK
  restoreMqttTransportAfterPowerDownAbort();
#endif
}

#if APP_CONTROLLER_POWER_MODE == APP_COMPONENT_MODE_POWER_DOWN
enum class EarlyBootEvent : uint8_t
{
  ColdOrNormalBoot,
  ScheduledDeepSleepWake,
  UnexpectedDeepSleepWake,
  CorruptSleepStateRejected,
  InterruptedSleepEntryRejected,
};

enum class PowerDownRequestOutcome : uint8_t
{
  RetrySleepPreparation,
  AbortActiveCycle,
};

EarlyBootEvent g_earlyBootEvent = EarlyBootEvent::ColdOrNormalBoot;
uint32_t g_previousRequestEpoch = 0U;
uint32_t g_previousDeadlineEpoch = 0U;
uint32_t g_previousWakeEpoch = 0U;
bool g_commandWindowActive = false;
uint32_t g_commandWindowStartedMs = 0U;
uint32_t g_lastSleepDelayLogMs = 0U;

[[noreturn]] void enterDeepSleep(
    uint32_t requestEpoch,
    uint32_t deadlineEpoch)
{
  quiesceRs485Interface();

  if (!holdPowerDownPins())
  {
    SerialMon.println("Power: GPIO hold failed; restarting instead of sleeping");
    SerialMon.flush();
    delay(20);
    ESP.restart();
  }

  SerialMon.print("Power: entering ESP32 deep sleep; RTC deadline=");
  SerialMon.print(deadlineEpoch);
  SerialMon.print(" (requested at ");
  SerialMon.print(requestEpoch);
  SerialMon.println(")");
  SerialMon.flush();
  delay(20);
  esp_deep_sleep_start();
}

PowerDownRequestOutcome requestPowerDownCycle()
{
#if APP_HAS_LORA
  if (!prepareLoraForPowerDown(AppConfig::kPowerSleepEntryTimeoutMs))
  {
    SerialMon.println(
        "Power: sleep delayed; LoRa has pending data, an incomplete frame, or busy AUX");
    return PowerDownRequestOutcome::RetrySleepPreparation;
  }
#elif APP_HAS_IP_UPLINK
  if (!prepareMqttTransportForPowerDown(
          AppConfig::kPowerSleepEntryTimeoutMs))
  {
    SerialMon.println("Power: IP transport could not enter deep sleep");
    restoreMqttTransportAfterPowerDownAbort();
    return PowerDownRequestOutcome::AbortActiveCycle;
  }
#endif

  const uint32_t requestEpoch = getEpochTime();
  if (requestEpoch < AppConfig::kPowerMinimumValidRtcEpoch)
  {
    SerialMon.println("Power: sleep rejected because RTC time is invalid");
    restoreActiveTransportAfterAbort();
    return PowerDownRequestOutcome::AbortActiveCycle;
  }

  const uint32_t deadlineEpoch =
      requestEpoch + AppConfig::kPowerSleepSeconds;
  if (!scheduleRtcWakeAlarm(deadlineEpoch))
  {
    SerialMon.println("Power: ESP32 timer-wakeup configuration failed");
    restoreActiveTransportAfterAbort();
    return PowerDownRequestOutcome::AbortActiveCycle;
  }

  if (!storePersistentSleepState(
          requestEpoch,
          deadlineEpoch,
          AppConfig::kPowerSleepSeconds))
  {
    cancelRtcWakeAlarm();
    clearPersistentSleepState();
    SerialMon.println("Power: RTC-memory sleep-state verification failed");
    restoreActiveTransportAfterAbort();
    return PowerDownRequestOutcome::AbortActiveCycle;
  }

  enterDeepSleep(requestEpoch, deadlineEpoch);
}

void reportEarlyBootEvent()
{
  switch (g_earlyBootEvent)
  {
    case EarlyBootEvent::ScheduledDeepSleepWake:
      SerialMon.print("Power: woke from ESP32 timer deep sleep; request=");
      SerialMon.print(g_previousRequestEpoch);
      SerialMon.print(" deadline=");
      SerialMon.print(g_previousDeadlineEpoch);
      SerialMon.print(" wake=");
      SerialMon.println(g_previousWakeEpoch);
      break;
    case EarlyBootEvent::UnexpectedDeepSleepWake:
      SerialMon.println("Power: deep-sleep wake was not caused by the scheduled timer");
      break;
    case EarlyBootEvent::CorruptSleepStateRejected:
      SerialMon.println("Power: corrupt RTC-memory sleep state rejected and cleared");
      break;
    case EarlyBootEvent::InterruptedSleepEntryRejected:
      SerialMon.println("Power: stale sleep request from an interrupted entry was cleared");
      break;
    case EarlyBootEvent::ColdOrNormalBoot:
    default:
      break;
  }
}
#else
bool g_stalePeriodicRequestCleared = false;
#endif
}

void powerManagerEarlyBoot()
{
  releasePowerPinHolds();

#if APP_CONTROLLER_POWER_MODE == APP_COMPONENT_MODE_POWER_DOWN
  const esp_sleep_wakeup_cause_t wakeCause =
      esp_sleep_get_wakeup_cause();
  const bool validState = persistentSleepStateIsValid();
  const bool emptyState = persistentSleepStateIsEmpty();

  if (wakeCause == ESP_SLEEP_WAKEUP_TIMER)
  {
    if (validState)
    {
      initializeRtc();
      g_previousRequestEpoch = g_persistentSleepState.requestEpoch;
      g_previousDeadlineEpoch = g_persistentSleepState.deadlineEpoch;
      g_previousWakeEpoch = getEpochTime();
      g_earlyBootEvent = EarlyBootEvent::ScheduledDeepSleepWake;
    }
    else
    {
      g_earlyBootEvent = emptyState
          ? EarlyBootEvent::UnexpectedDeepSleepWake
          : EarlyBootEvent::CorruptSleepStateRejected;
    }
    cancelRtcWakeAlarm();
    clearPersistentSleepState();
    return;
  }

  if (!emptyState)
  {
    g_earlyBootEvent = validState
        ? EarlyBootEvent::InterruptedSleepEntryRejected
        : EarlyBootEvent::CorruptSleepStateRejected;
    clearPersistentSleepState();
  }
  else if (wakeCause != ESP_SLEEP_WAKEUP_UNDEFINED)
  {
    g_earlyBootEvent = EarlyBootEvent::UnexpectedDeepSleepWake;
  }
#else
  if (g_persistentSleepState.magic == kSleepStateMagic)
  {
    clearPersistentSleepState();
    g_stalePeriodicRequestCleared = true;
  }
#endif
}

void initializePowerManagerAfterSetup()
{
  SerialMon.println("Power configuration:");
  printComponentMode(
      "ESP32 controller",
      AppConfig::kControllerPowerDown,
      true);
  printComponentMode(
      "LoRa module",
      AppConfig::kLoraPowerDown,
      APP_HAS_LORA != 0);
#if defined(USE_ESP8266)
  printComponentMode(
      "ESP8266",
      AppConfig::kWifiPowerDown,
      APP_HAS_IP_UPLINK != 0);
  printComponentMode("SIM800L", AppConfig::kSimPowerDown, false);
#else
  printComponentMode("ESP8266", AppConfig::kWifiPowerDown, false);
  printComponentMode(
      "SIM800L",
      AppConfig::kSimPowerDown,
      APP_HAS_IP_UPLINK != 0);
#endif

#if APP_CONTROLLER_POWER_MODE == APP_COMPONENT_MODE_POWER_DOWN
  reportEarlyBootEvent();
  SerialMon.print("Power cycle: ESP32_DEEP_SLEEP, sleep=");
  SerialMon.print(AppConfig::kPowerSleepSeconds);
  SerialMon.print(" s, command window=");
  SerialMon.print(AppConfig::kPowerCommandWindowMs);
  SerialMon.println(" ms");
#if APP_HAS_LORA
  SerialMon.println(
      "Power hardware check: E32 M0/M1 need pull-ups; RS485 DE needs a pull-down");
#elif APP_HAS_IP_UPLINK && defined(USE_ESP8266)
  SerialMon.println(
      "Power hardware: GPIO14 resets ESP8266 after wake; commands use the active window");
#endif

  AppRuntimeState& state = appState();
  const uint32_t nowMs = millis();
  state.lastReadMs = nowMs - state.samplingPeriodMs;
  state.lastSendMs = nowMs - state.transmissionPeriodMs;
  g_commandWindowActive = false;
#else
  SerialMon.println("Power mode: NORMAL (continuous operation; deep sleep disabled)");
  if (g_stalePeriodicRequestCleared)
  {
    SerialMon.println("Power: stale periodic sleep request cleared during normal-mode boot");
  }
#endif
}

bool powerManagerAllowsSensorWork()
{
#if APP_CONTROLLER_POWER_MODE == APP_COMPONENT_MODE_POWER_DOWN
  return !g_commandWindowActive;
#else
  return true;
#endif
}

void notifyPowerManagerTelemetryResult(bool delivered)
{
#if APP_CONTROLLER_POWER_MODE == APP_COMPONENT_MODE_POWER_DOWN
  if (!delivered || g_commandWindowActive)
  {
    if (!delivered)
    {
      SerialMon.println("Power: telemetry not delivered; node remains awake and will retry");
    }
    return;
  }

  g_commandWindowActive = true;
  g_commandWindowStartedMs = millis();
  g_lastSleepDelayLogMs = 0U;
  SerialMon.print("Power: telemetry delivered; listening for ");
#if APP_HAS_LORA
  SerialMon.print("LoRa");
#else
  SerialMon.print("server");
#endif
  SerialMon.print(" commands for ");
  SerialMon.print(AppConfig::kPowerCommandWindowMs);
  SerialMon.println(" ms");
#else
  (void)delivered;
#endif
}

void servicePowerManager()
{
#if APP_CONTROLLER_POWER_MODE == APP_COMPONENT_MODE_POWER_DOWN
  if (!g_commandWindowActive ||
      millis() - g_commandWindowStartedMs < AppConfig::kPowerCommandWindowMs)
  {
    return;
  }

  if (!activeTransportIsIdleForPowerDown())
  {
    const uint32_t nowMs = millis();
    if (g_lastSleepDelayLogMs == 0U ||
        nowMs - g_lastSleepDelayLogMs >= kSleepDelayLogPeriodMs)
    {
      g_lastSleepDelayLogMs = nowMs;
#if APP_HAS_LORA
      SerialMon.println("Power: waiting for LoRa receive/command activity to finish");
#else
      SerialMon.println("Power: waiting for MQTT publish/command activity to finish");
#endif
    }
    return;
  }

  if (requestPowerDownCycle() == PowerDownRequestOutcome::AbortActiveCycle)
  {
    g_commandWindowActive = false;
    AppRuntimeState& state = appState();
    const uint32_t nowMs = millis();
    state.lastReadMs = nowMs;
    state.lastSendMs = nowMs;
    SerialMon.println("Power: periodic sleep cycle aborted; active scheduling resumed");
  }
#endif
}
