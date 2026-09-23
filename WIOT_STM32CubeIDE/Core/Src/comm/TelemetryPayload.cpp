#include "comm/TelemetryPayload.hpp"

#include "app/AppState.hpp"
#include "comm/PacketCodec.hpp"
#include "config/AppConfig.hpp"
#include "devices/Rtc.hpp"
#include "generated/sensor.pb.h"
#include "platform/Stm32Platform.hpp"

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
  status.flow_rate = state.metrics.flowRate;
  status.velocity = state.metrics.velocity;
  status.flow_rate_per_day = state.metrics.flowPerDay;
  status.flow_rate_per_month = state.metrics.flowPerMonth;
  status.flow_rate_per_year = state.metrics.flowPerYear;
  status.node_status = state.nodeStatus;
  status.soil_temperature = state.soilMoistureTemperature.temperatureC;
  status.soil_moisture = state.soilMoistureTemperature.moisturePercent;
  status.soil_moisture_temp_valid = state.soilMoistureTemperature.isValid ? 1 : 0;
  status.ec_temperature = state.soilMoistureTemperatureEc.temperatureC;
  status.ec_moisture = state.soilMoistureTemperatureEc.moisturePercent;
  status.electrical_conductivity = state.soilMoistureTemperatureEc.electricalConductivity;
  status.soil_moisture_temp_ec_valid = state.soilMoistureTemperatureEc.isValid ? 1 : 0;
  status.active_sensor_count = state.activeSensorCount;
  status.sensor_mask = state.sensorMask;

  if (!encodeEncryptedMessage(Status_Message_fields, &status, payload, payloadCapacity, payloadLength))
  {
    SerialMon.println("Status payload encode FAILED");
    return false;
  }

  return true;
}
