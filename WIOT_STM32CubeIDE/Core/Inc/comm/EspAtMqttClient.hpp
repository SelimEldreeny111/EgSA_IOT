#ifndef WIOT_ESP_AT_MQTT_CLIENT_HPP
#define WIOT_ESP_AT_MQTT_CLIENT_HPP

#include <cstddef>
#include <cstdint>

class EspAtMqttClient
{
public:
  using MessageCallback = void (*)(const char *topic, const uint8_t *payload, size_t length);

  EspAtMqttClient();
  void begin(MessageCallback callback);
  bool ensureConnected();
  bool connected() const { return mqttConnected_; }
  void service();
  bool publish(const char *topic, const uint8_t *payload, size_t length);

private:
  static constexpr size_t AtWindowCapacity = 192U;
  static constexpr size_t IpPayloadCapacity = 640U;
  static constexpr size_t MqttRxCapacity = 768U;

  bool initializeEsp();
  bool openTcpAndMqtt();
  bool sendAt(const char *command, const char *success, uint32_t timeoutMs);
  bool waitFor(const char *success, uint32_t timeoutMs, const char *alternative = nullptr);
  bool sendTcp(const uint8_t *data, size_t length);
  bool sendConnect();
  bool sendSubscriptions();
  void pollSerial();
  void consumeSerialByte(uint8_t value);
  void appendAtText(uint8_t value);
  bool atWindowContains(const char *token) const;
  void consumeMqttBytes(const uint8_t *data, size_t length);
  void parseMqttPackets();
  void handleMqttPacket(const uint8_t *packet, size_t length);
  void markDisconnected();

  MessageCallback callback_;
  bool espInitialized_;
  bool tcpConnected_;
  bool mqttConnected_;
  uint32_t lastReconnectAttemptMs_;
  uint32_t lastActivityMs_;
  uint16_t packetId_;

  char atWindow_[AtWindowCapacity];
  size_t atWindowLength_;
  char ipHeader_[24];
  size_t ipHeaderLength_;
  bool ipHeaderCandidate_;
  size_t ipExpectedLength_;
  size_t ipPayloadLength_;
  uint8_t ipPayload_[IpPayloadCapacity];
  uint8_t mqttRx_[MqttRxCapacity];
  size_t mqttRxLength_;
};

extern EspAtMqttClient MqttClient;

#endif
