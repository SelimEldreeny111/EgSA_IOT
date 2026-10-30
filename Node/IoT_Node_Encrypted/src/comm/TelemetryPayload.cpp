/** @file TelemetryPayload.cpp @brief Status protobuf assembly and encrypted telemetry output. */
#include "TelemetryPayload.h"
#include "../storage/TelemetryArchive.h"

#include "../app/AppState.h"
#include "../config/AppConfig.h"
#include "../devices/RTC.h"
#include "../generated/sensor.pb.h"
#include "PacketCodec.h"
#include "SensorPayloadMapper.h"

#include <Arduino.h>

extern HardwareSerial SerialMon;
static_assert(((Telemetry_size / 16U + 1U) * 16U + 17U) <= AppConfig::kCodecBufferSize,
              "Telemetry schema exceeds encrypted frame buffer");

bool buildEncryptedStatusPayload(uint8_t* payload, size_t payloadCapacity, size_t& payloadLength)
{
  AppRuntimeState& state = appState();
  state.lastTimestamp = getEpochTime();
  refreshBatteryVoltage();

  Status_Message status = Status_Message_init_zero;
  status.node_id = AppConfig::kNodeId;
  status.timestamp = state.lastTimestamp;
  populateSensorPayloadFields(status, state);

  status.sample_time_valid = isRtcTrusted();
#if APP_ENABLE_SPI_FLASH && APP_ROLE == APP_ROLE_SENSOR_NODE
  if (!TelemetryArchive::storedStatus(status)) status.live_fallback = true;
  // Measurements use the committed sample; operational state must remain current.
  status.node_status = state.nodeStatus;
  status.wdt_reset_count = hardwareWatchdogResetCount();
  status.power_reset_count = powerResetCount();
  status.power_mode = powerManagerMode();
  status.power_state = powerManagerState();
  status.wake_remaining_seconds = powerManagerWakeRemainingSeconds();
#endif

  if (!encodeEncryptedMessage(Status_Message_fields, &status, payload, payloadCapacity, payloadLength))
  {
    SerialMon.println("Status payload encode FAILED");
    return false;
  }

  return true;
}
