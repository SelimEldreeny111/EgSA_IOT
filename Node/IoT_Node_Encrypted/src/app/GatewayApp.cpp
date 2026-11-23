/** @file GatewayApp.cpp @brief LoRa gateway startup, receive routing, and forwarding. */
#define APP_LOG_MODULE "GATEWAY"
#include "../platform/DebugLog.h"
#include "GatewayApp.h"

#include "../comm/MQTT.h"
#include "../comm/PacketCodec.h"
#include "../config/AppConfig.h"
#include "../config/RuntimeConfig.h"
#include "../platform/Watchdog.h"
#include "../radio/LoraLink.h"

#include <Arduino.h>
#include <stdio.h>

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

#if APP_ENABLE_DEBUG
/** @brief Inspect a complete LoRa DATA frame for reply correlation on the debug UART. */
void logNodeReply(const LoraFrame& frame)
{
  Telemetry reply = Telemetry_init_zero;
  if (!decodeEncryptedTelemetryPayload(frame.payload, frame.payloadLength, reply))
  {
    APP_LOG_EVENT_WARN("data_decode_failed source=%u bytes=%lu",
        static_cast<unsigned>(frame.sourceNodeId), static_cast<unsigned long>(frame.payloadLength));
    return;
  }
  if (reply.node_id != frame.sourceNodeId)
  {
    APP_LOG_EVENT_WARN("data_node_mismatch source=%u payload_node=%lu",
        static_cast<unsigned>(frame.sourceNodeId), static_cast<unsigned long>(reply.node_id));
    return;
  }
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
}
#endif

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
  static bool previousLoraPriority = false;
  const uint32_t now = millis();
  g_uptimeMs += static_cast<uint32_t>(now - g_previousTickMs);
  g_previousTickMs = now;
  bool mqttReady = false;

  // Drain the AS32 UART into the larger software buffer before any ESP-AT or
  // MQTT operation can block the loop. Frame processing continues below.
  serviceLoraInput();
  const bool loraPriority = isLoraReceiveTransactionActive();

  if (loraPriority != previousLoraPriority)
  {
    APP_DEBUG_PRINTLN(loraPriority
        ? "LoRa fragment transaction active; MQTT work deferred"
        : "LoRa fragment transaction complete; MQTT work resumed");
    previousLoraPriority = loraPriority;
  }

  if (!loraPriority)
  {
    mqttReady = ensureMqttConnection();
    mqttLoop();
    serviceHardwareWatchdog();
  }

  LoraFrame frame;
  while (receiveLoraFrame(frame))
  {
    serviceHardwareWatchdog();
    APP_DEBUG_ONLY(printLoraFrameSummary(frame, "LoRa RX"));

    const char* topicSuffix = nullptr;
    if (frame.type == LoraPayloadType::StatusTelemetry)
    {
      topicSuffix = "status";
    }
    else if (frame.type == LoraPayloadType::SystemTelemetry)
    {
      topicSuffix = "data";
#if APP_ENABLE_DEBUG
      logNodeReply(frame);
#endif
    }
    else
    {
      APP_DEBUG_PRINTLN("Gateway ignored non-uplink LoRa frame");
      continue;
    }

    char publishTopic[128];
    ++g_receivedNodeFrames;
    g_hasNodeUplink = true;
    g_lastNodeUptimeMs = g_uptimeMs;
    if (!buildNodeMqttTopic(frame.sourceNodeId, topicSuffix, publishTopic, sizeof(publishTopic)))
    {
      APP_LOG_ERROR("Gateway MQTT topic build failed");
      continue;
    }

    if (publishMqttPayload(publishTopic, frame.payload, frame.payloadLength))
    {
      ++g_forwardedNodeFrames;
      APP_LOG_EVENT("uplink source=%u type=%s bytes=%lu topic=%s stage=modem_write_accepted server_receipt=unconfirmed",
          frame.sourceNodeId, WiotDebug::frameName(static_cast<uint8_t>(frame.type)),
          static_cast<unsigned long>(frame.payloadLength), publishTopic);
    }
    else
    {
      ++g_forwardFailures;
      APP_LOG_ERROR("uplink_failed source=%u bytes=%lu topic=%s", frame.sourceNodeId,
          static_cast<unsigned long>(frame.payloadLength), publishTopic);
    }
    serviceHardwareWatchdog();
  }

  // Queued MQTT sends run only between LoRa receive transactions; keep fragment
  // ACK turnaround intact. The foreground TinyGSM driver is the only AT owner.
  if (!isLoraReceiveTransactionActive())
  {
    asyncPublishStep();
    serviceHardwareWatchdog();
    if (mqttReady && !mqttCommandWorkPending() && !isAsyncPublishBusy() &&
        !isLoraReceiveTransactionActive())
    {
      serviceGatewayHeartbeat();
      serviceHardwareWatchdog();
    }
  }

  if (AppConfig::kEnableGatewayHeartbeatLogs && millis() - lastHeartbeatMs >= 5000UL)
  {
    lastHeartbeatMs = millis();
    APP_DEBUG_PRINT("Gateway alive; waiting for LoRa frames. AS32 AUX=");
    APP_DEBUG_PRINTLN(digitalRead(AppConfig::kLoraAuxPin) == HIGH ? "HIGH" : "LOW");
    APP_DEBUG_ONLY(printLoraDiagnostics());
  }
}
