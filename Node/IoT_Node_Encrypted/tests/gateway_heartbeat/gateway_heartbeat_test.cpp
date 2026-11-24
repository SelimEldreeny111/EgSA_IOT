#include "../../src/app/GatewayApp.h"
#include "../../src/comm/ReplyDiagnostics.h"
#include "../../src/comm/GatewayDelivery.h"
#include "../../src/radio/LoraLink.h"
#include <algorithm>
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
Gateway_Delivery receipt{};
unsigned radioSends = 0;
std::vector<uint16_t> grants;
GatewayCommand command{};
bool commandPending = false;
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
const GatewayCommand* gatewayPendingCommand() { return commandPending ? &command : nullptr; }
void completeGatewayCommand(GatewayDeliveryPhase) { commandPending = false; }
bool takeGatewayReceipt(Gateway_Delivery& proof) {
    if (!receipt.request_id) return false;
    proof = receipt;
    receipt.request_id = 0;
    return true;
}
void serviceGatewayDeliveryEvents() {}
void reportGatewayReply(const Gateway_Delivery&) {}
bool loraCanStartTransmission() { return !radioBusy; }
bool sendLoraWakeCommand(LoraPayloadType type, const uint8_t* data, size_t size) {
    ++radioSends;
    if (type == LoraPayloadType::UplinkGrant) {
        assert(size == 2);
        grants.push_back(uint16_t((data[0] << 8) | data[1]));
    }
    return true;
}
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
        reply.flash_log.record_count = 17;
        reply.battery_voltage = 3.5f;
        reply.flow_rate = 12.5f;
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
#if APP_LORA_COORDINATED
    testTick = 2000;
    gatewayLoop();
    assert((grants == std::vector<uint16_t>{1}));
    command.proof.node_id = 3; command.proof.request_id = 60; command.receivedMs = testTick;
    commandPending = true;
    gatewayLoop();
    assert(commandPending && radioSends == 1); // Node 1 owns the channel.
    testTick += 5000;
    gatewayLoop();
    assert(!commandPending && radioSends == 2); // Command wins at the window boundary.
    testTick += 5000;
    gatewayLoop();
    assert((grants == std::vector<uint16_t>{1,2}));
    testTick += 5000;
    gatewayLoop();
    assert((grants == std::vector<uint16_t>{1,2,3}));
    testTick += 5000;
    gatewayLoop();
    assert(grants.size() == 3); // Per-node pacing keeps WOR from continuous wake probes.
    std::cout << "PASS coordinated gateway grants, command priority and per-node pacing\n";
    return 0;
#endif
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
    gatewayLoop(); // Status resends before the heartbeat reports its new counters.
    assert(snapshots.back().received_node_frames == 2 && snapshots.back().forwarded_node_frames == 2);
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
        testTick += 3000;
        SerialMon.text.clear();
        nodePending = true;
        gatewayLoop();
        if (nodePayload != 1 && nodePayload != 2) {
            assert(topics.back() == "wiot/Company_1/Region_1/3/data");
            assert(lastForwardedByte == nodePayload);
            if (nodePayload >= 3) {
                receipt.request_id = nodePayload == 5 ? 42 : 4294967294UL;
                receipt.node_id = 3;
                receipt.wire_bytes = 1;
                receipt.fingerprint = frameFingerprint(&nodePayload, 1);
            }
        }
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
#if APP_DEBUG_FULL_ENABLED
        if (nodePayload >= 3) {
            assert(log.find("reply_data dir=RX") != std::string::npos);
            if (nodePayload < 5) {
                assert(log.find("records=17") != std::string::npos);
                assert(log.find("flow rate=12.500") != std::string::npos);
            }
            const std::string received = log.substr(log.rfind("[tick_ms=", log.find("[INFO][REPLY]")));
            Telemetry emitted = Telemetry_init_zero;
            assert(decodeEncryptedTelemetryPayload(&nodePayload, 1, emitted));
            --decodeCalls; // Only count invocations made by the production gateway.
            SerialMon.text.clear();
            logReplyData("TX", emitted, &nodePayload, 1);
            std::string sent = SerialMon.text;
            for (auto offset = sent.find("dir=TX"); offset != std::string::npos;
                 offset = sent.find("dir=TX", offset + 6)) {
                sent.replace(offset, 6, "dir=RX");
            }
            // Reply diagnostic lines end before the gateway's separate MQTT uplink log.
            const auto uplink = received.find("[INFO][GATEWAY] uplink_");
            const auto end = uplink == std::string::npos ? received.size() : received.rfind("[tick_ms=", uplink);
            assert(sent == received.substr(0, end));
            assert(sent.find(" 0000: 0" + std::to_string(nodePayload)) != std::string::npos);
        } else {
            assert(log.find("reply_data ") == std::string::npos);
        }
#else
        assert(log.find("reply_data ") == std::string::npos);
#endif
#else
        assert(SerialMon.text.empty());
#endif
    }
    assert(beforeData == 0); // STATUS frames never enter the diagnostic decoder.
    assert(decodeCalls == 6U);
    // Radio receipt should outlive an MQTT disconnect. Wrong receipts must
    // leave the exact payload queued, and a correct receipt stops retries.
    auto dataPublishes = [] {
        return std::count(topics.begin(), topics.end(), "wiot/Company_1/Region_1/3/data");
    };
    gatewayLoop(); // Consume the prior successful History receipt.
    const auto beforeOffline = dataPublishes();
    connected = false;
    nodePayload = 3; nodePending = true;
    gatewayLoop();
    assert(dataPublishes() == beforeOffline);
    connected = true;
    gatewayLoop();
    assert(dataPublishes() == beforeOffline + 1 && lastForwardedByte == 3);
    testTick += 3000;
    receipt.node_id = 3; receipt.request_id = 4294967294UL; receipt.wire_bytes = 1;
    receipt.fingerprint = frameFingerprint(&nodePayload, 1) + 1U;
    gatewayLoop();
    assert(dataPublishes() == beforeOffline + 2 && lastForwardedByte == 3);
    testTick += 3000;
    receipt.request_id = 4294967294UL;
    receipt.fingerprint = frameFingerprint(&nodePayload, 1);
    gatewayLoop();
    assert(dataPublishes() == beforeOffline + 2);
    // Radio cannot dispatch a command during a partial LoRa receive transaction.
    command.proof.node_id = 3; command.proof.request_id = 60; command.receivedMs = testTick;
    commandPending = true;
    radioBusy = true;
    gatewayLoop();
    assert(commandPending && !radioSends);
    radioBusy = false;
    gatewayLoop();
    assert(!commandPending && radioSends == 1);
    std::cout << "PASS gateway reply correlation, DATA forwarding and debug gating\n";
    std::cout << "PASS gateway heartbeat without nodes, priorities, reconnect, retries, and tick wrap\n";
}
