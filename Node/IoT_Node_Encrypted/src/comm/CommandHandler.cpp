/** @file CommandHandler.cpp @brief Remote-command validation and node-side dispatch. */
#define APP_LOG_MODULE "CMD"
#include "../platform/DebugLog.h"
#include "CommandHandler.h"
#include "SensorPayloadMapper.h"
#include "CommandReplayCache.h"

#include "../config/AppConfig.h"
#include "../storage/TelemetryArchive.h"
#include "../app/AppState.h"
#include "PacketCodec.h"
#include "../devices/RTC.h"
#include "../devices/ValveController.h"
#include "../power/PowerManager.h"
#include "../platform/WatchdogResetCounter.h"
#include "../platform/PowerResetCounter.h"
#include "../platform/Watchdog.h"

#include <Arduino.h>
#include <string.h>

extern HardwareSerial SerialMon;

namespace {
// Match the server's accepted maximum; validate before narrowing to millis.
constexpr uint64_t kMaximumRateSeconds = 86400ULL;
CommandReplayCache ordinaryCommands;
}

bool handleRemoteWakeCommand(const CMD_Message& cmd, bool isBroadcastTopic)
{
  if (cmd.cmd_id != CMD_REMOTE_WAKE ||
      (!isBroadcastTopic && cmd.node_id != AppConfig::kNodeId))
  {
    APP_LOG_EVENT_WARN("WAKE rejected: command/node mismatch");
    return false;
  }
  const bool accepted = requestRemoteWake(cmd.cmd_data, cmd.request_id);
  APP_LOG_EVENT("result request=%lu command=WAKE hold_seconds=%s outcome=%s",
      static_cast<unsigned long>(cmd.request_id), WiotDebug::Decimal64(cmd.cmd_data).text,
      accepted ? "accepted" : "rejected");
  return accepted;
}

bool handleCommand(const CMD_Message& cmd, bool isBroadcastTopic)
{
  AppRuntimeState& state = appState();
  bool applied = false;

  APP_LOG_EVENT("received request=%lu command=%s(%lu) target=%lu local=%u scope=%s data=%s",
      static_cast<unsigned long>(cmd.request_id), WiotDebug::commandName(cmd.cmd_id),
      static_cast<unsigned long>(cmd.cmd_id), static_cast<unsigned long>(cmd.node_id),
      AppConfig::kNodeId, isBroadcastTopic ? "broadcast" : "direct",
      WiotDebug::Decimal64(cmd.cmd_data).text);

  /* ===================== NODE FILTER ===================== */
  if (!isBroadcastTopic && cmd.node_id != AppConfig::kNodeId) 
  {
    APP_DEBUG_PRINTLN(" Not for this node (node topic)");
    return false;
  }

  if (TelemetryArchive::command(cmd.cmd_id)) {
    const bool accepted = TelemetryArchive::handle(cmd, isBroadcastTopic);
    APP_LOG_EVENT("result request=%lu command=%s outcome=%s",
        static_cast<unsigned long>(cmd.request_id), WiotDebug::commandName(cmd.cmd_id),
        accepted ? "accepted" : "rejected");
    return accepted;
  }

  const auto match = ordinaryCommands.lookup(cmd.request_id, cmd.node_id, cmd.cmd_id,
                                            cmd.cmd_data, isBroadcastTopic, applied);
  if (match != CommandReplayCache::Missing)
  {
    APP_DEBUG_PRINTLN(match == CommandReplayCache::Duplicate
        ? "Duplicate command: reply with original result; no repeated effect"
        : "Command rejected: request ID reused for different intent");
    APP_LOG_EVENT("replay request=%lu match=%s original_result=%s",
        static_cast<unsigned long>(cmd.request_id),
        match == CommandReplayCache::Duplicate ? "duplicate" : "conflicting_intent",
        applied ? "accepted" : "rejected");
    return match == CommandReplayCache::Duplicate && applied;
  }

  if (isBroadcastTopic) 
  {
    APP_DEBUG_PRINTLN(" Broadcast command accepted");
  } 
  else 
  {
    APP_DEBUG_PRINTLN(" Direct node command accepted");
  }

  /* ===================== COMMAND HANDLING ===================== */
  switch (cmd.cmd_id) 
  {

    case CMD_SET_SAMPLING_PERIOD: 
    {
      APP_DEBUG_PRINTLN("CMD: SET_SAMPLING_PERIOD");

      if (cmd.cmd_data < AppConfig::kMinimumRateSeconds ||
          cmd.cmd_data > kMaximumRateSeconds)
      {
        APP_DEBUG_PRINT(" Invalid sampling period. Minimum is ");
        APP_DEBUG_PRINT(AppConfig::kMinimumRateSeconds);
        APP_DEBUG_PRINTLN(" seconds; maximum is 86400 seconds");
        break;
      }

      state.samplingPeriodMs = static_cast<uint32_t>(cmd.cmd_data) * 1000UL;
      applied = true;

      APP_DEBUG_PRINT("New Sampling Period: ");
      APP_DEBUG_PRINT(cmd.cmd_data);
      APP_DEBUG_PRINTLN(" sec");
      break;
    }

    case CMD_SET_TRANSMISSION_PERIOD: 
    {
      APP_DEBUG_PRINTLN("CMD: SET_TRANSMISSION_PERIOD");

      if (cmd.cmd_data < AppConfig::kMinimumRateSeconds ||
          cmd.cmd_data > kMaximumRateSeconds)
      {
        APP_DEBUG_PRINT(" Invalid transmission period. Minimum is ");
        APP_DEBUG_PRINT(AppConfig::kMinimumRateSeconds);
        APP_DEBUG_PRINTLN(" seconds; maximum is 86400 seconds");
        break;
      }

      state.transmissionPeriodMs = static_cast<uint32_t>(cmd.cmd_data) * 1000UL;
      applied = true;

      APP_DEBUG_PRINT("New Transmission Period: ");
      APP_DEBUG_PRINT(cmd.cmd_data);
      APP_DEBUG_PRINTLN(" sec");
      break;
    }

    case CMD_SYNC_RTC: 
    {
      APP_DEBUG_PRINTLN("CMD: SYNC_RTC");

      if (cmd.cmd_data > UINT32_MAX)
      {
        APP_LOG_EVENT_WARN("STIME rejected: epoch exceeds the 32-bit RTC range");
        break;
      }
      if (!syncRTCFromEpoch(static_cast<uint32_t>(cmd.cmd_data)))
      {
        APP_LOG_ERROR("STIME failed; clock was not marked trusted");
        break;
      }

      state.lastTimestamp = getEpochTime();
      applied = true;
      APP_DEBUG_PRINT("RTC synced to epoch: ");
      APP_DEBUG_PRINTLN(state.lastTimestamp);
      break;
    }

    case CMD_OPEN_CLOSE_NODE:
    {
      APP_DEBUG_PRINTLN("CMD: OPEN_CLOSE_NODE");

      if (cmd.cmd_data != 0 && cmd.cmd_data != 1)
      {
        APP_DEBUG_PRINTLN(" Invalid node status! Use 0=close/off, 1=open/on");
        break;
      }

      applied = commandValve(cmd.cmd_data == 1U);
      break;
    }

    case CMD_CLEAR_POWER_RESETS:
    case CMD_CLEAR_WDT_RESETS:
    {
      if (isBroadcastTopic || cmd.cmd_data != 0U || cmd.request_id == 0U) {
        APP_LOG_EVENT_WARN("Counter clear rejected: direct node, data=0 and request_id required");
        break;
      }
      markHardwareWatchdogStage(WatchdogStage::ResetCounterStorage);
      applied = cmd.cmd_id == CMD_CLEAR_POWER_RESETS
          ? PowerResetCounter::clear() : WatchdogResetCounter::clear();
      APP_DEBUG_PRINTLN(applied ? "Reset counter cleared and verified"
                                : "Counter clear FAILED; previous RAM count retained");
      break;
    }

    default: 
    {
      APP_DEBUG_PRINTLN(" Unknown CMD ID");
      break;
    }
  }

  APP_LOG_EVENT("result request=%lu command=%s outcome=%s srate_ms=%lu stran_ms=%lu valve=%u",
      static_cast<unsigned long>(cmd.request_id), WiotDebug::commandName(cmd.cmd_id),
      applied ? "applied" : "rejected", static_cast<unsigned long>(state.samplingPeriodMs),
      static_cast<unsigned long>(state.transmissionPeriodMs), state.nodeStatus);
  ordinaryCommands.remember(cmd.request_id, cmd.node_id, cmd.cmd_id, cmd.cmd_data,
                            isBroadcastTopic, applied);
  return applied;
}

bool handleGetTelemetryCommand(const CMD_Message* cmd, uint8_t* payload,
                               size_t& payloadLength, bool commandApplied)
{

  (void)cmd;
  AppRuntimeState& state = appState();

  state.lastTimestamp = getEpochTime();
  refreshBatteryVoltage();

  Telemetry tlm = Telemetry_init_zero;
  tlm.node_id = AppConfig::kNodeId;
  tlm.timestamp = state.lastTimestamp;
  tlm.sampling_rate = state.samplingPeriodMs;
  tlm.Transmission_rate = state.transmissionPeriodMs;
  populateSensorPayloadFields(tlm, state);
  tlm.power_mode = powerManagerMode();
  tlm.power_state = powerManagerState();
  tlm.wake_remaining_seconds = powerManagerWakeRemainingSeconds();
  // This acknowledges acceptance, not a fresh RS485 sample. The next normal
  // loop is explicitly scheduled to sample and send a fresh Status message.
  tlm.wake_command_ack = commandApplied && cmd != nullptr &&
      cmd->cmd_id == CMD_REMOTE_WAKE;
  tlm.wake_request_id = tlm.wake_command_ack ? powerManagerWakeRequestId() : 0U;
  if (cmd != nullptr && cmd->request_id != 0U)
  {
    tlm.command_ack_request_id = cmd->request_id;
    tlm.command_ack_cmd_id = cmd->cmd_id;
    tlm.command_ack_success = commandApplied;
  }

  if (cmd != nullptr) TelemetryArchive::reply(*cmd, tlm, commandApplied);

  /* ===================== ENCODE ===================== */
  if (!encodeEncryptedMessage(Telemetry_fields, &tlm, payload, AppConfig::kCodecBufferSize, payloadLength)) 
  {
    APP_LOG_ERROR(" Telemetry encode FAILED");
    return false;
  }

  APP_LOG_EVENT("reply_ready request=%lu command=%s result=%s epoch=%lu bytes=%lu sensor_mask=0x%X flash=%u history=%u",
      static_cast<unsigned long>(cmd ? cmd->request_id : 0U),
      cmd ? WiotDebug::commandName(cmd->cmd_id) : "GOSTM",
      tlm.command_ack_success ? "accepted" : "no_success_ack",
      static_cast<unsigned long>(tlm.timestamp), static_cast<unsigned long>(payloadLength),
      static_cast<unsigned>(tlm.sensor_mask), tlm.has_flash_log, tlm.has_history);
  APP_DEBUG_HEX("encrypted_command_reply", payload, payloadLength);

  return true;
}
