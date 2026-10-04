/** @file CommandHandler.cpp @brief Remote-command validation and node-side dispatch. */
#include "CommandHandler.h"
#include "SensorPayloadMapper.h"

#include "../config/AppConfig.h"
#include "../app/AppState.h"
#include "PacketCodec.h"
#include "../devices/RTC.h"
#include "../devices/ValveController.h"
#include "../power/PowerManager.h"

#include <Arduino.h>
#include <string.h>

extern HardwareSerial SerialMon;

namespace {
// Match the server's accepted maximum; validate before narrowing to millis.
constexpr uint64_t kMaximumRateSeconds = 86400ULL;
}

bool handleRemoteWakeCommand(const CMD_Message& cmd, bool isBroadcastTopic)
{
  if (cmd.cmd_id != CMD_REMOTE_WAKE ||
      (!isBroadcastTopic && cmd.node_id != AppConfig::kNodeId))
  {
    SerialMon.println("WAKE rejected: command/node mismatch");
    return false;
  }
  return requestRemoteWake(cmd.cmd_data, cmd.request_id);
}

bool handleCommand(const CMD_Message& cmd, bool isBroadcastTopic)
{
  AppRuntimeState& state = appState();
  bool applied = false;

  SerialMon.println("\n========== CMD RECEIVED ==========");
  SerialMon.print("Node ID : "); SerialMon.println(cmd.node_id);
  SerialMon.print("CMD ID  : "); SerialMon.println(cmd.cmd_id);
  SerialMon.print("DATA    : "); SerialMon.println(cmd.cmd_data);

  /* ===================== NODE FILTER ===================== */
  if (!isBroadcastTopic && cmd.node_id != AppConfig::kNodeId) 
  {
    SerialMon.println(" Not for this node (node topic)");
    return false;
  }

  if (isBroadcastTopic) 
  {
    SerialMon.println(" Broadcast command accepted");
  } 
  else 
  {
    SerialMon.println(" Direct node command accepted");
  }

  /* ===================== COMMAND HANDLING ===================== */
  switch (cmd.cmd_id) 
  {

    case CMD_SET_SAMPLING_PERIOD: 
    {
      SerialMon.println("CMD: SET_SAMPLING_PERIOD");

      if (cmd.cmd_data < AppConfig::kMinimumRateSeconds ||
          cmd.cmd_data > kMaximumRateSeconds)
      {
        SerialMon.print(" Invalid sampling period. Minimum is ");
        SerialMon.print(AppConfig::kMinimumRateSeconds);
        SerialMon.println(" seconds; maximum is 86400 seconds");
        break;
      }

      state.samplingPeriodMs = static_cast<uint32_t>(cmd.cmd_data) * 1000UL;
      applied = true;

      SerialMon.print("New Sampling Period: ");
      SerialMon.print(cmd.cmd_data);
      SerialMon.println(" sec");
      break;
    }

    case CMD_SET_TRANSMISSION_PERIOD: 
    {
      SerialMon.println("CMD: SET_TRANSMISSION_PERIOD");

      if (cmd.cmd_data < AppConfig::kMinimumRateSeconds ||
          cmd.cmd_data > kMaximumRateSeconds)
      {
        SerialMon.print(" Invalid transmission period. Minimum is ");
        SerialMon.print(AppConfig::kMinimumRateSeconds);
        SerialMon.println(" seconds; maximum is 86400 seconds");
        break;
      }

      state.transmissionPeriodMs = static_cast<uint32_t>(cmd.cmd_data) * 1000UL;
      applied = true;

      SerialMon.print("New Transmission Period: ");
      SerialMon.print(cmd.cmd_data);
      SerialMon.println(" sec");
      break;
    }

    case CMD_SYNC_RTC: 
    {
      SerialMon.println("CMD: SYNC_RTC");

      if (cmd.cmd_data > UINT32_MAX)
      {
        SerialMon.println("STIME rejected: epoch exceeds the 32-bit RTC range");
        break;
      }
      if (!syncRTCFromEpoch(static_cast<uint32_t>(cmd.cmd_data)))
      {
        SerialMon.println("STIME failed; clock was not marked trusted");
        break;
      }

      state.lastTimestamp = getEpochTime();
      applied = true;
      SerialMon.print("RTC synced to epoch: ");
      SerialMon.println(state.lastTimestamp);
      break;
    }

    case CMD_OPEN_CLOSE_NODE:
    {
      SerialMon.println("CMD: OPEN_CLOSE_NODE");

      if (cmd.cmd_data != 0 && cmd.cmd_data != 1)
      {
        SerialMon.println(" Invalid node status! Use 0=close/off, 1=open/on");
        break;
      }

      applied = commandValve(cmd.cmd_data == 1U);
      break;
    }

    default: 
    {
      SerialMon.println(" Unknown CMD ID");
      break;
    }
  }

  SerialMon.println("=====================================\n");
  return applied;
}

bool handleGetTelemetryCommand(const CMD_Message* cmd, uint8_t* payload,
                               size_t& payloadLength, bool commandApplied)
{
  SerialMon.println("\n============= HANDLE GET TELEMETRY CMD =============");

  (void)cmd;
  AppRuntimeState& state = appState();

  state.lastTimestamp = getEpochTime();
  refreshBatteryVoltage();
  SerialMon.print("Timestamp: ");
  SerialMon.println(state.lastTimestamp);

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

  SerialMon.println("Telemetry struct filled");

  /* ===================== ENCODE ===================== */
  if (!encodeEncryptedMessage(Telemetry_fields, &tlm, payload, AppConfig::kCodecBufferSize, payloadLength)) 
  {
    SerialMon.println(" Telemetry encode FAILED");
    return false;
  }

  SerialMon.print(" Encoded bytes: ");
  SerialMon.println(payloadLength);

  SerialMon.println("Encoded Payload (HEX):");
  for (size_t i = 0; i < payloadLength; i++)
  {
    if (payload[i] < 0x10) SerialMon.print("0");
    SerialMon.print(payload[i], HEX);
    SerialMon.print(" ");
  }
  SerialMon.println();

  SerialMon.println(" Telemetry response ready for publishing");
  SerialMon.println("====================================================\n");
  
  return true;
}
