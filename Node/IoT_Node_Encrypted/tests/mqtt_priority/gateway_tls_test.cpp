#include "../../src/comm/GatewayMqttTlsClient.h"
#include <cassert>
#include <iostream>

uint32_t testNow = 0;
bool tickOnMillis = true;
HardwareSerial SerialMon;

int main()
{
    HardwareSerial serial;
    TinyGsm modem(serial);
    GatewayMqttTlsClient client(modem);
    assert(client.connect("bad\"host", 8883) == 0);
    assert(client.connect("192.0.2.1", 8883) == 0);
    assert(client.connect(IPAddress(), 8883) == 0);
    assert(modem.atCommands.empty() && modem.secureConnectCalls == 0);

#if defined(USE_SIM800)
    const std::vector<std::string> expected{"+SSLOPT=0,0"};
#elif APP_MQTT_TLS_ESP_LEGACY
    const std::vector<std::string> expected{"+CIPSSLCCONF=2"};
#else
    const std::vector<std::string> expected{"+CIPSSLCCONF=0,2,0,0",
        "+CIPSSLCCN=0,\"broker.test\"", "+CIPSSLCSNI=0,\"broker.test\""};
#endif

#if (defined(USE_SIM800) || APP_MQTT_TLS_ESP_LEGACY) && !APP_MQTT_TLS_DEDICATED_CA_PROVISIONED
    assert(client.connect("broker.test", 8883) == 0);
    assert(modem.atCommands.empty() && modem.secureConnectCalls == 0);
#else
    for (int failedStep = 1; failedStep <= static_cast<int>(expected.size()); ++failedStep) {
        modem.atFailure = failedStep;
        modem.atCommands.clear();
        assert(client.connect("broker.test", 8883) == 0);
        assert(modem.secureConnectCalls == 0);
        assert(modem.atCommands == std::vector<std::string>(expected.begin(), expected.begin() + failedStep));
    }

    modem.atFailure = -1;
    modem.atCommands.clear();
    modem.secureConnectSuccess = false;
    assert(client.connect("broker.test", 8883) == 0);
    assert(modem.atCommands == expected);
    assert(modem.secureConnectCalls == 1 && !client.connected());
    modem.secureConnectSuccess = true;
    modem.atCommands.clear();
    assert(client.connect("broker.test", 8883) == 1);
    assert(modem.atCommands == expected);
    assert(modem.secureConnectCalls == 2 && client.connected());
    assert(modem.secureHost == "broker.test" && modem.securePort == 8883 && modem.secureTimeout == 12);
    client.stop();
    assert(!client.connected());
#endif
    std::cout << "PASS gateway MQTT TLS trust configuration and failure handling\n";
}
