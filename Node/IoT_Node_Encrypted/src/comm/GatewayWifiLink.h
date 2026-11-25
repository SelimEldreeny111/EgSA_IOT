/** @file GatewayWifiLink.h @brief Cooperative ESP8266 association for the LoRa gateway. */
#ifndef WIOT_GATEWAY_WIFI_LINK_H
#define WIOT_GATEWAY_WIFI_LINK_H

#include "GatewayEspAtStream.h"

struct GatewayWifiCredentials {
    char ssid[33];
    char password[65];
};

/** @brief Read the existing checksummed Wi-Fi fallback from STM32 flash. */
bool loadGatewaySavedWifiCredentials(GatewayWifiCredentials& credentials);

/** @brief Own the ESP-AT command stream until association succeeds. */
class GatewayWifiLink {
public:
    GatewayWifiLink(HardwareSerial& serial, GatewayEspAtStream& input)
        : serial_(serial), input_(input) {}
    /** @brief Start a hardware reset and return immediately. */
    void begin();
    /** @brief Advance one slice of association work. True once the AP is joined. */
    bool poll();
    bool connected() const { return state_ == State::Online; }

private:
    enum class State : uint8_t { Idle, Reset, Boot, Echo, Station, Mux, Joining,
                                 NextNetwork, RetryCycle, RetryReset, Online };
    enum class Source : uint8_t { Commissioned, Firmware, Saved, Exhausted };
    enum class Reply : uint8_t { Waiting, Ok, Error, Fail, Busy };

    void enter(State state, uint32_t now);
    void assertReset(uint32_t now);
    void send(const char* command, State state, uint32_t now);
    Reply takeReply();
    void startCandidate(uint32_t now);
    void sendJoin(uint32_t now);
    void joinFailed(const char* reason, uint32_t now, bool reset);
    static void driveReset(bool asserted);

    HardwareSerial& serial_;
    GatewayEspAtStream& input_;
    State state_ = State::Idle;
    Source source_ = Source::Commissioned;
    uint32_t started_ = 0;
    uint8_t failures_ = 0;
    bool legacyMode_ = false;
    bool legacyJoin_ = false;
    bool joinErrorCode_ = false;
    char line_[32] = {};
    size_t lineLength_ = 0;
    const char* ssid_ = nullptr;
    const char* password_ = nullptr;
    GatewayWifiCredentials saved_{};
};

#endif
