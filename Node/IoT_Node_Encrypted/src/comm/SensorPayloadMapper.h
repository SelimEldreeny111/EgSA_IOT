#ifndef SENSOR_PAYLOAD_MAPPER_H
#define SENSOR_PAYLOAD_MAPPER_H

#include "../app/AppState.h"
#include "../config/AppConfig.h"

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
    message.flow_rate = state.flow.flowRateM3h;
    message.velocity = state.flow.velocityMps;
    message.flow_rate_per_day = state.flow.volumeTodayM3;
    message.flow_rate_per_month = state.flow.volumeThisMonthM3;
    message.flow_rate_per_year = state.flow.volumeThisYearM3;
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

    message.flow_meter_type = static_cast<uint32_t>(state.flow.type);
    message.flow_period_source =
        static_cast<uint32_t>(state.flow.periodSource);
    message.flow_live_valid = state.flow.liveDataValid;
    message.flow_period_totals_valid = state.flow.periodTotalsValid;
    message.flow_cumulative_totals_valid =
        state.flow.cumulativeTotalsValid;
    message.rtc_valid = state.flow.rtcValid;
    message.forward_total_liters = state.flow.forwardTotalLiters;
    message.reverse_total_liters = state.flow.reverseTotalLiters;
    message.net_total_liters = state.flow.netTotalLiters;
    message.flow_period_quality =
        static_cast<uint32_t>(state.flow.periodQuality);
    message.flow_meter_alarm_flags = state.flow.alarmFlags;
}

#endif
