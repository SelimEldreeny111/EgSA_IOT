/** @file PowerManager.cpp @brief Per-component power policy and RTC-standby coordination. */
#define APP_LOG_MODULE "POWER"
#include "../platform/DebugLog.h"
#include "PowerManager.h"
#include "RemoteWakeCycle.h"
#include "../storage/TelemetryArchive.h"

#include "../app/AppState.h"
#include "../comm/MQTT.h"
#include "../config/AppConfig.h"
#include "../devices/RTC.h"
#include "../devices/BackupDomainAccess.h"
#include "../platform/Watchdog.h"
#include "../radio/LoraLink.h"

#include <Arduino.h>
#include <stm32f4xx_hal.h>
#if APP_CONTROLLER_POWER_MODE == APP_COMPONENT_MODE_LORA_WOR
#include "WorWakeInput.h"
#endif

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
#if APP_LORA_WOR_WAKE_SOURCE == APP_LORA_WOR_WAKE_SOURCE_UART_RX
constexpr uint32_t kWorWakePin = AppConfig::kLoraRxPin;
constexpr const char* kWorWakeSource = "UART_RX";
#else
constexpr uint32_t kWorWakePin = AppConfig::kLoraAuxPin;
constexpr const char* kWorWakeSource = "AUX";
#endif
volatile bool g_worWireInterrupt = false;
volatile bool g_worRtcInterrupt = false;
bool g_worCommandWindow = false;
uint32_t g_worWindowStartedMs = 0U;
#if APP_LORA_WOR_USE_APP_SCHEDULE
bool g_worSensorCycleActive = false;
#else
uint32_t g_worNextReportEpoch = 0U;
#endif

enum class WorPhase : uint32_t { Idle, RadioArming, ReceiveArmed, AlarmSetup, StopEntry, StopReturn, Heartbeat };
volatile WorPhase g_worPhase = WorPhase::Idle;
volatile WorPhase g_worWireEdgePhase = WorPhase::Idle;

void onWorWireInterrupt()
{
  g_worWireEdgePhase = g_worPhase;
  g_worWireInterrupt = true;
}
void onWorRtcInterrupt(void*) { g_worRtcInterrupt = true; }

#if APP_LORA_WOR_USE_APP_SCHEDULE
/** @brief Milliseconds until the first independent sample/report deadline.
 * Unsigned subtraction retains the sketch's millis-rollover semantics. A due
 * task returns zero and prevents Stop; neither task is forced by the other.
 */
uint32_t worNextWorkDelayMs()
{
  const AppRuntimeState& state = appState();
  const uint32_t now = millis();
  const uint32_t readAge = now - state.lastReadMs;
  const uint32_t sendAge = now - state.lastSendMs;
  const uint32_t readDelay = readAge >= state.samplingPeriodMs ? 0U : state.samplingPeriodMs - readAge;
  const uint32_t sendDelay = sendAge >= state.transmissionPeriodMs ? 0U : state.transmissionPeriodMs - sendAge;
  return readDelay < sendDelay ? readDelay : sendDelay;
}

/** @brief Read a coherent RTC seconds/subseconds snapshot for Stop elapsed time.
 * STM32RTC reports the fraction in elapsed milliseconds (0..999). Only elapsed
 * differences are used: server STIME changes while awake do not age schedules.
 */
uint64_t worRtcMilliseconds()
{
  uint32_t fraction = 0U;
  const uint64_t seconds = static_cast<uint64_t>(rtc.getEpoch(&fraction));
  return seconds * 1000ULL + fraction;
}

/** @brief Age application timestamps by time missing from suspended SysTick.
 * Do not change HAL/Arduino global time or manufacture a new sample/report.
 * Millis already accounts for foreground/restore work; subtract only the
 * missing Stop residence. The next ordinary sketch pass consumes due work.
 * @return False on a discontinuous/unrepresentable RTC interval; stay awake.
 */
bool accountWorStoppedTime(uint64_t rtcBefore, uint32_t tickBefore)
{
  const uint64_t rtcAfter = worRtcMilliseconds();
  if (rtcAfter < rtcBefore || rtcAfter - rtcBefore > UINT32_MAX) return false;
  const uint32_t rtcElapsed = static_cast<uint32_t>(rtcAfter - rtcBefore);
  const uint32_t tickElapsed = millis() - tickBefore;
  if (rtcElapsed > tickElapsed)
  {
    const uint32_t stoppedMs = rtcElapsed - tickElapsed;
    AppRuntimeState& state = appState();
    state.lastReadMs -= stoppedMs;
    state.lastSendMs -= stoppedMs;
  }
  return true;
}
#endif

/** @brief Name the foreground phase in which the wake callback was delivered. */
const char* worPhaseName(WorPhase phase)
{
  switch (phase)
  {
    case WorPhase::RadioArming: return "RADIO_ARMING";
    case WorPhase::ReceiveArmed: return "RECEIVE_ARMED";
    case WorPhase::AlarmSetup: return "ALARM_SETUP";
    case WorPhase::StopEntry: return "STOP_ENTRY";
    case WorPhase::StopReturn: return "STOP_RETURN";
    case WorPhase::Heartbeat: return "HEARTBEAT";
    default: return "NONE";
  }
}

/** @brief Reserve PC13 for AUX without disabling the internal RTC alarm.
 * @details RTC backup-domain configuration can survive MCU resets. RTC alarm
 * output, calibration output, timestamp and tamper-1 can override PC13 GPIO.
 * This board uses none of those external functions. Preserve the calendar,
 * backup registers, oscillator and alarm/interrupt enable bits.
 */
bool reserveWorAuxGpio()
{
#if defined(PC13) && defined(RTC_CR_OSEL) && defined(RTC_TAFCR_TAMP1E)
  if (AppConfig::kLoraAuxPin != PC13) return true;
  RTC_HandleTypeDef* handle = rtc.getHandle();
  if (handle == nullptr || handle->Instance == nullptr) return false;
  constexpr uint32_t externalCrMask = RTC_CR_OSEL | RTC_CR_COE | RTC_CR_TSE;
  const uint32_t oldCr = handle->Instance->CR;
  const uint32_t oldTafcr = handle->Instance->TAFCR;
  APP_DEBUG_PRINT("Power: WOR PC13 RTC pin functions before=0x");
  APP_DEBUG_PRINT(oldCr & externalCrMask, HEX);
  APP_DEBUG_PRINT(" tamper1=");
  APP_DEBUG_PRINTLN((oldTafcr & RTC_TAFCR_TAMP1E) != 0U ? 1U : 0U);
  {
    const BackupDomainAccess access;
    __HAL_RTC_WRITEPROTECTION_DISABLE(handle);
    handle->Instance->CR &= ~externalCrMask;
    handle->Instance->TAFCR &= ~RTC_TAFCR_TAMP1E;
    __HAL_RTC_WRITEPROTECTION_ENABLE(handle);
  }
  const bool released = (handle->Instance->CR & externalCrMask) == 0U &&
      (handle->Instance->TAFCR & RTC_TAFCR_TAMP1E) == 0U;
  if ((oldCr & externalCrMask) != 0U || (oldTafcr & RTC_TAFCR_TAMP1E) != 0U)
    APP_DEBUG_PRINTLN(released ? "Power: WOR released retained RTC pin functions; PC13 reserved for AUX"
                              : "Power: WOR PC13 RTC pin release failed");
  return released;
#else
  return true;
#endif
}

/** @brief Snapshot foreground WOR evidence; a wake edge is not a decoded command. */
void printWorSnapshot(const char* event, uint32_t stopCalls, uint32_t elapsedSeconds)
{
  APP_DEBUG_PRINT("Power: WOR ");
  APP_DEBUG_PRINT(event);
  APP_DEBUG_PRINT(" stop_calls=");
  APP_DEBUG_PRINT(stopCalls);
  APP_DEBUG_PRINT(" rtc_elapsed_s=");
  APP_DEBUG_PRINT(elapsedSeconds);
  APP_DEBUG_PRINT(" AUX=");
  APP_DEBUG_PRINT(digitalRead(AppConfig::kLoraAuxPin) == HIGH ? "HIGH" : "LOW");
  APP_DEBUG_PRINT(" wake_source=");
  APP_DEBUG_PRINT(kWorWakeSource);
  APP_DEBUG_PRINT(" wake_level=");
  APP_DEBUG_PRINT(digitalRead(kWorWakePin) == HIGH ? "HIGH" : "LOW");
  APP_DEBUG_PRINT(" wake_irq=");
  APP_DEBUG_PRINT(g_worWireInterrupt ? 1U : 0U);
  APP_DEBUG_PRINT(" wake_edge_phase=");
  APP_DEBUG_PRINT(worPhaseName(g_worWireEdgePhase));
  APP_DEBUG_PRINT(" wake_pending=");
  APP_DEBUG_PRINT(__HAL_GPIO_EXTI_GET_IT(digitalPinToBitMask(kWorWakePin)) != RESET ? 1U : 0U);
  APP_DEBUG_PRINT(" rtc_irq=");
  APP_DEBUG_PRINT(g_worRtcInterrupt ? 1U : 0U);
  APP_DEBUG_PRINT(" uart_rx=");
  APP_DEBUG_PRINT(SerialLoRa.available());
  APP_DEBUG_PRINT(" M0=");
  APP_DEBUG_PRINT(digitalRead(AppConfig::kLoraMd0Pin) == HIGH ? 1U : 0U);
  APP_DEBUG_PRINT(" M1=");
  APP_DEBUG_PRINTLN(digitalRead(AppConfig::kLoraMd1Pin) == HIGH ? 1U : 0U);
}

void runLoraWorStopCycle()
{
  const uint32_t nowEpoch = getEpochTime();
  if (!isRtcTrusted() || nowEpoch < AppConfig::kPowerMinimumValidRtcEpoch)
  {
    g_worCommandWindow = false;
    APP_DEBUG_PRINTLN("Power: Stop requires trusted RTC; send STIME before sleeping");
    return;
  }
#if APP_LORA_WOR_USE_APP_SCHEDULE
  if (worNextWorkDelayMs() == 0U) return;
#else
  if (g_worNextReportEpoch <= nowEpoch ||
      g_worNextReportEpoch - nowEpoch > AppConfig::kPowerSleepSeconds + 5UL)
  {
    g_worCommandWindow = false;
    scheduleFreshSensorCycle();
    return;
  }
#endif
  if (!reserveWorAuxGpio())
  {
    g_worCommandWindow = false;
    APP_DEBUG_PRINTLN("Power: WOR AUX GPIO ownership unavailable; staying awake");
    return;
  }
#if APP_LORA_WOR_WAKE_SOURCE == APP_LORA_WOR_WAKE_SOURCE_UART_RX
  if (!WorWakeInput::uartModeReady(kWorWakePin))
  {
    g_worCommandWindow = false;
    APP_DEBUG_PRINTLN("Power: WOR RX pin is not in UART alternate-function mode; staying awake");
    return;
  }
#endif
  g_worPhase = WorPhase::RadioArming;
  // Detached GPIO edges can leave a pending EXTI bit during normal traffic.
  // Clear ONLY this line's stale state while wake is idle, BEFORE Mode 2 is
  // selected. The final receive baseline is established after Mode 2 is ready.
  // Never clear the shared NVIC vector or edges after that boundary.
  const uint32_t savedPrimask = __get_PRIMASK();
  __disable_irq();
  g_worWireInterrupt = false;
  g_worWireEdgePhase = WorPhase::Idle;
  g_worRtcInterrupt = false;
  const uint32_t wakeMask = digitalPinToBitMask(kWorWakePin);
  const bool staleWakePending = __HAL_GPIO_EXTI_GET_IT(wakeMask) != RESET;
  const bool wakeWasHigh = digitalRead(kWorWakePin) == HIGH;
  if (wakeWasHigh)
    __HAL_GPIO_EXTI_CLEAR_IT(wakeMask);
  __set_PRIMASK(savedPrimask);
  if (staleWakePending)
    APP_DEBUG_PRINTLN(wakeWasHigh
        ? "Power: WOR cleared pre-arm stale wake pending flag while line HIGH"
        : "Power: WOR pre-arm wake LOW; pending flag preserved");

  if (!prepareLoraForWakeOnRadio(AppConfig::kPowerSleepEntryTimeoutMs))
  {
    APP_LOG_ERROR("Power: E32 Mode 2 preparation failed; staying awake");
    g_worCommandWindow = false;
    return;
  }

  // HAL_GPIO_Init/attachInterrupt does not clear EXTI pending history. Route
  // the GPIO with IRQ delivery masked, then establish the idle baseline only
  // AFTER Mode 2 has settled. Keep the UART open so received bytes during the
  // transition prevent sleep rather than being discarded by Serial.end().
  const uint32_t armPrimask = __get_PRIMASK();
  __disable_irq();
#if APP_LORA_WOR_WAKE_SOURCE == APP_LORA_WOR_WAKE_SOURCE_UART_RX
  const bool wakeArmed = WorWakeInput::attachUartRx(kWorWakePin, onWorWireInterrupt);
#else
  attachInterrupt(digitalPinToInterrupt(kWorWakePin), onWorWireInterrupt, FALLING);
  const bool wakeArmed = true;
#endif
  const bool armBusy = digitalRead(kWorWakePin) == LOW ||
      SerialLoRa.available() > 0;
  const bool armHistory = __HAL_GPIO_EXTI_GET_IT(wakeMask) != RESET;
  if (!armBusy) __HAL_GPIO_EXTI_CLEAR_IT(wakeMask);
  // A falling edge after this clear remains pending. Recheck level/UART below
  // as well, including an arrival while the baseline was being established.
  const bool activityAtArm = armBusy ||
      digitalRead(kWorWakePin) == LOW || SerialLoRa.available() > 0;
  g_worPhase = WorPhase::ReceiveArmed;
  __set_PRIMASK(armPrimask);
  if (armHistory && !armBusy)
    APP_DEBUG_PRINTLN("Power: WOR idle receive baseline; pre-arm wake history cleared");
  rtc.attachInterrupt(onWorRtcInterrupt, STM32RTC::ALARM_A);
  bool radioWake = false;
  bool storageWake = false;
  bool failed = !wakeArmed;
  uint32_t stopCalls = 0U;
  const uint32_t startedEpoch = getEpochTime();
  const char* exitReason = wakeArmed
#if APP_LORA_WOR_USE_APP_SCHEDULE
      ? "APPLICATION_DEADLINE"
#else
      ? "REPORT_DEADLINE"
#endif
      : "WAKE_PIN_ARM_FAILED";
  printWorSnapshot("armed", stopCalls, 0U);
  while (!failed &&
#if APP_LORA_WOR_USE_APP_SCHEDULE
      worNextWorkDelayMs() != 0U)
#else
      getEpochTime() < g_worNextReportEpoch)
#endif
  {
    serviceHardwareWatchdog(WatchdogStage::PowerTransition);
    const uint32_t now = getEpochTime();
    if (TelemetryArchive::maintenanceDue(now)) {
      storageWake = true;
      exitReason = "STORAGE_MAINTENANCE";
      break;
    }
    uint32_t alarmEpoch = now + AppConfig::kLoraWorWatchdogWakeSeconds;
#if APP_LORA_WOR_USE_APP_SCHEDULE
    const uint32_t remainingMs = worNextWorkDelayMs();
    if (remainingMs == 0U) break;
    // Alarm A is second-granular. Include the current fraction and round UP:
    // a 100-s deadline entered at xx.750 must not wake 750 ms too early.
    const uint32_t fraction = static_cast<uint32_t>(worRtcMilliseconds() % 1000ULL);
    const uint32_t workEpoch = now + (fraction + remainingMs + 999U) / 1000U;
    if (alarmEpoch > workEpoch) alarmEpoch = workEpoch;
#else
    if (alarmEpoch > g_worNextReportEpoch) alarmEpoch = g_worNextReportEpoch;
#endif
    const uint32_t storageDeadline = TelemetryArchive::expiry();
    if (storageDeadline > now && storageDeadline < alarmEpoch) alarmEpoch = storageDeadline;
    // Preserve all edges after the receive baseline, including heartbeat gaps.
    g_worRtcInterrupt = false;
    g_worPhase = WorPhase::AlarmSetup;
    if (!scheduleRtcWakeAlarm(alarmEpoch))
    {
      failed = true;
      exitReason = "RTC_ALARM_SETUP_FAILED";
      break;
    }
    if (g_worWireInterrupt || digitalRead(kWorWakePin) == LOW ||
        SerialLoRa.available() > 0 || activityAtArm)
    {
      radioWake = true;
      exitReason = g_worWireInterrupt ? "WAKE_EDGE_BEFORE_STOP" :
          (SerialLoRa.available() > 0 ? "UART_DATA_BEFORE_STOP" :
          (activityAtArm ? "WAKE_ACTIVITY_AT_ARM" : "WAKE_LOW_BEFORE_STOP"));
      break;
    }
    g_worPhase = WorPhase::StopEntry;
    APP_DEBUG_PRINT("Power: WOR Stop requested; alarm_epoch=");
    APP_DEBUG_PRINTLN(alarmEpoch);
    // Drain our own diagnostic TX before WFI so a pending debug-UART TX IRQ
    // does not immediately end the Stop attempt. Never print from an ISR.
    APP_DEBUG_FLUSH();
    if (!TelemetryArchive::prepareSleep()) {
      failed = true;
      exitReason = "STORAGE_BUSY";
      break;
    }
#if APP_LORA_WOR_USE_APP_SCHEDULE
    const uint64_t rtcBeforeStop = worRtcMilliseconds();
    const uint32_t tickBeforeStop = millis();
#endif
    HAL_SuspendTick();
    SCB->ICSR = SCB_ICSR_PENDSTCLR_Msk;
    // Close the check-to-WFI race: a pending wake/RTC IRQ must prevent a lost
    // wake. Restore clocks before pending handlers are allowed to run.
    __disable_irq();
    __DSB();
    __ISB();
    bool stopCalled = false;
    if (!g_worWireInterrupt && !g_worRtcInterrupt &&
        digitalRead(kWorWakePin) != LOW && SerialLoRa.available() == 0)
    {
      stopCalled = true;
      ++stopCalls;
      HAL_PWR_EnterSTOPMode(PWR_LOWPOWERREGULATOR_ON, PWR_STOPENTRY_WFI);
      g_worPhase = WorPhase::StopReturn;
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
    TelemetryArchive::resume();
#if APP_LORA_WOR_USE_APP_SCHEDULE
    if (stopCalled && !accountWorStoppedTime(rtcBeforeStop, tickBeforeStop))
    {
      failed = true;
      exitReason = "RTC_CLOCK_DISCONTINUITY";
      break;
    }
#endif
    if (g_worWireInterrupt || digitalRead(kWorWakePin) == LOW ||
        SerialLoRa.available() > 0)
    {
      radioWake = true;
      exitReason = !g_worWireInterrupt && SerialLoRa.available() > 0
          ? (stopCalled ? "UART_DATA_AFTER_STOP" : "UART_DATA_BEFORE_STOP")
          : stopCalled
          ? (g_worWireInterrupt ? "WAKE_EDGE_AFTER_STOP" : "WAKE_LOW_AFTER_STOP")
          : (g_worWireInterrupt ? "WAKE_EDGE_BEFORE_STOP" : "WAKE_LOW_BEFORE_STOP");
      break;
    }
    if (!g_worRtcInterrupt && getEpochTime() < alarmEpoch)
    {
      failed = true;
      exitReason = "UNEXPECTED_WAKE";
      break;
    }
    g_worPhase = WorPhase::Heartbeat;
    printWorSnapshot("RTC heartbeat", stopCalls, getEpochTime() - startedEpoch);
    cancelRtcWakeAlarm();
  }
  // These fields describe the event before radio restoration changes wake/M0/M1.
  APP_DEBUG_PRINT("Power: WOR exit reason=");
  APP_DEBUG_PRINTLN(exitReason);
  printWorSnapshot("exit", stopCalls, getEpochTime() - startedEpoch);
  cancelRtcWakeAlarm();
  rtc.detachInterrupt(STM32RTC::ALARM_A);
  detachInterrupt(digitalPinToInterrupt(kWorWakePin));
  g_worPhase = WorPhase::Idle;
  serviceHardwareWatchdog(WatchdogStage::PowerTransition);
  if (!resumeLoraFromWakeOnRadio(AppConfig::kLoraTxCompleteTimeoutMs))
  {
    // Fail open and reinitialize the radio; never silently claim a reachable
    // sleep state when Mode 0 could not be restored.
    APP_LOG_ERROR("Power: E32 Mode 0 restore failed; radio reinitialized");
    initializeLoraLink();
    failed = true;
  }
  if (failed)
  {
    g_worCommandWindow = false;
    APP_DEBUG_PRINTLN("Power: Stop cycle aborted; active scheduling resumed");
  }
  else if (storageWake)
  {
    g_worCommandWindow = true;
    g_worWindowStartedMs = millis() - AppConfig::kLoraWorCommandWindowMs;
    APP_DEBUG_PRINTLN("Power: RTC retention deadline; service flash before resuming Stop");
  }
  else if (radioWake)
  {
    g_worCommandWindow = true;
    g_worWindowStartedMs = millis();
    APP_DEBUG_PRINTLN("Power: WOR receive activity; window opened (command not yet confirmed)");
  }
  else
  {
    g_worCommandWindow = false;
#if APP_LORA_WOR_USE_APP_SCHEDULE
    // Age accounting made only the due application task(s) eligible. Preserve
    // their phase and let the main loop service commands before normal work.
    APP_DEBUG_PRINTLN("Power: SRATE/STRAN deadline woke STM32; run only due work");
#else
    scheduleFreshSensorCycle();
    APP_DEBUG_PRINTLN("Power: RTC report deadline woke STM32");
#endif
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
  APP_DEBUG_PRINT("  ");
  APP_DEBUG_PRINT(component);
  APP_DEBUG_PRINT(": ");
  APP_DEBUG_PRINT(componentModeName(powerDown));
  APP_DEBUG_PRINTLN(selected ? " [ACTIVE]" : " [NOT SELECTED]");
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
  if (TelemetryArchive::blocking()) return false;
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

  APP_DEBUG_PRINT("Power: sleep request committed; RTC deadline=");
  APP_DEBUG_PRINT(deadlineEpoch);
  APP_DEBUG_PRINT(" (requested at ");
  APP_DEBUG_PRINT(requestEpoch);
  APP_DEBUG_PRINTLN(")");
  APP_DEBUG_PRINTLN("Power: software reset will enter STM32 Standby before IWDG starts");
  APP_DEBUG_FLUSH();

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
    APP_LOG_WARN("Power: sleep rejected because RTC time is invalid");
    return PowerDownRequestOutcome::AbortActiveCycle;
  }

  const uint32_t imminentStorageDeadline = TelemetryArchive::expiry();
  if (imminentStorageDeadline && imminentStorageDeadline <= requestEpoch + 5U)
    return PowerDownRequestOutcome::RetrySleepPreparation;

#if APP_HAS_LORA
  if (!prepareLoraForPowerDown(AppConfig::kPowerSleepEntryTimeoutMs))
  {
    APP_DEBUG_PRINTLN(
        "Power: sleep delayed; LoRa has pending data, an incomplete frame, or busy AUX");
    return PowerDownRequestOutcome::RetrySleepPreparation;
  }
#elif APP_HAS_IP_UPLINK
  if (!prepareMqttTransportForPowerDown(
          AppConfig::kPowerSleepEntryTimeoutMs))
  {
    APP_DEBUG_PRINTLN("Power: IP transport could not enter deep sleep");
    restoreMqttTransportAfterPowerDownAbort();
    return PowerDownRequestOutcome::AbortActiveCycle;
  }
#endif

  // A command may have queued a clear while the transport was quiescing.
  // Never reset into Standby with an uncommitted record/metadata operation.
  if (!TelemetryArchive::prepareSleep())
  {
#if APP_HAS_LORA
    initializeLoraLink();
#elif APP_HAS_IP_UPLINK
    restoreMqttTransportAfterPowerDownAbort();
#endif
    return PowerDownRequestOutcome::RetrySleepPreparation;
  }

  uint32_t deadlineEpoch = requestEpoch + AppConfig::kPowerSleepSeconds;
  const uint32_t storageDeadline = TelemetryArchive::expiry();
  if (storageDeadline > requestEpoch + 5U && storageDeadline < deadlineEpoch)
    deadlineEpoch = storageDeadline;
  if (!storePersistentSleepState(
          requestEpoch,
          deadlineEpoch,
          deadlineEpoch - requestEpoch))
  {
    clearPersistentSleepState();
    TelemetryArchive::resume();
    APP_LOG_ERROR("Power: RTC backup-state verification failed; sleep cancelled");
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
      APP_DEBUG_PRINT("Power: woke from STM32 Standby; request=");
      APP_DEBUG_PRINT(g_previousRequestEpoch);
      APP_DEBUG_PRINT(" deadline=");
      APP_DEBUG_PRINT(g_previousDeadlineEpoch);
      APP_DEBUG_PRINT(" wake=");
      APP_DEBUG_PRINTLN(g_previousWakeEpoch);
      break;
    case EarlyBootEvent::UnexpectedStandbyWake:
      APP_DEBUG_PRINTLN("Power: Standby wake detected without a valid scheduled request");
      break;
    case EarlyBootEvent::CorruptSleepStateRejected:
      APP_LOG_WARN("Power: corrupt RTC backup sleep state rejected and cleared");
      break;
    case EarlyBootEvent::ExpiredSleepStateRejected:
      APP_LOG_WARN("Power: expired RTC backup sleep request rejected and cleared");
      break;
    case EarlyBootEvent::RtcSleepStateRejected:
      APP_LOG_WARN("Power: pending sleep rejected because RTC/state timing was invalid");
      break;
    case EarlyBootEvent::StandbyEntryFailed:
      APP_DEBUG_PRINTLN("Power: HAL returned from Standby entry; request cleared, normal boot continued");
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
  APP_DEBUG_PRINTLN("Power configuration:");
#if APP_CONTROLLER_POWER_MODE == APP_COMPONENT_MODE_REMOTE_WAKE
  APP_DEBUG_PRINTLN("  STM32 controller: REMOTE_WAKE [ACTIVE]");
#elif APP_CONTROLLER_POWER_MODE == APP_COMPONENT_MODE_LORA_WOR
  APP_DEBUG_PRINTLN("  STM32 controller: LORA_WOR_STOP [ACTIVE]");
#else
  printComponentMode(
      "STM32 controller",
      AppConfig::kControllerPowerDown,
      true);
#endif
#if APP_CONTROLLER_POWER_MODE == APP_COMPONENT_MODE_LORA_WOR
  APP_DEBUG_PRINTLN("  LoRa module: E32 MODE_2_WAKE_ON_RADIO [ACTIVE]");
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
  APP_DEBUG_PRINT(AppConfig::kQueuedCommands
      ? "Power cycle: RTC_QUEUED, sleep="
      : "Power cycle: RTC_PERIODIC, sleep=");
  APP_DEBUG_PRINT(AppConfig::kPowerSleepSeconds);
  APP_DEBUG_PRINT(" s, command window=");
  APP_DEBUG_PRINT(AppConfig::kQueuedCommands
      ? AppConfig::kQueuedCommandWindowMs
      : AppConfig::kPowerCommandWindowMs);
  APP_DEBUG_PRINTLN(" ms");
#if APP_HAS_LORA
  APP_DEBUG_PRINTLN(
      "Power hardware check: E32 M0/M1 need external pull-ups; RS485 DE needs a pull-down");
#elif APP_HAS_IP_UPLINK && defined(USE_ESP8266)
  APP_DEBUG_PRINTLN(
      "Power hardware: ESP8266 wakes through PB8/ESP_RST; server commands wait for the active window");
#endif

  // Make one fresh sample and one telemetry send due on the first loop after
  // every cold boot or RTC wake. Unsigned arithmetic keeps millis() rollover safe.
  scheduleFreshSensorCycle();
  g_commandWindowActive = false;
#elif APP_CONTROLLER_POWER_MODE == APP_COMPONENT_MODE_REMOTE_WAKE
  APP_DEBUG_PRINTLN("Power mode: REMOTE_WAKE (CPU Sleep; selected radio remains NORMAL)");
  if (AppConfig::kRemoteWakeUsesAppSchedule)
    APP_DEBUG_PRINT("Power: SRATE/STRAN scheduled idle; no fixed sleep interval; default WAKE lease=");
  else
  {
    APP_DEBUG_PRINT("Power: legacy reachable idle interval=");
    APP_DEBUG_PRINT(AppConfig::kPowerSleepSeconds);
    APP_DEBUG_PRINT(" s; default WAKE lease=");
  }
  APP_DEBUG_PRINT(AppConfig::kRemoteWakeDefaultSeconds);
  APP_DEBUG_PRINTLN(" s; watchdog remains armed");
  g_remoteWakeCycle.begin(millis(), AppConfig::kPowerSleepSeconds * 1000UL,
                         AppConfig::kPowerCommandWindowMs, AppConfig::kRemoteWakeUsesAppSchedule);
  g_remoteSensorCycleActive = false;
  g_lastRemotePollMs = millis();
  scheduleFreshSensorCycle();
#elif APP_CONTROLLER_POWER_MODE == APP_COMPONENT_MODE_LORA_WOR
#if APP_LORA_WOR_USE_APP_SCHEDULE
  APP_DEBUG_PRINT("Power: WOR follows independent SRATE/STRAN; APP_POWER_SLEEP_SECONDS ignored; IWDG RTC heartbeat=");
#else
  APP_DEBUG_PRINT("Power: RTC report interval=");
  APP_DEBUG_PRINT(AppConfig::kPowerSleepSeconds);
  APP_DEBUG_PRINT(" s, IWDG RTC heartbeat=");
#endif
  APP_DEBUG_PRINT(AppConfig::kLoraWorWatchdogWakeSeconds);
  APP_DEBUG_PRINTLN(" s; gateway must enable Mode-1 wake probe");
  APP_DEBUG_PRINT("Power: WOR wake source=");
  APP_DEBUG_PRINT(kWorWakeSource);
  APP_DEBUG_PRINTLN("; AUX retained for radio readiness");
  initializeRtc();
  scheduleFreshSensorCycle();
  g_worCommandWindow = false;
#if APP_LORA_WOR_USE_APP_SCHEDULE
  g_worSensorCycleActive = false;
#endif
#else
  APP_DEBUG_PRINTLN("Power mode: NORMAL (continuous operation; Standby disabled)");
  if (g_stalePeriodicRequestCleared)
  {
    APP_DEBUG_PRINTLN("Power: stale periodic sleep request cleared during normal-mode boot");
  }
#endif
}

void notifyPowerManagerSensorCycle(bool active)
{
#if APP_CONTROLLER_POWER_MODE == APP_COMPONENT_MODE_REMOTE_WAKE
  g_remoteSensorCycleActive = active;
#elif APP_CONTROLLER_POWER_MODE == APP_COMPONENT_MODE_LORA_WOR && APP_LORA_WOR_USE_APP_SCHEDULE
  g_worSensorCycleActive = active;
#else
  (void)active;
#endif
}

bool powerManagerAllowsSensorWork()
{
#if APP_CONTROLLER_USES_STANDBY || APP_CONTROLLER_POWER_MODE == APP_COMPONENT_MODE_LORA_WOR
  // A long history download defers sleep, not the sampling/report deadlines.
  if (TelemetryArchive::transferring()) return true;
#endif
#if APP_CONTROLLER_USES_STANDBY
#if APP_CONTROLLER_POWER_MODE == APP_COMPONENT_MODE_QUEUED
  if (queuedWakeActive()) return true;
#endif
  return !g_commandWindowActive;
#elif APP_CONTROLLER_POWER_MODE == APP_COMPONENT_MODE_REMOTE_WAKE
  return g_remoteWakeCycle.active();
#elif APP_CONTROLLER_POWER_MODE == APP_COMPONENT_MODE_LORA_WOR
#if APP_LORA_WOR_USE_APP_SCHEDULE
  // The receive window delays Stop, never independent application deadlines.
  return true;
#else
  return queuedWakeActive() || !g_worCommandWindow;
#endif
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
      APP_DEBUG_PRINTLN("Power: telemetry not delivered; node remains awake and will retry");
    }
    return;
  }

  g_commandWindowActive = true;
  g_commandWindowStartedMs = millis();
  g_lastSleepDelayLogMs = 0U;
  APP_DEBUG_PRINT("Power: telemetry delivered; listening for ");
#if APP_HAS_LORA
  APP_DEBUG_PRINT("LoRa");
#else
  APP_DEBUG_PRINT("server");
#endif
  APP_DEBUG_PRINT(" commands for ");
  APP_DEBUG_PRINT(AppConfig::kQueuedCommands
      ? AppConfig::kQueuedCommandWindowMs
      : AppConfig::kPowerCommandWindowMs);
  APP_DEBUG_PRINTLN(" ms");
#elif APP_CONTROLLER_POWER_MODE == APP_COMPONENT_MODE_REMOTE_WAKE
  if (delivered) g_remoteWakeCycle.telemetryDelivered(millis());
  else APP_LOG_ERROR("Power: report failed; radio remains connected for retry");
#elif APP_CONTROLLER_POWER_MODE == APP_COMPONENT_MODE_LORA_WOR
  if (delivered)
  {
    g_worCommandWindow = true;
    g_worWindowStartedMs = millis();
#if !APP_LORA_WOR_USE_APP_SCHEDULE
    const uint32_t now = getEpochTime();
    g_worNextReportEpoch = now + AppConfig::kPowerSleepSeconds;
#endif
    APP_DEBUG_PRINTLN("Power: report delivered; LoRa command window opened");
  }
  else
  {
#if APP_LORA_WOR_USE_APP_SCHEDULE
    g_worCommandWindow = false;
    APP_LOG_ERROR("Power: report failed; retry at next STRAN deadline");
#else
    APP_LOG_ERROR("Power: report failed; staying awake for retry");
#endif
  }
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
  transportIdle = transportIdle && !TelemetryArchive::blocking();
  const uint32_t nowMs = millis();
  const AppRuntimeState& state = appState();
  const bool applicationDue = nowMs - state.lastReadMs >= state.samplingPeriodMs ||
      nowMs - state.lastSendMs >= state.transmissionPeriodMs;
  const auto transition = g_remoteWakeCycle.advance(nowMs, transportIdle,
      applicationDue, g_remoteSensorCycleActive);
  if (transition == RemoteWakeCycle::Transition::EnteredIdle)
  {
    APP_DEBUG_PRINTLN(AppConfig::kRemoteWakeUsesAppSchedule ?
        "Power: REACHABLE_IDLE; waiting for SRATE/STRAN or commands; radio/WDT serviced" :
        "Power: REACHABLE_IDLE; sensor work paused, radio and watchdog remain active");
  }
  else if (transition == RemoteWakeCycle::Transition::PeriodicWake)
  {
    APP_DEBUG_PRINTLN("Power: periodic wake from reachable idle; sampling/reporting");
    scheduleFreshSensorCycle();
  }
  else if (transition == RemoteWakeCycle::Transition::ScheduledWake)
  {
    // Do not reset timestamps: only the independent work that is due may run.
    APP_DEBUG_PRINTLN("Power: scheduled work/reply pending; resume without forcing other deadlines");
  }
#elif APP_CONTROLLER_POWER_MODE == APP_COMPONENT_MODE_LORA_WOR
  if (TelemetryArchive::blocking()) return;
#if APP_LORA_WOR_USE_APP_SCHEDULE
  // Uncommissioned RTC stays awake. Repeated loop passes must not spam Stop
  // preparation/logging before a server STIME establishes trusted time.
#if APP_ENABLE_DEBUG
  static bool reportedUntrustedRtc = false;
  if (!isRtcTrusted()) {
    if (!reportedUntrustedRtc) APP_LOG_WARN("sleep_deferred reason=RTC_UNTRUSTED action=send_STIME");
    reportedUntrustedRtc = true;
  } else if (reportedUntrustedRtc) {
    APP_LOG_INFO("sleep_permitted rtc=trusted scheduler=SRATE_STRAN");
    reportedUntrustedRtc = false;
  }
#endif
  if (!isRtcTrusted() || g_worSensorCycleActive || queuedWakeActive() ||
      worNextWorkDelayMs() == 0U || !isLoraIdleForPowerDown()) return;
  if (g_worCommandWindow &&
      millis() - g_worWindowStartedMs < AppConfig::kLoraWorCommandWindowMs) return;
#else
  if (!g_worCommandWindow || queuedWakeActive() ||
      millis() - g_worWindowStartedMs < AppConfig::kLoraWorCommandWindowMs ||
      !isLoraIdleForPowerDown()) return;
#endif
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
      APP_DEBUG_PRINTLN("Power: waiting for LoRa receive/command activity to finish");
#else
      APP_DEBUG_PRINTLN("Power: waiting for MQTT publish/command activity to finish");
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
    APP_DEBUG_PRINTLN("Power: periodic sleep cycle aborted; active scheduling resumed");
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
      APP_LOG_WARN("WAKE rejected: changed or expired duplicate request");
      return false;
    }
    APP_DEBUG_PRINTLN("Power: duplicate WAKE acknowledged; original deadline unchanged");
    return true;
  }
  if (!g_remoteWakeCycle.requestWake(millis(), seconds, AppConfig::kRemoteWakeDefaultSeconds))
  {
    APP_LOG_WARN("WAKE rejected: duration must be 0 (default) or 1..86400 seconds");
    return false;
  }
  g_lastWakeRequestId = requestId;
  g_lastWakeRequestSeconds = seconds;
  scheduleFreshSensorCycle();
  APP_DEBUG_PRINT("Power: WAKE accepted; ACTIVE for ");
  APP_DEBUG_PRINT(g_remoteWakeCycle.remainingSeconds(millis()));
  APP_DEBUG_PRINTLN(" seconds (no controller reset)");
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
  APP_DEBUG_PRINT("Power: WAKE accepted for ");
  APP_DEBUG_PRINT(static_cast<uint32_t>(acceptedSeconds));
  APP_DEBUG_PRINTLN(" seconds; low-power entry postponed");
  return true;
#else
  (void)seconds;
  (void)requestId;
  APP_LOG_WARN("WAKE rejected: select controller REMOTE_WAKE; NORMAL/RTC_PERIODIC are unchanged");
  return false;
#endif
}

bool powerManagerShouldRunApplication()
{
#if APP_CONTROLLER_POWER_MODE == APP_COMPONENT_MODE_REMOTE_WAKE
  if (g_remoteWakeCycle.active() || TelemetryArchive::blocking()) return true;
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
  if (!g_remoteWakeCycle.active() && !TelemetryArchive::blocking())
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
