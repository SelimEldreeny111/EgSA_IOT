#include "GatewayApp.h"

#include "../comm/MQTT.h"
#include "../config/AppConfig.h"
#include "../platform/SerialPorts.h"
#include "../platform/Watchdog.h"
#include "../radio/LoraLink.h"

#include <Arduino.h>
#include <stdio.h>

extern HardwareSerial& SerialMon;

namespace
{
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
  beginDebugSerial(115200);
  watchdogDelay(1000);
  reportHardwareWatchdogStatus();
  serviceHardwareWatchdog();

  SerialMon.println("=============== EgSA LoRa MQTT Gateway ===============");
  SerialMon.println("Role: AS32 LoRa receiver + WiFi/SIM MQTT uplink");

  initializeLoraLink();
  serviceHardwareWatchdog();
  initializeMqttTransport();
  serviceHardwareWatchdog();
  if (!connectNetwork())
  {
    SerialMon.println("Gateway network initialization failed; will retry in loop.");
  }
  initializeMqttClient();
  serviceHardwareWatchdog();

  SerialMon.println("Gateway setup complete. Entering LoRa receive loop...");
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
    SerialMon.println(loraPriority
        ? "LoRa fragment transaction active; MQTT work deferred"
        : "LoRa fragment transaction complete; MQTT work resumed");
    previousLoraPriority = loraPriority;
  }

  if (!loraPriority && !isAsyncPublishBusy())
  {
    ensureMqttConnection();
    mqttLoop();
    serviceHardwareWatchdog();
  }

  LoraFrame frame;
  while (receiveLoraFrame(frame))
  {
    serviceHardwareWatchdog();
    printLoraFrameSummary(frame, "LoRa RX");

    const char* topicSuffix = nullptr;
    if (frame.type == LoraPayloadType::StatusTelemetry)
    {
      topicSuffix = "Status";
    }
    else if (frame.type == LoraPayloadType::SystemTelemetry)
    {
      topicSuffix = "Telemetry";
    }
    else
    {
      SerialMon.println("Gateway ignored non-uplink LoRa frame");
      continue;
    }

    char publishTopic[80];
    if (!buildNodeMqttTopic(frame.sourceNodeId, topicSuffix, publishTopic, sizeof(publishTopic)))
    {
      SerialMon.println("Gateway MQTT topic build failed");
      continue;
    }

    if (publishMqttPayload(publishTopic, frame.payload, frame.payloadLength))
    {
      SerialMon.print("Gateway published LoRa payload to MQTT topic: ");
      SerialMon.println(publishTopic);
    }
    else
    {
      SerialMon.println("Gateway MQTT publish failed");
    }
    serviceHardwareWatchdog();
  }

  // Even the cooperative ESP-AT publisher owns the modem bus. Do not advance
  // it between LoRa fragments; ACK turnaround has priority until reassembly
  // completes or its priority window expires.
  if (!isLoraReceiveTransactionActive())
  {
    asyncPublishStep();
    serviceHardwareWatchdog();
  }

  if (AppConfig::kEnableGatewayHeartbeatLogs && millis() - lastHeartbeatMs >= 5000UL)
  {
    lastHeartbeatMs = millis();
    SerialMon.print("Gateway alive; waiting for LoRa frames. AS32 AUX=");
    SerialMon.println(digitalRead(AppConfig::kLoraAuxPin) == HIGH ? "HIGH" : "LOW");
    printLoraDiagnostics();
  }
}
