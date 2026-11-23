/** @file ReplyDiagnostics.cpp @brief Shared node and gateway reply-data format. */
#define APP_LOG_MODULE "REPLY"
#include "../platform/DebugLog.h"

#if APP_DEBUG_FULL_ENABLED
#include "ReplyDiagnostics.h"

namespace {
void printReadings(const char* prefix, const char* kind, const char* const* names,
                   const float* values, size_t count)
{
    APP_DEBUG_PRINT(prefix);
    APP_DEBUG_PRINT(kind);
    for (size_t i = 0; i < count; ++i)
    {
        APP_DEBUG_PRINT(names[i]);
        APP_DEBUG_PRINT(values[i], 3);
    }
    APP_DEBUG_PRINTLN();
}
}

void logReplyData(const char* direction, const Telemetry& t, const uint8_t* payload, size_t length)
{
    const uint32_t request = t.command_ack_request_id ? t.command_ack_request_id :
        (t.has_history ? t.history.request_id : 0U);
    if (!request) return;

    char prefix[100];
    snprintf(prefix, sizeof(prefix), "reply_data dir=%s request=%lu source=%lu phase=%lu index=%lu ",
        direction, static_cast<unsigned long>(request), static_cast<unsigned long>(t.node_id),
        static_cast<unsigned long>(t.has_history ? t.history.phase : 0U),
        static_cast<unsigned long>(t.has_history ? t.history.index : 0U));

    APP_LOG_INFO("%sstate ack=%u srate_ms=%lu stran_ms=%lu valve=%lu wake_s=%lu wdt_resets=%lu power_resets=%lu sensor_mask=0x%lX",
        prefix, static_cast<unsigned>(t.command_ack_success),
        static_cast<unsigned long>(t.sampling_rate), static_cast<unsigned long>(t.Transmission_rate),
        static_cast<unsigned long>(t.node_status), static_cast<unsigned long>(t.wake_remaining_seconds),
        static_cast<unsigned long>(t.wdt_reset_count), static_cast<unsigned long>(t.power_reset_count),
        static_cast<unsigned long>(t.sensor_mask));

    if (t.has_flash_log)
    {
        const FlashLogInfo& f = t.flash_log;
        APP_LOG_INFO("%sflash state=%lu capacity=%lu used=%lu free=%lu records=%lu generation=%lu remaining=%lu",
            prefix, static_cast<unsigned long>(f.state), static_cast<unsigned long>(f.capacity_bytes),
            static_cast<unsigned long>(f.used_bytes), static_cast<unsigned long>(f.free_bytes),
            static_cast<unsigned long>(f.record_count), static_cast<unsigned long>(f.generation),
            static_cast<unsigned long>(f.clear_sectors_remaining));
    }
    if (t.has_history)
    {
        APP_LOG_INFO("%shistory total=%lu sequence=%lu result=%lu",
            prefix, static_cast<unsigned long>(t.history.total),
            static_cast<unsigned long>(t.history.sequence), static_cast<unsigned long>(t.history.result));
    }

    static const char* const sensorNames[] = {
        " battery_v=", " soil_c=", " soil_moisture=", " ec_c=", " ec_moisture=", " conductivity="
    };
    const float sensors[] = {t.battery_voltage, t.soil_temperature, t.soil_moisture,
                            t.ec_temperature, t.ec_moisture, t.electrical_conductivity};
    printReadings(prefix, "sensors", sensorNames, sensors, sizeof(sensors) / sizeof(sensors[0]));

    static const char* const flowNames[] = {
        " rate=", " velocity=", " day_m3=", " month_m3=", " year_m3="
    };
    const float primary[] = {t.flow_rate, t.velocity, t.flow_rate_per_day, t.flow_rate_per_month, t.flow_rate_per_year};
    printReadings(prefix, "flow", flowNames, primary, sizeof(primary) / sizeof(primary[0]));
    if (t.has_secondary_flow_meter)
    {
        const FlowReading& f = t.secondary_flow_meter;
        const float secondary[] = {f.flow_rate, f.velocity, f.flow_rate_per_day, f.flow_rate_per_month, f.flow_rate_per_year};
        printReadings(prefix, "secondary_flow", flowNames, secondary, sizeof(secondary) / sizeof(secondary[0]));
    }

#if APP_DEBUG_REPLY_BYTES || APP_DEBUG_RAW_FRAMES
    WiotDebug::hex(APP_LOG_MODULE, prefix, payload, length, true);
#else
    (void)payload;
    (void)length;
#endif
}
#endif
