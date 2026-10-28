/** @file PowerManager.cpp @brief Per-component power policy and RTC-standby coordination. */
#include "PowerManager.h"
#include "RemoteWakeCycle.h"

#include "../app/AppState.h"
#include "../comm/MQTT.h"
#include "../config/AppConfig.h"
#include "../devices/RTC.h"
#include "../devices/BackupDomainAccess.h"
#include "../platform/Watchdog.h"
#include "../radio/LoraLink.h"

#include <Arduino.h>
#include <stm32f4xx_hal.h>

extern HardwareSerial SerialMon;
extern HardwareSerial SerialAT;
extern HardwareSerial SerialLoRa;
#if APP_CONTROLLER_POWER_MODE == APP_COMPONENT_MODE_LORA_WOR
extern STM32RTC& rtc;
extern "C" void SystemClock_Config(void);
#endif

namespace
{
void scheduleFreshSensorCycle();
#if APP_CONTROLLER_POWER_MODE == APP_COMPONENT_MODE_REMOTE_WAKE
RemoteWakeCycle g_remoteWakeCycle;
bool g_remoteSensorCycleActive = false;
uint32_t g_lastRemotePollMs = 0U;
uint32_t g_lastWakeRequestId = 0U;
uint64_t g_lastWakeRequestSeconds = 0U;
#endif
#if APP_CONTROLLER_POWER_MODE == APP_COMPONENT_MODE_QUEUED || \
    APP_CONTROLLER_POWER_MODE == APP_COMPONENT_MODE_LORA_WOR
uint32_t g_queuedWakeStartedMs = 0U;
uint32_t g_queuedWakeDurationMs = 0U;
uint32_t g_queuedWakeRequestId = 0U;
uint64_t g_queuedWakeRequestSeconds = 0U;

bool queuedWakeActive()
{
  return g_queuedWakeDurationMs != 0U &&
      millis() - g_queuedWakeStartedMs < g_queuedWakeDurationMs;
}
#endif

#if APP_CONTROLLER_POWER_MODE == APP_COMPONENT_MODE_LORA_WOR
volatile bool g_worAuxInterrupt = false;
volatile bool g_worRtcInterrupt = false;
bool g_worCommandWindow = false;
uint32_t g_worWindowStartedMs = 0U;
uint32_t g_worNextReportEpoch = 0U;

void onWorAuxInterrupt() { g_worAuxInterrupt = true; }
void onWorRtcInterrupt(void*) { g_worRtcInterrupt = true; }

/** @brief Snapshot foreground WOR evidence; an AUX edge is not a decoded command. */
void printWorSnapshot(const char* event, uint32_t stopCalls, uint32_t elapsedSeconds)
{
  SerialMon.print("Power: WOR ");
  SerialMon.print(event);
  SerialMon.print(" stop_calls=");
  SerialMon.print(stopCalls);
  SerialMon.print(" rtc_elapsed_s=");
  SerialMon.print(elapsedSeconds);
  SerialMon.print(" AUX=");
  SerialMon.print(digitalRead(AppConfig::kLoraAuxPin) == HIGH ? "HIGH" : "LOW");
  SerialMon.print(" aux_irq=");
  SerialMon.print(g_worAuxInterrupt ? 1U : 0U);
  SerialMon.print(" aux_pending=");
  SerialMon.print(__HAL_GPIO_EXTI_GET_IT(digitalPinToBitMask(AppConfig::kLoraAuxPin)) != RESET ? 1U : 0U);
  SerialMon.print(" rtc_irq=");
  SerialMon.print(g_worRtcInterrupt ? 1U : 0U);
  SerialMon.print(" M0=");
  SerialMon.print(digitalRead(AppConfig::kLoraMd0Pin) == HIGH ? 1U : 0U);
  SerialMon.print(" M1=");
  SerialMon.println(digitalRead(AppConfig::kLoraMd1Pin) == HIGH ? 1U : 0U);
}

void runLoraWorStopCycle()
{
  const uint32_t nowEpoch = getEpochTime();
  if (!isRtcTrusted() || nowEpoch < AppConfig::kPowerMinimumValidRtcEpoch)
  {
    g_worCommandWindow = false;
    SerialMon.println("Power: Stop requires trusted RTC; send STIME before sleeping");
    return;
  }
  if (g_worNextReportEpoch <= nowEpoch ||
      g_worNextReportEpoch - nowEpoch > AppConfig::kPowerSleepSeconds + 5UL)
  {
    g_worCommandWindow = false;
    scheduleFreshSensorCycle();
    return;
  }
  // Detached GPIO edges can leave a pending EXTI bit during normal traffic.
  // Clear ONLY this line's stale state while AUX is idle, BEFORE Mode 2 is
  // selected. Never clear the shared NVIC vector or edges after arming WOR.
  const uint32_t savedPrimask = __get_PRIMASK();
  __disable_irq();
  g_worAuxInterrupt = false;
  g_worRtcInterrupt = false;
  const uint32_t auxMask = digitalPinToBitMask(AppConfig::kLoraAuxPin);
  const bool staleAuxPending = __HAL_GPIO_EXTI_GET_IT(auxMask) != RESET;
  const bool auxWasHigh = digitalRead(AppConfig::kLoraAuxPin) == HIGH;
  if (auxWasHigh)
    __HAL_GPIO_EXTI_CLEAR_IT(auxMask);
  __set_PRIMASK(savedPrimask);
  if (staleAuxPending)
    SerialMon.println(auxWasHigh
        ? "Power: WOR cleared pre-arm stale AUX pending flag while line HIGH"
        : "Power: WOR pre-arm AUX LOW; pending flag preserved");

  if (!prepareLoraForWakeOnRadio(AppConfig::kPowerSleepEntryTimeoutMs))
  {
    SerialMon.println("Power: E32 Mode 2 preparation failed; staying awake");
    g_worCommandWindow = false;
    return;
  }

  attachInterrupt(digitalPinToInterrupt(AppConfig::kLoraAuxPin),
                  onWorAuxInterrupt, FALLING);
  rtc.attachInterrupt(onWorRtcInterrupt, STM32RTC::ALARM_A);
  bool radioWake = false;
  bool failed = false;
  uint32_t stopCalls = 0U;
  const uint32_t startedEpoch = getEpochTime();
  const char* exitReason = "REPORT_DEADLINE";
  printWorSnapshot("armed", stopCalls, 0U);
  while (getEpochTime() < g_worNextReportEpoch)
  {
    serviceHardwareWatchdog(WatchdogStage::PowerTransition);
    const uint32_t now = getEpochTime();
    uint32_t alarmEpoch = now + AppConfig::kLoraWorWatchdogWakeSeconds;
    if (alarmEpoch > g_worNextReportEpoch) alarmEpoch = g_worNextReportEpoch;
    // Keep an AUX edge that arrived during radio preparation/arming or the
    // previous foreground heartbeat. Clearing it here can lose a real probe.
    g_worRtcInterrupt = false;
    if (!scheduleRtcWakeAlarm(alarmEpoch))
    {
      failed = true;
      exitReason = "RTC_ALARM_SETUP_FAILED";
      break;
    }
    if (g_worAuxInterrupt || digitalRead(AppConfig::kLoraAuxPin) == LOW)
    {
      radioWake = true;
      exitReason = g_worAuxInterrupt ? "AUX_EDGE_BEFORE_STOP" : "AUX_LOW_BEFORE_STOP";
      break;
    }
    SerialMon.print("Power: WOR Stop requested; alarm_epoch=");
    SerialMon.println(alarmEpoch);
    // Drain our own diagnostic TX before WFI so a pending debug-UART TX IRQ
    // does not immediately end the Stop attempt. Never print from an ISR.
    SerialMon.flush();
    HAL_SuspendTick();
    SCB->ICSR = SCB_ICSR_PENDSTCLR_Msk;
    // Close the check-to-WFI race: a pending AUX/RTC IRQ must prevent a lost
    // wake. Restore clocks before pending handlers are allowed to run.
    __disable_irq();
    __DSB();
    __ISB();
    bool stopCalled = false;
    if (!g_worAuxInterrupt && !g_worRtcInterrupt &&
        digitalRead(AppConfig::kLoraAuxPin) != LOW)
    {
      stopCalled = true;
      ++stopCalls;
      HAL_PWR_EnterSTOPMode(PWR_LOWPOWERREGULATOR_ON, PWR_STOPENTRY_WFI);
    }
    // F401 returns on HSI after Stop. Restore the Arduino board PLL before
    // touching Serial, millis(), or the LoRa UART.
    if (stopCalled)
    {
      SystemClock_Config();
      SystemCoreClockUpdate();
    }
    HAL_ResumeTick();
    __enable_irq();
    if (g_worAuxInterrupt || digitalRead(AppConfig::kLoraAuxPin) == LOW)
    {
      radioWake = true;
      exitReason = stopCalled
          ? (g_worAuxInterrupt ? "AUX_EDGE_AFTER_STOP" : "AUX_LOW_AFTER_STOP")
          : (g_worAuxInterrupt ? "AUX_EDGE_BEFORE_STOP" : "AUX_LOW_BEFORE_STOP");
      break;
    }
    if (!g_worRtcInterrupt && getEpochTime() < alarmEpoch)
    {
      failed = true;
      exitReason = "UNEXPECTED_WAKE";
      break;
    }
    printWorSnapshot("RTC heartbeat", stopCalls, getEpochTime() - startedEpoch);
    cancelRtcWakeAlarm();
  }
  // These fields describe the event before radio restoration changes AUX/M0/M1.
  SerialMon.print("Power: WOR exit reason=");
  SerialMon.println(exitReason);
  printWorSnapshot("exit", stopCalls, getEpochTime() - startedEpoch);
  cancelRtcWakeAlarm();
  rtc.detachInterrupt(STM32RTC::ALARM_A);
  detachInterrupt(digitalPinToInterrupt(AppConfig::kLoraAuxPin));
  serviceHardwareWatchdog(WatchdogStage::PowerTransition);
  if (!resumeLoraFromWakeOnRadio(AppConfig::kLoraTxCompleteTimeoutMs))
  {
    // Fail open and reinitialize the radio; never silently claim a reachable
    // sleep state when Mode 0 could not be restored.
    SerialMon.println("Power: E32 Mode 0 restore failed; radio reinitialized");
    initializeLoraLink();
    failed = true;
  }
  if (failed)
  {
    g_worCommandWindow = false;
    SerialMon.println("Power: Stop cycle aborted; active scheduling resumed");
  }
  else if (radioWake)
  {
    g_worCommandWindow = true;
    g_worWindowStartedMs = millis();
    SerialMon.println("Power: WOR AUX activity; receive window opened (command not yet confirmed)");
  }
  else
  {
    g_worCommandWindow = false;
    scheduleFreshSensorCycle();
    SerialMon.println("Power: RTC report deadline woke STM32");
  }
}
#endif

void scheduleFreshSensorCycle()
{
  AppRuntimeState& state = appState();
  const uint32_t nowMs = millis();
  state.lastReadMs = nowMs - state.samplingPeriodMs;
  state.lastSendMs = nowMs - state.transmissionPeriodMs;
}

const char* componentModeName(bool powerDown)
{
  return powerDown ? "POWER_DOWN" : "NORMAL";
}

/** @brief Print one component's selected power mode and support status. */
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

#if APP_CONTROLLER_USES_STANDBY
constexpr uint32_t kSleepStateMagic = 0x50444E31UL; // "PDN1"
constexpr uint32_t kBackupMagicRegister = RTC_BKP_DR15;
constexpr uint32_t kBackupRequestEpochRegister = RTC_BKP_DR16;
constexpr uint32_t kBackupDeadlineEpochRegister = RTC_BKP_DR17;
constexpr uint32_t kBackupDurationRegister = RTC_BKP_DR18;
constexpr uint32_t kBackupChecksumRegister = RTC_BKP_DR19;
constexpr uint32_t kSleepEntryMinimumLeadSeconds = 2UL;
constexpr uint32_t kSleepDelayLogPeriodMs = 5000UL;
constexpr uint32_t kRs485TransmitEnablePin = PA8;

struct PersistentSleepState
{
  uint32_t magic;
  uint32_t requestEpoch;
  uint32_t deadlineEpoch;
  uint32_t durationSeconds;
  uint32_t checksum;
};

enum class PersistentStateStatus : uint8_t
{
  Empty,
  Valid,
  Corrupt,
};

enum class EarlyBootEvent : uint8_t
{
  ColdOrNormalBoot,
  ScheduledStandbyWake,
  UnexpectedStandbyWake,
  CorruptSleepStateRejected,
  ExpiredSleepStateRejected,
  RtcSleepStateRejected,
  StandbyEntryFailed,
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

RTC_HandleTypeDef makeBackupHandle()
{
  RTC_HandleTypeDef handle = {};
  handle.Instance = RTC;
  return handle;
}

uint32_t readBackupRegister(uint32_t backupRegister)
{
  const BackupDomainAccess access;
  RTC_HandleTypeDef handle = makeBackupHandle();
  const uint32_t value = HAL_RTCEx_BKUPRead(&handle, backupRegister);
  return value;
}

void writeBackupRegister(uint32_t backupRegister, uint32_t value)
{
  const BackupDomainAccess access;
  RTC_HandleTypeDef handle = makeBackupHandle();
  HAL_RTCEx_BKUPWrite(&handle, backupRegister, value);
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
  if (state.requestEpoch < AppConfig::kPowerMinimumValidRtcEpoch ||
      state.durationSeconds < 5UL ||
      state.durationSeconds > AppConfig::kPowerMaximumSleepSeconds)
  {
    return false;
  }

  return state.deadlineEpoch > state.requestEpoch &&
      state.deadlineEpoch - state.requestEpoch == state.durationSeconds;
}

PersistentStateStatus loadPersistentSleepState(PersistentSleepState& state)
{
  state.magic = readBackupRegister(kBackupMagicRegister);
  if (state.magic != kSleepStateMagic)
  {
    state = {};
    return PersistentStateStatus::Empty;
  }

  state.requestEpoch = readBackupRegister(kBackupRequestEpochRegister);
  state.deadlineEpoch = readBackupRegister(kBackupDeadlineEpochRegister);
  state.durationSeconds = readBackupRegister(kBackupDurationRegister);
  state.checksum = readBackupRegister(kBackupChecksumRegister);

  if (state.checksum != calculateSleepStateChecksum(state) ||
      !sleepStateFieldsAreSane(state))
  {
    return PersistentStateStatus::Corrupt;
  }
  return PersistentStateStatus::Valid;
}

void clearPersistentSleepState()
{
  // Invalidate the record first so a reset during cleanup cannot create a
  // valid-looking partial request.
  writeBackupRegister(kBackupChecksumRegister, 0U);
  writeBackupRegister(kBackupMagicRegister, 0U);
  writeBackupRegister(kBackupRequestEpochRegister, 0U);
  writeBackupRegister(kBackupDeadlineEpochRegister, 0U);
  writeBackupRegister(kBackupDurationRegister, 0U);
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

  // The checksum is committed last. A brownout or reset during these writes
  // is therefore rejected by the next boot rather than entering a sleep loop.
  writeBackupRegister(kBackupChecksumRegister, 0U);
  writeBackupRegister(kBackupMagicRegister, state.magic);
  writeBackupRegister(kBackupRequestEpochRegister, state.requestEpoch);
  writeBackupRegister(kBackupDeadlineEpochRegister, state.deadlineEpoch);
  writeBackupRegister(kBackupDurationRegister, state.durationSeconds);
  writeBackupRegister(kBackupChecksumRegister, state.checksum);

  PersistentSleepState verified = {};
  return loadPersistentSleepState(verified) == PersistentStateStatus::Valid &&
      verified.requestEpoch == requestEpoch &&
      verified.deadlineEpoch == deadlineEpoch &&
      verified.durationSeconds == durationSeconds;
}

void clearPowerWakeFlags()
{
  __HAL_PWR_CLEAR_FLAG(PWR_FLAG_WU | PWR_FLAG_SB);
}

bool pendingStateMatchesRtc(
    const PersistentSleepState& state,
    uint32_t nowEpoch)
{
  if (nowEpoch < AppConfig::kPowerMinimumValidRtcEpoch ||
      state.deadlineEpoch <= nowEpoch + kSleepEntryMinimumLeadSeconds)
  {
    return false;
  }

  // Permit a few seconds of RTC quantization/reset latency, but reject a
  // clock that moved behind the recorded request or far before the deadline.
  if (nowEpoch + 5UL < state.requestEpoch)
  {
    return false;
  }

  return state.deadlineEpoch - nowEpoch <= state.durationSeconds + 5UL;
}

void quiesceRs485Interface()
{
  Serial1.flush();
  Serial1.end();
  pinMode(kRs485TransmitEnablePin, OUTPUT);
  digitalWrite(kRs485TransmitEnablePin, LOW);
}

void assertEarlySleepPins()
{
#if APP_HAS_LORA
  forceLoraPowerDownPins();
#endif
  pinMode(kRs485TransmitEnablePin, OUTPUT);
  digitalWrite(kRs485TransmitEnablePin, LOW);
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

[[noreturn]] void resetIntoStandby(
    uint32_t requestEpoch,
    uint32_t deadlineEpoch)
{
  quiesceRs485Interface();

  SerialMon.print("Power: sleep request committed; RTC deadline=");
  SerialMon.print(deadlineEpoch);
  SerialMon.print(" (requested at ");
  SerialMon.print(requestEpoch);
  SerialMon.println(")");
  SerialMon.println("Power: software reset will enter STM32 Standby before IWDG starts");
  SerialMon.flush();

  NVIC_SystemReset();

  // NVIC_SystemReset() is not expected to return. If a debugger blocks the
  // reset, do not feed the active IWDG; its hardware reset retries the same
  // validated sleep handoff.
  while (true)
  {
  }
}

PowerDownRequestOutcome requestPowerDownCycle()
{
  serviceHardwareWatchdog(WatchdogStage::PowerTransition);
  const uint32_t requestEpoch = getEpochTime();
  if (requestEpoch < AppConfig::kPowerMinimumValidRtcEpoch ||
      (AppConfig::kQueuedCommands && !isRtcTrusted()))
  {
    SerialMon.println("Power: sleep rejected because RTC time is invalid");
    return PowerDownRequestOutcome::AbortActiveCycle;
  }

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

  const uint32_t deadlineEpoch =
      requestEpoch + AppConfig::kPowerSleepSeconds;
  if (!storePersistentSleepState(
          requestEpoch,
          deadlineEpoch,
          AppConfig::kPowerSleepSeconds))
  {
    clearPersistentSleepState();
    SerialMon.println("Power: RTC backup-state verification failed; sleep cancelled");
#if APP_HAS_LORA
    initializeLoraLink();
#elif APP_HAS_IP_UPLINK
    restoreMqttTransportAfterPowerDownAbort();
#endif
    return PowerDownRequestOutcome::AbortActiveCycle;
  }

  resetIntoStandby(requestEpoch, deadlineEpoch);
}

void reportEarlyBootEvent()
{
  switch (g_earlyBootEvent)
  {
    case EarlyBootEvent::ScheduledStandbyWake:
      SerialMon.print("Power: woke from STM32 Standby; request=");
      SerialMon.print(g_previousRequestEpoch);
      SerialMon.print(" deadline=");
      SerialMon.print(g_previousDeadlineEpoch);
      SerialMon.print(" wake=");
      SerialMon.println(g_previousWakeEpoch);
      break;
    case EarlyBootEvent::UnexpectedStandbyWake:
      SerialMon.println("Power: Standby wake detected without a valid scheduled request");
      break;
    case EarlyBootEvent::CorruptSleepStateRejected:
      SerialMon.println("Power: corrupt RTC backup sleep state rejected and cleared");
      break;
    case EarlyBootEvent::ExpiredSleepStateRejected:
      SerialMon.println("Power: expired RTC backup sleep request rejected and cleared");
      break;
    case EarlyBootEvent::RtcSleepStateRejected:
      SerialMon.println("Power: pending sleep rejected because RTC/state timing was invalid");
      break;
    case EarlyBootEvent::StandbyEntryFailed:
      SerialMon.println("Power: HAL returned from Standby entry; request cleared, normal boot continued");
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
#if APP_CONTROLLER_USES_STANDBY
  __HAL_RCC_PWR_CLK_ENABLE();
  const bool resumedFromStandby =
      __HAL_PWR_GET_FLAG(PWR_FLAG_SB) != RESET;

  PersistentSleepState state = {};
  const PersistentStateStatus stateStatus =
      loadPersistentSleepState(state);

  if (resumedFromStandby)
  {
    clearPowerWakeFlags();
    if (stateStatus == PersistentStateStatus::Valid)
    {
      initializeRtc();
      g_previousRequestEpoch = state.requestEpoch;
      g_previousDeadlineEpoch = state.deadlineEpoch;
      g_previousWakeEpoch = getEpochTime();
      cancelRtcWakeAlarm();
      clearPersistentSleepState();
      g_earlyBootEvent = EarlyBootEvent::ScheduledStandbyWake;
    }
    else
    {
      if (stateStatus == PersistentStateStatus::Corrupt)
      {
        clearPersistentSleepState();
      }
      g_earlyBootEvent = EarlyBootEvent::UnexpectedStandbyWake;
    }
    return;
  }

  if (stateStatus == PersistentStateStatus::Empty)
  {
    return;
  }

  if (stateStatus == PersistentStateStatus::Corrupt)
  {
    clearPersistentSleepState();
    g_earlyBootEvent = EarlyBootEvent::CorruptSleepStateRejected;
    return;
  }

  assertEarlySleepPins();
  initializeRtc();
  const uint32_t nowEpoch = getEpochTime();
  if (state.deadlineEpoch <= nowEpoch + kSleepEntryMinimumLeadSeconds)
  {
    clearPersistentSleepState();
    g_earlyBootEvent = EarlyBootEvent::ExpiredSleepStateRejected;
    return;
  }

  if (!pendingStateMatchesRtc(state, nowEpoch))
  {
    clearPersistentSleepState();
    g_earlyBootEvent = EarlyBootEvent::RtcSleepStateRejected;
    return;
  }

  HAL_PWR_DisableWakeUpPin(PWR_WAKEUP_PIN1);
  clearPowerWakeFlags();
  if (!scheduleRtcWakeAlarm(state.deadlineEpoch))
  {
    clearPersistentSleepState();
    g_earlyBootEvent = EarlyBootEvent::StandbyEntryFailed;
    return;
  }

  // No active application timing is needed on this pre-IWDG boot path. Stop
  // SysTick and clear a pending tick so it cannot make WFI return immediately
  // instead of committing the Standby transition.
  HAL_SuspendTick();
  SCB->ICSR = SCB_ICSR_PENDSTCLR_Msk;
  __DSB();
  __ISB();
  HAL_PWR_EnterSTANDBYMode();

  // Standby exits through a reset. Returning here is a hardware/HAL failure,
  // so invalidate the request and allow setup() to recover in awake mode.
  HAL_ResumeTick();
  cancelRtcWakeAlarm();
  clearPersistentSleepState();
  clearPowerWakeFlags();
  g_earlyBootEvent = EarlyBootEvent::StandbyEntryFailed;
#else
  // Returning to normal mode is also an explicit recovery operation. Remove
  // only this feature's own magic-tagged backup record so re-enabling periodic
  // mode later cannot honor an old, still-future deadline.
  const BackupDomainAccess access;
  RTC_HandleTypeDef handle = {};
  handle.Instance = RTC;
  if (HAL_RTCEx_BKUPRead(&handle, RTC_BKP_DR15) == 0x50444E31UL)
  {
    HAL_RTCEx_BKUPWrite(&handle, RTC_BKP_DR19, 0U);
    HAL_RTCEx_BKUPWrite(&handle, RTC_BKP_DR15, 0U);
    HAL_RTCEx_BKUPWrite(&handle, RTC_BKP_DR16, 0U);
    HAL_RTCEx_BKUPWrite(&handle, RTC_BKP_DR17, 0U);
    HAL_RTCEx_BKUPWrite(&handle, RTC_BKP_DR18, 0U);
    g_stalePeriodicRequestCleared = true;
  }
#endif
}

void initializePowerManagerAfterSetup()
{
  SerialMon.println("Power configuration:");
#if APP_CONTROLLER_POWER_MODE == APP_COMPONENT_MODE_REMOTE_WAKE
  SerialMon.println("  STM32 controller: REMOTE_WAKE [ACTIVE]");
#elif APP_CONTROLLER_POWER_MODE == APP_COMPONENT_MODE_LORA_WOR
  SerialMon.println("  STM32 controller: LORA_WOR_STOP [ACTIVE]");
#else
  printComponentMode(
      "STM32 controller",
      AppConfig::kControllerPowerDown,
      true);
#endif
#if APP_CONTROLLER_POWER_MODE == APP_COMPONENT_MODE_LORA_WOR
  SerialMon.println("  LoRa module: E32 MODE_2_WAKE_ON_RADIO [ACTIVE]");
#else
  printComponentMode("LoRa module", AppConfig::kLoraPowerDown, APP_HAS_LORA != 0);
#endif
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

#if APP_CONTROLLER_USES_STANDBY
  reportEarlyBootEvent();
  SerialMon.print(AppConfig::kQueuedCommands
      ? "Power cycle: RTC_QUEUED, sleep="
      : "Power cycle: RTC_PERIODIC, sleep=");
  SerialMon.print(AppConfig::kPowerSleepSeconds);
  SerialMon.print(" s, command window=");
  SerialMon.print(AppConfig::kQueuedCommands
      ? AppConfig::kQueuedCommandWindowMs
      : AppConfig::kPowerCommandWindowMs);
  SerialMon.println(" ms");
#if APP_HAS_LORA
  SerialMon.println(
      "Power hardware check: E32 M0/M1 need external pull-ups; RS485 DE needs a pull-down");
#elif APP_HAS_IP_UPLINK && defined(USE_ESP8266)
  SerialMon.println(
      "Power hardware: ESP8266 wakes through PB8/ESP_RST; server commands wait for the active window");
#endif

  // Make one fresh sample and one telemetry send due on the first loop after
  // every cold boot or RTC wake. Unsigned arithmetic keeps millis() rollover safe.
  scheduleFreshSensorCycle();
  g_commandWindowActive = false;
#elif APP_CONTROLLER_POWER_MODE == APP_COMPONENT_MODE_REMOTE_WAKE
  SerialMon.println("Power mode: REMOTE_WAKE (CPU Sleep; selected radio remains NORMAL)");
  if (AppConfig::kRemoteWakeUsesAppSchedule)
    SerialMon.print("Power: SRATE/STRAN scheduled idle; no fixed sleep interval; default WAKE lease=");
  else
  {
    SerialMon.print("Power: legacy reachable idle interval=");
    SerialMon.print(AppConfig::kPowerSleepSeconds);
    SerialMon.print(" s; default WAKE lease=");
  }
  SerialMon.print(AppConfig::kRemoteWakeDefaultSeconds);
  SerialMon.println(" s; watchdog remains armed");
  g_remoteWakeCycle.begin(millis(), AppConfig::kPowerSleepSeconds * 1000UL,
                         AppConfig::kPowerCommandWindowMs, AppConfig::kRemoteWakeUsesAppSchedule);
  g_remoteSensorCycleActive = false;
  g_lastRemotePollMs = millis();
  scheduleFreshSensorCycle();
#elif APP_CONTROLLER_POWER_MODE == APP_COMPONENT_MODE_LORA_WOR
  SerialMon.print("Power: RTC report interval=");
  SerialMon.print(AppConfig::kPowerSleepSeconds);
  SerialMon.print(" s, IWDG RTC heartbeat=");
  SerialMon.print(AppConfig::kLoraWorWatchdogWakeSeconds);
  SerialMon.println(" s; gateway must enable Mode-1 wake probe");
  initializeRtc();
  scheduleFreshSensorCycle();
  g_worCommandWindow = false;
#else
  SerialMon.println("Power mode: NORMAL (continuous operation; Standby disabled)");
  if (g_stalePeriodicRequestCleared)
  {
    SerialMon.println("Power: stale periodic sleep request cleared during normal-mode boot");
  }
#endif
}

void notifyPowerManagerSensorCycle(bool active)
{
#if APP_CONTROLLER_POWER_MODE == APP_COMPONENT_MODE_REMOTE_WAKE
  g_remoteSensorCycleActive = active;
#else
  (void)active;
#endif
}

bool powerManagerAllowsSensorWork()
{
#if APP_CONTROLLER_USES_STANDBY
#if APP_CONTROLLER_POWER_MODE == APP_COMPONENT_MODE_QUEUED
  if (queuedWakeActive()) return true;
#endif
  return !g_commandWindowActive;
#elif APP_CONTROLLER_POWER_MODE == APP_COMPONENT_MODE_REMOTE_WAKE
  return g_remoteWakeCycle.active();
#elif APP_CONTROLLER_POWER_MODE == APP_COMPONENT_MODE_LORA_WOR
  return queuedWakeActive() || !g_worCommandWindow;
#else
  return true;
#endif
}

void notifyPowerManagerTelemetryResult(bool delivered)
{
#if APP_CONTROLLER_USES_STANDBY
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
  SerialMon.print(AppConfig::kQueuedCommands
      ? AppConfig::kQueuedCommandWindowMs
      : AppConfig::kPowerCommandWindowMs);
  SerialMon.println(" ms");
#elif APP_CONTROLLER_POWER_MODE == APP_COMPONENT_MODE_REMOTE_WAKE
  if (delivered) g_remoteWakeCycle.telemetryDelivered(millis());
  else SerialMon.println("Power: report failed; radio remains connected for retry");
#elif APP_CONTROLLER_POWER_MODE == APP_COMPONENT_MODE_LORA_WOR
  if (delivered)
  {
    g_worCommandWindow = true;
    g_worWindowStartedMs = millis();
    const uint32_t now = getEpochTime();
    g_worNextReportEpoch = now + AppConfig::kPowerSleepSeconds;
    SerialMon.println("Power: report delivered; LoRa command window opened");
  }
  else SerialMon.println("Power: report failed; staying awake for retry");
#else
  (void)delivered;
#endif
}

void servicePowerManager()
{
#if APP_CONTROLLER_POWER_MODE == APP_COMPONENT_MODE_REMOTE_WAKE
  bool transportIdle = true;
#if APP_HAS_IP_UPLINK
  transportIdle = !isAsyncPublishBusy();
#elif APP_HAS_LORA
  transportIdle = isLoraIdleForPowerDown();
#endif
  const uint32_t nowMs = millis();
  const AppRuntimeState& state = appState();
  const bool applicationDue = nowMs - state.lastReadMs >= state.samplingPeriodMs ||
      nowMs - state.lastSendMs >= state.transmissionPeriodMs;
  const auto transition = g_remoteWakeCycle.advance(nowMs, transportIdle,
      applicationDue, g_remoteSensorCycleActive);
  if (transition == RemoteWakeCycle::Transition::EnteredIdle)
  {
    SerialMon.println(AppConfig::kRemoteWakeUsesAppSchedule ?
        "Power: REACHABLE_IDLE; waiting for SRATE/STRAN or commands; radio/WDT serviced" :
        "Power: REACHABLE_IDLE; sensor work paused, radio and watchdog remain active");
  }
  else if (transition == RemoteWakeCycle::Transition::PeriodicWake)
  {
    SerialMon.println("Power: periodic wake from reachable idle; sampling/reporting");
    scheduleFreshSensorCycle();
  }
  else if (transition == RemoteWakeCycle::Transition::ScheduledWake)
  {
    // Do not reset timestamps: only the independent work that is due may run.
    SerialMon.println("Power: scheduled work/reply pending; resume without forcing other deadlines");
  }
#elif APP_CONTROLLER_POWER_MODE == APP_COMPONENT_MODE_LORA_WOR
  if (!g_worCommandWindow || queuedWakeActive() ||
      millis() - g_worWindowStartedMs < AppConfig::kLoraWorCommandWindowMs ||
      !isLoraIdleForPowerDown()) return;
  runLoraWorStopCycle();
#elif APP_CONTROLLER_USES_STANDBY
#if APP_CONTROLLER_POWER_MODE == APP_COMPONENT_MODE_QUEUED
  if (queuedWakeActive()) return;
#endif
  const uint32_t commandWindowMs = AppConfig::kQueuedCommands
      ? AppConfig::kQueuedCommandWindowMs
      : AppConfig::kPowerCommandWindowMs;
  if (!g_commandWindowActive ||
      millis() - g_commandWindowStartedMs < commandWindowMs)
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
    // Resume the normal active scheduler after an unrecoverable preparation
    // error. This prevents a bad RTC/backup domain from freezing the node in
    // an awake-but-no-more-samples state.
    g_commandWindowActive = false;
    AppRuntimeState& state = appState();
    const uint32_t nowMs = millis();
    state.lastReadMs = nowMs;
    state.lastSendMs = nowMs;
    SerialMon.println("Power: periodic sleep cycle aborted; active scheduling resumed");
  }
#endif
}

bool requestRemoteWake(uint64_t seconds, uint32_t requestId)
{
#if APP_CONTROLLER_POWER_MODE == APP_COMPONENT_MODE_REMOTE_WAKE
  if (requestId != 0U && requestId == g_lastWakeRequestId)
  {
    // QoS retransmission: acknowledge the same active lease without resetting
    // its timer or scheduling another sample. Reject changed/expired repeats.
    if (seconds != g_lastWakeRequestSeconds || !g_remoteWakeCycle.active() ||
        g_remoteWakeCycle.remainingSeconds(millis()) == 0U)
    {
      SerialMon.println("WAKE rejected: changed or expired duplicate request");
      return false;
    }
    SerialMon.println("Power: duplicate WAKE acknowledged; original deadline unchanged");
    return true;
  }
  if (!g_remoteWakeCycle.requestWake(millis(), seconds, AppConfig::kRemoteWakeDefaultSeconds))
  {
    SerialMon.println("WAKE rejected: duration must be 0 (default) or 1..86400 seconds");
    return false;
  }
  g_lastWakeRequestId = requestId;
  g_lastWakeRequestSeconds = seconds;
  scheduleFreshSensorCycle();
  SerialMon.print("Power: WAKE accepted; ACTIVE for ");
  SerialMon.print(g_remoteWakeCycle.remainingSeconds(millis()));
  SerialMon.println(" seconds (no controller reset)");
  return true;
#elif APP_CONTROLLER_POWER_MODE == APP_COMPONENT_MODE_QUEUED || \
      APP_CONTROLLER_POWER_MODE == APP_COMPONENT_MODE_LORA_WOR
  const uint64_t acceptedSeconds = seconds == 0U
      ? AppConfig::kRemoteWakeDefaultSeconds : seconds;
  if (acceptedSeconds == 0U || acceptedSeconds > AppConfig::kRemoteWakeMaximumSeconds)
  {
    return false;
  }
  if (requestId != 0U && requestId == g_queuedWakeRequestId)
  {
    return seconds == g_queuedWakeRequestSeconds && queuedWakeActive();
  }
  g_queuedWakeRequestId = requestId;
  g_queuedWakeRequestSeconds = seconds;
  g_queuedWakeStartedMs = millis();
  g_queuedWakeDurationMs = static_cast<uint32_t>(acceptedSeconds * 1000ULL);
  scheduleFreshSensorCycle();
  SerialMon.print("Power: WAKE accepted for ");
  SerialMon.print(static_cast<uint32_t>(acceptedSeconds));
  SerialMon.println(" seconds; low-power entry postponed");
  return true;
#else
  (void)seconds;
  (void)requestId;
  SerialMon.println("WAKE rejected: select controller REMOTE_WAKE; NORMAL/RTC_PERIODIC are unchanged");
  return false;
#endif
}

bool powerManagerShouldRunApplication()
{
#if APP_CONTROLLER_POWER_MODE == APP_COMPONENT_MODE_REMOTE_WAKE
  if (g_remoteWakeCycle.active()) return true;
  bool uartReady = false;
#if APP_HAS_IP_UPLINK
  uartReady = SerialAT.available() > 0;
#elif APP_HAS_LORA
  uartReady = SerialLoRa.available() > 0;
#endif
  const uint32_t nowMs = millis();
  if (uartReady || nowMs - g_lastRemotePollMs >= AppConfig::kRemoteWakePollIntervalMs)
  {
    g_lastRemotePollMs = nowMs;
    return true;
  }
  return false;
#else
  return true;
#endif
}

void powerManagerIdleCpu()
{
#if APP_CONTROLLER_POWER_MODE == APP_COMPONENT_MODE_REMOTE_WAKE
  if (!g_remoteWakeCycle.active())
  {
    // Keep SysTick and UART interrupts running. The 1-ms tick bounds a lost
    // wake-edge race; regular application checkpoints feed IWDG, never an ISR.
    SCB->SCR &= ~SCB_SCR_SLEEPDEEP_Msk;
    __DSB();
    __WFI();
  }
#endif
}

uint32_t powerManagerMode()
{
#if APP_CONTROLLER_POWER_MODE == APP_COMPONENT_MODE_REMOTE_WAKE
  return 3U;
#elif APP_CONTROLLER_POWER_MODE == APP_COMPONENT_MODE_QUEUED
  return 4U;
#elif APP_CONTROLLER_POWER_MODE == APP_COMPONENT_MODE_LORA_WOR
  return 5U;
#elif APP_CONTROLLER_USES_STANDBY
  return 2U;
#else
  return 1U;
#endif
}

uint32_t powerManagerState()
{
#if APP_CONTROLLER_POWER_MODE == APP_COMPONENT_MODE_REMOTE_WAKE
  return g_remoteWakeCycle.active() ? 1U : 2U;
#else
  return 1U;
#endif
}

uint32_t powerManagerWakeRemainingSeconds()
{
#if APP_CONTROLLER_POWER_MODE == APP_COMPONENT_MODE_REMOTE_WAKE
  return g_remoteWakeCycle.remainingSeconds(millis());
#elif APP_CONTROLLER_POWER_MODE == APP_COMPONENT_MODE_QUEUED || \
      APP_CONTROLLER_POWER_MODE == APP_COMPONENT_MODE_LORA_WOR
  return queuedWakeActive()
      ? (g_queuedWakeDurationMs - (millis() - g_queuedWakeStartedMs) + 999U) / 1000U
      : 0U;
#else
  return 0U;
#endif
}

uint32_t powerManagerWakeRequestId()
{
#if APP_CONTROLLER_POWER_MODE == APP_COMPONENT_MODE_REMOTE_WAKE
  return g_lastWakeRequestId;
#elif APP_CONTROLLER_POWER_MODE == APP_COMPONENT_MODE_QUEUED || \
      APP_CONTROLLER_POWER_MODE == APP_COMPONENT_MODE_LORA_WOR
  return g_queuedWakeRequestId;
#else
  return 0U;
#endif
}
