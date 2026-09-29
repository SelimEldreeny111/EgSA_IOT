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

namespace
{
#if APP_CONTROLLER_POWER_MODE == APP_COMPONENT_MODE_REMOTE_WAKE
RemoteWakeCycle g_remoteWakeCycle;
uint32_t g_lastRemotePollMs = 0U;
uint32_t g_lastWakeRequestId = 0U;
uint64_t g_lastWakeRequestSeconds = 0U;
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

#if APP_CONTROLLER_POWER_MODE == APP_COMPONENT_MODE_POWER_DOWN
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
  if (requestEpoch < AppConfig::kPowerMinimumValidRtcEpoch)
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
#if APP_CONTROLLER_POWER_MODE == APP_COMPONENT_MODE_POWER_DOWN
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
#else
  printComponentMode(
      "STM32 controller",
      AppConfig::kControllerPowerDown,
      true);
#endif
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
  SerialMon.print("Power cycle: RTC_PERIODIC, sleep=");
  SerialMon.print(AppConfig::kPowerSleepSeconds);
  SerialMon.print(" s, command window=");
  SerialMon.print(AppConfig::kPowerCommandWindowMs);
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
  SerialMon.print("Power: reachable idle interval=");
  SerialMon.print(AppConfig::kPowerSleepSeconds);
  SerialMon.print(" s; default WAKE lease=");
  SerialMon.print(AppConfig::kRemoteWakeDefaultSeconds);
  SerialMon.println(" s; watchdog remains armed");
  g_remoteWakeCycle.begin(millis(), AppConfig::kPowerSleepSeconds * 1000UL,
                         AppConfig::kPowerCommandWindowMs);
  g_lastRemotePollMs = millis();
  scheduleFreshSensorCycle();
#else
  SerialMon.println("Power mode: NORMAL (continuous operation; Standby disabled)");
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
#elif APP_CONTROLLER_POWER_MODE == APP_COMPONENT_MODE_REMOTE_WAKE
  return g_remoteWakeCycle.active();
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
#elif APP_CONTROLLER_POWER_MODE == APP_COMPONENT_MODE_REMOTE_WAKE
  if (delivered) g_remoteWakeCycle.telemetryDelivered(millis());
  else SerialMon.println("Power: report failed; radio remains connected for retry");
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
  const auto transition = g_remoteWakeCycle.advance(millis(), transportIdle);
  if (transition == RemoteWakeCycle::Transition::EnteredIdle)
  {
    SerialMon.println("Power: REACHABLE_IDLE; sensor work paused, radio and watchdog remain active");
  }
  else if (transition == RemoteWakeCycle::Transition::PeriodicWake)
  {
    SerialMon.println("Power: periodic wake from reachable idle; sampling/reporting");
    scheduleFreshSensorCycle();
  }
#elif APP_CONTROLLER_POWER_MODE == APP_COMPONENT_MODE_POWER_DOWN
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
#elif APP_CONTROLLER_POWER_MODE == APP_COMPONENT_MODE_POWER_DOWN
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
#else
  return 0U;
#endif
}

uint32_t powerManagerWakeRequestId()
{
#if APP_CONTROLLER_POWER_MODE == APP_COMPONENT_MODE_REMOTE_WAKE
  return g_lastWakeRequestId;
#else
  return 0U;
#endif
}
