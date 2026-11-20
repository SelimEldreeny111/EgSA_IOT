/** @file RuntimeConfig.h @brief Persisted commissioning settings for the selected hardware profile. */
#pragma once

#include "AppConfig.h"

#if APP_ENABLE_SERIAL_CONFIG
namespace RuntimeConfig {
constexpr uint32_t kMaximumRateSeconds = 86400U; // Same range as SRATE/STRAN.

struct Sensor {
    uint8_t enabled;
    uint8_t address;
};

struct Settings {
    uint32_t sampleSeconds;
    uint32_t transmitSeconds;
    uint32_t sleepSeconds;
    uint32_t retentionSeconds;
    uint32_t heartbeatSeconds;
    uint16_t nodeId;
    uint16_t gatewayId;
    uint16_t networkId;
    uint16_t brokerPort;
    uint8_t powerMode;
    uint8_t commandReplies;
    uint8_t gatewayWor;
    uint8_t gatewayHeartbeat;
    Sensor sensors[4]; // TUF, Supmea, HNDA, Sondas.
    char company[25];
    char region[25];
    char broker[64];
    char apn[64]; // Empty selects the provisioned SIM APN.
    char ssid[33]; // Empty selects the provisioned network.
    char password[65];
};

struct Topics {
    char prefix[56];
    char clientId[64];
    char status[69];
    char telemetry[69];
    char command[69];
    char broadcast[67];
    char gatewayCommands[63];
};

enum class LoadResult { Defaults, Saved, Invalid };

Settings defaults();
const Settings& active();
const Topics& topics();
bool supportsPowerMode(uint8_t mode);
const char* powerModeName(uint8_t mode);
/** @return Human-readable validation error or nullptr. */
const char* validate(const Settings& settings);
LoadResult load();
bool save(const Settings& settings);
}
#endif

#if APP_ENABLE_SERIAL_CONFIG
#define WIOT_ACTIVE_TOPIC(defaultName, field) (::RuntimeConfig::topics().field)
#define WIOT_ACTIVE_VALUE(defaultValue, field) (::RuntimeConfig::active().field)
#else
#define WIOT_ACTIVE_TOPIC(defaultName, field) (defaultName)
#define WIOT_ACTIVE_VALUE(defaultValue, field) (defaultValue)
#endif
