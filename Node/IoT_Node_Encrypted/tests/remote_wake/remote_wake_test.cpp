#include "fakes/TestAppConfig.h"
#include "../../src/power/PowerManager.h"
#include "../../src/power/RemoteWakeCycle.h"
#include "../../src/comm/CommandHandler.h"
#include <cassert>
#include <iostream>
#include <limits>

HardwareSerial SerialMon, SerialAT, SerialLoRa;
PWR_TypeDef powerRegs; RTC_TypeDef rtcRegs; SCB_TypeDef scbRegs;
PWR_TypeDef* PWR=&powerRegs; RTC_TypeDef* RTC=&rtcRegs; SCB_TypeDef* SCB=&scbRegs;
AppRuntimeState state;
uint32_t nowMs=0U, backup[20]={}, wfiCount=0U, watchdogFeeds=0U;
bool publishing=false;
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
void digitalWrite(uint32_t, uint8_t) {}
bool commandValve(bool open) { state.nodeStatus = open ? 1U : 0U; return true; }
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

int main()
{
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
  assert(handleGetTelemetryCommand(&cmd,output,length,true));
  assert(encodedTelemetry.command_ack_request_id==44U &&
         encodedTelemetry.command_ack_cmd_id==CMD_OPEN_CLOSE_NODE &&
         encodedTelemetry.command_ack_success);
  cmd.cmd_data=2U;
  assert(!handleCommand(cmd,false));
  assert(handleGetTelemetryCommand(&cmd,output,length,false));
  assert(!encodedTelemetry.command_ack_success &&
         !encodedTelemetry.wake_command_ack);
  for (const uint32_t id : {uint32_t(CMD_SET_SAMPLING_PERIOD), uint32_t(CMD_SET_TRANSMISSION_PERIOD)}) {
    cmd={7U,id,10U,45U};
    assert(handleCommand(cmd,false));
    cmd.cmd_data=86400U; assert(handleCommand(cmd,false));
    assert((id==CMD_SET_SAMPLING_PERIOD?state.samplingPeriodMs:state.transmissionPeriodMs)==86400000U);
    for (const uint64_t invalid : {uint64_t(0),uint64_t(9),uint64_t(86401),uint64_t(4294968),UINT64_MAX}) {
      cmd.cmd_data=invalid; assert(!handleCommand(cmd,false));
      assert((id==CMD_SET_SAMPLING_PERIOD?state.samplingPeriodMs:state.transmissionPeriodMs)==86400000U);
    }
  }
  cmd={7U,CMD_SYNC_RTC,1800000000ULL,46U};
  assert(handleCommand(cmd,false) && rtcSyncCalls==1U);
  cmd.cmd_data=uint64_t(UINT32_MAX)+1ULL+1800000000ULL;
  assert(!handleCommand(cmd,false) && rtcSyncCalls==1U);
  cmd.cmd_data=UINT64_MAX;
  assert(!handleCommand(cmd,false) && rtcSyncCalls==1U);
  std::cout << "PASS: remote policy, actual power manager, WAKE filtering/ACK, rollover, retry, duplicate, WDT, UART and command-width/rate bounds\n";
}
