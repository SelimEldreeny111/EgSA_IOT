#include "comm/EspAtMqttClient.hpp"

#include "config/AppConfig.hpp"
#include "platform/Stm32Platform.hpp"

#include <cstdio>
#include <cstdlib>
#include <cstring>

#if APP_ROLE == APP_ROLE_LORA_GATEWAY

EspAtMqttClient MqttClient;

namespace
{
bool appendByte(uint8_t *buffer, size_t capacity, size_t &length, uint8_t value)
{
  if (length >= capacity) return false;
  buffer[length++] = value;
  return true;
}

bool appendData(
    uint8_t *buffer,
    size_t capacity,
    size_t &length,
    const uint8_t *data,
    size_t dataLength)
{
  if (data == nullptr || length + dataLength > capacity) return false;
  std::memcpy(buffer + length, data, dataLength);
  length += dataLength;
  return true;
}

bool appendMqttString(
    uint8_t *buffer,
    size_t capacity,
    size_t &length,
    const char *value)
{
  const size_t valueLength = std::strlen(value);
  if (valueLength > 0xFFFFU || length + 2U + valueLength > capacity) return false;
  return appendByte(buffer, capacity, length, static_cast<uint8_t>(valueLength >> 8U)) &&
         appendByte(buffer, capacity, length, static_cast<uint8_t>(valueLength)) &&
         appendData(buffer, capacity, length,
                    reinterpret_cast<const uint8_t *>(value), valueLength);
}

size_t encodeRemainingLength(size_t value, uint8_t *output)
{
  size_t length = 0U;
  do
  {
    uint8_t encoded = static_cast<uint8_t>(value % 128U);
    value /= 128U;
    if (value > 0U) encoded |= 0x80U;
    output[length++] = encoded;
  } while (value > 0U && length < 4U);
  return length;
}
}

EspAtMqttClient::EspAtMqttClient()
    : callback_(nullptr), espInitialized_(false), tcpConnected_(false),
      mqttConnected_(false), lastReconnectAttemptMs_(0U), lastActivityMs_(0U),
      packetId_(1U), atWindow_{}, atWindowLength_(0U), ipHeader_{},
      ipHeaderLength_(0U), ipHeaderCandidate_(false), ipExpectedLength_(0U),
      ipPayloadLength_(0U), ipPayload_{}, mqttRx_{}, mqttRxLength_(0U)
{
}

void EspAtMqttClient::begin(MessageCallback callback)
{
  callback_ = callback;
  (void)SerialAt.begin(115200U, Platform::UartFrameFormat::Data8N1);
  SerialAt.clearRx();
  lastReconnectAttemptMs_ = Platform::millis() - AppConfig::kMqttReconnectIntervalMs;
}

void EspAtMqttClient::appendAtText(uint8_t value)
{
  if (atWindowLength_ + 1U >= sizeof(atWindow_))
  {
    const size_t keep = sizeof(atWindow_) / 2U;
    std::memmove(atWindow_, atWindow_ + atWindowLength_ - keep, keep);
    atWindowLength_ = keep;
  }
  atWindow_[atWindowLength_++] = static_cast<char>(value);
  atWindow_[atWindowLength_] = '\0';
  if (std::strstr(atWindow_, "CLOSED") != nullptr ||
      std::strstr(atWindow_, "WIFI DISCONNECT") != nullptr)
  {
    markDisconnected();
  }
}

bool EspAtMqttClient::atWindowContains(const char *token) const
{
  return token != nullptr && std::strstr(atWindow_, token) != nullptr;
}

void EspAtMqttClient::consumeSerialByte(uint8_t value)
{
  static const char prefix[] = "+IPD,";
  if (ipExpectedLength_ > 0U)
  {
    if (ipPayloadLength_ < sizeof(ipPayload_)) ipPayload_[ipPayloadLength_] = value;
    ++ipPayloadLength_;
    if (ipPayloadLength_ >= ipExpectedLength_)
    {
      if (ipPayloadLength_ <= sizeof(ipPayload_))
        consumeMqttBytes(ipPayload_, ipPayloadLength_);
      ipExpectedLength_ = 0U;
      ipPayloadLength_ = 0U;
    }
    return;
  }

  if (!ipHeaderCandidate_)
  {
    if (value == '+')
    {
      ipHeaderCandidate_ = true;
      ipHeaderLength_ = 0U;
      ipHeader_[ipHeaderLength_++] = static_cast<char>(value);
    }
    else
    {
      appendAtText(value);
    }
    return;
  }

  if (ipHeaderLength_ < sizeof(ipHeader_) - 1U)
    ipHeader_[ipHeaderLength_++] = static_cast<char>(value);
  ipHeader_[ipHeaderLength_] = '\0';

  if (ipHeaderLength_ <= sizeof(prefix) - 1U)
  {
    if (std::strncmp(ipHeader_, prefix, ipHeaderLength_) == 0) return;
    for (size_t index = 0U; index < ipHeaderLength_; ++index)
      appendAtText(static_cast<uint8_t>(ipHeader_[index]));
    ipHeaderCandidate_ = false;
    ipHeaderLength_ = 0U;
    return;
  }

  if (value == ':')
  {
    char *digits = ipHeader_ + sizeof(prefix) - 1U;
    char *lastComma = std::strrchr(digits, ',');
    if (lastComma != nullptr) digits = lastComma + 1;
    ipExpectedLength_ = static_cast<size_t>(std::strtoul(digits, nullptr, 10));
    ipPayloadLength_ = 0U;
    ipHeaderCandidate_ = false;
    ipHeaderLength_ = 0U;
    if (ipExpectedLength_ == 0U || ipExpectedLength_ > sizeof(ipPayload_))
    {
      ipExpectedLength_ = 0U;
      markDisconnected();
    }
  }
  else if (ipHeaderLength_ + 1U >= sizeof(ipHeader_) || value == '\n')
  {
    for (size_t index = 0U; index < ipHeaderLength_; ++index)
      appendAtText(static_cast<uint8_t>(ipHeader_[index]));
    ipHeaderCandidate_ = false;
    ipHeaderLength_ = 0U;
  }
}

void EspAtMqttClient::pollSerial()
{
  while (SerialAt.available() > 0)
  {
    const int value = SerialAt.read();
    if (value >= 0) consumeSerialByte(static_cast<uint8_t>(value));
  }
}

bool EspAtMqttClient::waitFor(
    const char *success,
    uint32_t timeoutMs,
    const char *alternative)
{
  atWindowLength_ = 0U;
  atWindow_[0] = '\0';
  const uint32_t start = Platform::millis();
  while (Platform::millis() - start < timeoutMs)
  {
    pollSerial();
    if (atWindowContains(success) || atWindowContains(alternative)) return true;
    if (atWindowContains("ERROR") || atWindowContains("FAIL")) return false;
    Platform::delayMs(1U);
  }
  return false;
}

bool EspAtMqttClient::sendAt(
    const char *command,
    const char *success,
    uint32_t timeoutMs)
{
  atWindowLength_ = 0U;
  atWindow_[0] = '\0';
  SerialAt.write(reinterpret_cast<const uint8_t *>(command), std::strlen(command));
  static const uint8_t crlf[] = {'\r', '\n'};
  SerialAt.write(crlf, sizeof(crlf));
  return waitFor(success, timeoutMs);
}

bool EspAtMqttClient::initializeEsp()
{
  SerialMon.println("Initializing ESP8266 with native ESP-AT driver...");
  if (!sendAt("AT", "OK", 1500U))
  {
    SerialMon.println("ESP8266 did not answer AT");
    return false;
  }
  (void)sendAt("ATE0", "OK", 1000U);
  if (!sendAt("AT+CWMODE=1", "OK", 1500U)) return false;

  char join[128];
  const int written = std::snprintf(
      join, sizeof(join), "AT+CWJAP=\"%s\",\"%s\"", kWifiSsid, kWifiPassword);
  if (written <= 0 || static_cast<size_t>(written) >= sizeof(join)) return false;
  if (!sendAt(join, "OK", 25000U))
  {
    SerialMon.println("ESP8266 Wi-Fi association failed");
    return false;
  }
  if (!sendAt("AT+CIPMUX=0", "OK", 1500U)) return false;
  espInitialized_ = true;
  SerialMon.println("ESP8266 Wi-Fi connected");
  return true;
}

bool EspAtMqttClient::sendTcp(const uint8_t *data, size_t length)
{
  if (!tcpConnected_ || data == nullptr || length == 0U) return false;
  char command[32];
  std::snprintf(command, sizeof(command), "AT+CIPSEND=%u", static_cast<unsigned>(length));
  atWindowLength_ = 0U;
  atWindow_[0] = '\0';
  SerialAt.write(reinterpret_cast<const uint8_t *>(command), std::strlen(command));
  static const uint8_t crlf[] = {'\r', '\n'};
  SerialAt.write(crlf, sizeof(crlf));
  if (!waitFor(">", 3000U))
  {
    markDisconnected();
    return false;
  }
  if (SerialAt.write(data, length) != length || !waitFor("SEND OK", 5000U))
  {
    markDisconnected();
    return false;
  }
  lastActivityMs_ = Platform::millis();
  return true;
}

bool EspAtMqttClient::sendConnect()
{
  uint8_t body[128]{};
  size_t bodyLength = 0U;
  const uint8_t protocolHeader[] = {0x00, 0x04, 'M', 'Q', 'T', 'T', 0x04, 0x02,
      static_cast<uint8_t>(AppConfig::kMqttKeepAliveSeconds >> 8U),
      static_cast<uint8_t>(AppConfig::kMqttKeepAliveSeconds)};
  if (!appendData(body, sizeof(body), bodyLength, protocolHeader, sizeof(protocolHeader)) ||
      !appendMqttString(body, sizeof(body), bodyLength, kMqttClientId)) return false;

  uint8_t packet[140]{};
  uint8_t remaining[4];
  const size_t remainingLength = encodeRemainingLength(bodyLength, remaining);
  size_t length = 0U;
  appendByte(packet, sizeof(packet), length, 0x10U);
  appendData(packet, sizeof(packet), length, remaining, remainingLength);
  appendData(packet, sizeof(packet), length, body, bodyLength);
  mqttConnected_ = false;
  if (!sendTcp(packet, length)) return false;

  const uint32_t start = Platform::millis();
  while (Platform::millis() - start < 5000U && !mqttConnected_)
  {
    pollSerial();
    Platform::delayMs(1U);
  }
  return mqttConnected_;
}

bool EspAtMqttClient::sendSubscriptions()
{
  uint8_t body[220]{};
  size_t bodyLength = 0U;
  const uint16_t id = packetId_++;
  appendByte(body, sizeof(body), bodyLength, static_cast<uint8_t>(id >> 8U));
  appendByte(body, sizeof(body), bodyLength, static_cast<uint8_t>(id));
  if (!appendMqttString(body, sizeof(body), bodyLength, kMqttGatewayCommandWildcardTopic) ||
      !appendByte(body, sizeof(body), bodyLength, 0U) ||
      !appendMqttString(body, sizeof(body), bodyLength, kMqttBroadcastTopic) ||
      !appendByte(body, sizeof(body), bodyLength, 0U)) return false;

  uint8_t packet[228]{};
  uint8_t remaining[4];
  const size_t remainingLength = encodeRemainingLength(bodyLength, remaining);
  size_t length = 0U;
  appendByte(packet, sizeof(packet), length, 0x82U);
  appendData(packet, sizeof(packet), length, remaining, remainingLength);
  appendData(packet, sizeof(packet), length, body, bodyLength);
  return sendTcp(packet, length);
}

bool EspAtMqttClient::openTcpAndMqtt()
{
  char command[128];
  std::snprintf(command, sizeof(command),
                "AT+CIPSTART=\"TCP\",\"%s\",%u",
                kMqttServer, static_cast<unsigned>(AppConfig::kMqttPort));
  atWindowLength_ = 0U;
  atWindow_[0] = '\0';
  SerialAt.write(reinterpret_cast<const uint8_t *>(command), std::strlen(command));
  static const uint8_t crlf[] = {'\r', '\n'};
  SerialAt.write(crlf, sizeof(crlf));
  if (!waitFor("CONNECT", 10000U, "ALREADY CONNECTED")) return false;
  tcpConnected_ = true;
  if (!sendConnect())
  {
    SerialMon.println("MQTT CONNACK failed");
    markDisconnected();
    return false;
  }
  if (!sendSubscriptions())
  {
    markDisconnected();
    return false;
  }
  SerialMon.println("MQTT connected and command topics subscribed");
  return true;
}

bool EspAtMqttClient::ensureConnected()
{
  service();
  if (mqttConnected_) return true;
  const uint32_t now = Platform::millis();
  if (now - lastReconnectAttemptMs_ < AppConfig::kMqttReconnectIntervalMs) return false;
  lastReconnectAttemptMs_ = now;
  if (!espInitialized_ && !initializeEsp()) return false;
  if (!openTcpAndMqtt())
  {
    espInitialized_ = false;
    return false;
  }
  return true;
}

void EspAtMqttClient::markDisconnected()
{
  tcpConnected_ = false;
  mqttConnected_ = false;
}

void EspAtMqttClient::consumeMqttBytes(const uint8_t *data, size_t length)
{
  if (mqttRxLength_ + length > sizeof(mqttRx_))
  {
    mqttRxLength_ = 0U;
    markDisconnected();
    return;
  }
  std::memcpy(mqttRx_ + mqttRxLength_, data, length);
  mqttRxLength_ += length;
  lastActivityMs_ = Platform::millis();
  parseMqttPackets();
}

void EspAtMqttClient::parseMqttPackets()
{
  while (mqttRxLength_ >= 2U)
  {
    size_t multiplier = 1U;
    size_t remaining = 0U;
    size_t index = 1U;
    uint8_t encoded;
    do
    {
      if (index >= mqttRxLength_ || index > 4U) return;
      encoded = mqttRx_[index++];
      remaining += (encoded & 0x7FU) * multiplier;
      multiplier *= 128U;
    } while ((encoded & 0x80U) != 0U);
    const size_t packetLength = index + remaining;
    if (packetLength > mqttRxLength_) return;
    handleMqttPacket(mqttRx_, packetLength);
    std::memmove(mqttRx_, mqttRx_ + packetLength, mqttRxLength_ - packetLength);
    mqttRxLength_ -= packetLength;
  }
}

void EspAtMqttClient::handleMqttPacket(const uint8_t *packet, size_t length)
{
  size_t index = 1U;
  while (index < length && (packet[index++] & 0x80U) != 0U) {}
  const uint8_t packetType = packet[0] >> 4U;
  if (packetType == 2U)
  {
    if (index + 2U <= length && packet[index + 1U] == 0U)
      mqttConnected_ = true;
    return;
  }
  if (packetType != 3U || index + 2U > length) return;

  const size_t topicLength = static_cast<size_t>(packet[index] << 8U) | packet[index + 1U];
  index += 2U;
  if (topicLength == 0U || topicLength >= 96U || index + topicLength > length) return;
  char topic[96];
  std::memcpy(topic, packet + index, topicLength);
  topic[topicLength] = '\0';
  index += topicLength;
  const uint8_t qos = (packet[0] >> 1U) & 0x03U;
  if (qos > 0U)
  {
    if (index + 2U > length) return;
    index += 2U;
  }
  if (callback_ != nullptr) callback_(topic, packet + index, length - index);
}

void EspAtMqttClient::service()
{
  pollSerial();
  if (!mqttConnected_) return;
  const uint32_t pingPeriod = static_cast<uint32_t>(AppConfig::kMqttKeepAliveSeconds) * 500UL;
  if (Platform::millis() - lastActivityMs_ >= pingPeriod)
  {
    const uint8_t ping[] = {0xC0U, 0x00U};
    if (!sendTcp(ping, sizeof(ping))) markDisconnected();
  }
}

bool EspAtMqttClient::publish(
    const char *topic,
    const uint8_t *payload,
    size_t length)
{
  if (!mqttConnected_ || topic == nullptr || payload == nullptr) return false;
  uint8_t body[600]{};
  size_t bodyLength = 0U;
  if (!appendMqttString(body, sizeof(body), bodyLength, topic) ||
      !appendData(body, sizeof(body), bodyLength, payload, length)) return false;
  uint8_t packet[608]{};
  uint8_t remaining[4];
  const size_t remainingLength = encodeRemainingLength(bodyLength, remaining);
  size_t packetLength = 0U;
  appendByte(packet, sizeof(packet), packetLength, 0x30U);
  appendData(packet, sizeof(packet), packetLength, remaining, remainingLength);
  appendData(packet, sizeof(packet), packetLength, body, bodyLength);
  return sendTcp(packet, packetLength);
}

#endif
