/**
 * @file SensorPayloadMapper.h
 * @brief Common mapping from runtime measurements to protobuf sensor fields.
 */
#ifndef SENSOR_PAYLOAD_MAPPER_H
#define SENSOR_PAYLOAD_MAPPER_H

#include "../app/AppState.h"
#include "../config/AppConfig.h"
#include "../generated/sensor.pb.h"
#include "../power/PowerManager.h"
#include "../platform/Watchdog.h"

template <typename FlowFields>
inline void populateFlowFields(
    FlowFields& fields,
    const FlowMeterMetrics& flow)
{
    // Invalid is unavailable, not a real zero-flow measurement. Encode zero
    // and preserve validity bits so consumers can distinguish the two.
    fields.flow_rate = flow.liveDataValid ? flow.flowRateM3h : 0.0f;
    fields.velocity = flow.liveDataValid ? flow.velocityMps : 0.0f;
    fields.flow_rate_per_day = flow.periodTotalsValid ? flow.volumeTodayM3 : 0.0f;
    fields.flow_rate_per_month = flow.periodTotalsValid ? flow.volumeThisMonthM3 : 0.0f;
    fields.flow_rate_per_year = flow.periodTotalsValid ? flow.volumeThisYearM3 : 0.0f;
    fields.flow_meter_type = static_cast<uint32_t>(flow.type);
    fields.flow_period_source = static_cast<uint32_t>(flow.periodSource);
    fields.flow_live_valid = flow.liveDataValid;
    fields.flow_period_totals_valid = flow.periodTotalsValid;
    fields.flow_cumulative_totals_valid = flow.cumulativeTotalsValid;
    fields.rtc_valid = flow.rtcValid;
    fields.forward_total_liters = flow.cumulativeTotalsValid ? flow.forwardTotalLiters : 0U;
    fields.reverse_total_liters = flow.cumulativeTotalsValid ? flow.reverseTotalLiters : 0U;
    fields.net_total_liters = flow.cumulativeTotalsValid ? flow.netTotalLiters : 0;
    fields.flow_period_quality = static_cast<uint32_t>(flow.periodQuality);
    fields.flow_meter_alarm_flags = flow.alarmFlags;
}

/**
 * @brief Copy flow, soil, battery, and validity fields into a protobuf record.
 *
 * Status_Message and Telemetry intentionally share this sensor field set.
 * Keeping this mapping central prevents the LoRa, direct-MQTT, and command
 * response paths from silently producing different payloads.
 * @tparam Message Status_Message or Telemetry nanopb structure.
 * @param message Output message whose sensor fields are replaced.
 * @param state Current application snapshot.
 */
template <typename Message>
inline void populateSensorPayloadFields(
    Message& message,
    const AppRuntimeState& state)
{
    message.sensor_id = AppConfig::kSensorId;
    message.battery_voltage = state.batteryVoltage;
    message.wdt_reset_count = hardwareWatchdogResetCount();
    message.power_reset_count = powerResetCount();
    // Keep the V1 flow fields for old consumers. TUF has priority only when
    // both meters are enabled; Supmea remains the primary in Supmea-only builds.
    if (AppConfig::kEnableTufSensor)
    {
        populateFlowFields(message, state.tufFlow);
    }
    else if (AppConfig::kEnableSupmeaSensor)
    {
        populateFlowFields(message, state.supmeaFlow);
    }

    message.has_secondary_flow_meter =
        AppConfig::kEnableTufSensor && AppConfig::kEnableSupmeaSensor;
    if (message.has_secondary_flow_meter)
    {
        populateFlowFields(message.secondary_flow_meter, state.supmeaFlow);
    }
    message.node_status = state.nodeStatus;

    const bool hndaValid = AppConfig::kEnableHndaSensor && state.hnda.isValid;
    const bool sondasValid = AppConfig::kEnableSondasSensor && state.sondas.isValid;
    message.soil_temperature = hndaValid ? state.hnda.temperatureC : 0.0f;
    message.soil_moisture = hndaValid ? state.hnda.moisturePercent : 0.0f;
    message.soil_moisture_temp_valid = hndaValid ? 1U : 0U;
    message.ec_temperature = sondasValid ? state.sondas.temperatureC : 0.0f;
    message.ec_moisture = sondasValid ? state.sondas.moisturePercent : 0.0f;
    message.electrical_conductivity = sondasValid ? state.sondas.electricalConductivity : 0.0f;
    message.soil_moisture_temp_ec_valid = sondasValid ? 1U : 0U;
    message.active_sensor_count = state.activeSensorCount;
    message.sensor_mask = state.sensorMask;
    message.power_mode = powerManagerMode();
    message.power_state = powerManagerState();
    message.wake_remaining_seconds = powerManagerWakeRemainingSeconds();
}

#endif
