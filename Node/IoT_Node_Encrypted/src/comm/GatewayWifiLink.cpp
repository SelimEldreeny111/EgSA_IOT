/** @file GatewayWifiLink.cpp @brief Bounded Wi-Fi join and retry steps for the gateway. */
#define APP_LOG_MODULE "MQTT"
#include "../platform/DebugLog.h"
#include "../config/AppConfig.h"

#if APP_ROLE == APP_ROLE_LORA_GATEWAY && defined(USE_ESP8266)
#include "GatewayWifiLink.h"
#include "../config/RuntimeConfig.h"
#include <cstring>

namespace {
constexpr uint32_t kAtTimeoutMs = 3000;
constexpr uint32_t kJoinTimeoutMs = 30000;
constexpr uint32_t kRetrySpacingMs = 5000;
constexpr uint32_t kRetryCycleMs = 30000;

// ESP-AT uses quoted strings, with backslash escapes for reserved characters.
bool appendCredential(char*& out, const char* input, size_t maxLength)
{
    *out++ = '"';
    for (size_t i = 0; input[i]; ++i) {
        const char c = input[i];
        if (i >= maxLength || c == '\r' || c == '\n') return false;
        if (c == '"' || c == '\\' || c == ',') *out++ = '\\';
        *out++ = c;
    }
    *out++ = '"';
    return true;
}
}

void GatewayWifiLink::enter(State state, uint32_t now)
{
    state_ = state;
    started_ = now;
}

void GatewayWifiLink::driveReset(bool asserted)
{
    digitalWrite(AppConfig::kEspResetPin, asserted != AppConfig::kEspResetActiveLow ? HIGH : LOW);
}

void GatewayWifiLink::assertReset(uint32_t now)
{
    driveReset(true);
    input_.resetInput();
    legacyMode_ = legacyJoin_ = false;
    enter(State::Reset, now);
}

void GatewayWifiLink::begin()
{
    pinMode(AppConfig::kEspEnablePin, OUTPUT);
    pinMode(AppConfig::kEspResetPin, OUTPUT);
    assertReset(millis());
    digitalWrite(AppConfig::kEspEnablePin, AppConfig::kEspEnableActiveHigh ? HIGH : LOW);
    serial_.begin(MODEM_BAUD);
    source_ = Source::Commissioned;
    failures_ = 0;
}

void GatewayWifiLink::send(const char* command, State state, uint32_t now)
{
    lineLength_ = 0;
    const size_t length = strlen(command);
    if (input_.write(reinterpret_cast<const uint8_t*>(command), length) != length) {
        APP_LOG_EVENT_WARN("wifi_offline reason=at_write lora=active");
        enter(State::RetryReset, now);
        return;
    }
    enter(state, now);
}

GatewayWifiLink::Reply GatewayWifiLink::takeReply()
{
    for (unsigned i = 0; i < 256; ++i) {
        const int byte = input_.readStagedAtByte();
        if (byte < 0) break;
        if (byte == '\r') continue;
        if (byte != '\n') {
            if (lineLength_ < sizeof(line_)) line_[lineLength_++] = static_cast<char>(byte);
            continue;
        }
        const size_t length = lineLength_;
        lineLength_ = 0;
        if (!length || length == sizeof(line_)) continue;
        line_[length] = '\0';
        if (!strcmp(line_, "OK")) return Reply::Ok;
        if (!strcmp(line_, "ERROR")) return Reply::Error;
        if (!strcmp(line_, "FAIL")) return Reply::Fail;
        if (!strncmp(line_, "busy", 4)) return Reply::Busy;
        if (!strncmp(line_, "+CWJAP:", 7)) joinErrorCode_ = true;
    }
    return Reply::Waiting;
}

void GatewayWifiLink::startCandidate(uint32_t now)
{
#if APP_ENABLE_SERIAL_CONFIG
    const auto& configured = RuntimeConfig::active();
    const char* configuredSsid = configured.ssid;
    const char* configuredPassword = configured.password;
#else
    const char* configuredSsid = "";
    const char* configuredPassword = "";
#endif
    const char* label = nullptr;
    ssid_ = password_ = nullptr;
    while (source_ != Source::Exhausted && !ssid_) {
        switch (source_) {
        case Source::Commissioned:
            if (*configuredSsid) {
                ssid_ = configuredSsid;
                password_ = configuredPassword;
                label = "serial";
            } else source_ = Source::Firmware;
            break;
        case Source::Firmware:
            if (*kWifiSsid && (strcmp(kWifiSsid, configuredSsid) ||
                             strcmp(kWifiPassword, configuredPassword))) {
                ssid_ = kWifiSsid;
                password_ = kWifiPassword;
                label = "firmware";
            } else source_ = Source::Saved;
            break;
        case Source::Saved:
            if (loadGatewaySavedWifiCredentials(saved_) &&
                (strcmp(saved_.ssid, configuredSsid) || strcmp(saved_.password, configuredPassword)) &&
                (strcmp(saved_.ssid, kWifiSsid) || strcmp(saved_.password, kWifiPassword))) {
                ssid_ = saved_.ssid;
                password_ = saved_.password;
                label = "flash";
            } else source_ = Source::Exhausted;
            break;
        default:
            break;
        }
    }
    if (!ssid_) {
        APP_LOG_EVENT_WARN("wifi_offline reason=credentials_exhausted lora=active retry_ms=%lu",
            static_cast<unsigned long>(kRetryCycleMs));
        enter(State::RetryCycle, now);
        return;
    }
    APP_LOG_EVENT("wifi_join_started source=%s lora=active", label);
    (void)label;
    legacyJoin_ = false;
    sendJoin(now);
}

void GatewayWifiLink::sendJoin(uint32_t now)
{
    char command[224]; // Both credentials may need two AT bytes per character.
    const char* prefix = legacyJoin_ ? "AT+CWJAP=" : "AT+CWJAP_CUR=";
    strcpy(command, prefix);
    char* out = command + strlen(prefix);
    if (!appendCredential(out, ssid_, 32U)) {
        joinFailed("invalid_ssid", now, false);
        return;
    }
    *out++ = ',';
    if (!appendCredential(out, password_, 64U)) {
        joinFailed("invalid_password", now, false);
        return;
    }
    strcpy(out, "\r\n");
    joinErrorCode_ = false;
    input_.takeWifiDisconnect();
    send(command, State::Joining, now);
}

void GatewayWifiLink::joinFailed(const char* reason, uint32_t now, bool reset)
{
    APP_LOG_EVENT_WARN("wifi_join_failed reason=%s lora=active", reason);
    (void)reason;
    source_ = static_cast<Source>(static_cast<uint8_t>(source_) + 1U);
    if (++failures_ >= AppConfig::kNetworkRetriesPerStage) {
        failures_ = 0;
        reset = true;
    }
    enter(reset ? State::RetryReset : State::NextNetwork, now);
}

bool GatewayWifiLink::poll()
{
    if (state_ == State::Idle) return false;
    const uint32_t now = millis();
    const uint32_t elapsed = now - started_;
    input_.serviceUart();

    if (state_ == State::Online) {
        if (input_.takeWifiDisconnect()) {
            APP_LOG_EVENT_WARN("wifi_offline reason=disconnected lora=active");
            source_ = Source::Commissioned;
            enter(State::NextNetwork, now);
        }
        return connected();
    }

    if (input_.fault()) {
        input_.resetInput();
        if (state_ == State::Joining) {
            joinFailed("uart_fault", now, true);
            return false;
        }
        if (state_ != State::Reset && state_ != State::Boot && state_ != State::RetryReset) {
            enter(State::RetryReset, now);
            return false;
        }
    }
    const Reply reply = takeReply();
    switch (state_) {
    case State::Reset:
        if (elapsed >= AppConfig::kEspResetPulseMs) {
            driveReset(false);
            enter(State::Boot, now);
        }
        break;
    case State::Boot:
        if (elapsed >= AppConfig::kEspBootDelayMs) {
            input_.resetInput();
            send("ATE0\r\n", State::Echo, now);
        }
        break;
    case State::Echo:
    case State::Station:
    case State::Mux:
        if (reply == Reply::Ok) {
            if (state_ == State::Echo) send("AT+CWMODE_CUR=1\r\n", State::Station, now);
            else if (state_ == State::Station) send("AT+CIPMUX=1\r\n", State::Mux, now);
            else startCandidate(now);
        } else if (state_ == State::Station && reply == Reply::Error && !legacyMode_) {
            legacyMode_ = true;
            send("AT+CWMODE=1\r\n", State::Station, now);
        } else if (reply != Reply::Waiting || elapsed >= kAtTimeoutMs) {
            APP_LOG_EVENT_WARN("wifi_offline reason=modem_setup lora=active");
            enter(State::RetryReset, now);
        }
        break;
    case State::Joining:
        if (reply == Reply::Ok) {
            if (input_.takeWifiDisconnect()) joinFailed("disconnected", now, false);
            else {
                APP_LOG_EVENT("wifi_online lora=active");
                failures_ = 0;
                enter(State::Online, now);
            }
        } else if (reply == Reply::Error && !legacyJoin_ && !joinErrorCode_) {
            legacyJoin_ = true;
            sendJoin(now);
        } else if (reply != Reply::Waiting || elapsed >= kJoinTimeoutMs) {
            const bool timeout = reply == Reply::Waiting;
            joinFailed(timeout ? "timeout" : "rejected", now, timeout || reply == Reply::Busy);
        }
        break;
    case State::NextNetwork:
        if (elapsed >= kRetrySpacingMs) startCandidate(now);
        break;
    case State::RetryCycle:
        if (elapsed >= kRetryCycleMs) {
            source_ = Source::Commissioned;
            startCandidate(now);
        }
        break;
    case State::RetryReset:
        if (elapsed >= kRetrySpacingMs) assertReset(now);
        break;
    default:
        break;
    }
    return connected();
}
#endif
