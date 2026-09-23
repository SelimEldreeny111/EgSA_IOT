#include "TelemetryPayload.h"

#include "../app/AppState.h"
#include "../config/AppConfig.h"
#include "../devices/RTC.h"
#include "../generated/sensor.pb.h"
#include "PacketCodec.h"

#include <Arduino.h>

extern HardwareSerial& SerialMon;

bool buildEncryptedStatusPayload(uint8_t* payload, size_t payloadCapacity, size_t& payloadLength)
{
  AppRuntimeState& state = appState();
  state.lastTimestamp = getEpochTime();
  refreshBatteryVoltage();

  Status_Message status = Status_Message_init_zero;
  status.node_id = AppConfig::kNodeId;
  status.sensor_id = AppConfig::kSensorId;
  status.timestamp = state.lastTimestamp;
  status.battery_voltage = state.batteryVoltage;
  status.flow_rate = state.tuf.flowRate;
  status.velocity = state.tuf.velocity;
  status.flow_rate_per_day = state.tuf.flowPerDay;
  status.flow_rate_per_month = state.tuf.flowPerMonth;
  status.flow_rate_per_year = state.tuf.flowPerYear;
  status.node_status = state.nodeStatus;
  status.soil_temperature = state.hnda.temperatureC;
  status.soil_moisture = state.hnda.moisturePercent;
  status.soil_moisture_temp_valid = state.hnda.isValid ? 1 : 0;
  status.ec_temperature = state.sondas.temperatureC;
  status.ec_moisture = state.sondas.moisturePercent;
  status.electrical_conductivity = state.sondas.electricalConductivity;
  status.soil_moisture_temp_ec_valid = state.sondas.isValid ? 1 : 0;
  status.active_sensor_count = state.activeSensorCount;
  status.sensor_mask = state.sensorMask;

  if (!encodeEncryptedMessage(Status_Message_fields, &status, payload, payloadCapacity, payloadLength))
  {
    SerialMon.println("Status payload encode FAILED");
    return false;
  }

  return true;
}
