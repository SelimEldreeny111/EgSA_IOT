/** @file GatewayApp.cpp @brief LoRa gateway startup, receive routing, and forwarding. */
#define APP_LOG_MODULE "GATEWAY"
#include "../platform/DebugLog.h"
#include "GatewayApp.h"

#include "../comm/MQTT.h"
#include "../config/AppConfig.h"
#include "../platform/Watchdog.h"
#include "../radio/LoraLink.h"

#include <Arduino.h>
#include <stdio.h>

extern HardwareSerial SerialMon;

namespace
{
/** @brief Format a node-scoped MQTT topic, rejecting a truncated result. */
bool buildNodeMqttTopic(uint16_t nodeId, const char* suffix, char* topic, size_t topicSize)
{
  const int written = snprintf(
      topic,
      topicSize,
      "%s/%u/%s",
      kMqttCompanyTopicPrefix,
      static_cast<unsigned>(nodeId),
      suffix);
  return written > 0 && static_cast<size_t>(written) < topicSize;
}
}

void gatewaySetup()
{
  APP_DEBUG_BEGIN(115200);
  watchdogDelay(1000);
  reportHardwareWatchdogStatus();
  serviceHardwareWatchdog();

  APP_DEBUG_PRINTLN("=============== EgSA LoRa MQTT Gateway ===============");
  APP_LOG_INFO("boot role=GATEWAY node=%u topics=%s debug=enabled raw_frames=%u command_ack=%u",
      AppConfig::kNodeId, kMqttCompanyTopicPrefix, APP_DEBUG_RAW_FRAMES, APP_ENABLE_COMMAND_ACK_REPLIES);

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
    ensureMqttConnection();
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
    }
    else
    {
      APP_DEBUG_PRINTLN("Gateway ignored non-uplink LoRa frame");
      continue;
    }

    char publishTopic[128];
    if (!buildNodeMqttTopic(frame.sourceNodeId, topicSuffix, publishTopic, sizeof(publishTopic)))
    {
      APP_LOG_ERROR("Gateway MQTT topic build failed");
      continue;
    }

    if (publishMqttPayload(publishTopic, frame.payload, frame.payloadLength))
    {
      APP_LOG_INFO("uplink source=%u type=%s bytes=%lu topic=%s stage=modem_write_accepted server_receipt=unconfirmed",
          frame.sourceNodeId, WiotDebug::frameName(static_cast<uint8_t>(frame.type)),
          static_cast<unsigned long>(frame.payloadLength), publishTopic);
    }
    else
    {
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
  }

  if (AppConfig::kEnableGatewayHeartbeatLogs && millis() - lastHeartbeatMs >= 5000UL)
  {
    lastHeartbeatMs = millis();
    APP_DEBUG_PRINT("Gateway alive; waiting for LoRa frames. AS32 AUX=");
    APP_DEBUG_PRINTLN(digitalRead(AppConfig::kLoraAuxPin) == HIGH ? "HIGH" : "LOW");
    APP_DEBUG_ONLY(printLoraDiagnostics());
  }
}
