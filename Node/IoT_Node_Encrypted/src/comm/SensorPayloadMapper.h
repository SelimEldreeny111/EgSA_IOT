#ifndef SENSOR_PAYLOAD_MAPPER_H
#define SENSOR_PAYLOAD_MAPPER_H

#include "../app/AppState.h"
#include "../config/AppConfig.h"
#include "../generated/sensor.pb.h"
#include "../power/PowerManager.h"

template <typename FlowFields>
inline void populateFlowFields(
    FlowFields& fields,
    const FlowMeterMetrics& flow)
{
    fields.flow_rate = flow.flowRateM3h;
    fields.velocity = flow.velocityMps;
    fields.flow_rate_per_day = flow.volumeTodayM3;
    fields.flow_rate_per_month = flow.volumeThisMonthM3;
    fields.flow_rate_per_year = flow.volumeThisYearM3;
    fields.flow_meter_type = static_cast<uint32_t>(flow.type);
    fields.flow_period_source = static_cast<uint32_t>(flow.periodSource);
    fields.flow_live_valid = flow.liveDataValid;
    fields.flow_period_totals_valid = flow.periodTotalsValid;
    fields.flow_cumulative_totals_valid = flow.cumulativeTotalsValid;
    fields.rtc_valid = flow.rtcValid;
    fields.forward_total_liters = flow.forwardTotalLiters;
    fields.reverse_total_liters = flow.reverseTotalLiters;
    fields.net_total_liters = flow.netTotalLiters;
    fields.flow_period_quality = static_cast<uint32_t>(flow.periodQuality);
    fields.flow_meter_alarm_flags = flow.alarmFlags;
}

// Status_Message and Telemetry intentionally share this sensor field set.
// Keeping the mapping in one template prevents the LoRa, direct-MQTT, and
// command-response paths from silently producing different payloads.
template <typename Message>
inline void populateSensorPayloadFields(
    Message& message,
    const AppRuntimeState& state)
{
    message.sensor_id = AppConfig::kSensorId;
    message.battery_voltage = state.batteryVoltage;
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

    message.soil_temperature = state.hnda.temperatureC;
    message.soil_moisture = state.hnda.moisturePercent;
    message.soil_moisture_temp_valid = state.hnda.isValid ? 1U : 0U;
    message.ec_temperature = state.sondas.temperatureC;
    message.ec_moisture = state.sondas.moisturePercent;
    message.electrical_conductivity = state.sondas.electricalConductivity;
    message.soil_moisture_temp_ec_valid = state.sondas.isValid ? 1U : 0U;
    message.active_sensor_count = state.activeSensorCount;
    message.sensor_mask = state.sensorMask;
    message.power_mode = powerManagerMode();
    message.power_state = powerManagerState();
    message.wake_remaining_seconds = powerManagerWakeRemainingSeconds();
}

#endif
