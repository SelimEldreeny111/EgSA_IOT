#include "fakes/TestAppConfig.h"
#include "../../src/power/PowerManager.h"
#include "../../src/power/RemoteWakeCycle.h"
#include "../../src/comm/CommandHandler.h"
#include "../../src/comm/CommandReplayCache.h"
#include <cassert>
#include <iostream>
#include <limits>

HardwareSerial SerialMon, SerialAT, SerialLoRa;
PWR_TypeDef powerRegs; RTC_TypeDef rtcRegs; SCB_TypeDef scbRegs;
PWR_TypeDef* PWR=&powerRegs; RTC_TypeDef* RTC=&rtcRegs; SCB_TypeDef* SCB=&scbRegs;
AppRuntimeState state;
uint32_t nowMs=0U, backup[20]={}, wfiCount=0U, watchdogFeeds=0U;
bool publishing=false;
bool TelemetryArchive::busyForTest=false;
Telemetry encodedTelemetry;
const void* Telemetry_fields=nullptr;
uint32_t millis() { return nowMs; }
AppRuntimeState& appState() { return state; }
bool isAsyncPublishBusy() { return publishing; }
void __WFI() { ++wfiCount; }
void HAL_PWR_EnableBkUpAccess() { PWR->CR |= PWR_CR_DBP; }
void HAL_PWR_DisableBkUpAccess() { PWR->CR &= ~PWR_CR_DBP; }
uint32_t HAL_RTCEx_BKUPRead(RTC_HandleTypeDef*, uint32_t index) { return backup[index]; }
void HAL_RTCEx_BKUPWrite(RTC_HandleTypeDef*, uint32_t index, uint32_t value) { backup[index]=value; }
void serviceHardwareWatchdog(WatchdogStage) { ++watchdogFeeds; }
void markHardwareWatchdogStage(WatchdogStage) {}
static uint32_t wdtClearCalls=0, powerClearCalls=0;
static bool counterClearSuccess=true;
namespace WatchdogResetCounter { bool clear() { ++wdtClearCalls; return counterClearSuccess; } }
namespace PowerResetCounter { bool clear() { ++powerClearCalls; return counterClearSuccess; } }
void digitalWrite(uint32_t, uint8_t) {}
uint32_t valveCalls=0U;
bool commandValve(bool open) { ++valveCalls; state.nodeStatus = open ? 1U : 0U; return true; }
uint32_t getEpochTime() { return 1800000000U; }
uint32_t rtcSyncCalls=0U;
bool syncRTCFromEpoch(uint32_t) { ++rtcSyncCalls; return true; }
void refreshBatteryVoltage() {}
void populateSensorPayloadFields(Telemetry& message, const AppRuntimeState&) {
  message.power_mode=powerManagerMode(); message.power_state=powerManagerState();
  message.wake_remaining_seconds=powerManagerWakeRemainingSeconds();
}
bool encodeEncryptedMessage(const void*, const void* data, uint8_t*, size_t, size_t& length) {
  encodedTelemetry=*static_cast<const Telemetry*>(data); length=1U; return true;
}

#if TEST_REMOTE_APP_SCHEDULE
// Actual PowerManager/CommandHandler with hardware-only fakes. Independent
// timestamps represent the same cooperative sensor/publish decisions as loop().
void runApplicationScheduleTests()
{
  state.samplingPeriodMs=10000U; state.transmissionPeriodMs=30000U;
  initializePowerManagerAfterSetup(); servicePowerManager();
  assert(powerManagerAllowsSensorWork()); // Initial fresh snapshot/report due.
  state.lastReadMs=state.lastSendMs=nowMs;
  notifyPowerManagerSensorCycle(true); servicePowerManager();
  assert(powerManagerAllowsSensorWork()); // Finish all four sensor groups.
  notifyPowerManagerTelemetryResult(false); // Failure cannot keep an idle CPU spinning.
  notifyPowerManagerSensorCycle(false); servicePowerManager();
  assert(!powerManagerAllowsSensorWork() && powerManagerState()==2U);
  powerManagerIdleCpu(); assert(wfiCount==1U && watchdogFeeds==0U);
  TelemetryArchive::busyForTest=true;servicePowerManager();
  assert(powerManagerAllowsSensorWork()&&powerManagerShouldRunApplication());
  powerManagerIdleCpu();assert(wfiCount==1U); // No sleep while flash/transfer work is pending.
  TelemetryArchive::busyForTest=false;servicePowerManager();assert(!powerManagerAllowsSensorWork());
  SerialAT.queued=1; assert(powerManagerShouldRunApplication()); SerialAT.queued=0;

  nowMs=9999U; servicePowerManager(); assert(!powerManagerAllowsSensorWork());
  nowMs=10000U; servicePowerManager(); assert(powerManagerAllowsSensorWork());
  assert(nowMs-state.lastReadMs==10000U && state.lastSendMs==0U);
  state.lastReadMs=nowMs; notifyPowerManagerSensorCycle(true);
  nowMs=12500U; servicePowerManager(); assert(powerManagerAllowsSensorWork());
  notifyPowerManagerSensorCycle(false); servicePowerManager();
  assert(!powerManagerAllowsSensorWork() && state.lastSendMs==0U); // Sampling-only, no forced Status.
  nowMs=20000U; servicePowerManager(); assert(powerManagerAllowsSensorWork());
  state.lastReadMs=nowMs; servicePowerManager(); assert(!powerManagerAllowsSensorWork());
  nowMs=30000U; servicePowerManager(); assert(powerManagerAllowsSensorWork());
  state.lastReadMs=state.lastSendMs=nowMs; publishing=true; servicePowerManager();
  assert(powerManagerAllowsSensorWork()); // Never idle with a pending response/Status.
  publishing=false; notifyPowerManagerTelemetryResult(true); servicePowerManager();
  assert(!powerManagerAllowsSensorWork()); // No legacy five-second command window.

  state.samplingPeriodMs=60000U; state.transmissionPeriodMs=10000U;
  nowMs=40000U; servicePowerManager(); assert(powerManagerAllowsSensorWork());
  assert(state.lastReadMs==30000U); // Transmission-only must not force a sensor read.
  state.lastSendMs=nowMs; servicePowerManager(); assert(!powerManagerAllowsSensorWork());
  nowMs=40500U;
  CMD_Message cmd={7U,CMD_SET_SAMPLING_PERIOD,10U,800U};
  assert(handleCommand(cmd,false)); servicePowerManager();
  assert(powerManagerAllowsSensorWork() && state.lastReadMs==30000U);
  state.lastReadMs=nowMs; servicePowerManager(); assert(!powerManagerAllowsSensorWork());
  nowMs=50000U; cmd={7U,CMD_SET_TRANSMISSION_PERIOD,10U,801U};
  assert(handleCommand(cmd,false)); servicePowerManager();
  assert(powerManagerAllowsSensorWork() && state.lastReadMs==40500U);
  state.lastSendMs=nowMs; servicePowerManager(); assert(!powerManagerAllowsSensorWork());

  // Ordinary commands do not create an active lease or force fresh sample/report.
  const uint32_t readBefore=state.lastReadMs, sendBefore=state.lastSendMs;
  cmd={7U,CMD_OPEN_CLOSE_NODE,1U,802U}; assert(handleCommand(cmd,false));
  cmd={7U,CMD_GET_TELEMETRY,0U,803U}; uint8_t payload[10]={}; size_t length=0U;
  assert(handleGetTelemetryCommand(&cmd,payload,length));
  assert(state.lastReadMs==readBefore && state.lastSendMs==sendBefore);
  publishing=true; servicePowerManager(); assert(powerManagerAllowsSensorWork());
  publishing=false; servicePowerManager(); assert(!powerManagerAllowsSensorWork());

  // Explicit WAKE retains its documented lease and duplicate protection.
  cmd={7U,CMD_REMOTE_WAKE,2U,804U}; assert(handleRemoteWakeCommand(cmd,false));
  state.lastReadMs=state.lastSendMs=nowMs;
  notifyPowerManagerTelemetryResult(true); servicePowerManager();
  assert(powerManagerAllowsSensorWork() && powerManagerWakeRemainingSeconds()==2U);
  nowMs=51999U; servicePowerManager(); assert(powerManagerAllowsSensorWork());
  assert(handleRemoteWakeCommand(cmd,false) && powerManagerWakeRemainingSeconds()==1U);
  nowMs=52000U; publishing=true; servicePowerManager();
  assert(powerManagerAllowsSensorWork() && powerManagerWakeRemainingSeconds()==0U);
  assert(!handleRemoteWakeCommand(cmd,false));
  publishing=false; servicePowerManager(); assert(!powerManagerAllowsSensorWork());

  state.samplingPeriodMs=state.transmissionPeriodMs=86400000U;
  nowMs=90000U; servicePowerManager(); assert(!powerManagerAllowsSensorWork());
  // More than the legacy 30-second sleep interval elapsed: no forced cycle.

  // Actual manager deadline arithmetic survives millis rollover.
  nowMs=0xFFFFFF00U; state.samplingPeriodMs=10000U; state.transmissionPeriodMs=20000U;
  initializePowerManagerAfterSetup(); servicePowerManager(); assert(powerManagerAllowsSensorWork());
  state.lastReadMs=state.lastSendMs=nowMs; servicePowerManager();
  assert(!powerManagerAllowsSensorWork());
  nowMs=9743U; servicePowerManager(); assert(!powerManagerAllowsSensorWork());
  nowMs=9744U; servicePowerManager(); assert(powerManagerAllowsSensorWork());
  assert(nowMs-state.lastReadMs==10000U && nowMs-state.lastSendMs<state.transmissionPeriodMs);
  state.lastReadMs=nowMs; servicePowerManager(); assert(!powerManagerAllowsSensorWork());
  assert(watchdogFeeds==0U);
}
#endif

int main()
{
  for (uint32_t command=1U;command<=6U;++command) {
    assert(shouldSendCommandTelemetryReply(command,true));
    assert(shouldSendCommandTelemetryReply(command,false)==(command==CMD_GET_TELEMETRY));
  }
#if TEST_REMOTE_APP_SCHEDULE
  runApplicationScheduleTests();
  std::cout << "PASS: actual schedule-driven remote power manager: independent SRATE/STRAN, UART, snapshot/reply guards, command rates, WAKE leases, failure idle, no fixed cycle, rollover\n";
  return 0;
#endif
  CommandReplayCache boundedCache;
  bool cachedResult=true;
  assert(boundedCache.lookup(0U,7U,5U,1U,false,cachedResult)==CommandReplayCache::Missing);
  boundedCache.remember(1U,7U,5U,1U,false,false);
  assert(boundedCache.lookup(1U,7U,5U,1U,false,cachedResult)==CommandReplayCache::Duplicate && !cachedResult);
  assert(boundedCache.lookup(1U,7U,5U,1U,true,cachedResult)==CommandReplayCache::Conflict);
  assert(boundedCache.lookup(1U,8U,5U,1U,false,cachedResult)==CommandReplayCache::Conflict);
  assert(boundedCache.lookup(1U,7U,3U,1U,false,cachedResult)==CommandReplayCache::Conflict);
  for (uint32_t request=2U;request<=9U;++request) boundedCache.remember(request,7U,5U,1U,false,true);
  assert(boundedCache.lookup(1U,7U,5U,1U,false,cachedResult)==CommandReplayCache::Missing); // documented FIFO eviction
  RemoteWakeCycle cycle;
  cycle.begin(0U, 30000U, 5000U);
  assert(cycle.active());
  assert(cycle.advance(20000U,true)==RemoteWakeCycle::Transition::None); // no successful send
  cycle.telemetryDelivered(20000U);
  assert(cycle.advance(24999U,true)==RemoteWakeCycle::Transition::None);
  assert(cycle.advance(25000U,false)==RemoteWakeCycle::Transition::None); // busy cannot be interrupted
  assert(cycle.advance(25000U,true)==RemoteWakeCycle::Transition::EnteredIdle);
  assert(!cycle.active());
  assert(!cycle.requestWake(26000U,86401ULL,60U));
  assert(!cycle.requestWake(26000U,std::numeric_limits<uint64_t>::max(),60U));
  assert(!cycle.active());
  assert(cycle.requestWake(26000U,0U,60U));
  assert(cycle.remainingSeconds(26000U)==60U);
  cycle.telemetryDelivered(27000U); // never shortens command lease to 5 s
  assert(cycle.remainingSeconds(27000U)==59U);
  assert(cycle.advance(86000U,true)==RemoteWakeCycle::Transition::EnteredIdle);
  assert(cycle.advance(115999U,true)==RemoteWakeCycle::Transition::None);
  assert(cycle.advance(116000U,true)==RemoteWakeCycle::Transition::PeriodicWake);
  cycle.begin(0xFFFFFF00U,30000U,5000U);
  assert(cycle.requestWake(0xFFFFFF00U,1U,60U));
  assert(cycle.remainingSeconds(744U)==0U);
  assert(cycle.advance(744U,true)==RemoteWakeCycle::Transition::EnteredIdle);
  cycle.begin(0U,30000U,0U); cycle.telemetryDelivered(0U);
  assert(cycle.advance(0U,true)==RemoteWakeCycle::Transition::EnteredIdle);

  // Actual PowerManager.cpp and CommandHandler.cpp, with only hardware faked.
  backup[15]=0x50444E31U; backup[0]=1234U; backup[14]=5678U;
  powerManagerEarlyBoot();
  assert(backup[15]==0U && backup[0]==1234U && backup[14]==5678U);
  initializePowerManagerAfterSetup();
  assert(powerManagerAllowsSensorWork() && powerManagerMode()==3U);
  notifyPowerManagerTelemetryResult(false);
  nowMs=1000U; servicePowerManager(); assert(powerManagerAllowsSensorWork());
  notifyPowerManagerTelemetryResult(true);
  nowMs=6000U; servicePowerManager();
  assert(!powerManagerAllowsSensorWork() && powerManagerState()==2U);
  SCB->SCR=SCB_SCR_SLEEPDEEP_Msk;
  powerManagerIdleCpu(); assert(wfiCount==1U && SCB->SCR==0U);
  TelemetryArchive::busyForTest=true;assert(powerManagerShouldRunApplication());
  powerManagerIdleCpu();assert(wfiCount==1U);
  TelemetryArchive::busyForTest=false;
  assert(watchdogFeeds==0U); // never mask hangs by feeding from sleep/interrupt code
  assert(powerManagerShouldRunApplication());
  assert(!powerManagerShouldRunApplication());
  SerialAT.queued=1; assert(powerManagerShouldRunApplication()); SerialAT.queued=0;
  nowMs+=100U; assert(powerManagerShouldRunApplication());
  CMD_Message cmd={8U,CMD_REMOTE_WAKE,30U,42U};
  assert(!handleRemoteWakeCommand(cmd,false)); // wrong node
  cmd.node_id=7U; cmd.cmd_data=86401U;
  assert(!handleRemoteWakeCommand(cmd,false));
  assert(!powerManagerAllowsSensorWork());
  cmd.cmd_data=30U;
  assert(handleRemoteWakeCommand(cmd,false));
  assert(powerManagerAllowsSensorWork() && powerManagerWakeRemainingSeconds()==30U);
  assert(nowMs-state.lastReadMs==state.samplingPeriodMs);
  uint8_t output[10]={}; size_t length=0U;
  assert(handleGetTelemetryCommand(&cmd,output,length));
  assert(encodedTelemetry.wake_command_ack && encodedTelemetry.wake_request_id==42U);
  assert(encodedTelemetry.command_ack_request_id==42U &&
         encodedTelemetry.command_ack_cmd_id==CMD_REMOTE_WAKE &&
         encodedTelemetry.command_ack_success);
  assert(encodedTelemetry.power_mode==3U && encodedTelemetry.power_state==1U);
  nowMs+=10000U;
  assert(handleRemoteWakeCommand(cmd,false)); // duplicate keeps original deadline
  assert(powerManagerWakeRemainingSeconds()==20U);
  cmd.cmd_data=31U; assert(!handleRemoteWakeCommand(cmd,false));
  cmd.cmd_data=30U;
  notifyPowerManagerTelemetryResult(true); assert(powerManagerWakeRemainingSeconds()==20U);
  nowMs+=20000U; publishing=true; servicePowerManager();
  assert(powerManagerAllowsSensorWork()); publishing=false; servicePowerManager();
  assert(!powerManagerAllowsSensorWork());
  assert(!handleRemoteWakeCommand(cmd,false)); // expired retransmission cannot re-wake
  cmd.request_id=43U; cmd.node_id=99U;
  assert(handleRemoteWakeCommand(cmd,true)); // deliberate broadcast uses same filtering convention
  cmd.cmd_id=CMD_GET_TELEMETRY;
  assert(handleGetTelemetryCommand(&cmd,output,length));
  assert(!encodedTelemetry.wake_command_ack && encodedTelemetry.wake_request_id==0U);
  cmd={7U,CMD_OPEN_CLOSE_NODE,1U,44U};
  assert(handleCommand(cmd,false));
  assert(handleCommand(cmd,false) && valveCalls==1U); // QoS duplicate: no second pulse
  assert(handleGetTelemetryCommand(&cmd,output,length,true));
  assert(encodedTelemetry.command_ack_request_id==44U &&
         encodedTelemetry.command_ack_cmd_id==CMD_OPEN_CLOSE_NODE &&
         encodedTelemetry.command_ack_success);
  cmd.cmd_data=0U; assert(!handleCommand(cmd,false) && valveCalls==1U); // ID conflict
  cmd.cmd_data=2U; cmd.request_id=500U;
  assert(!handleCommand(cmd,false));
  assert(handleGetTelemetryCommand(&cmd,output,length,false));
  assert(!encodedTelemetry.command_ack_success &&
         !encodedTelemetry.wake_command_ack);
  uint32_t freshRequest=100U;
  for (const uint32_t id : {uint32_t(CMD_SET_SAMPLING_PERIOD), uint32_t(CMD_SET_TRANSMISSION_PERIOD)}) {
    cmd={7U,id,10U,freshRequest++};
    assert(handleCommand(cmd,false));
    const auto oldRate=cmd;
    cmd.cmd_data=86400U; cmd.request_id=freshRequest++; assert(handleCommand(cmd,false));
    assert(handleCommand(oldRate,false)); // reply original result; do not restore old rate
    assert((id==CMD_SET_SAMPLING_PERIOD?state.samplingPeriodMs:state.transmissionPeriodMs)==86400000U);
    for (const uint64_t invalid : {uint64_t(0),uint64_t(9),uint64_t(86401),uint64_t(4294968),UINT64_MAX}) {
      cmd.cmd_data=invalid; cmd.request_id=freshRequest++; assert(!handleCommand(cmd,false));
      assert((id==CMD_SET_SAMPLING_PERIOD?state.samplingPeriodMs:state.transmissionPeriodMs)==86400000U);
    }
  }
  cmd={7U,CMD_SYNC_RTC,1800000000ULL,46U};
  assert(handleCommand(cmd,false) && rtcSyncCalls==1U);
  assert(handleCommand(cmd,false) && rtcSyncCalls==1U); // no stale clock rewind
  cmd.cmd_data=uint64_t(UINT32_MAX)+1ULL+1800000000ULL;
  cmd.request_id=freshRequest++;
  assert(!handleCommand(cmd,false) && rtcSyncCalls==1U);
  cmd.cmd_data=UINT64_MAX;
  cmd.request_id=freshRequest++;
  assert(!handleCommand(cmd,false) && rtcSyncCalls==1U);
  cmd={7U,CMD_OPEN_CLOSE_NODE,0U,0U}; // old firmware/server ID zero keeps legacy behavior
  assert(handleCommand(cmd,false)); assert(handleCommand(cmd,false));
  assert(valveCalls==3U);
  cmd={7U,CMD_CLEAR_POWER_RESETS,0U,9001U};
  assert(handleCommand(cmd,false) && powerClearCalls==1U && wdtClearCalls==0U);
  assert(handleCommand(cmd,false) && powerClearCalls==1U); // Duplicate does not clear again.
  cmd={7U,CMD_CLEAR_WDT_RESETS,0U,9002U};
  assert(handleCommand(cmd,false) && wdtClearCalls==1U && powerClearCalls==1U);
  cmd={7U,CMD_CLEAR_WDT_RESETS,1U,9003U}; assert(!handleCommand(cmd,false));
  cmd={7U,CMD_CLEAR_WDT_RESETS,0U,0U}; assert(!handleCommand(cmd,false));
  cmd={7U,CMD_CLEAR_POWER_RESETS,0U,9004U}; assert(!handleCommand(cmd,true));
  cmd={99U,CMD_CLEAR_POWER_RESETS,0U,9005U}; assert(!handleCommand(cmd,false));
  assert(powerClearCalls==1U && wdtClearCalls==1U);
  counterClearSuccess=false;
  cmd={7U,CMD_CLEAR_WDT_RESETS,0U,9006U}; assert(!handleCommand(cmd,false));
  counterClearSuccess=true;
  assert(!handleCommand(cmd,false) && wdtClearCalls==2U); // Cache the failed result too.
  cmd.request_id=9007U; assert(handleCommand(cmd,false) && wdtClearCalls==3U);
  std::cout << "PASS: reset-counter command isolation, validation, duplicate suppression and failure ACK\n";
  std::cout << "PASS: remote policy, actual power manager, WAKE filtering/ACK, rollover, retry, duplicate, WDT, UART and command-width/rate bounds\n";
}
