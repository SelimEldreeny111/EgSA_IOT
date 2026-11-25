/** @file gateway_wifi_receive_test.cpp @brief Exercise the actual MQTT client on staged ESP-AT input. */
#include "../../src/comm/MQTT.h"
#include "../../src/comm/GatewayDelivery.h"
#include "../../src/comm/GatewayWifiLink.h"
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
const char kWifiSsid[] = "configured", kWifiPassword[] = "pw";
bool loadGatewaySavedWifiCredentials(GatewayWifiCredentials& credentials) {
    strcpy(credentials.ssid, "fallback");
    strcpy(credentials.password, "saved");
    return true;
}
void serviceHardwareWatchdog() {}
void serviceHardwareWatchdog(WatchdogStage) {}
void watchdogDelay(uint32_t ms) { delay(ms); }
[[noreturn]] void forceHardwareWatchdogReset(const char*) { assert(false); std::abort(); }
bool connectNetwork() { assert(false); return false; }
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
static void finishBrokerSubscriptions() {
    for (int i=0; i<3; ++i) mqttLoop();
    assert(ensureMqttConnection());
}

static void pollWifi(const char* expectedCommand = nullptr, uint32_t advance = 0) {
    SerialAT.rawTx.clear();
    testNow += advance;
    const uint32_t before = testNow;
    const int connects = gsmClient.connects;
    assert(!ensureMqttConnection());
    assert(testNow - before < 10U); // No synchronous modem delay.
    assert(gsmClient.connects == connects);
    assert(SerialAT.rawTx == (expectedCommand ? expectedCommand : ""));
}

static void bootWifi(uint32_t settleMs = 3000) {
    pollWifi(nullptr, 100);
    pollWifi("ATE0\r\n", settleMs);
    putText("OK\r\n"); pollWifi("AT+CWMODE_CUR=1\r\n");
    putText("OK\r\n"); pollWifi("AT+CIPMUX=1\r\n");
}

static void finishJoin() {
    putText("WIFI CONNECTED\r\nWIFI GOT IP\r\nOK\r\n");
    assert(!ensureMqttConnection());
    assert(gatewayWifiConnected());
    finishBrokerSubscriptions();
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

    const std::string shortRecord = "+IPD,0,12:ab";
    port.rawRx.insert(port.rawRx.end(), shortRecord.begin(), shortRecord.end());
    input.serviceUart();
    testNow += 1100;
    input.serviceUart();
    const auto ipd = input.ipdProgress();
    assert(std::string(input.fault()) == "esp_ipd_timeout");
    assert(ipd.announced == 12 && ipd.received == 2);
    input.resetSocket();
    assert(input.fault() == nullptr && input.ipdProgress().announced == 0);
}

static void exerciseUartBurst() {
    // One AT record can exceed the hardware RX ring while the radio owns
    // the foreground. MQTT sees a complete packet after the exchange.
    std::vector<uint8_t> burst{0x30, 0x98, 0x04, 0, 1, 'x'};
    burst.resize(539, 0xff);  // 536-byte MQTT body plus its 3-byte header.
    auto next = command();
    next[next.size() - 2U] = 43;
    burst.insert(burst.end(), next.begin(), next.end());
    putText(("+IPD,0," + std::to_string(burst.size()) + ":").c_str());
    size_t overruns = 0;
    for (size_t i = 0; i < burst.size(); ++i) {
        if (SerialAT.rawRx.size() < 511U) SerialAT.rawRx.push_back(burst[i]);
        else ++overruns;
        if ((i + 1U) % 11U == 0U) {
            ++testNow;
            serviceGatewayModemRxDuringRadio();
        }
    }
    testNow += 1300;
    serviceGatewayModemRxDuringRadio();
    assert(overruns == 0 && !gatewayPendingCommand());
    serviceGatewayMqttIntake(); // Ignore the unrelated topic.
    serviceGatewayMqttIntake(); // Queue the complete command after it.
    assert(gatewayPendingCommand() && gatewayPendingCommand()->proof.request_id == 43);
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
    const uint32_t before = testNow;
    initializeMqttTransport();
    initializeMqttClient();
    assert(testNow - before < 10U && !gatewayWifiConnected());
    bootWifi();
    putText("OK\r\n"); pollWifi("AT+CWJAP_CUR=\"configured\",\"pw\"\r\n");
    for (int i = 0; i < 28; ++i) pollWifi(nullptr, 1000);
    putText("+CWJAP:3\r\nFAIL\r\n"); pollWifi();
    pollWifi("AT+CWJAP_CUR=\"fallback\",\"saved\"\r\n", 5000);
    for (int i = 0; i < 29; ++i) pollWifi(nullptr, 1000);
    pollWifi(nullptr, 1000);  // A silent modem is reset separately.
    pollWifi(nullptr, 5000);
    bootWifi();
    putText("OK\r\n"); pollWifi(); // Wait out the retry cycle after both networks failed.
    pollWifi("AT+CWJAP_CUR=\"configured\",\"pw\"\r\n", 30000);
    finishJoin();
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
    // A radio exchange owns the foreground for longer than the IPD timeout.
    // The UART-only hook drains the arriving record without running callbacks.
    serviceGatewayModemRxDuringRadio();
    testNow += 1300;
    serviceGatewayModemRxDuringRadio();
    assert(!gatewayPendingCommand() && SerialAT.rawRx.empty());
    assert(gsmClient.writes == initialWrites && gsmClient.stops == initialStops);
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
    assert(mqtt.state()!=0);
    assert(gsmClient.writes == initialWrites+1 && gsmClient.stops == initialStops);
    assert(gatewayPendingCommand() && gatewayPendingCommand()->proof.request_id == 42);
    pollWifi();
    pollWifi(nullptr, 3000);
    bootWifi();
    putText("OK\r\n"); pollWifi("AT+CWJAP_CUR=\"configured\",\"pw\"\r\n");
    finishJoin();
    assert(mqttConnectionGeneration()==2 && gatewayPendingCommand());
    completeGatewayCommand(GatewayDispatched);
    // Use a fresh request ID after reconnect to check ingress behind a UART burst.
    exerciseUartBurst();
    putText("WIFI DISCONNECT\r\n");
    pollWifi();
    assert(!gatewayWifiConnected() && mqtt.state() != 0);
    pollWifi("AT+CWJAP_CUR=\"configured\",\"pw\"\r\n", 5000);
    assert(gatewayPendingCommand()->proof.request_id == 43);
    std::cout<<"PASS Wi-Fi offline startup, timeout, fallback, disconnect and MQTT/IPD recovery\n";
}
