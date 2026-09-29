#include "CommandHandler.h"
#include "SensorPayloadMapper.h"

#include "../config/AppConfig.h"
#include "../app/AppState.h"
#include "PacketCodec.h"
#include "../devices/RTC.h"
#include "../power/PowerManager.h"

#include <Arduino.h>
#include <string.h>

extern HardwareSerial SerialMon;

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

void handleCommand(const CMD_Message& cmd, bool isBroadcastTopic)
{
  AppRuntimeState& state = appState();

  SerialMon.println("\n========== CMD RECEIVED ==========");
  SerialMon.print("Node ID : "); SerialMon.println(cmd.node_id);
  SerialMon.print("CMD ID  : "); SerialMon.println(cmd.cmd_id);
  SerialMon.print("DATA    : "); SerialMon.println(cmd.cmd_data);

  /* ===================== NODE FILTER ===================== */
  if (!isBroadcastTopic && cmd.node_id != AppConfig::kNodeId) 
  {
    SerialMon.println(" Not for this node (node topic)");
    return;
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

      if (cmd.cmd_data < AppConfig::kMinimumRateSeconds) 
      {
        SerialMon.print(" Sampling period too low! Minimum is ");
        SerialMon.print(AppConfig::kMinimumRateSeconds);
        SerialMon.println(" seconds");
        break;
      }

      state.samplingPeriodMs = cmd.cmd_data * 1000UL;

      SerialMon.print("New Sampling Period: ");
      SerialMon.print(cmd.cmd_data);
      SerialMon.println(" sec");
      break;
    }

    case CMD_SET_TRANSMISSION_PERIOD: 
    {
      SerialMon.println("CMD: SET_TRANSMISSION_PERIOD");

      if (cmd.cmd_data < AppConfig::kMinimumRateSeconds) 
      {
        SerialMon.print(" Transmission period too low! Minimum is ");
        SerialMon.print(AppConfig::kMinimumRateSeconds);
        SerialMon.println(" seconds");
        break;
      }

      state.transmissionPeriodMs = cmd.cmd_data * 1000UL;

      SerialMon.print("New Transmission Period: ");
      SerialMon.print(cmd.cmd_data);
      SerialMon.println(" sec");
      break;
    }

    case CMD_SYNC_RTC: 
    {
      SerialMon.println("CMD: SYNC_RTC");

      if (!syncRTCFromEpoch(cmd.cmd_data))
      {
        SerialMon.println("STIME failed; clock was not marked trusted");
        break;
      }

      state.lastTimestamp = getEpochTime();
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

      if (!AppConfig::kEnableOpenCloseNodeOutput)
      {
        SerialMon.println(" OPEN_CLOSE rejected: output GPIO conflicts with AS32 AUX");
        break;
      }

      state.nodeStatus = static_cast<uint8_t>(cmd.cmd_data);
      const uint8_t outputLevel = AppConfig::kOpenCloseNodeActiveLow
          ? (state.nodeStatus ? LOW : HIGH)
          : (state.nodeStatus ? HIGH : LOW);
      digitalWrite(AppConfig::kOpenCloseNodeGpio, outputLevel);

      SerialMon.print("Node Status: ");
      SerialMon.println(state.nodeStatus ? "OPEN/ON" : "CLOSE/OFF");
      SerialMon.print("GPIO: ");
      SerialMon.print(AppConfig::kOpenCloseNodeGpio);
      SerialMon.print(" level=");
      SerialMon.println(outputLevel == HIGH ? "HIGH" : "LOW");
      break;
    }

    default: 
    {
      SerialMon.println(" Unknown CMD ID");
      break;
    }
  }

  SerialMon.println("=====================================\n");
}

bool handleGetTelemetryCommand(const CMD_Message* cmd, uint8_t* payload, size_t& payloadLength)
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
  // This acknowledges acceptance, not a fresh RS485 sample. The next normal
  // loop is explicitly scheduled to sample and send a fresh Status message.
  tlm.wake_command_ack = cmd != nullptr && cmd->cmd_id == CMD_REMOTE_WAKE;
  tlm.wake_request_id = tlm.wake_command_ack ? powerManagerWakeRequestId() : 0U;

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
