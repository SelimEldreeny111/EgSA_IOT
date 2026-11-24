/** @file GatewayApp.cpp @brief LoRa gateway startup, receive routing, and forwarding. */
#define APP_LOG_MODULE "GATEWAY"
#include "../platform/DebugLog.h"
#include "GatewayApp.h"

#include "../comm/MQTT.h"
#include "../comm/GatewayDelivery.h"
#include "../comm/PacketCodec.h"
#include "../comm/ReplyDiagnostics.h"
#include "../config/AppConfig.h"
#include "../config/RuntimeConfig.h"
#include "../platform/Watchdog.h"
#include "../radio/LoraLink.h"

#include <Arduino.h>
#include <stdio.h>

#if APP_ROLE == APP_ROLE_LORA_GATEWAY

extern HardwareSerial SerialMon;

namespace
{
uint64_t g_uptimeMs = 0;
uint64_t g_lastNodeUptimeMs = 0;
uint32_t g_previousTickMs = 0;
uint32_t g_receivedNodeFrames = 0;
uint32_t g_forwardedNodeFrames = 0;
uint32_t g_forwardFailures = 0;
bool g_hasNodeUplink = false;

constexpr uint32_t kUplinkLifetimeMs = 300000U;
constexpr uint32_t kCommandQueueLifetimeMs = 60000U;
constexpr uint32_t kStartWindowMs = 5000U;

struct Uplink {
  LoraFrame frame;
  uint32_t request, queuedAt, attemptedAt;
  uint64_t fingerprint;
  bool used, attempted;
};
Uplink g_replies[8] = {};
Uplink g_statuses[8] = {};
uint32_t g_windowStart = 0;
uint16_t g_radioOwner = 0;
uint32_t g_radioRequest = 0;
Gateway_Delivery g_radioProof = Gateway_Delivery_init_zero;
#if APP_LORA_COORDINATED
constexpr uint16_t kRoster[] = {APP_LORA_COORDINATED_NODES};
constexpr size_t kRosterSize = sizeof(kRoster) / sizeof(kRoster[0]);
static_assert(kRosterSize > 0 && kRosterSize <= 32, "Specify 1 to 32 coordinated LoRa node IDs");
size_t g_rosterNext = 0;
uint32_t g_lastGrant = 0;
unsigned g_commandsSinceGrant = 0;
uint32_t g_lastNodeGrant[kRosterSize] = {};
bool g_nodeWasGranted[kRosterSize] = {};
#endif

/** @brief Log the application reply that the gateway has already decoded. */
void logNodeReply(const LoraFrame& frame, const Telemetry& reply)
{
  (void)frame;
  if (reply.command_ack_request_id != 0U)
  {
    APP_LOG_EVENT("reply_rx request=%lu command=%s(%lu) source=%u result=%s bytes=%lu transport=LoRa flash=%u history=%u",
        static_cast<unsigned long>(reply.command_ack_request_id),
        WiotDebug::commandName(reply.command_ack_cmd_id),
        static_cast<unsigned long>(reply.command_ack_cmd_id), static_cast<unsigned>(frame.sourceNodeId),
        reply.command_ack_success ? "accepted" : "rejected",
        static_cast<unsigned long>(frame.payloadLength), static_cast<unsigned>(reply.has_flash_log),
        static_cast<unsigned>(reply.has_history));
  }
  else if (reply.has_history && reply.history.request_id != 0U)
  {
    APP_LOG_EVENT("history_rx request=%lu source=%u index=%lu total=%lu phase=%lu result=%lu bytes=%lu transport=LoRa",
        static_cast<unsigned long>(reply.history.request_id), static_cast<unsigned>(frame.sourceNodeId),
        static_cast<unsigned long>(reply.history.index), static_cast<unsigned long>(reply.history.total),
        static_cast<unsigned long>(reply.history.phase), static_cast<unsigned long>(reply.history.result),
        static_cast<unsigned long>(frame.payloadLength));
  }
  APP_DEBUG_ONLY(logReplyData("RX", reply, frame.payload, frame.payloadLength));
}

/** @brief Send the newest gateway health snapshot between radio transactions.
 * Uses uptime and server receive time, so no gateway RTC commissioning is required.
 * A failed send is retried after five seconds. Connection recovery sends a fresh
 * heartbeat immediately. Heartbeats are QoS 0 and are never retained or queued.
 */
void serviceGatewayHeartbeat()
{
#if APP_ENABLE_SERIAL_CONFIG || APP_ENABLE_GATEWAY_HEARTBEAT
  if (!WIOT_ACTIVE_VALUE(APP_ENABLE_GATEWAY_HEARTBEAT, gatewayHeartbeat)) return;
  static uint32_t lastAttemptMs = 0;
  static uint32_t lastSuccessMs = 0;
  static uint32_t publishedConnection = 0;
  static uint32_t sequence = 0;
  static bool attempted = false;
  static bool published = false;
  const uint32_t now = millis();
  const uint32_t connection = mqttConnectionGeneration();
  if ((attempted && now - lastAttemptMs < 5000UL) ||
      (published && connection == publishedConnection &&
       now - lastSuccessMs < WIOT_ACTIVE_VALUE(APP_GATEWAY_HEARTBEAT_SECONDS, heartbeatSeconds) * 1000UL)) return;
  attempted = true;
  lastAttemptMs = now;

  char topic[160];
  const int written = snprintf(topic, sizeof(topic), "%s/gateway/%u/status",
      WIOT_ACTIVE_TOPIC(kMqttCompanyTopicPrefix, prefix), static_cast<unsigned>(WIOT_ACTIVE_VALUE(APP_GATEWAY_ID, gatewayId)));
  if (written <= 0 || static_cast<size_t>(written) >= sizeof(topic))
  {
    APP_LOG_ERROR("Heartbeat topic is too long");
    return;
  }
  Gateway_Status status = Gateway_Status_init_zero;
  status.gateway_id = WIOT_ACTIVE_VALUE(APP_GATEWAY_ID, gatewayId);
  status.uptime_seconds = g_uptimeMs / 1000U;
  status.heartbeat_sequence = ++sequence;
  status.heartbeat_interval_seconds = WIOT_ACTIVE_VALUE(APP_GATEWAY_HEARTBEAT_SECONDS, heartbeatSeconds);
#if defined(USE_SIM800)
  status.uplink_transport = 2;
#else
  status.uplink_transport = 1;
#endif
  status.received_node_frames = g_receivedNodeFrames;
  status.forwarded_node_frames = g_forwardedNodeFrames;
  status.forward_failures = g_forwardFailures;
  status.has_node_uplink = g_hasNodeUplink;
  status.last_node_age_seconds = g_hasNodeUplink ? (g_uptimeMs - g_lastNodeUptimeMs) / 1000U : 0;
  status.wdt_reset_count = hardwareWatchdogResetCount();
  status.power_reset_count = powerResetCount();
  status.lora_aux_high = digitalRead(AppConfig::kLoraAuxPin) == HIGH;
  uint8_t payload[AppConfig::kCodecBufferSize];
  size_t length = 0;
  const bool accepted = encodeEncryptedMessage(Gateway_Status_fields, &status,
      payload, sizeof(payload), length) && publishMqttPayload(topic, payload, length);
  if (accepted)
  {
    published = true;
    publishedConnection = connection;
    lastSuccessMs = millis();
  }
  APP_LOG_EVENT("heartbeat gateway=%u sequence=%lu uptime_s=%s bytes=%lu local_write=%u",
      WIOT_ACTIVE_VALUE(APP_GATEWAY_ID, gatewayId), static_cast<unsigned long>(sequence),
      WiotDebug::Decimal64(status.uptime_seconds).text,
      static_cast<unsigned long>(length), accepted);
#endif
}

/** @brief Format a node-scoped MQTT topic, rejecting a truncated result. */
bool buildNodeMqttTopic(uint16_t nodeId, const char* suffix, char* topic, size_t topicSize)
{
  const int written = snprintf(
      topic,
      topicSize,
      "%s/%u/%s",
      WIOT_ACTIVE_TOPIC(kMqttCompanyTopicPrefix, prefix),
      static_cast<unsigned>(nodeId),
      suffix);
  return written > 0 && static_cast<size_t>(written) < topicSize;
}
Uplink* freeReplySlot()
{
  for (auto& entry : g_replies)
    if (!entry.used) return &entry;
  return nullptr;
}

void storeUplink(const LoraFrame& frame, Uplink& reservedReply)
{
  uint32_t request = 0;
  Uplink* entry = &reservedReply;
  if (frame.type == LoraPayloadType::StatusTelemetry)
  {
    entry = &g_statuses[0];
    for (auto& status : g_statuses)
    {
      if (status.used && status.frame.sourceNodeId == frame.sourceNodeId) {
        entry = &status;
        break;
      }
      if (!status.used || (entry->used && millis() - status.queuedAt > millis() - entry->queuedAt))
        entry = &status;
    }
  }
  else if (frame.type == LoraPayloadType::SystemTelemetry)
  {
    Telemetry telemetry = Telemetry_init_zero;
    if (!decodeEncryptedTelemetryPayload(frame.payload, frame.payloadLength, telemetry) ||
        telemetry.node_id != frame.sourceNodeId)
    {
      ++g_forwardFailures;
      APP_LOG_EVENT_WARN("uplink_decode_failed source=%u", static_cast<unsigned>(frame.sourceNodeId));
      return;
    }
    request = telemetry.command_ack_request_id;
    if (!request && telemetry.has_history) request = telemetry.history.request_id;
    logNodeReply(frame, telemetry);
  }
  else return;

  ++g_receivedNodeFrames;
  g_hasNodeUplink = true;
  g_lastNodeUptimeMs = g_uptimeMs;
  entry->frame = frame;
  entry->queuedAt = millis();
  entry->request = request;
  entry->fingerprint = request ? frameFingerprint(frame.payload, frame.payloadLength) : 0U;
  if (request)
  {
    for (const auto& queued : g_replies) {
      if (queued.used && queued.request == request && queued.fingerprint == entry->fingerprint &&
          queued.frame.sourceNodeId == frame.sourceNodeId && queued.frame.payloadLength == frame.payloadLength)
        return;
    }
  }
  entry->used = true;
  entry->attempted = false;
  if (g_radioOwner == frame.sourceNodeId && (!g_radioRequest || g_radioRequest == request))
    g_radioOwner = 0;
  if (request && g_radioProof.request_id == request && g_radioProof.node_id == frame.sourceNodeId) {
    reportGatewayReply(g_radioProof);
    g_radioProof.request_id = 0;
  }
}

void serviceServerReceipts()
{
  Gateway_Delivery proof;
  while (takeGatewayReceipt(proof))
  {
    for (auto& entry : g_replies) {
      if (entry.used && entry.request == proof.request_id && entry.fingerprint == proof.fingerprint &&
          entry.frame.sourceNodeId == proof.node_id && entry.frame.payloadLength == proof.wire_bytes)
      {
        entry.used = false;
        APP_LOG_EVENT("uplink_persisted request=%lu source=%u",
            static_cast<unsigned long>(proof.request_id), static_cast<unsigned>(proof.node_id));
        break;
      }
    }
  }
}

void expireUplinks()
{
  for (auto& reply : g_replies) {
    if (!reply.used || millis() - reply.queuedAt < kUplinkLifetimeMs) continue;
    reply.used = false;
    ++g_forwardFailures;
    APP_LOG_EVENT_WARN("uplink_expired request=%lu source=%u server_receipt=unconfirmed",
        static_cast<unsigned long>(reply.request), static_cast<unsigned>(reply.frame.sourceNodeId));
  }
}

bool serviceOneUplink(bool allowStatus)
{
  const uint32_t now = millis();
  Uplink* next = nullptr;
  for (auto& reply : g_replies) {
    if (reply.used && (!reply.attempted || now - reply.attemptedAt >= 3000U) &&
        (!next || now - reply.queuedAt > now - next->queuedAt)) next = &reply;
  }
  if (!next && allowStatus) {
    for (auto& status : g_statuses) {
      if (status.used && (!status.attempted || now - status.attemptedAt >= 3000U) &&
          (!next || now - status.queuedAt > now - next->queuedAt)) next = &status;
    }
  }
  if (!next) return false;
  const LoraFrame& frame = next->frame;
  char topic[144];
  next->attempted = true;
  next->attemptedAt = now;
  if (buildNodeMqttTopic(frame.sourceNodeId,
      frame.type == LoraPayloadType::StatusTelemetry ? "status" : "data", topic, sizeof(topic)) &&
      publishMqttPayload(topic, frame.payload, frame.payloadLength))
  {
    ++g_forwardedNodeFrames;
    if (!next->request) next->used = false;
  }
  else {
    ++g_forwardFailures;
    APP_LOG_EVENT_WARN("uplink_publish_deferred request=%lu source=%u",
        static_cast<unsigned long>(next->request), static_cast<unsigned>(frame.sourceNodeId));
  }
  return true;
}

bool serviceRadioScheduler()
{
  const auto* command = gatewayPendingCommand();
  if (command && command->superseded)
  {
    completeGatewayCommand(GatewaySuperseded);
    return true;
  }
  if (command && millis() - command->receivedMs >= kCommandQueueLifetimeMs)
  {
    completeGatewayCommand(GatewayQueueExpired);
    return true;
  }
  if (!loraCanStartTransmission()) return false;

#if APP_LORA_COORDINATED
  if ((!command || g_commandsSinceGrant >= 2U) && millis() - g_lastGrant >= 1200U)
  {
    const uint32_t now = millis();
    for (size_t i = 0; i < kRosterSize; ++i)
    {
      const size_t slot = (g_rosterNext + i) % kRosterSize;
      if (g_nodeWasGranted[slot] && now - g_lastNodeGrant[slot] < APP_LORA_GRANT_POLL_MS) continue;
      const uint16_t target = kRoster[slot];
      g_rosterNext = (slot + 1U) % kRosterSize;
      g_nodeWasGranted[slot] = true;
      g_lastNodeGrant[slot] = now;
      g_commandsSinceGrant = 0U;
      g_lastGrant = now;
      const uint8_t payload[] = {static_cast<uint8_t>(target >> 8), static_cast<uint8_t>(target)};
      if (target && sendLoraWakeCommand(LoraPayloadType::UplinkGrant, payload, sizeof(payload)))
      {
        g_radioOwner = target;
        g_radioRequest = 0;
        g_windowStart = millis();
      }
      return true;
    }
  }
#endif
  if (!command) return false;
#if APP_LORA_COORDINATED
  if (command->broadcast)
  {
    APP_LOG_EVENT_WARN("broadcast_requires_unicast_in_coordinated_mode");
    completeGatewayCommand(GatewayRadioFailed);
    return true;
  }
  ++g_commandsSinceGrant;
#endif
  const auto type = command->broadcast ? LoraPayloadType::BroadcastCommand : LoraPayloadType::Command;
  const bool sent = sendLoraWakeCommand(type, command->payload, command->proof.wire_bytes);
  if (sent && !command->broadcast) {
    g_radioOwner = static_cast<uint16_t>(command->proof.node_id);
    g_radioRequest = command->proof.request_id;
    g_radioProof = command->proof;
    g_windowStart = millis();
  }
  completeGatewayCommand(sent ? GatewayDispatched : GatewayRadioFailed);
  return true;
}

}

void gatewaySetup()
{
#if !APP_ENABLE_SERIAL_CONFIG
  APP_DEBUG_BEGIN(115200);
#endif
  watchdogDelay(1000);
  reportHardwareWatchdogStatus();
  serviceHardwareWatchdog();

  APP_DEBUG_PRINTLN("=============== EgSA LoRa MQTT Gateway ===============");
  APP_LOG_EVENT("boot role=GATEWAY node=%u topics=%s debug=%s raw_frames=%u command_ack=%u",
      AppConfig::kNodeId, WIOT_ACTIVE_TOPIC(kMqttCompanyTopicPrefix, prefix), APP_DEBUG_LITE ? "LITE" : "FULL",
        APP_DEBUG_FULL_ENABLED && APP_DEBUG_RAW_FRAMES, AppConfig::kEnableCommandAckReplies);

  initializeLoraLink();
  serviceHardwareWatchdog();
  initializeMqttTransport();
  serviceHardwareWatchdog();
  if (!connectNetwork())
  {
    APP_LOG_ERROR("Gateway network initialization failed; will retry in loop.");
  }
  initializeMqttClient();
  serviceHardwareWatchdog();

  APP_DEBUG_PRINTLN("Gateway setup complete. Entering LoRa receive loop...");
}

void gatewayLoop()
{
  static uint32_t lastHeartbeatMs = 0;
  const uint32_t now = millis();
  g_uptimeMs += static_cast<uint32_t>(now - g_previousTickMs);
  g_previousTickMs = now;

  serviceLoraInput();
  expireUplinks();
  LoraFrame frame;
  while (auto* free = freeReplySlot())
  {
    if (!receiveLoraFrame(frame)) break;
    storeUplink(frame, *free);
    serviceHardwareWatchdog();
  }

  if (g_radioOwner && millis() - g_windowStart >= kStartWindowMs) g_radioOwner = 0;
  if (g_radioOwner || isLoraReceiveTransactionActive()) return;

  const bool mqttReady = ensureMqttConnection();
  mqttLoop();
  serviceServerReceipts();
  serviceHardwareWatchdog();
  if (isLoraReceiveTransactionActive()) return;

  if (mqttReady)
  {
    serviceGatewayDeliveryEvents();
    if (!serviceOneUplink(!mqttCommandWorkPending()) && !mqttCommandWorkPending() && !isAsyncPublishBusy()) serviceGatewayHeartbeat();
  }
  serviceHardwareWatchdog();
  if (!isLoraReceiveTransactionActive()) serviceRadioScheduler();

  if (AppConfig::kEnableGatewayHeartbeatLogs && millis() - lastHeartbeatMs >= 5000UL)
  {
    lastHeartbeatMs = millis();
    APP_DEBUG_PRINTLN("Gateway alive; waiting for LoRa frames");
    APP_DEBUG_ONLY(printLoraDiagnostics());
  }
}
#endif
