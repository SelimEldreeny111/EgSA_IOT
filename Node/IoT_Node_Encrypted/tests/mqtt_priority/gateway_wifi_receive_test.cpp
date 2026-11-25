/** @file gateway_wifi_receive_test.cpp @brief Exercise the actual MQTT client on staged ESP-AT input. */
#include "../../src/comm/MQTT.h"
#include "../../src/comm/GatewayDelivery.h"
#include "../../src/comm/GatewayEspAtStream.h"
#include "../../src/comm/CachedTinyGsmClient.h"
#include <cassert>
#include <iostream>

uint32_t testNow = 5000;
bool tickOnMillis = true;
HardwareSerial SerialMon, SerialAT;
extern CachedTinyGsmClient gsmClient;
extern PubSubClient mqtt;
const char kMqttServer[]="test",kMqttClientId[]="test-client";
const char kMqttCommandTopic[]="wiot/Test/Region_1/1/cmd",kMqttBroadcastTopic[]="wiot/Test/Region_1/broadcast";
const char kMqttPublishTopicStatus[]="wiot/Test/Region_1/1/status",kMqttPublishTopicTlm[]="wiot/Test/Region_1/1/data";
const char kMqttCompanyTopicPrefix[]="wiot/Test/Region_1";
const char kMqttGatewayCommandWildcardTopic[]="wiot/Test/Region_1/+/cmd";
const pb_msgdesc_t Gateway_Delivery_msg = {};
int networkJoins = 0;
void serviceHardwareWatchdog() {}
void serviceHardwareWatchdog(WatchdogStage) {}
void watchdogDelay(uint32_t ms) { delay(ms); }
[[noreturn]] void forceHardwareWatchdogReset(const char*) { assert(false); std::abort(); }
bool connectNetwork() { ++networkJoins; return true; }
bool decodeEncryptedCommandPayload(const uint8_t* bytes, size_t length, CMD_Message& cmd) {
    if (length != 4 || bytes[3] != 0xff) return false;
    cmd.node_id = bytes[0]; cmd.cmd_id = bytes[1]; cmd.request_id = bytes[2]; return true;
}
bool decodeEncryptedGatewayDelivery(const uint8_t*, size_t, Gateway_Delivery&) { return false; }
bool encodeEncryptedMessage(const pb_msgdesc_t*,const void*,uint8_t*,size_t,size_t&) { return false; }
bool buildEncryptedStatusPayload(uint8_t*,size_t,size_t&) { return false; }

static void putText(const char* text) {
    while (*text) SerialAT.rawRx.push_back(static_cast<uint8_t>(*text++));
}
static void putIpd(const std::vector<uint8_t>& bytes) {
    putText(("+IPD,0," + std::to_string(bytes.size()) + ":").c_str());
    SerialAT.rawRx.insert(SerialAT.rawRx.end(), bytes.begin(), bytes.end());
}
static std::vector<uint8_t> command() {
    const std::string topic = kMqttCommandTopic;
    std::vector<uint8_t> data = {0x32, uint8_t(topic.size()+8), 0, uint8_t(topic.size())};
    data.insert(data.end(), topic.begin(), topic.end());
    data.insert(data.end(), {0, 51, 1, 4, 42, 0xff});
    return data;
}
static void connectBroker() {
    assert(!ensureMqttConnection());
    for (int i=0; i<3; ++i) mqttLoop();
    assert(ensureMqttConnection());
}

static void exerciseEspInput() {
    HardwareSerial port;
    GatewayEspAtStream input(port);
    auto& socket = input.socketInput();
    const std::string header = "AT text +IPX\r\n+IPD,0,8:";
    port.rawRx.insert(port.rawRx.end(), header.begin(), header.end());
    assert(socket.available() == 0 && input.fault() == nullptr);
    // Bytes may already be buffered after the STM32 spent time in a radio exchange.
    testNow += 1100;
    const std::vector<uint8_t> binary{0x00, 0xff, '+', 'I', 'P', 'D', ',', ':'};
    port.rawRx.insert(port.rawRx.end(), binary.begin(), binary.end());
    const std::string suffix = "\r\nSEND OK\r\n";
    port.rawRx.insert(port.rawRx.end(), suffix.begin(), suffix.end());
    assert(socket.available() == static_cast<int>(binary.size()));
    for (const auto byte : binary) assert(socket.read() == byte);
    std::string modemText;
    while (input.available()) modemText += static_cast<char>(input.read());
    assert(modemText == "AT text +IPX\r\n" + suffix && input.fault() == nullptr);
}

int main() {
    exerciseEspInput();
    gsmClient.live = false;
    gsmClient.onSend = [](const std::vector<uint8_t>& bytes) {
        if (bytes[0] == 0x10) putIpd({0x20,0x02,0x00,0x00});
        if (bytes[0] == 0x82) {
            assert(bytes.back() == 1);
            putText("\r\nOK\r\n");
            putIpd({0x90,3,bytes[2],bytes[3],1});
        }
    };
    initializeMqttClient(); connectBroker();
    const auto bytes = command();
    const int initialWrites = gsmClient.writes, initialStops = gsmClient.stops;

    // Split the ESP-AT prefix, then split an MQTT packet across two IPD indications.
    putText("+IP"); serviceGatewayMqttIntake();
    assert(!gatewayPendingCommand() && gsmClient.writes == initialWrites);
    const size_t split = bytes.size()-3;
    putText(("D,0,"+std::to_string(split)+":").c_str());
    SerialAT.rawRx.insert(SerialAT.rawRx.end(), bytes.begin(), bytes.begin()+split);
    serviceGatewayMqttIntake();
    assert(!gatewayPendingCommand() && gsmClient.writes == initialWrites);
    putIpd({bytes[split], bytes[split+1], bytes[split+2]});
    serviceGatewayMqttIntake();
    assert(gatewayPendingCommand() && gatewayPendingCommand()->proof.request_id == 42);
    assert(gsmClient.writes == initialWrites && gsmClient.stops == initialStops);
    mqttLoop();
    assert(gsmClient.writes == initialWrites+1);
    assert((gsmClient.sent.back() == std::vector<uint8_t>{0x40,2,0,51}));

    // A truncated modem record previously stalled inside TinyGSM. Recover only
    // when the quiet foreground loop services the modem.
    putText("+IPD,0,12:");
    SerialAT.rawRx.push_back(0x30);
    serviceGatewayMqttIntake();
    testNow+=1100;
    serviceGatewayMqttIntake();
    assert(mqtt.state()!=0 && networkJoins==0);
    assert(gsmClient.writes == initialWrites+1 && gsmClient.stops == initialStops);
    assert(gatewayPendingCommand() && gatewayPendingCommand()->proof.request_id == 42);
    assert(!ensureMqttConnection() && networkJoins==0);
    testNow+=3000;
    assert(!ensureMqttConnection() && networkJoins==1);
    testNow+=3000;
    connectBroker();
    assert(mqttConnectionGeneration()==2 && gatewayPendingCommand());
    std::cout<<"PASS gateway ESP-AT fragmented command, deferred PUBACK and local fault recovery\n";
}
