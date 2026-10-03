/** @file TelemetryPayload.cpp @brief Status protobuf assembly and encrypted telemetry output. */
#include "TelemetryPayload.h"

#include "../app/AppState.h"
#include "../config/AppConfig.h"
#include "../devices/RTC.h"
#include "../generated/sensor.pb.h"
#include "PacketCodec.h"
#include "SensorPayloadMapper.h"

#include <Arduino.h>

extern HardwareSerial SerialMon;

bool buildEncryptedStatusPayload(uint8_t* payload, size_t payloadCapacity, size_t& payloadLength)
{
  AppRuntimeState& state = appState();
  state.lastTimestamp = getEpochTime();
  refreshBatteryVoltage();

  Status_Message status = Status_Message_init_zero;
  status.node_id = AppConfig::kNodeId;
  status.timestamp = state.lastTimestamp;
  populateSensorPayloadFields(status, state);

  if (!encodeEncryptedMessage(Status_Message_fields, &status, payload, payloadCapacity, payloadLength))
  {
    SerialMon.println("Status payload encode FAILED");
    return false;
  }

  return true;
}
