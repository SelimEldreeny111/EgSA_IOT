#include "CommandHandler.h"

#include "../config/AppConfig.h"
#include "../app/AppState.h"
#include "PacketCodec.h"
#include "../devices/RTC.h"

#include <Arduino.h>
#include <string.h>

extern HardwareSerial& SerialMon;

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

      state.lastTimestamp = cmd.cmd_data;
      syncRTCFromEpoch(cmd.cmd_data);

      SerialMon.print("RTC synced to epoch: ");
      SerialMon.println(cmd.cmd_data);
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
  tlm.battery_voltage = state.batteryVoltage;
  tlm.active_sensor_count = state.activeSensorCount;
  tlm.sensor_id = AppConfig::kSensorId;
  tlm.flow_rate = state.tuf.flowRate;
  tlm.velocity = state.tuf.velocity;
  tlm.flow_rate_per_day = state.tuf.flowPerDay;
  tlm.flow_rate_per_month = state.tuf.flowPerMonth;
  tlm.flow_rate_per_year = state.tuf.flowPerYear;
  tlm.node_status = state.nodeStatus;
  tlm.soil_temperature = state.hnda.temperatureC;
  tlm.soil_moisture = state.hnda.moisturePercent;
  tlm.soil_moisture_temp_valid = state.hnda.isValid ? 1 : 0;
  tlm.ec_temperature = state.sondas.temperatureC;
  tlm.ec_moisture = state.sondas.moisturePercent;
  tlm.electrical_conductivity = state.sondas.electricalConductivity;
  tlm.soil_moisture_temp_ec_valid = state.sondas.isValid ? 1 : 0;
  tlm.sensor_mask = state.sensorMask;

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
  for (int i = 0; i < payloadLength; i++) 
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
