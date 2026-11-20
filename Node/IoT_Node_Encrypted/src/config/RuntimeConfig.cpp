/** @file RuntimeConfig.cpp @brief Versioned, verified settings storage in STM32 EEPROM emulation. */
#include "RuntimeConfig.h"

#if APP_ENABLE_SERIAL_CONFIG
#include <EEPROM.h>
#include <stdio.h>
#include <string.h>

namespace AppConfig {
#define WIOT_SETTING(type, name) type name = name##Default
WIOT_SETTING(uint16_t, kNodeId);
WIOT_SETTING(uint16_t, kLoraNetworkId);
WIOT_SETTING(bool, kEnableTufSensor);
WIOT_SETTING(bool, kEnableSupmeaSensor);
WIOT_SETTING(bool, kEnableHndaSensor);
WIOT_SETTING(bool, kEnableSondasSensor);
WIOT_SETTING(uint8_t, kTufModbusAddress);
WIOT_SETTING(uint8_t, kSupmeaSensorModbusAddress);
WIOT_SETTING(uint8_t, kHndaModbusAddress);
WIOT_SETTING(uint8_t, kSondasModbusAddress);
WIOT_SETTING(uint16_t, kMqttPort);
WIOT_SETTING(bool, kEnableCommandAckReplies);
#undef WIOT_SETTING
}

namespace RuntimeConfig {
namespace {
constexpr size_t kAddress = 256U;
constexpr uint32_t kMagic = 0x57434647UL;
constexpr uint16_t kVersion = 1U;

struct Record {
    uint32_t magic;
    uint16_t version;
    uint16_t settingsSize;
    Settings settings;
    uint32_t checksum;
};

static_assert(sizeof(Settings) == 316U && offsetof(Settings, password) + 65U == sizeof(Settings),
              "Settings record layout changed");
static_assert(kAddress >= AppConfig::kPowerCounterEepromAddress + 20U,
              "Configuration overlaps reset counters");
static_assert(kAddress + sizeof(Record) <= E2END + 1U, "Configuration exceeds EEPROM capacity");

Settings current{};
Topics routing{};

uint32_t checksum(const Record& record)
{
    const auto* bytes = reinterpret_cast<const uint8_t*>(&record);
    uint32_t crc = 0xFFFFFFFFUL;
    for (size_t i = 0; i < offsetof(Record, checksum); ++i) {
        crc ^= bytes[i];
        for (unsigned bit = 0; bit < 8; ++bit)
            crc = (crc >> 1) ^ ((crc & 1U) ? 0xEDB88320UL : 0U);
    }
    return ~crc;
}

Record readRecord()
{
    Record record;
    auto* bytes = reinterpret_cast<uint8_t*>(&record);
    eeprom_buffer_fill();
    for (size_t i = 0; i < sizeof(record); ++i)
        bytes[i] = eeprom_buffered_read_byte(kAddress + i);
    return record;
}

void apply(const Settings& s)
{
    current = s;
    AppConfig::kNodeId = s.nodeId;
    AppConfig::kLoraNetworkId = s.networkId;
    AppConfig::kEnableTufSensor = APP_HAS_SENSORS && s.sensors[0].enabled;
    AppConfig::kEnableSupmeaSensor = APP_HAS_SENSORS && s.sensors[1].enabled;
    AppConfig::kEnableHndaSensor = APP_HAS_SENSORS && s.sensors[2].enabled;
    AppConfig::kEnableSondasSensor = APP_HAS_SENSORS && s.sensors[3].enabled;
    AppConfig::kTufModbusAddress = s.sensors[0].address;
    AppConfig::kSupmeaSensorModbusAddress = s.sensors[1].address;
    AppConfig::kHndaModbusAddress = s.sensors[2].address;
    AppConfig::kSondasModbusAddress = s.sensors[3].address;
    AppConfig::kMqttPort = s.brokerPort;
    AppConfig::kEnableCommandAckReplies = s.commandReplies;
    snprintf(routing.prefix, sizeof(routing.prefix), "wiot/%s/%s", s.company, s.region);
#if APP_HAS_IP_UPLINK
    const unsigned id = s.nodeId;
    snprintf(routing.clientId, sizeof(routing.clientId), "wiot-%s-%s-%u", s.company, s.region, id);
    snprintf(routing.status, sizeof(routing.status), "%s/%u/status", routing.prefix, id);
    snprintf(routing.telemetry, sizeof(routing.telemetry), "%s/%u/data", routing.prefix, id);
    snprintf(routing.command, sizeof(routing.command), "%s/%u/cmd", routing.prefix, id);
    snprintf(routing.broadcast, sizeof(routing.broadcast), "%s/broadcast", routing.prefix);
    snprintf(routing.gatewayCommands, sizeof(routing.gatewayCommands), "%s/+/cmd", routing.prefix);
#endif
}

bool validBroker(const char* host)
{
    for (const char* c = host; *c; ++c) {
        const char ch = *c;
        if (!((ch >= 'a' && ch <= 'z') || (ch >= 'A' && ch <= 'Z') ||
              (ch >= '0' && ch <= '9') || ch == '-' || ch == '.')) return false;
    }
    return *host != '\0';
}
}

Settings defaults()
{
    Settings s{};
    s.sampleSeconds = AppConfig::kDefaultSamplingPeriodMs / 1000U;
    s.transmitSeconds = AppConfig::kDefaultTransmissionPeriodMs / 1000U;
    s.sleepSeconds = APP_POWER_SLEEP_SECONDS;
    s.retentionSeconds = APP_FLASH_RETENTION_SECONDS;
    s.heartbeatSeconds = APP_GATEWAY_HEARTBEAT_SECONDS;
    s.nodeId = APP_NODE_ID;
    s.gatewayId = APP_GATEWAY_ID;
    s.networkId = APP_LORA_NETWORK_ID;
    s.brokerPort = AppConfig::kMqttPortDefault;
    s.powerMode = APP_CONTROLLER_POWER_MODE;
    s.commandReplies = APP_ENABLE_COMMAND_ACK_REPLIES;
    s.gatewayWor = APP_LORA_GATEWAY_WOR_TX;
    s.gatewayHeartbeat = APP_ENABLE_GATEWAY_HEARTBEAT;
    s.sensors[0] = {APP_ENABLE_TUF_SENSOR, AppConfig::kTufModbusAddressDefault};
    s.sensors[1] = {APP_ENABLE_SUPMEA_SENSOR, AppConfig::kSupmeaSensorModbusAddressDefault};
    s.sensors[2] = {APP_ENABLE_HNDA_SENSOR, AppConfig::kHndaModbusAddressDefault};
    s.sensors[3] = {APP_ENABLE_SONDAS_SENSOR, AppConfig::kSondasModbusAddressDefault};
    strcpy(s.company, APP_MQTT_COMPANY);
    strcpy(s.region, APP_MQTT_REGION);
    snprintf(s.broker, sizeof(s.broker), "%s", kMqttServer);
    return s;
}

const Settings& active() { return current; }
const Topics& topics() { return routing; }

bool supportsPowerMode(uint8_t mode)
{
    switch (mode) {
    case APP_COMPONENT_MODE_NORMAL: return true;
    case APP_COMPONENT_MODE_REMOTE_WAKE: return APP_HAS_SENSORS;
    case APP_COMPONENT_MODE_LORA_WOR:
        return APP_HAS_SENSORS && APP_HAS_LORA &&
            (!AppConfig::kEnableHardwareWatchdog ||
             AppConfig::kWatchdogTimeoutUs > (APP_LORA_WOR_WATCHDOG_WAKE_SECONDS + 2UL) * 1000000UL);
    case APP_COMPONENT_MODE_POWER_DOWN:
    case APP_COMPONENT_MODE_QUEUED:
#if defined(USE_ESP8266)
        return APP_HAS_SENSORS;
#else
        return APP_HAS_SENSORS && APP_HAS_LORA;
#endif
    default: return false;
    }
}

const char* powerModeName(uint8_t mode)
{
    switch (mode) {
    case APP_COMPONENT_MODE_NORMAL: return "NORMAL";
    case APP_COMPONENT_MODE_POWER_DOWN: return "RTC_PERIODIC";
    case APP_COMPONENT_MODE_REMOTE_WAKE: return "REMOTE_WAKE";
    case APP_COMPONENT_MODE_LORA_WOR: return "LORA_WOR";
    case APP_COMPONENT_MODE_QUEUED: return "RTC_QUEUED";
    default: return "invalid";
    }
}

const char* validate(const Settings& s)
{
    if (!s.nodeId || !s.gatewayId || !s.networkId || !s.brokerPort) return "IDs and port must be nonzero.";
    if (s.sampleSeconds < AppConfig::kMinimumRateSeconds ||
        s.sampleSeconds > kMaximumRateSeconds ||
        s.transmitSeconds < AppConfig::kMinimumRateSeconds ||
        s.transmitSeconds > kMaximumRateSeconds) return "Sampling or transmission interval out of range.";
    if (s.sleepSeconds < 5U || s.sleepSeconds > AppConfig::kPowerMaximumSleepSeconds ||
        s.heartbeatSeconds < 10U || s.heartbeatSeconds > 86400U) return "Sleep or heartbeat interval out of range.";
    if (!supportsPowerMode(s.powerMode)) return "Power mode unavailable for this hardware profile.";
    if (s.commandReplies > 1 || s.gatewayHeartbeat > 1 || s.gatewayWor > 1 ||
        (APP_HAS_SENSORS && s.gatewayWor)) return "Invalid on/off selection.";
    if (s.company[24] || s.region[24] || s.broker[63] || s.apn[63] || s.ssid[32] || s.password[64] ||
        !MqttTopicRouting::validSegment(s.company) || !MqttTopicRouting::validSegment(s.region) ||
        !validBroker(s.broker) || (s.apn[0] && !validBroker(s.apn))) return "Invalid company, region, broker or network text.";
    for (size_t i = 0; i < 4; ++i) {
        const Sensor& sensor = s.sensors[i];
        if (sensor.enabled > 1U || sensor.address < 1U || sensor.address > 247U)
            return "Modbus address must be 1..247.";
        for (size_t j = 0; APP_HAS_SENSORS && j < i; ++j)
            if (sensor.enabled && s.sensors[j].enabled && sensor.address == s.sensors[j].address)
                return "Enabled sensors must have distinct Modbus addresses.";
    }
    return nullptr;
}

LoadResult load()
{
    const Record record = readRecord();
    if (record.magic == kMagic && record.version == kVersion &&
        record.settingsSize == sizeof(Settings) && record.checksum == checksum(record) &&
        !validate(record.settings)) {
        apply(record.settings);
        return LoadResult::Saved;
    }
    apply(defaults());
    return record.magic == 0xFFFFFFFFUL ? LoadResult::Defaults : LoadResult::Invalid;
}

bool save(const Settings& settings)
{
    if (validate(settings)) return false;
    Record record{};
    record.magic = kMagic;
    record.version = kVersion;
    record.settingsSize = sizeof(Settings);
    record.settings = settings;
    record.checksum = checksum(record);
    const auto* bytes = reinterpret_cast<const uint8_t*>(&record);
    const Record previous = readRecord();
    if (!memcmp(&record, &previous, sizeof(record))) return true;
    for (size_t i = 0; i < sizeof(record); ++i)
        eeprom_buffered_write_byte(kAddress + i, bytes[i]);
    eeprom_buffer_flush();
    const Record verified = readRecord();
    return !memcmp(&record, &verified, sizeof(record));
}
}
#endif
