/** @file wor_stop_test.cpp @brief Production WOR state machine with deterministic IRQ/RTC hardware fakes. */
#include "fakes/TestAppConfig.h"
#include "../../src/power/PowerManager.h"
#include <cassert>
#include <iostream>
#include <string>

HardwareSerial SerialMon, SerialAT, SerialLoRa;
GPIO_TypeDef fakeRxPort;
PWR_TypeDef pwrRegs; RTC_TypeDef rtcRegs; SCB_TypeDef scbRegs;
PWR_TypeDef* PWR=&pwrRegs; RTC_TypeDef* RTC=&rtcRegs; SCB_TypeDef* SCB=&scbRegs;
STM32RTC rtcInstance;
STM32RTC& rtc=rtcInstance;
AppRuntimeState state;
std::string scenario;
uint32_t fakeExtiPending=0U, nowMs=0U, epoch=1800000000U, alarmEpoch=0U, primask=0U;
uint32_t rtcSubMs=0U;
unsigned stopCalls=0U, clockRestores=0U, restores=0U, reinitializations=0U;
bool auxHigh=true, trusted=true, alarmHealthy=true, prepareHealthy=true;
bool restoreHealthy=true, idle=true, tickSuspended=false, injected=false;
bool fakeRtcWritable=false;
bool flashAsleep=false;
namespace TelemetryArchive {
bool blocking(){return scenario=="storage_busy"||scenario=="storage_transfer"||scenario=="app_storage_busy";}
bool transferring(){return scenario=="storage_transfer";}
uint32_t expiry(){return scenario=="storage_deadline"||scenario=="app_storage_deadline"?1800000020U:0U;}
bool maintenanceDue(uint32_t now){return expiry()&&now>=expiry();}
bool prepareSleep(){if(scenario=="storage_sleep_failure")return false;flashAsleep=true;return true;}
void resume(){flashAsleep=false;}
}
int m0=LOW, m1=LOW;
void (*auxCallback)()=nullptr;
bool armCompleted=false, rxHigh=true;
constexpr bool rxWake = APP_LORA_WOR_WAKE_SOURCE == APP_LORA_WOR_WAKE_SOURCE_UART_RX;
constexpr uint32_t wakePin = rxWake ? 12U : 13U;
constexpr uint32_t wakeBit = 1U << wakePin;
constexpr uint32_t neighbourBit = rxWake ? (1U << 13) : (1U << 12);
void setWakeLow() { if (rxWake) rxHigh=false; else auxHigh=false; }

RTC_HandleTypeDef* STM32RTC::getHandle() {
  static RTC_HandleTypeDef handle;
  handle.Instance=RTC;
  return scenario=="rtc_handle_failure" ? nullptr : &handle;
}
uint32_t STM32RTC::getEpoch(uint32_t* fraction) {
  if (fraction) *fraction=rtcSubMs;
  return epoch;
}

void injectEdge() {
  fakeExtiPending |= wakeBit;
  if (!primask && auxCallback) {
    fakeExtiPending &= ~(wakeBit);
    auxCallback();
  }
}
uint32_t millis() { return nowMs; }
uint32_t getEpochTime() { return epoch; }
bool isRtcTrusted() { return trusted; }
void initializeRtc() {}
AppRuntimeState& appState() { return state; }
int digitalRead(uint32_t pin) { return pin==12U ? (rxHigh ? HIGH : LOW) : (pin==13U ? (auxHigh ? HIGH : LOW) : (pin==2U ? m0 : m1)); }
void attachInterrupt(uint32_t pin, void (*fn)(), int) {
  assert(pin==wakePin); auxCallback=fn;
  if (pin==12U) {
    fakeRxPort.MODER &= ~(3UL << 24); // Real attachInterrupt temporarily selects GPIO input.
    fakeRxPort.OSPEEDR |= 3UL << 24;
  }
  assert(primask==1U); // GPIO routing and the receive baseline are atomic.
  if (scenario=="edge_during_attach") injectEdge();
  if (!primask && (fakeExtiPending & (wakeBit))) {
    fakeExtiPending &= ~(wakeBit); auxCallback();
  }
}
void detachInterrupt(uint32_t) { auxCallback=nullptr; }
uint32_t __get_PRIMASK() { return primask; }
void __disable_irq() { primask=1U; }
void __set_PRIMASK(uint32_t value) {
  primask=value;
  if (!primask && auxCallback && rxWake) {
    assert(((fakeRxPort.MODER >> 24) & 3U)==2U);
    assert(((fakeRxPort.OSPEEDR >> 24) & 3U)==1U);
  }
  if (auxCallback && !armCompleted) {
    armCompleted=true;
    if (scenario=="edge_after_arm") injectEdge();
  }
  if (!primask && auxCallback && (fakeExtiPending & (wakeBit))) {
    fakeExtiPending &= ~(wakeBit); auxCallback();
  }
}
void __enable_irq() { __set_PRIMASK(0U); }
void fakeClearExti(uint32_t mask) {
  fakeExtiPending &= ~mask;
  if (auxCallback && scenario=="edge_after_baseline_clear" && !injected) {
    injectEdge(); injected=true; // New edge must survive the baseline clear.
  }
  if (auxCallback && scenario=="low_after_baseline_clear" && !injected) {
    setWakeLow(); injected=true;
  }
}
void HAL_SuspendTick() {
  tickSuspended=true;
  if (scenario=="edge_before_wfi") injectEdge();
}
void HAL_ResumeTick() {
  tickSuspended=false;
  if (scenario=="app_active_ticks") {
    nowMs+=10U;rtcSubMs+=10U;
    if(rtcSubMs>=1000U){++epoch;rtcSubMs-=1000U;}
  }
}
void HAL_PWR_EnableBkUpAccess() { PWR->CR |= PWR_CR_DBP; }
void HAL_PWR_DisableBkUpAccess() { PWR->CR &= ~PWR_CR_DBP; }
uint32_t HAL_RTCEx_BKUPRead(RTC_HandleTypeDef*, uint32_t) { return 0U; }
void HAL_RTCEx_BKUPWrite(RTC_HandleTypeDef*, uint32_t, uint32_t) {}
void serviceHardwareWatchdog(WatchdogStage) {}
bool isLoraIdleForPowerDown() { return idle; }
bool prepareLoraForWakeOnRadio(uint32_t) {
  if (!prepareHealthy) return false;
  m0=LOW; m1=HIGH;
  if (scenario=="edge_during_prepare" || scenario=="rx_during_prepare" || scenario=="low_during_prepare") injectEdge();
  if (scenario=="rx_during_prepare") SerialLoRa.rxBytes=12;
  if (scenario=="low_during_prepare") setWakeLow();
  return true;
}
bool resumeLoraFromWakeOnRadio(uint32_t) {
  ++restores; m0=m1=LOW; return restoreHealthy;
}
void initializeLoraLink() { ++reinitializations; }
bool scheduleRtcWakeAlarm(uint32_t deadline) {
  assert(!fakeRtcWritable && (RTC->CR & (RTC_CR_OSEL | RTC_CR_COE | RTC_CR_TSE))==0U);
  alarmEpoch=deadline;
  if (scenario=="aux_low_before_stop") setWakeLow();
  if (scenario=="edge_during_alarm") injectEdge();
  if (scenario=="uart_during_alarm") SerialLoRa.rxBytes=12;
  if (scenario=="aux_noise") fakeExtiPending |= 1U << 13; // AUX must not own the RX callback.
  return alarmHealthy;
}
void cancelRtcWakeAlarm() {
  if (scenario=="edge_after_heartbeat" && !injected) {
    injectEdge(); injected=true;
  }
}
extern "C" void SystemClock_Config() { ++clockRestores; }
void SystemCoreClockUpdate() {}
void HAL_PWR_EnterSTOPMode(uint32_t, uint32_t) {
  assert(tickSuspended && primask==1U);
  assert(SerialMon.flushes>stopCalls); // Drain debug TX before each Stop attempt.
  ++stopCalls;
  if (scenario=="aux_after_stop" || scenario=="app_command_wake") {
    epoch+=2U;
    assert(auxCallback); injectEdge(); // Short pulse: physical AUX is HIGH again.
  } else if (scenario=="uart_after_stop") {
    epoch+=2U; SerialLoRa.rxBytes=12;
  } else if (scenario=="app_rtc_backward") {
    --epoch;
    assert(rtc.callback); rtc.callback(nullptr);
  } else if (scenario!="unexpected_wake") {
    epoch=alarmEpoch;
    rtcSubMs=0U;
    assert(rtc.callback); rtc.callback(nullptr);
  }
}
void requireLog(const std::string& part) {
  if (SerialMon.output.str().find(part)==std::string::npos) {
    std::cerr << "Missing: " << part << '\n' << SerialMon.output.str(); assert(false);
  }
}

#if APP_LORA_WOR_USE_APP_SCHEDULE
/** @brief Advance foreground time without suspending SysTick. */
void activeTime(uint32_t ms) {
  nowMs+=ms;
  const uint64_t rtcMs=uint64_t(rtcSubMs)+ms;
  epoch+=uint32_t(rtcMs/1000U);rtcSubMs=uint32_t(rtcMs%1000U);
}
bool sampleDue(){return nowMs-state.lastReadMs>=state.samplingPeriodMs;}
bool reportDue(){return nowMs-state.lastSendMs>=state.transmissionPeriodMs;}

/** @brief Exercise production Stop against independent application deadlines. */
void applicationScheduleTest() {
  constexpr uint32_t startEpoch=1800000000U;
  initializePowerManagerAfterSetup();
  requireLog("WOR follows independent SRATE/STRAN");
  // Model the ordinary sketch consuming its initial boot sample/report.
  state.samplingPeriodMs=100000U;state.transmissionPeriodMs=300000U;
  state.lastReadMs=state.lastSendMs=nowMs;
  notifyPowerManagerTelemetryResult(true);
  assert(powerManagerAllowsSensorWork()); // Receive windows never block due work.
  activeTime(10000U); // Well beyond command window; no work is yet due.

  if(scenario=="app_transmission_only" || scenario=="app_failed_report") {
    state.samplingPeriodMs=300000U;state.transmissionPeriodMs=100000U;
  } else if(scenario=="app_rate_increase") {
    state.samplingPeriodMs=300000U;state.transmissionPeriodMs=400000U;
  } else if(scenario=="app_rate_decrease") {
    activeTime(30000U);
    state.samplingPeriodMs=30000U; // Changing SRATE does not reset elapsed age.
    const auto before=state.lastReadMs;
    servicePowerManager();assert(stopCalls==0U&&sampleDue()&&!reportDue());
    assert(state.lastReadMs==before);return;
  } else if(scenario=="app_partial_cycle") {
    notifyPowerManagerSensorCycle(true);servicePowerManager();assert(stopCalls==0U);
    notifyPowerManagerSensorCycle(false); // No successful report required to sleep.
  } else if(scenario=="app_window_deadline") {
    state.samplingPeriodMs=11000U;
    notifyPowerManagerTelemetryResult(true); // New window opens at t=10 s.
    activeTime(1000U);
    assert(powerManagerAllowsSensorWork());
    servicePowerManager();assert(stopCalls==0U&&sampleDue()&&!reportDue());return;
  } else if(scenario=="app_millis_wrap") {
    nowMs=UINT32_MAX-5000U;
    state.lastReadMs=state.lastSendMs=nowMs-10000U;
    notifyPowerManagerTelemetryResult(true);
    activeTime(6000U); // Core tick rolls over while awake, then Stop must age it.
  } else if(scenario=="app_rtc_sync") {
    epoch+=3600U; // An awake STIME update must not consume an hour of SRATE.
  } else if(scenario=="app_rtc_sync_back") {
    epoch-=3600U;
  } else if(scenario=="app_fractional_stop") {
    rtcSubMs=750U;
  } else if(scenario=="app_untrusted") {
    trusted=false;
    servicePowerManager();assert(stopCalls==0U);return;
  }
  const uint32_t readAge=nowMs-state.lastReadMs,sendAge=nowMs-state.lastSendMs;
  const uint32_t readBefore=state.lastReadMs,sendBefore=state.lastSendMs;
  servicePowerManager();
  if(scenario=="app_storage_busy") {
    assert(stopCalls==0U&&state.lastReadMs==readBefore&&state.lastSendMs==sendBefore);return;
  }
  if(scenario=="app_command_wake") {
    assert(stopCalls==1U&&!sampleDue()&&!reportDue());
    assert(nowMs-state.lastReadMs==readAge+2000U&&nowMs-state.lastSendMs==sendAge+2000U);
    requireLog("reason=WAKE_EDGE_AFTER_STOP");return;
  }
  if(scenario=="app_rtc_backward") {
    assert(stopCalls==1U&&state.lastReadMs==readBefore&&state.lastSendMs==sendBefore);
    requireLog("reason=RTC_CLOCK_DISCONTINUITY");return;
  }
  if(scenario=="app_storage_deadline") {
    assert(epoch==startEpoch+20U&&!sampleDue()&&!reportDue());
    assert(nowMs-state.lastReadMs==20000U);
    requireLog("reason=STORAGE_MAINTENANCE");return;
  }
  requireLog("reason=APPLICATION_DEADLINE");
  requireLog("run only due work");
  if(scenario=="app_transmission_only" || scenario=="app_failed_report") {
    assert(!sampleDue()&&reportDue());
    assert(epoch==startEpoch+100U);
    // Reporting at t=100 must not sample early or move the t=300 sample.
    state.lastSendMs=nowMs;notifyPowerManagerTelemetryResult(scenario!="app_failed_report");
    if(scenario!="app_failed_report")activeTime(5000U);
    servicePowerManager();
    assert(epoch==startEpoch+200U&&!sampleDue()&&reportDue());return;
  }
  assert(sampleDue()&&!reportDue());
  if(scenario=="app_rate_increase")assert(epoch==startEpoch+300U);
  else if(scenario=="app_rtc_sync")assert(epoch==startEpoch+3700U);
  else if(scenario=="app_rtc_sync_back")assert(epoch==startEpoch-3500U);
  else if(scenario=="app_fractional_stop") {
    assert(nowMs-state.lastReadMs>=100000U&&nowMs-state.lastReadMs<101000U);
  } else if(scenario=="app_active_ticks") {
    assert(nowMs-state.lastReadMs>=100000U&&nowMs-state.lastReadMs<101000U);
  } else if(scenario=="app_millis_wrap") {
    assert(nowMs-state.lastReadMs==100000U);
  } else assert(epoch==startEpoch+100U); // Ignores fixed kPowerSleepSeconds=60.
  if(scenario=="app_independent") {
    // Sample-only wakes at t=100 and t=200, both tasks due together at t=300.
    state.lastReadMs=nowMs;servicePowerManager();
    assert(epoch==startEpoch+200U&&sampleDue()&&!reportDue());
    state.lastReadMs=nowMs;servicePowerManager();
    assert(epoch==startEpoch+300U&&sampleDue()&&reportDue());
  }
}
#endif
int main(int argc, char** argv) {
  assert(argc==2); scenario=argv[1];
  fakeRxPort.MODER = (2UL << 24) | (3UL << 20);
  fakeRxPort.OSPEEDR = 1UL << 24;
  fakeRxPort.PUPDR = 1UL << 24;
  fakeRxPort.AFR[1] = 0xA00800BBU;
  if (scenario=="rx_mode_invalid") fakeRxPort.MODER &= ~(3UL << 24);
  const uint32_t originalMode=fakeRxPort.MODER;
#if APP_LORA_WOR_USE_APP_SCHEDULE
  assert(scenario.compare(0,4,"app_")==0);
  applicationScheduleTest();
  assert(fakeRxPort.MODER==originalMode&&primask==0U&&!tickSuspended&&!flashAsleep);
  std::cout << "PASS " << (rxWake?"RX ":"AUX ") << scenario << '\n';
  return 0;
#endif
  initializePowerManagerAfterSetup();
  const uint32_t originalReadMs=state.lastReadMs;
  if (scenario=="untrusted") trusted=false;
  if (scenario=="alarm_failure") alarmHealthy=false;
  if (scenario=="prepare_failure") prepareHealthy=false;
  if (scenario=="restore_failure") restoreHealthy=false;
  if (scenario=="busy") idle=false;
  if (scenario=="stale_pending") fakeExtiPending=wakeBit | neighbourBit;
  constexpr uint32_t preservedCr=(1U << 6) | (1U << 8) | (1U << 12); // FMT, ALRAE, ALRAIE.
  constexpr uint32_t preservedTafcr=(1U << 3) | (1U << 18); // Other tamper/output-type fields.
  RTC->CR=preservedCr; RTC->TAFCR=preservedTafcr;
  if (scenario=="retained_rtc_pin") {
    RTC->CR |= RTC_CR_OSEL | RTC_CR_COE | RTC_CR_TSE;
    RTC->TAFCR |= RTC_TAFCR_TAMP1E;
  }
  if (scenario=="pending_aux_low") {
    setWakeLow(); fakeExtiPending=wakeBit; prepareHealthy=false;
  }
  notifyPowerManagerTelemetryResult(scenario!="report_failure");
  nowMs=4999U; servicePowerManager(); assert(stopCalls==0U);
  if (scenario=="wake_lease") assert(requestRemoteWake(30U, 123U));
  nowMs=5000U; servicePowerManager();
  if(scenario=="storage_transfer")assert(powerManagerAllowsSensorWork());
  if (scenario=="rtc_deadline" || scenario=="stale_pending" || scenario=="restore_failure" || scenario=="retained_rtc_pin" || scenario=="edge_during_prepare" || scenario=="edge_during_attach" || scenario=="aux_noise" || scenario=="mode_preserved") {
    assert(stopCalls==4U && clockRestores==4U && restores==1U);
    requireLog("Power: WOR RTC heartbeat");
    requireLog("reason=REPORT_DEADLINE");
    requireLog("rtc_elapsed_s=60");
    if (scenario=="stale_pending") {
      assert(fakeExtiPending==neighbourBit); // Shared-vector neighbour is untouched.
      requireLog("cleared pre-arm stale wake pending flag");
    }
    if (scenario=="restore_failure") assert(reinitializations==1U);
    else requireLog("Power: RTC report deadline woke STM32");
    if (scenario=="retained_rtc_pin") requireLog("released retained RTC pin functions");
    if (scenario=="edge_during_prepare" || scenario=="edge_during_attach")
      requireLog("idle receive baseline; pre-arm wake history cleared");
  } else if (scenario=="storage_deadline") {
    assert(stopCalls==2U && restores==1U && epoch==1800000020U);
    requireLog("reason=STORAGE_MAINTENANCE");
    assert(state.lastReadMs==originalReadMs); // Storage service does not force a sensor read.
  } else if (scenario=="storage_sleep_failure") {
    assert(stopCalls==0U && restores==1U);requireLog("reason=STORAGE_BUSY");
  } else if (scenario=="aux_after_stop" || scenario=="edge_after_heartbeat") {
    assert(stopCalls==1U && clockRestores==1U && restores==1U);
    requireLog(scenario=="aux_after_stop" ? "reason=WAKE_EDGE_AFTER_STOP" : "reason=WAKE_EDGE_BEFORE_STOP");
    requireLog("wake_level=HIGH wake_irq=1");
    requireLog("command not yet confirmed");
  } else if (scenario=="edge_after_arm" || scenario=="edge_after_baseline_clear" || scenario=="low_during_prepare" || scenario=="edge_during_alarm" || scenario=="edge_before_wfi") {
    assert(stopCalls==0U && clockRestores==0U && restores==1U);
    requireLog("reason=WAKE_EDGE_BEFORE_STOP"); requireLog("stop_calls=0");
    if (scenario=="edge_during_alarm") requireLog("wake_edge_phase=ALARM_SETUP");
    if (scenario=="edge_after_arm" || scenario=="edge_after_baseline_clear" || scenario=="low_during_prepare")
      requireLog("wake_edge_phase=RECEIVE_ARMED");
    if (scenario=="edge_before_wfi") requireLog("wake_edge_phase=STOP_ENTRY");
  } else if (scenario=="rx_during_prepare" || scenario=="uart_during_alarm") {
    assert(stopCalls==0U && clockRestores==0U && restores==1U);
    assert(SerialLoRa.available()==12); // Arming does not consume application bytes.
    requireLog(scenario=="rx_during_prepare" ? "reason=WAKE_EDGE_BEFORE_STOP" : "reason=UART_DATA_BEFORE_STOP");
  } else if (scenario=="uart_after_stop") {
    assert(stopCalls==1U && restores==1U && SerialLoRa.available()==12);
    requireLog("reason=UART_DATA_AFTER_STOP");
  } else if (scenario=="rx_mode_invalid") {
    assert(rxWake && stopCalls==0U && restores==0U);
    requireLog("RX pin is not in UART alternate-function mode");
  } else if (scenario=="low_after_baseline_clear") {
    assert(stopCalls==0U && restores==1U);
    requireLog("reason=WAKE_ACTIVITY_AT_ARM");
  } else if (scenario=="aux_low_before_stop") {
    assert(stopCalls==0U && restores==1U);
    requireLog("reason=WAKE_LOW_BEFORE_STOP"); requireLog("wake_level=LOW");
  } else if (scenario=="unexpected_wake") {
    assert(stopCalls==1U && restores==1U); requireLog("reason=UNEXPECTED_WAKE");
  } else if (scenario=="alarm_failure") {
    assert(stopCalls==0U && restores==1U); requireLog("reason=RTC_ALARM_SETUP_FAILED");
  } else if (scenario=="untrusted") {
    assert(stopCalls==0U && restores==0U); requireLog("Stop requires trusted RTC");
  } else if (scenario=="rtc_handle_failure") {
    assert(stopCalls==0U && restores==0U); requireLog("AUX GPIO ownership unavailable");
  } else if (scenario=="prepare_failure" || scenario=="pending_aux_low") {
    assert(stopCalls==0U && restores==0U); requireLog("Mode 2 preparation failed");
    if (scenario=="pending_aux_low") {
      assert(fakeExtiPending==(wakeBit)); requireLog("pending flag preserved");
    }
  } else {
    assert(scenario=="busy" || scenario=="wake_lease" || scenario=="report_failure" || scenario=="storage_busy" || scenario=="storage_transfer");
    assert(stopCalls==0U && restores==0U);
  }
  assert(fakeRxPort.MODER==originalMode && fakeRxPort.OSPEEDR==(1UL << 24));
  assert(fakeRxPort.PUPDR==(1UL << 24) && fakeRxPort.AFR[1]==0xA00800BBU);
  assert(!tickSuspended && primask==0U);
  assert(!flashAsleep);
  assert(!fakeRtcWritable);
  if (scenario!="retained_rtc_pin" || stopCalls>0U) {
    assert(RTC->CR==preservedCr && RTC->TAFCR==preservedTafcr);
  }
  std::cout << "PASS " << (rxWake ? "RX " : "AUX ") << scenario << '\n';
}
