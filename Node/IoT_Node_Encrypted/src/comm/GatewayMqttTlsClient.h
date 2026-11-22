/** @file GatewayMqttTlsClient.h @brief Verified native TLS socket for the LoRa gateway. */
#ifndef WIOT_GATEWAY_MQTT_TLS_CLIENT_H
#define WIOT_GATEWAY_MQTT_TLS_CLIENT_H

#include "../platform/DebugLog.h"
#include <TinyGsmClient.h>

class GatewayMqttTlsClient : public TinyGsmClientSecure
{
public:
    explicit GatewayMqttTlsClient(TinyGsm& modem) : TinyGsmClientSecure(modem), modem_(modem) {}

    int connect(const char* host, uint16_t port) override
    {
        if (!isBrokerName(host) || !port)
        {
            APP_LOG_ERROR("Gateway MQTT/TLS requires a valid broker hostname and port");
            return 0;
        }
        if (!configureTrust(host))
        {
            APP_LOG_ERROR("Gateway MQTT/TLS trust setup failed");
            return 0;
        }
        return TinyGsmClientSecure::connect(host, port, 12);
    }

    int connect(IPAddress, uint16_t) override { return 0; }
    // Use the driver's bounded close so it shares the existing 30 s watchdog budget.
    void stop() override { TinyGsmClientSecure::stop(2000UL); }
    uint8_t connected() override { return sock_connected; }
    operator bool() override { return connected() != 0U; }

private:
    static bool isBrokerName(const char* host)
    {
        if (!host || !*host) return false;
        // The hostname is sent as a quoted AT parameter. The commissioning
        // settings and ESP-AT hostname fields allow up to 63 characters.
        size_t length = 0;
        bool hasLetter = false;
        for (const char* p = host; *p; ++p)
        {
            const bool letter = (*p >= 'a' && *p <= 'z') || (*p >= 'A' && *p <= 'Z');
            hasLetter |= letter;
            if (++length > 63 || !(letter || (*p >= '0' && *p <= '9') || *p == '-' || *p == '.'))
                return false;
        }
        return hasLetter;
    }

    bool configureTrust(const char* host)
    {
#if defined(USE_SIM800) || APP_MQTT_TLS_ESP_LEGACY
        (void)host;
        if (!APP_MQTT_TLS_DEDICATED_CA_PROVISIONED)
        {
            APP_LOG_ERROR("Gateway MQTT/TLS requires the provisioned broker-only CA");
            return false;
        }
#endif
#if defined(USE_SIM800)
        // SIMCom option 0 controls ignoring invalid server certificates.
        modem_.sendAT("+SSLOPT=0,0");
        return modem_.waitResponse(1000UL) == 1;
#elif APP_MQTT_TLS_ESP_LEGACY
        modem_.sendAT("+CIPSSLCCONF=2");
        return modem_.waitResponse(1000UL) == 1;
#else
        // TinyGSM uses CIPMUX=1 and socket 0. CA slot 0 is provisioned separately.
        modem_.sendAT("+CIPSSLCCONF=0,2,0,0");
        if (modem_.waitResponse(1000UL) != 1) return false;
        modem_.sendAT("+CIPSSLCCN=0,\"", host, "\"");
        if (modem_.waitResponse(1000UL) != 1) return false;
        modem_.sendAT("+CIPSSLCSNI=0,\"", host, "\"");
        return modem_.waitResponse(1000UL) == 1;
#endif
    }

    TinyGsm& modem_;
};
#endif
