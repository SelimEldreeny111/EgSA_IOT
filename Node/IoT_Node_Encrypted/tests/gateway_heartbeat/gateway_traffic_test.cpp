/** @file gateway_traffic_test.cpp @brief Simulated radio timing against the production gateway loop. */
#include "../../src/app/GatewayApp.h"
#include "../../src/comm/GatewayDelivery.h"
#include "../../src/radio/LoraLink.h"
#include <array>
#include <cassert>
#include <cstdio>
#include <cstring>
#include <deque>
#include <set>

uint32_t testTick = 0;
HardwareSerial SerialMon;
const char kMqttCompanyTopicPrefix[] = "wiot/Company_1/Region_1";
const pb_msgdesc_t Gateway_Status_msg = {};
namespace {
constexpr uint16_t kRoster[] = {APP_LORA_COORDINATED_NODES};
constexpr unsigned kNodes = sizeof(kRoster) / sizeof(kRoster[0]);
constexpr uint32_t kRuntimeMs = 600000;
struct SimNode {
    uint32_t nextStatus = 0, lastGrant = 0, maxGrantGap = 0;
    unsigned grants = 0, statuses = 0, forwarded = 0;
};
struct Exchange {
    uint32_t rxStart = 0, complete = 0, request = 0;
    uint16_t node = 0;
    LoraPayloadType type = LoraPayloadType::StatusTelemetry;
    bool active = false;
};
std::array<SimNode, kNodes + 1> nodes{};
Exchange air;
bool online = false;
unsigned offlineStatuses = 0;
std::deque<GatewayCommand> commands, socketArrivals;
unsigned receivedDuringExchange = 0;
std::deque<Gateway_Delivery> receipts;
std::set<uint32_t> commandsSent, repliesPersisted;
unsigned busyChecks = 0, silentGrants = 0, pendingDuringReport = 0;
unsigned repliesWhileOffline = 0, replayed = 0;

bool radioInFlight() { return air.active && testTick < air.complete; }
void queueCommand(uint32_t request, uint16_t target) {
    GatewayCommand cmd{};
    cmd.receivedMs = testTick;
    cmd.proof.node_id = target;
    cmd.proof.request_id = request;
    cmd.proof.wire_bytes = 1;
    socketArrivals.push_back(cmd);
    if (radioInFlight() && air.type == LoraPayloadType::StatusTelemetry) ++pendingDuringReport;
}
}

void serviceHardwareWatchdog() {}
void watchdogDelay(uint32_t) {}
void reportHardwareWatchdogStatus() {}
uint32_t hardwareWatchdogResetCount() { return 0; }
uint32_t powerResetCount() { return 0; }
void initializeMqttTransport() {}
bool connectNetwork() { assert(false); return false; }
void initializeMqttClient() {}
bool ensureMqttConnection() { return online; }
void mqttLoop() {}
void serviceGatewayMqttIntake() {
    if (socketArrivals.empty()) return;
    if (radioInFlight()) ++receivedDuringExchange;
    commands.push_back(socketArrivals.front());
    socketArrivals.pop_front();
}
bool mqttCommandWorkPending() { return !commands.empty(); }
bool isAsyncPublishBusy() { return false; }
uint32_t mqttConnectionGeneration() { return 1; }
const GatewayCommand* gatewayPendingCommand() {
    return commands.empty() ? nullptr : &commands.front();
}
void completeGatewayCommand(GatewayDeliveryPhase phase) {
    assert(phase == GatewayDispatched);
    commands.pop_front();
}
bool takeGatewayReceipt(Gateway_Delivery& proof) {
    if (receipts.empty()) return false;
    proof = receipts.front();
    receipts.pop_front();
    return true;
}
void serviceGatewayDeliveryEvents() {}
void reportGatewayReply(const Gateway_Delivery&) {}
bool encodeEncryptedMessage(const pb_msgdesc_t*, const void*, uint8_t*, size_t, size_t&) { return false; }
bool decodeEncryptedTelemetryPayload(const uint8_t* payload, size_t length, Telemetry& reply) {
    if (length != 5) return false;
    reply.node_id = payload[0];
    memcpy(&reply.command_ack_request_id, payload + 1, sizeof(uint32_t));
    reply.command_ack_cmd_id = 4;
    reply.command_ack_success = true;
    return true;
}
bool publishMqttPayload(const char* topic, const uint8_t* payload, size_t length) {
    assert(online);
    assert(!isLoraReceiveTransactionActive());
    if (strstr(topic, "/status") && length == 1) {
        ++nodes[payload[0]].forwarded;
        return true;
    }
    assert(length == 5 && strstr(topic, "/data"));
    Gateway_Delivery receipt = Gateway_Delivery_init_zero;
    receipt.node_id = payload[0];
    memcpy(&receipt.request_id, payload + 1, sizeof(uint32_t));
    receipt.wire_bytes = length;
    receipt.fingerprint = frameFingerprint(payload, length);
    receipt.phase = ServerPersisted;
    const bool first = repliesPersisted.insert(receipt.request_id).second;
    // Drop the first persistence receipt for selected requests.
    if (!first) ++replayed;
    if (!first || receipt.request_id % 5) receipts.push_back(receipt);
    return true;
}
void initializeLoraLink() {}
void serviceLoraInput() {}
bool isLoraReceiveTransactionActive() {
    const bool receiving = radioInFlight() && testTick >= air.rxStart;
    if (receiving) ++busyChecks;
    return receiving;
}
// The gateway cannot sense a node that has not begun UART delivery.
bool loraCanStartTransmission() { return !isLoraReceiveTransactionActive(); }
bool receiveLoraFrame(LoraFrame& frame) {
    if (!air.active || testTick < air.complete) return false;
    frame.type = air.type;
    frame.sourceNodeId = air.node;
    frame.payload[0] = static_cast<uint8_t>(air.node);
    frame.payloadLength = 1;
    if (frame.type == LoraPayloadType::SystemTelemetry) {
        memcpy(frame.payload + 1, &air.request, sizeof(air.request));
        frame.payloadLength += sizeof(air.request);
        if (!online) ++repliesWhileOffline;
    }
    if (!online && frame.type == LoraPayloadType::StatusTelemetry) ++offlineStatuses;
    air.active = false;
    return true;
}
bool sendLoraWakeCommand(LoraPayloadType type, const uint8_t* payload, size_t length) {
    // Detect a new grant or command while the previous simulated RF exchange is in flight.
    assert(!radioInFlight());
    if (type == LoraPayloadType::UplinkGrant) {
        assert(length == 2);
        const uint16_t target = (static_cast<uint16_t>(payload[0]) << 8) | payload[1];
        assert(target && target <= kNodes);
        auto& node = nodes[target];
        if (node.grants) {
            const uint32_t gap = testTick - node.lastGrant;
            assert(gap >= 30000U);
            if (gap > node.maxGrantGap) node.maxGrantGap = gap;
        }
        node.lastGrant = testTick;
        ++node.grants;
        // A silent grant owns its initial window but produces no frame.
        if (testTick < node.nextStatus || (target == kNodes && node.grants % 4U == 0)) {
            ++silentGrants;
            return true;
        }
        ++node.statuses;
        node.nextStatus = (testTick / 60000U + 1U) * 60000U;
        const uint32_t duration = target == 1 && node.grants == 1 ? 6500U : 1800U;
        air = {testTick + 350U, testTick + duration, 0, target, LoraPayloadType::StatusTelemetry, true};
        return true;
    }
    assert(type == LoraPayloadType::Command);
    const auto& command = commands.front();
    assert(commandsSent.insert(command.proof.request_id).second);
    air = {testTick + 400U, testTick + 2200U, command.proof.request_id,
        static_cast<uint16_t>(command.proof.node_id), LoraPayloadType::SystemTelemetry, true};
    return true;
}
void printLoraDiagnostics() {}
void printLoraFrameSummary(const LoraFrame&, const char*) {}

int main() {
    gatewaySetup(); // Wi-Fi offline at boot. The synchronous join must not be called.
    uint32_t request = 0;
    for (testTick = 0; testTick < kRuntimeMs + 15000U; testTick += 50U) {
        online = testTick >= 60000U && !(testTick >= 180000U && testTick < 192000U);
        if (testTick >= 60000U && testTick < kRuntimeMs && (testTick % 20000U == 1300U || testTick % 20000U == 1400U)) {
            ++request;
            queueCommand(request, static_cast<uint16_t>(1U + (request - 1U) % kNodes));
        }
        gatewayLoop();
    }
    assert(commands.empty());
    assert(commandsSent.size() == request && repliesPersisted == commandsSent);
    assert(busyChecks);
    assert(pendingDuringReport && receivedDuringExchange);
    assert(silentGrants);
    assert(replayed);
    assert(repliesWhileOffline && offlineStatuses);
    unsigned totalGrants = 0, completedStatuses = 0, publishedStatuses = 0;
    uint32_t maxGap = 0;
    for (unsigned i = 1; i <= kNodes; ++i) {
        const auto& node = nodes[i];
        assert(node.grants >= 2 && node.statuses > 0 && node.forwarded > 0);
        totalGrants += node.grants;
        completedStatuses += node.statuses;
        publishedStatuses += node.forwarded;
        if (node.maxGrantGap > maxGap) maxGap = node.maxGrantGap;
    }
    std::printf("PASS traffic nodes=%u commands=%lu status_rx=%u status_published=%u grants=%u max_grant_gap_ms=%lu queued_during_status=%u reply_retries=%u offline_replies=%u\n",
        kNodes, static_cast<unsigned long>(request), completedStatuses, publishedStatuses, totalGrants,
        static_cast<unsigned long>(maxGap), pendingDuringReport, replayed, repliesWhileOffline);
}
