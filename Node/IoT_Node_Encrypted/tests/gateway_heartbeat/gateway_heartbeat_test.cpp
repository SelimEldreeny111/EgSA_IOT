#include "../../src/app/GatewayApp.h"
#include "../../src/radio/LoraLink.h"
#include <cassert>
#include <iostream>
#include <string>
#include <vector>

uint32_t testTick = 1000;
HardwareSerial SerialMon;
const char kMqttCompanyTopicPrefix[] = "wiot/Company_1/Region_1";
const pb_msgdesc_t Gateway_Status_msg = {};
bool connected = true, radioBusy = false, commandBusy = false, publishBusy = false, sendOk = true;
bool nodePending = false;
uint32_t connection = 1;
std::vector<Gateway_Status> snapshots;
std::vector<std::string> topics;
void serviceHardwareWatchdog() {}
void watchdogDelay(uint32_t) {}
void reportHardwareWatchdogStatus() {}
uint32_t hardwareWatchdogResetCount() { return 2; }
uint32_t powerResetCount() { return 5; }
void initializeMqttTransport() {}
bool connectNetwork() { return connected; }
void initializeMqttClient() {}
bool ensureMqttConnection() { return connected; }
void mqttLoop() {}
void asyncPublishStep() {}
bool mqttCommandWorkPending() { return commandBusy; }
bool isAsyncPublishBusy() { return publishBusy; }
uint32_t mqttConnectionGeneration() { return connection; }
bool publishMqttPayload(const char* topic, const uint8_t*, size_t) {
    topics.emplace_back(topic);
    return sendOk;
}
bool encodeEncryptedMessage(const pb_msgdesc_t* fields, const void* data, uint8_t* out, size_t, size_t& size) {
    assert(fields == Gateway_Status_fields);
    snapshots.push_back(*static_cast<const Gateway_Status*>(data));
    out[0] = 1;
    size = 1;
    return true;
}
void initializeLoraLink() {}
void serviceLoraInput() {}
bool isLoraReceiveTransactionActive() { return radioBusy; }
bool receiveLoraFrame(LoraFrame& frame) {
    if (!nodePending) return false;
    nodePending = false;
    frame.type = LoraPayloadType::StatusTelemetry;
    frame.sourceNodeId = 3;
    frame.payloadLength = 1;
    return true;
}
void printLoraDiagnostics() {}
void printLoraFrameSummary(const LoraFrame&, const char*) {}

int main() {
    gatewayLoop();
#if APP_ENABLE_GATEWAY_HEARTBEAT
    assert(snapshots.size() == 1 && !snapshots.back().has_node_uplink);
    assert(snapshots.back().received_node_frames == 0 && snapshots.back().gateway_id == 7);
    assert(snapshots.back().wdt_reset_count == 2 && snapshots.back().power_reset_count == 5);
    assert(topics.back() == "wiot/Company_1/Region_1/gateway/7/status");
    testTick += 59999;
    gatewayLoop();
    assert(snapshots.size() == 1);
    ++testTick;
    radioBusy = true;
    gatewayLoop();
    assert(snapshots.size() == 1);
    radioBusy = false;
    commandBusy = true;
    gatewayLoop();
    assert(snapshots.size() == 1);
    commandBusy = false;
    publishBusy = true;
    gatewayLoop();
    assert(snapshots.size() == 1);
    publishBusy = false;
    gatewayLoop();
    assert(snapshots.size() == 2);
    testTick += 5000;
    ++connection;
    gatewayLoop();
    assert(snapshots.size() == 3); // Reconnect does not wait a full interval.
    testTick += 60000;
    sendOk = false;
    gatewayLoop();
    assert(snapshots.size() == 4);
    testTick += 4999;
    gatewayLoop();
    assert(snapshots.size() == 4);
    ++testTick;
    sendOk = true;
    gatewayLoop();
    assert(snapshots.size() == 5);
    nodePending = true;
    gatewayLoop();
    testTick += 60000;
    gatewayLoop();
    assert(snapshots.back().received_node_frames == 1 && snapshots.back().forwarded_node_frames == 1);
    assert(snapshots.back().has_node_uplink && snapshots.back().last_node_age_seconds == 60);
    nodePending = true;
    sendOk = false;
    gatewayLoop();
    sendOk = true;
    testTick += 60000;
    gatewayLoop();
    assert(snapshots.back().received_node_frames == 2 && snapshots.back().forwarded_node_frames == 1);
    assert(snapshots.back().forward_failures == 1);
    testTick = 0xFFFFFF00U;
    gatewayLoop();
    const uint64_t beforeWrap = snapshots.back().uptime_seconds;
    testTick += 60000;
    gatewayLoop();
    assert(snapshots.back().uptime_seconds > beforeWrap);
#else
    testTick += 120000;
    gatewayLoop();
    assert(snapshots.empty() && topics.empty());
#endif
    std::cout << "PASS gateway heartbeat without nodes, priorities, reconnect, retries, and tick wrap\n";
}
