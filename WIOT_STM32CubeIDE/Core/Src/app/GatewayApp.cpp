#include "app/GatewayApp.hpp"

#include "comm/EspAtMqttClient.hpp"
#include "config/AppConfig.hpp"
#include "platform/Stm32Platform.hpp"
#include "radio/LoraLink.hpp"

#include <cstdio>
#include <cstdlib>
#include <cstring>

#if APP_ROLE == APP_ROLE_LORA_GATEWAY

namespace
{
bool buildNodeTopic(uint16_t nodeId, const char *suffix, char *topic, size_t capacity)
{
  const int written = std::snprintf(
      topic, capacity, "%s/%u/%s", kMqttCompanyTopicPrefix,
      static_cast<unsigned>(nodeId), suffix);
  return written > 0 && static_cast<size_t>(written) < capacity;
}

bool parseDirectNodeTopic(const char *topic, uint16_t &nodeId)
{
  const size_t prefixLength = std::strlen(kMqttCompanyTopicPrefix);
  if (std::strncmp(topic, kMqttCompanyTopicPrefix, prefixLength) != 0 ||
      topic[prefixLength] != '/') return false;
  const char *nodeStart = topic + prefixLength + 1U;
  char *end = nullptr;
  const unsigned long parsed = std::strtoul(nodeStart, &end, 10);
  if (end == nodeStart || parsed > 0xFFFFU || std::strcmp(end, "/CMD") != 0) return false;
  nodeId = static_cast<uint16_t>(parsed);
  return true;
}

void mqttCommandReceived(const char *topic, const uint8_t *payload, size_t length)
{
  if (length == 0U || length > sizeof(LoraFrame::payload))
  {
    SerialMon.println("Gateway rejected invalid MQTT command length");
    return;
  }
  LoraPayloadType type = LoraPayloadType::Command;
  if (std::strcmp(topic, kMqttBroadcastTopic) == 0)
  {
    type = LoraPayloadType::BroadcastCommand;
  }
  else
  {
    uint16_t targetNode = 0U;
    if (!parseDirectNodeTopic(topic, targetNode))
    {
      SerialMon.println("Gateway ignored MQTT topic outside command routing");
      return;
    }
    SerialMon.print("MQTT direct command target node "); SerialMon.println(targetNode);
  }
  const bool sent = sendLoraFrame(type, AppConfig::kGatewayNodeId, payload, length);
  SerialMon.println(sent ? "Encrypted MQTT command forwarded by LoRa"
                         : "MQTT-to-LoRa command forwarding failed");
}
}

namespace GatewayApp
{
void setup()
{
  (void)SerialMon.begin(115200U);
  Platform::delayMs(300U);
  SerialMon.println("\r\n=============== EgSA LoRa MQTT Gateway ===============");
  SerialMon.println("Native STM32F401RCT6 HAL + ESP-AT MQTT 3.1.1");
  initializeLoraLink();
  MqttClient.begin(mqttCommandReceived);
  (void)MqttClient.ensureConnected();
  SerialMon.println("Gateway initialization complete");
}

void loop()
{
  static uint32_t lastHeartbeatMs = 0U;
  serviceLoraInput();
  const bool loraPriority = isLoraReceiveTransactionActive();
  if (!loraPriority)
  {
    MqttClient.service();
    (void)MqttClient.ensureConnected();
  }

  LoraFrame frame{};
  while (receiveLoraFrame(frame))
  {
    printLoraFrameSummary(frame, "LoRa RX");
    const char *suffix = frame.type == LoraPayloadType::StatusTelemetry
        ? "Status"
        : (frame.type == LoraPayloadType::SystemTelemetry ? "Telemetry" : nullptr);
    if (suffix == nullptr)
    {
      SerialMon.println("Gateway ignored non-uplink LoRa application frame");
      continue;
    }
    char topic[80];
    if (!buildNodeTopic(frame.sourceNodeId, suffix, topic, sizeof(topic)))
    {
      SerialMon.println("Gateway MQTT topic overflow");
      continue;
    }
    if (!MqttClient.connected() && !MqttClient.ensureConnected())
    {
      SerialMon.println("MQTT offline; uplink payload was not published");
      continue;
    }
    const bool published = MqttClient.publish(topic, frame.payload, frame.payloadLength);
    SerialMon.println(published ? "Encrypted LoRa payload published to MQTT"
                                : "Gateway MQTT publish failed");
  }

  const uint32_t now = Platform::millis();
  if (AppConfig::kEnableGatewayHeartbeatLogs && now - lastHeartbeatMs >= 5000UL)
  {
    lastHeartbeatMs = now;
    SerialMon.print("Gateway alive; MQTT=");
    SerialMon.print(MqttClient.connected() ? "connected" : "offline");
    SerialMon.print(" AUX=");
    SerialMon.println(Platform::gpioRead(AppConfig::kLoraAuxPin) == GPIO_PIN_SET
                          ? "HIGH" : "LOW");
    printLoraDiagnostics();
  }
}
}

#endif
