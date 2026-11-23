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
LoraPayloadType nodeFrameType = LoraPayloadType::StatusTelemetry;
uint8_t nodePayload = 0;
uint8_t lastForwardedByte = 0;
unsigned decodeCalls = 0;
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
bool publishMqttPayload(const char* topic, const uint8_t* payload, size_t length) {
    assert(length == 1);
    lastForwardedByte = payload[0];
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
bool decodeEncryptedTelemetryPayload(const uint8_t* payload, size_t length, Telemetry& reply) {
    assert(length == 1);
    ++decodeCalls;
    switch (payload[0]) {
    case 1: return false; // Cannot inspect, but still forward the original frame.
    case 2: reply.node_id = 4; break;
    default: reply.node_id = 3; break;
    }
    if (payload[0] == 3 || payload[0] == 4) {
        reply.command_ack_request_id = 4294967294UL;
        reply.command_ack_cmd_id = 10;
        reply.command_ack_success = payload[0] == 3;
        reply.has_flash_log = true;
    }
    if (payload[0] == 5) {
        reply.has_history = true;
        reply.history.request_id = 42;
        reply.history.phase = 2;
        reply.history.index = 1;
        reply.history.total = 4;
    }
    return true;
}
void initializeLoraLink() {}
void serviceLoraInput() {}
bool isLoraReceiveTransactionActive() { return radioBusy; }
bool receiveLoraFrame(LoraFrame& frame) {
    if (!nodePending) return false;
    nodePending = false;
    frame.type = nodeFrameType;
    frame.payload[0] = nodePayload;
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
    const unsigned beforeData = decodeCalls;
    nodeFrameType = LoraPayloadType::SystemTelemetry;
    for (nodePayload = 0; nodePayload <= 5; ++nodePayload) {
        SerialMon.text.clear();
        nodePending = true;
        gatewayLoop();
        assert(topics.back() == "wiot/Company_1/Region_1/3/data");
        assert(lastForwardedByte == nodePayload);
#if APP_ENABLE_DEBUG
        const auto& log = SerialMon.text;
        const auto replyLine = log.find("reply_rx request=4294967294 command=FLASH_STATUS(10) source=3 result=");
        if (nodePayload == 3 || nodePayload == 4) {
            assert(replyLine != std::string::npos);
            assert(log.find(nodePayload == 3 ? "result=accepted" : "result=rejected", replyLine) != std::string::npos);
        } else {
            assert(log.find("reply_rx ") == std::string::npos);
        }
        assert((log.find("history_rx request=42 source=3 index=1 total=4 phase=2") != std::string::npos) ==
               (nodePayload == 5));
#else
        assert(SerialMon.text.empty());
#endif
    }
    assert(beforeData == 0); // STATUS frames never enter the diagnostic decoder.
    assert(decodeCalls == (APP_ENABLE_DEBUG ? 6U : 0U));
    std::cout << "PASS gateway reply correlation, DATA forwarding and debug gating\n";
    std::cout << "PASS gateway heartbeat without nodes, priorities, reconnect, retries, and tick wrap\n";
}
