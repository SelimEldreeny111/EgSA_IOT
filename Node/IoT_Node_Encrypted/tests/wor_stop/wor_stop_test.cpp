/** @file wor_stop_test.cpp @brief Production WOR state machine with deterministic IRQ/RTC hardware fakes. */
#include "fakes/TestAppConfig.h"
#include "../../src/power/PowerManager.h"
#include <cassert>
#include <iostream>
#include <string>

HardwareSerial SerialMon, SerialAT, SerialLoRa;
PWR_TypeDef pwrRegs; RTC_TypeDef rtcRegs; SCB_TypeDef scbRegs;
PWR_TypeDef* PWR=&pwrRegs; RTC_TypeDef* RTC=&rtcRegs; SCB_TypeDef* SCB=&scbRegs;
STM32RTC rtcInstance;
STM32RTC& rtc=rtcInstance;
AppRuntimeState state;
std::string scenario;
uint32_t fakeExtiPending=0U, nowMs=0U, epoch=1800000000U, alarmEpoch=0U, primask=0U;
unsigned stopCalls=0U, clockRestores=0U, restores=0U, reinitializations=0U;
bool auxHigh=true, trusted=true, alarmHealthy=true, prepareHealthy=true;
bool restoreHealthy=true, idle=true, tickSuspended=false, injected=false;
bool fakeRtcWritable=false;
int m0=LOW, m1=LOW;
void (*auxCallback)()=nullptr;
bool armCompleted=false;
RTC_HandleTypeDef* STM32RTC::getHandle() {
  static RTC_HandleTypeDef handle;
  handle.Instance=RTC;
  return scenario=="rtc_handle_failure" ? nullptr : &handle;
}

void injectEdge() {
  fakeExtiPending |= 1U << 13;
  if (!primask && auxCallback) {
    fakeExtiPending &= ~(1U << 13);
    auxCallback();
  }
}
uint32_t millis() { return nowMs; }
uint32_t getEpochTime() { return epoch; }
bool isRtcTrusted() { return trusted; }
void initializeRtc() {}
AppRuntimeState& appState() { return state; }
int digitalRead(uint32_t pin) { return pin==13U ? (auxHigh ? HIGH : LOW) : (pin==2U ? m0 : m1); }
void attachInterrupt(uint32_t pin, void (*fn)(), int) {
  assert(pin==13U); auxCallback=fn;
  assert(primask==1U); // GPIO routing and the receive baseline are atomic.
  if (scenario=="edge_during_attach") injectEdge();
  if (!primask && (fakeExtiPending & (1U << 13))) {
    fakeExtiPending &= ~(1U << 13); auxCallback();
  }
}
void detachInterrupt(uint32_t) { auxCallback=nullptr; }
uint32_t __get_PRIMASK() { return primask; }
void __disable_irq() { primask=1U; }
void __set_PRIMASK(uint32_t value) {
  primask=value;
  if (auxCallback && !armCompleted) {
    armCompleted=true;
    if (scenario=="edge_after_arm") injectEdge();
  }
  if (!primask && auxCallback && (fakeExtiPending & (1U << 13))) {
    fakeExtiPending &= ~(1U << 13); auxCallback();
  }
}
void __enable_irq() { __set_PRIMASK(0U); }
void fakeClearExti(uint32_t mask) {
  fakeExtiPending &= ~mask;
  if (auxCallback && scenario=="edge_after_baseline_clear" && !injected) {
    injectEdge(); injected=true; // New edge must survive the baseline clear.
  }
  if (auxCallback && scenario=="low_after_baseline_clear" && !injected) {
    auxHigh=false; injected=true;
  }
}
void HAL_SuspendTick() {
  tickSuspended=true;
  if (scenario=="edge_before_wfi") injectEdge();
}
void HAL_ResumeTick() { tickSuspended=false; }
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
  if (scenario=="low_during_prepare") auxHigh=false;
  return true;
}
bool resumeLoraFromWakeOnRadio(uint32_t) {
  ++restores; m0=m1=LOW; return restoreHealthy;
}
void initializeLoraLink() { ++reinitializations; }
bool scheduleRtcWakeAlarm(uint32_t deadline) {
  assert(!fakeRtcWritable && (RTC->CR & (RTC_CR_OSEL | RTC_CR_COE | RTC_CR_TSE))==0U);
  alarmEpoch=deadline;
  if (scenario=="aux_low_before_stop") auxHigh=false;
  if (scenario=="edge_during_alarm") injectEdge();
  if (scenario=="uart_during_alarm") SerialLoRa.rxBytes=12;
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
  if (scenario=="aux_after_stop") {
    epoch+=2U;
    assert(auxCallback); auxCallback(); // Short pulse: physical AUX is HIGH again.
  } else if (scenario!="unexpected_wake") {
    epoch=alarmEpoch;
    assert(rtc.callback); rtc.callback(nullptr);
  }
}
void requireLog(const std::string& part) {
  if (SerialMon.output.str().find(part)==std::string::npos) {
    std::cerr << "Missing: " << part << '\n' << SerialMon.output.str(); assert(false);
  }
}
int main(int argc, char** argv) {
  assert(argc==2); scenario=argv[1];
  initializePowerManagerAfterSetup();
  if (scenario=="untrusted") trusted=false;
  if (scenario=="alarm_failure") alarmHealthy=false;
  if (scenario=="prepare_failure") prepareHealthy=false;
  if (scenario=="restore_failure") restoreHealthy=false;
  if (scenario=="busy") idle=false;
  if (scenario=="stale_pending") fakeExtiPending=(1U << 13) | (1U << 12);
  constexpr uint32_t preservedCr=(1U << 6) | (1U << 8) | (1U << 12); // FMT, ALRAE, ALRAIE.
  constexpr uint32_t preservedTafcr=(1U << 3) | (1U << 18); // Other tamper/output-type fields.
  RTC->CR=preservedCr; RTC->TAFCR=preservedTafcr;
  if (scenario=="retained_rtc_pin") {
    RTC->CR |= RTC_CR_OSEL | RTC_CR_COE | RTC_CR_TSE;
    RTC->TAFCR |= RTC_TAFCR_TAMP1E;
  }
  if (scenario=="pending_aux_low") {
    auxHigh=false; fakeExtiPending=1U << 13; prepareHealthy=false;
  }
  notifyPowerManagerTelemetryResult(scenario!="report_failure");
  nowMs=4999U; servicePowerManager(); assert(stopCalls==0U);
  if (scenario=="wake_lease") assert(requestRemoteWake(30U, 123U));
  nowMs=5000U; servicePowerManager();
  if (scenario=="rtc_deadline" || scenario=="stale_pending" || scenario=="restore_failure" || scenario=="retained_rtc_pin" || scenario=="edge_during_prepare" || scenario=="edge_during_attach") {
    assert(stopCalls==4U && clockRestores==4U && restores==1U);
    requireLog("Power: WOR RTC heartbeat");
    requireLog("reason=REPORT_DEADLINE");
    requireLog("rtc_elapsed_s=60");
    if (scenario=="stale_pending") {
      assert(fakeExtiPending==(1U << 12)); // Shared-vector neighbour is untouched.
      requireLog("cleared pre-arm stale AUX pending flag");
    }
    if (scenario=="restore_failure") assert(reinitializations==1U);
    else requireLog("Power: RTC report deadline woke STM32");
    if (scenario=="retained_rtc_pin") requireLog("released retained RTC pin functions");
    if (scenario=="edge_during_prepare" || scenario=="edge_during_attach")
      requireLog("idle receive baseline; pre-arm AUX history cleared");
  } else if (scenario=="aux_after_stop" || scenario=="edge_after_heartbeat") {
    assert(stopCalls==1U && clockRestores==1U && restores==1U);
    requireLog(scenario=="aux_after_stop" ? "reason=AUX_EDGE_AFTER_STOP" : "reason=AUX_EDGE_BEFORE_STOP");
    requireLog("AUX=HIGH aux_irq=1");
    requireLog("command not yet confirmed");
  } else if (scenario=="edge_after_arm" || scenario=="edge_after_baseline_clear" || scenario=="low_during_prepare" || scenario=="edge_during_alarm" || scenario=="edge_before_wfi") {
    assert(stopCalls==0U && clockRestores==0U && restores==1U);
    requireLog("reason=AUX_EDGE_BEFORE_STOP"); requireLog("stop_calls=0");
    if (scenario=="edge_during_alarm") requireLog("aux_edge_phase=ALARM_SETUP");
    if (scenario=="edge_after_arm" || scenario=="edge_after_baseline_clear" || scenario=="low_during_prepare")
      requireLog("aux_edge_phase=RECEIVE_ARMED");
    if (scenario=="edge_before_wfi") requireLog("aux_edge_phase=STOP_ENTRY");
  } else if (scenario=="rx_during_prepare" || scenario=="uart_during_alarm") {
    assert(stopCalls==0U && clockRestores==0U && restores==1U);
    assert(SerialLoRa.available()==12); // Arming does not consume application bytes.
    requireLog(scenario=="rx_during_prepare" ? "reason=AUX_EDGE_BEFORE_STOP" : "reason=UART_DATA_BEFORE_STOP");
  } else if (scenario=="low_after_baseline_clear") {
    assert(stopCalls==0U && restores==1U);
    requireLog("reason=AUX_ACTIVITY_AT_ARM");
  } else if (scenario=="aux_low_before_stop") {
    assert(stopCalls==0U && restores==1U);
    requireLog("reason=AUX_LOW_BEFORE_STOP"); requireLog("AUX=LOW");
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
      assert(fakeExtiPending==(1U << 13)); requireLog("pending flag preserved");
    }
  } else {
    assert(scenario=="busy" || scenario=="wake_lease" || scenario=="report_failure");
    assert(stopCalls==0U && restores==0U);
  }
  assert(!tickSuspended && primask==0U);
  assert(!fakeRtcWritable);
  if (scenario!="retained_rtc_pin" || stopCalls>0U) {
    assert(RTC->CR==preservedCr && RTC->TAFCR==preservedTafcr);
  }
  std::cout << "PASS " << scenario << '\n';
}
