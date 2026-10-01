#include "LoraLink.h"
#include "../config/AppConfig.h"
#include "../platform/Watchdog.h"
#include "AS32_Config.h"

#include <Arduino.h>
#include <string.h>

#if APP_HAS_LORA && (SERIAL_RX_BUFFER_SIZE < 269 || SERIAL_TX_BUFFER_SIZE < 269)
#error "LoRa requires 269-byte-or-larger UART rings. Keep IoT_Node_Encrypted/build_opt.h with the sketch."
#endif

extern HardwareSerial SerialMon;
extern HardwareSerial SerialLoRa;

namespace
{
constexpr uint8_t kMagic0 = 'E';
constexpr uint8_t kMagic1 = 'G';
constexpr uint8_t kFrameVersion = 1;
constexpr size_t kHeaderLength = 10U;
constexpr size_t kCrcLength = 2U;
constexpr size_t kFragmentHeaderLength = 9U;
constexpr size_t kMaxWireFrameLength = AppConfig::kLoraMaxWireFrameBytes;
constexpr size_t kMaxWirePayloadLength =
    kMaxWireFrameLength - kHeaderLength - kCrcLength;
constexpr size_t kFragmentDataLength =
    kMaxWirePayloadLength - kFragmentHeaderLength;
constexpr size_t kMaxBufferedLength =
    kHeaderLength + sizeof(LoraFrame::payload) + kCrcLength;
constexpr size_t kDiagnosticPrefixLength = 12U;
constexpr size_t kAckPayloadLength = 5U;
constexpr uint16_t kMaxFragmentMaskBits = 16U;

static_assert(kMaxWireFrameLength <= 63U,
              "AS32 physical frames must remain below its 63-byte boundary");
static_assert(kFragmentDataLength > 0U,
              "LoRa wire frame is too small for fragment metadata");
static_assert(
    ((sizeof(LoraFrame::payload) + kFragmentDataLength - 1U) /
     kFragmentDataLength) <= kMaxFragmentMaskBits,
    "Fragment mask is too small for the logical payload capacity");

struct ReassemblyContext
{
  bool active;
  uint16_t sourceNodeId;
  uint16_t messageId;
  LoraPayloadType originalType;
  uint8_t fragmentCount;
  uint16_t totalLength;
  uint16_t logicalCrc;
  uint16_t receivedMask;
  size_t bytesReceived;
  uint32_t lastUpdateMs;
  uint8_t payload[sizeof(LoraFrame::payload)];
};

struct FragmentAckRecord
{
  bool valid;
  uint16_t ackSourceNodeId;
  uint16_t targetNodeId;
  uint16_t messageId;
  uint8_t fragmentIndex;
};

uint8_t g_rxBuffer[kMaxBufferedLength];
size_t g_rxLength = 0U;
uint32_t g_lastRxByteMs = 0U;

ReassemblyContext g_reassembly[AppConfig::kLoraReassemblyContextCount] = {};
LoraFrame g_pendingFrames[AppConfig::kLoraPendingFrameCount] = {};
size_t g_pendingHead = 0U;
size_t g_pendingCount = 0U;
FragmentAckRecord g_lastAck = {};
uint16_t g_nextMessageId = 1U;

uint32_t g_totalRawBytes = 0U;
uint32_t g_noiseDrops = 0U;
uint32_t g_versionDrops = 0U;
uint32_t g_networkDrops = 0U;
uint32_t g_lengthDrops = 0U;
uint32_t g_crcDrops = 0U;
uint32_t g_overflowDrops = 0U;
uint32_t g_timeoutDrops = 0U;
uint32_t g_fragmentDrops = 0U;
uint32_t g_fragmentTimeoutDrops = 0U;
uint32_t g_pendingDrops = 0U;
uint32_t g_totalRxFrames = 0U;
uint32_t g_totalTxFrames = 0U;
uint32_t g_totalRxWireFrames = 0U;
uint32_t g_totalTxWireFrames = 0U;
uint32_t g_totalTxBytes = 0U;
uint32_t g_fragmentAcksRx = 0U;
uint32_t g_fragmentAcksTx = 0U;
uint32_t g_fragmentAckTimeouts = 0U;
uint32_t g_fragmentRetries = 0U;
bool g_lastDataRssiValid = false;
int16_t g_lastDataRssiDbm = 0;
uint8_t g_lastDataRssiRaw = 0U;
bool g_lastEnvironmentRssiValid = false;
int16_t g_lastEnvironmentRssiDbm = 0;
uint8_t g_lastEnvironmentRssiRaw = 0U;
uint32_t g_lastRssiQueryWireFrameCount = 0U;
uint32_t g_rssiQuerySuccesses = 0U;
uint32_t g_rssiQueryFailures = 0U;

uint16_t crc16Ccitt(const uint8_t* data, size_t length)
{
  uint16_t crc = 0xFFFFU;
  for (size_t i = 0; i < length; ++i)
  {
    crc ^= static_cast<uint16_t>(data[i]) << 8;
    for (uint8_t bit = 0; bit < 8U; ++bit)
    {
      crc = (crc & 0x8000U)
          ? static_cast<uint16_t>((crc << 1) ^ 0x1021U)
          : static_cast<uint16_t>(crc << 1);
    }
  }
  return crc;
}

void printHexByte(uint8_t value)
{
  if (value < 0x10U)
  {
    SerialMon.print('0');
  }
  SerialMon.print(value, HEX);
}

void printHexWord(uint16_t value)
{
  printHexByte(static_cast<uint8_t>((value >> 8) & 0xFFU));
  printHexByte(static_cast<uint8_t>(value & 0xFFU));
}

void printHexOffset(size_t value)
{
  if (value < 0x1000U)
  {
    SerialMon.print('0');
  }
  if (value < 0x0100U)
  {
    SerialMon.print('0');
  }
  if (value < 0x0010U)
  {
    SerialMon.print('0');
  }
  SerialMon.print(static_cast<unsigned long>(value), HEX);
}

void printRawBytes(const char* label, const uint8_t* data, size_t length)
{
  SerialMon.print(label);
  SerialMon.print(" (");
  SerialMon.print(length);
  SerialMon.println(" bytes):");

  for (size_t i = 0; i < length; ++i)
  {
    if ((i % 16U) == 0U)
    {
      SerialMon.print("  ");
      printHexOffset(i);
      SerialMon.print(':');
    }

    SerialMon.print(' ');
    printHexByte(data[i]);

    if ((i % 16U) == 15U || i + 1U == length)
    {
      SerialMon.println();
    }
  }
}

void printDecodedHeader(
    const char* label,
    uint8_t version,
    uint16_t networkId,
    LoraPayloadType type,
    uint16_t sourceNodeId,
    size_t payloadLength,
    size_t totalLength,
    uint16_t crc)
{
  SerialMon.print(label);
  SerialMon.print(": version=");
  SerialMon.print(version);
  SerialMon.print(" network=0x");
  printHexWord(networkId);
  SerialMon.print(" type=");
  SerialMon.print(static_cast<uint8_t>(type));
  SerialMon.print(" source=");
  SerialMon.print(sourceNodeId);
  SerialMon.print(" payload=");
  SerialMon.print(payloadLength);
  SerialMon.print(" total=");
  SerialMon.print(totalLength);
  SerialMon.print(" crc=0x");
  printHexWord(crc);
  SerialMon.println();
}

void printRxPrefix()
{
  SerialMon.print("LoRa RX prefix:");
  const size_t count = g_rxLength < kDiagnosticPrefixLength
      ? g_rxLength
      : kDiagnosticPrefixLength;
  for (size_t i = 0; i < count; ++i)
  {
    SerialMon.print(' ');
    printHexByte(g_rxBuffer[i]);
  }
  SerialMon.println();
}

bool isApplicationType(LoraPayloadType type)
{
  return type == LoraPayloadType::StatusTelemetry ||
         type == LoraPayloadType::Command ||
         type == LoraPayloadType::Ack ||
         type == LoraPayloadType::BroadcastCommand ||
         type == LoraPayloadType::SystemTelemetry ||
         type == LoraPayloadType::WakeProbe;
}

uint16_t localRadioNodeId()
{
#if APP_ROLE == APP_ROLE_LORA_GATEWAY
  return AppConfig::kGatewayNodeId;
#else
  return AppConfig::kNodeId;
#endif
}

void discardBytes(size_t count)
{
  if (count >= g_rxLength)
  {
    g_rxLength = 0U;
    g_lastRxByteMs = 0U;
    return;
  }

  memmove(g_rxBuffer, g_rxBuffer + count, g_rxLength - count);
  g_rxLength -= count;
}

size_t expectedBufferedFrameLength()
{
  if (g_rxLength < kHeaderLength ||
      g_rxBuffer[0] != kMagic0 ||
      g_rxBuffer[1] != kMagic1)
  {
    return 0U;
  }

  const uint16_t payloadLength =
      (static_cast<uint16_t>(g_rxBuffer[8]) << 8) |
      g_rxBuffer[9];
  if (payloadLength > kMaxWirePayloadLength)
  {
    return 0U;
  }

  return kHeaderLength + payloadLength + kCrcLength;
}

void expireIncompleteRxStream()
{
  if (g_rxLength == 0U || g_lastRxByteMs == 0U)
  {
    return;
  }

  const uint32_t idleMs = millis() - g_lastRxByteMs;
  if (idleMs < AppConfig::kLoraRxAssemblyTimeoutMs)
  {
    return;
  }

  SerialMon.print("LoRa RX wire timeout: buffered=");
  SerialMon.print(g_rxLength);
  const size_t expectedLength = expectedBufferedFrameLength();
  if (expectedLength > 0U)
  {
    SerialMon.print(" expected=");
    SerialMon.print(expectedLength);
  }
  SerialMon.print(" idle_ms=");
  SerialMon.println(idleMs);
  if (AppConfig::kEnableLoraErrorHexLogs)
  {
    printRawBytes("LoRa RX incomplete wire data", g_rxBuffer, g_rxLength);
  }

  ++g_timeoutDrops;
  g_rxLength = 0U;
  g_lastRxByteMs = 0U;
}

void drainLoraUart()
{
  bool receivedBytes = false;
  while (SerialLoRa.available() > 0)
  {
    const int value = SerialLoRa.read();
    if (value < 0)
    {
      break;
    }

    ++g_totalRawBytes;
    if (g_rxLength >= sizeof(g_rxBuffer))
    {
      SerialMon.println("LoRa software RX buffer overflow; resyncing");
      if (AppConfig::kEnableLoraErrorHexLogs)
      {
        printRawBytes("LoRa RX overflow data", g_rxBuffer, g_rxLength);
      }
      ++g_overflowDrops;
      g_rxLength = 0U;
    }

    g_rxBuffer[g_rxLength++] = static_cast<uint8_t>(value);
    g_lastRxByteMs = millis();
    receivedBytes = true;
  }

  // Drain hardware bytes first so a delayed packet is never discarded only
  // because MQTT or ESP-AT temporarily blocked the application loop.
  if (!receivedBytes)
  {
    expireIncompleteRxStream();
  }
}

bool writeLoraUartReliably(const uint8_t* data, size_t length)
{
  const uint32_t startMs = millis();
  for (size_t i = 0; i < length; ++i)
  {
    while (SerialLoRa.availableForWrite() <= 0)
    {
      if (millis() - startMs >= AppConfig::kLoraUartWriteTimeoutMs)
      {
        SerialMon.print("LoRa send failed: UART TX timeout after ");
        SerialMon.print(i);
        SerialMon.print('/');
        SerialMon.print(length);
        SerialMon.println(" bytes");
        return false;
      }
      yield();
    }

    if (SerialLoRa.write(data[i]) != 1U)
    {
      SerialMon.print("LoRa send failed: UART rejected byte index ");
      SerialMon.println(i);
      return false;
    }
  }

  SerialLoRa.flush();
  return true;
}

bool waitForAs32PacketComplete(uint32_t guardMs)
{
  const uint32_t busyStartMs = millis();
  bool sawBusy = false;
  while (millis() - busyStartMs < AppConfig::kLoraAuxBusyDetectTimeoutMs)
  {
    if (digitalRead(AppConfig::kLoraAuxPin) == LOW)
    {
      sawBusy = true;
      break;
    }
    delay(1);
  }

  if (sawBusy &&
      !AS32Config::waitForAuxHigh(
          AppConfig::kLoraAuxPin,
          AppConfig::kLoraTxCompleteTimeoutMs))
  {
    SerialMon.println("LoRa send failed: AS32 AUX remained busy");
    return false;
  }

  if (!sawBusy)
  {
    SerialMon.println("LoRa TX AUX busy pulse not observed; safety guard applied");
  }

  delay(guardMs);
  return true;
}

bool transmitWireFrame(
    LoraPayloadType type,
    uint16_t sourceNodeId,
    const uint8_t* payload,
    size_t payloadLength,
    uint32_t guardMs,
    bool verbose)
{
  if ((payload == nullptr && payloadLength > 0U) ||
      payloadLength > kMaxWirePayloadLength)
  {
    SerialMon.println("LoRa wire send failed: invalid payload length");
    return false;
  }

  serviceHardwareWatchdog(WatchdogStage::LoraTransmit);

  uint8_t frame[kMaxWireFrameLength];
  size_t offset = 0U;
  frame[offset++] = kMagic0;
  frame[offset++] = kMagic1;
  frame[offset++] = kFrameVersion;
  frame[offset++] = static_cast<uint8_t>((AppConfig::kLoraNetworkId >> 8) & 0xFFU);
  frame[offset++] = static_cast<uint8_t>(AppConfig::kLoraNetworkId & 0xFFU);
  frame[offset++] = static_cast<uint8_t>(type);
  frame[offset++] = static_cast<uint8_t>((sourceNodeId >> 8) & 0xFFU);
  frame[offset++] = static_cast<uint8_t>(sourceNodeId & 0xFFU);
  frame[offset++] = static_cast<uint8_t>((payloadLength >> 8) & 0xFFU);
  frame[offset++] = static_cast<uint8_t>(payloadLength & 0xFFU);
  if (payloadLength > 0U)
  {
    memcpy(frame + offset, payload, payloadLength);
  }
  offset += payloadLength;

  const uint16_t crc = crc16Ccitt(frame, offset);
  frame[offset++] = static_cast<uint8_t>((crc >> 8) & 0xFFU);
  frame[offset++] = static_cast<uint8_t>(crc & 0xFFU);

  if (offset > kMaxWireFrameLength)
  {
    SerialMon.println("LoRa wire send failed: frame exceeds safe AS32 limit");
    return false;
  }

  if (verbose && AppConfig::kEnableLoraFrameHexLogs)
  {
    printDecodedHeader(
        "LoRa TX wire header",
        kFrameVersion,
        AppConfig::kLoraNetworkId,
        type,
        sourceNodeId,
        payloadLength,
        offset,
        crc);
    printRawBytes("LoRa TX wire raw", frame, offset);
  }

  if (!AS32Config::waitForAuxHigh(
          AppConfig::kLoraAuxPin,
          AppConfig::kLoraTxCompleteTimeoutMs))
  {
    SerialMon.println("LoRa wire send failed: AS32 AUX was not ready");
    return false;
  }
  // AUX became ready: this is verified radio progress. Start a fresh IWDG
  // window before UART transfer instead of treating the complete multi-stage
  // send as one approximately 24-second blocking section.
  serviceHardwareWatchdog(WatchdogStage::LoraTransmit);

  if (!writeLoraUartReliably(frame, offset))
  {
    return false;
  }
  serviceHardwareWatchdog(WatchdogStage::LoraTransmit);

  if (!waitForAs32PacketComplete(guardMs))
  {
    return false;
  }
  serviceHardwareWatchdog(WatchdogStage::LoraTransmit);

  ++g_totalTxWireFrames;
  g_totalTxBytes += offset;
  return true;
}

bool extractWireFrame(LoraFrame& frame)
{
  while (g_rxLength >= 2U &&
         (g_rxBuffer[0] != kMagic0 || g_rxBuffer[1] != kMagic1))
  {
    ++g_noiseDrops;
    discardBytes(1U);
  }

  if (g_rxLength < kHeaderLength)
  {
    return false;
  }

  if (g_rxBuffer[2] != kFrameVersion)
  {
    SerialMon.print("LoRa wire dropped: unsupported version received=");
    SerialMon.println(g_rxBuffer[2]);
    printRxPrefix();
    ++g_versionDrops;
    discardBytes(1U);
    return false;
  }

  const uint16_t networkId =
      (static_cast<uint16_t>(g_rxBuffer[3]) << 8) |
      g_rxBuffer[4];
  if (networkId != AppConfig::kLoraNetworkId)
  {
    SerialMon.print("LoRa wire dropped: wrong network ID received=0x");
    printHexWord(networkId);
    SerialMon.print(" expected=0x");
    printHexWord(AppConfig::kLoraNetworkId);
    SerialMon.println();
    printRxPrefix();
    ++g_networkDrops;
    discardBytes(1U);
    return false;
  }

  const uint16_t payloadLength =
      (static_cast<uint16_t>(g_rxBuffer[8]) << 8) |
      g_rxBuffer[9];
  if (payloadLength > kMaxWirePayloadLength)
  {
    SerialMon.print("LoRa wire dropped: payload exceeds safe limit length=");
    SerialMon.println(payloadLength);
    printRxPrefix();
    ++g_lengthDrops;
    discardBytes(1U);
    return false;
  }

  const size_t totalLength = kHeaderLength + payloadLength + kCrcLength;
  if (g_rxLength < totalLength)
  {
    return false;
  }

  const uint16_t receivedCrc =
      (static_cast<uint16_t>(g_rxBuffer[totalLength - 2U]) << 8) |
      g_rxBuffer[totalLength - 1U];
  const uint16_t calculatedCrc =
      crc16Ccitt(g_rxBuffer, totalLength - kCrcLength);
  if (receivedCrc != calculatedCrc)
  {
    SerialMon.print("LoRa wire dropped: CRC mismatch received=0x");
    printHexWord(receivedCrc);
    SerialMon.print(" calculated=0x");
    printHexWord(calculatedCrc);
    SerialMon.println();
    printRxPrefix();
    if (AppConfig::kEnableLoraErrorHexLogs)
    {
      printRawBytes("LoRa RX rejected wire", g_rxBuffer, totalLength);
    }
    ++g_crcDrops;
    discardBytes(1U);
    return false;
  }

  frame.type = static_cast<LoraPayloadType>(g_rxBuffer[5]);
  frame.sourceNodeId =
      (static_cast<uint16_t>(g_rxBuffer[6]) << 8) |
      g_rxBuffer[7];
  frame.payloadLength = payloadLength;
  if (payloadLength > 0U)
  {
    memcpy(frame.payload, g_rxBuffer + kHeaderLength, payloadLength);
  }

  if (AppConfig::kEnableLoraFrameHexLogs &&
      frame.type != LoraPayloadType::TransportFragmentAck)
  {
    printDecodedHeader(
        "LoRa RX wire header",
        g_rxBuffer[2],
        networkId,
        frame.type,
        frame.sourceNodeId,
        payloadLength,
        totalLength,
        receivedCrc);
    printRawBytes("LoRa RX wire raw", g_rxBuffer, totalLength);
  }

  discardBytes(totalLength);
  ++g_totalRxWireFrames;
  return true;
}

bool enqueuePendingFrame(const LoraFrame& frame)
{
  if (g_pendingCount >= AppConfig::kLoraPendingFrameCount)
  {
    SerialMon.println("LoRa pending application queue full; frame dropped");
    ++g_pendingDrops;
    return false;
  }

  const size_t tail =
      (g_pendingHead + g_pendingCount) % AppConfig::kLoraPendingFrameCount;
  g_pendingFrames[tail] = frame;
  ++g_pendingCount;
  return true;
}

bool dequeuePendingFrame(LoraFrame& frame)
{
  if (g_pendingCount == 0U)
  {
    return false;
  }

  frame = g_pendingFrames[g_pendingHead];
  g_pendingHead =
      (g_pendingHead + 1U) % AppConfig::kLoraPendingFrameCount;
  --g_pendingCount;
  return true;
}

void resetReassemblyContext(ReassemblyContext& context)
{
  memset(&context, 0, sizeof(context));
}

ReassemblyContext* acquireReassemblyContext(
    uint16_t sourceNodeId,
    uint16_t messageId,
    LoraPayloadType originalType,
    uint8_t fragmentCount,
    uint16_t totalLength,
    uint16_t logicalCrc,
    uint8_t fragmentIndex)
{
  ReassemblyContext* inactive = nullptr;
  ReassemblyContext* sameSource = nullptr;
  ReassemblyContext* oldest = &g_reassembly[0];
  uint32_t oldestAge = 0U;
  const uint32_t now = millis();

  for (size_t i = 0; i < AppConfig::kLoraReassemblyContextCount; ++i)
  {
    ReassemblyContext& context = g_reassembly[i];
    if (context.active &&
        context.sourceNodeId == sourceNodeId &&
        context.messageId == messageId)
    {
      if (context.originalType != originalType ||
          context.fragmentCount != fragmentCount ||
          context.totalLength != totalLength ||
          context.logicalCrc != logicalCrc)
      {
        // A node can restart and reuse message ID 1 while an old partial
        // assembly is still alive. Fragment zero safely starts the new boot
        // session; later fragments may never replace an existing message.
        if (fragmentIndex != 0U)
        {
          SerialMon.println("LoRa fragment metadata changed inside one message; dropped");
          ++g_fragmentDrops;
          return nullptr;
        }

        SerialMon.print("LoRa reassembly restarted after node reset: source=");
        SerialMon.print(sourceNodeId);
        SerialMon.print(" message=");
        SerialMon.println(messageId);
        resetReassemblyContext(context);
        context.active = true;
        context.sourceNodeId = sourceNodeId;
        context.messageId = messageId;
        context.originalType = originalType;
        context.fragmentCount = fragmentCount;
        context.totalLength = totalLength;
        context.logicalCrc = logicalCrc;
        context.lastUpdateMs = now;
        return &context;
      }
      return &context;
    }

    if (!context.active && inactive == nullptr)
    {
      inactive = &context;
    }
    if (context.active && context.sourceNodeId == sourceNodeId)
    {
      sameSource = &context;
    }

    const uint32_t age = context.active ? (now - context.lastUpdateMs) : 0xFFFFFFFFUL;
    if (age > oldestAge)
    {
      oldestAge = age;
      oldest = &context;
    }
  }

  ReassemblyContext* selected = inactive != nullptr
      ? inactive
      : (sameSource != nullptr ? sameSource : oldest);
  if (selected->active)
  {
    SerialMon.print("LoRa reassembly context replaced: source=");
    SerialMon.print(selected->sourceNodeId);
    SerialMon.print(" message=");
    SerialMon.println(selected->messageId);
    ++g_fragmentDrops;
  }

  resetReassemblyContext(*selected);
  selected->active = true;
  selected->sourceNodeId = sourceNodeId;
  selected->messageId = messageId;
  selected->originalType = originalType;
  selected->fragmentCount = fragmentCount;
  selected->totalLength = totalLength;
  selected->logicalCrc = logicalCrc;
  selected->lastUpdateMs = now;
  return selected;
}

void expireReassemblyContexts()
{
  const uint32_t now = millis();
  for (size_t i = 0; i < AppConfig::kLoraReassemblyContextCount; ++i)
  {
    ReassemblyContext& context = g_reassembly[i];
    if (!context.active ||
        now - context.lastUpdateMs < AppConfig::kLoraFragmentAssemblyTimeoutMs)
    {
      continue;
    }

    SerialMon.print("LoRa fragment assembly timeout: source=");
    SerialMon.print(context.sourceNodeId);
    SerialMon.print(" message=");
    SerialMon.print(context.messageId);
    SerialMon.print(" mask=0x");
    printHexWord(context.receivedMask);
    SerialMon.println();
    ++g_fragmentTimeoutDrops;
    resetReassemblyContext(context);
  }
}

bool sendFragmentAck(
    uint16_t targetNodeId,
    uint16_t messageId,
    uint8_t fragmentIndex)
{
  uint8_t payload[kAckPayloadLength];
  payload[0] = static_cast<uint8_t>((targetNodeId >> 8) & 0xFFU);
  payload[1] = static_cast<uint8_t>(targetNodeId & 0xFFU);
  payload[2] = static_cast<uint8_t>((messageId >> 8) & 0xFFU);
  payload[3] = static_cast<uint8_t>(messageId & 0xFFU);
  payload[4] = fragmentIndex;

  SerialMon.print("LoRa TX fragment ACK: target=");
  SerialMon.print(targetNodeId);
  SerialMon.print(" message=");
  SerialMon.print(messageId);
  SerialMon.print(" part=");
  SerialMon.println(fragmentIndex + 1U);

  if (!transmitWireFrame(
          LoraPayloadType::TransportFragmentAck,
          localRadioNodeId(),
          payload,
          sizeof(payload),
          AppConfig::kLoraFinalPacketGuardMs,
          false))
  {
    return false;
  }

  ++g_fragmentAcksTx;
  return true;
}

void handleFragmentAck(const LoraFrame& wireFrame)
{
  if (wireFrame.payloadLength != kAckPayloadLength)
  {
    SerialMon.println("LoRa fragment ACK dropped: invalid length");
    ++g_fragmentDrops;
    return;
  }

  g_lastAck.valid = true;
  g_lastAck.ackSourceNodeId = wireFrame.sourceNodeId;
  g_lastAck.targetNodeId =
      (static_cast<uint16_t>(wireFrame.payload[0]) << 8) |
      wireFrame.payload[1];
  g_lastAck.messageId =
      (static_cast<uint16_t>(wireFrame.payload[2]) << 8) |
      wireFrame.payload[3];
  g_lastAck.fragmentIndex = wireFrame.payload[4];
  ++g_fragmentAcksRx;

  SerialMon.print("LoRa RX fragment ACK: from=");
  SerialMon.print(g_lastAck.ackSourceNodeId);
  SerialMon.print(" target=");
  SerialMon.print(g_lastAck.targetNodeId);
  SerialMon.print(" message=");
  SerialMon.print(g_lastAck.messageId);
  SerialMon.print(" part=");
  SerialMon.println(g_lastAck.fragmentIndex + 1U);
}

bool handleFragmentFrame(const LoraFrame& wireFrame, LoraFrame& completedFrame)
{
  if (wireFrame.payloadLength < kFragmentHeaderLength)
  {
    SerialMon.println("LoRa fragment dropped: metadata is incomplete");
    ++g_fragmentDrops;
    return false;
  }

  const LoraPayloadType originalType =
      static_cast<LoraPayloadType>(wireFrame.payload[0]);
  const uint16_t messageId =
      (static_cast<uint16_t>(wireFrame.payload[1]) << 8) |
      wireFrame.payload[2];
  const uint8_t fragmentIndex = wireFrame.payload[3];
  const uint8_t fragmentCount = wireFrame.payload[4];
  const uint16_t totalLength =
      (static_cast<uint16_t>(wireFrame.payload[5]) << 8) |
      wireFrame.payload[6];
  const uint16_t logicalCrc =
      (static_cast<uint16_t>(wireFrame.payload[7]) << 8) |
      wireFrame.payload[8];
  const size_t chunkLength = wireFrame.payloadLength - kFragmentHeaderLength;

  const size_t expectedFragmentCount = totalLength == 0U
      ? 1U
      : (totalLength + kFragmentDataLength - 1U) / kFragmentDataLength;
  const size_t fragmentOffset =
      static_cast<size_t>(fragmentIndex) * kFragmentDataLength;
  const size_t remaining = fragmentOffset < totalLength
      ? totalLength - fragmentOffset
      : 0U;
  const size_t expectedChunkLength = remaining < kFragmentDataLength
      ? remaining
      : kFragmentDataLength;

  if (!isApplicationType(originalType) ||
      messageId == 0U ||
      totalLength > sizeof(completedFrame.payload) ||
      fragmentCount == 0U ||
      fragmentCount > kMaxFragmentMaskBits ||
      expectedFragmentCount != fragmentCount ||
      fragmentIndex >= fragmentCount ||
      chunkLength != expectedChunkLength)
  {
    SerialMon.print("LoRa fragment dropped: invalid metadata source=");
    SerialMon.print(wireFrame.sourceNodeId);
    SerialMon.print(" message=");
    SerialMon.print(messageId);
    SerialMon.print(" part=");
    SerialMon.print(fragmentIndex + 1U);
    SerialMon.print('/');
    SerialMon.println(fragmentCount);
    ++g_fragmentDrops;
    return false;
  }

  ReassemblyContext* context = acquireReassemblyContext(
      wireFrame.sourceNodeId,
      messageId,
      originalType,
      fragmentCount,
      totalLength,
      logicalCrc,
      fragmentIndex);
  if (context == nullptr)
  {
    return false;
  }

  const uint16_t fragmentBit =
      static_cast<uint16_t>(1U << fragmentIndex);
  const bool duplicate = (context->receivedMask & fragmentBit) != 0U;
  if (!duplicate)
  {
    if (chunkLength > 0U)
    {
      memcpy(
          context->payload + fragmentOffset,
          wireFrame.payload + kFragmentHeaderLength,
          chunkLength);
    }
    context->receivedMask |= fragmentBit;
    context->bytesReceived += chunkLength;
  }
  context->lastUpdateMs = millis();

  SerialMon.print(duplicate ? "LoRa RX duplicate fragment: source="
                            : "LoRa RX fragment: source=");
  SerialMon.print(wireFrame.sourceNodeId);
  SerialMon.print(" message=");
  SerialMon.print(messageId);
  SerialMon.print(" part=");
  SerialMon.print(fragmentIndex + 1U);
  SerialMon.print('/');
  SerialMon.print(fragmentCount);
  SerialMon.print(" data=");
  SerialMon.print(chunkLength);
  SerialMon.print(" mask=0x");
  printHexWord(context->receivedMask);
  SerialMon.println();

#if APP_ROLE == APP_ROLE_LORA_GATEWAY
  if (wireFrame.sourceNodeId != AppConfig::kGatewayNodeId)
  {
    sendFragmentAck(wireFrame.sourceNodeId, messageId, fragmentIndex);
  }
#endif

  const uint16_t completeMask = static_cast<uint16_t>(
      (1UL << fragmentCount) - 1UL);
  if (context->receivedMask != completeMask ||
      context->bytesReceived != context->totalLength)
  {
    return false;
  }

  const uint16_t calculatedLogicalCrc =
      crc16Ccitt(context->payload, context->totalLength);
  if (calculatedLogicalCrc != context->logicalCrc)
  {
    SerialMon.print("LoRa logical message dropped: CRC mismatch source=");
    SerialMon.print(context->sourceNodeId);
    SerialMon.print(" message=");
    SerialMon.print(context->messageId);
    SerialMon.print(" received=0x");
    printHexWord(context->logicalCrc);
    SerialMon.print(" calculated=0x");
    printHexWord(calculatedLogicalCrc);
    SerialMon.println();
    ++g_fragmentDrops;
    resetReassemblyContext(*context);
    return false;
  }

  completedFrame.type = context->originalType;
  completedFrame.sourceNodeId = context->sourceNodeId;
  completedFrame.payloadLength = context->totalLength;
  if (context->totalLength > 0U)
  {
    memcpy(
        completedFrame.payload,
        context->payload,
        context->totalLength);
  }

  SerialMon.print("LoRa logical message complete: source=");
  SerialMon.print(context->sourceNodeId);
  SerialMon.print(" message=");
  SerialMon.print(context->messageId);
  SerialMon.print(" fragments=");
  SerialMon.print(context->fragmentCount);
  SerialMon.print(" payload=");
  SerialMon.println(context->totalLength);

  resetReassemblyContext(*context);
  return true;
}

void processWireFrame(const LoraFrame& wireFrame)
{
  if (wireFrame.type == LoraPayloadType::TransportFragmentAck)
  {
    handleFragmentAck(wireFrame);
    return;
  }

  LoraFrame logicalFrame;
  if (wireFrame.type == LoraPayloadType::TransportFragment)
  {
    if (!handleFragmentFrame(wireFrame, logicalFrame))
    {
      return;
    }
  }
  else
  {
    if (!isApplicationType(wireFrame.type))
    {
      SerialMon.print("LoRa wire dropped: unknown payload type=");
      SerialMon.println(static_cast<uint8_t>(wireFrame.type));
      ++g_fragmentDrops;
      return;
    }
    logicalFrame = wireFrame;
  }

  ++g_totalRxFrames;
  enqueuePendingFrame(logicalFrame);
}

void processIncomingWireFrames()
{
  drainLoraUart();
  expireReassemblyContexts();

  while (true)
  {
    const size_t beforeLength = g_rxLength;
    LoraFrame wireFrame;
    if (extractWireFrame(wireFrame))
    {
      processWireFrame(wireFrame);
      continue;
    }

    // An invalid header/CRC discards at least one byte. Continue immediately
    // so the next real magic word is recovered in the same application pass.
    if (g_rxLength < beforeLength)
    {
      continue;
    }
    break;
  }
}

bool waitForFragmentAck(
    uint16_t targetNodeId,
    uint16_t messageId,
    uint8_t fragmentIndex)
{
  // This loop is deliberately not serviced internally. A valid ACK or the
  // bounded 12-second timeout must return control to the caller first.
  serviceHardwareWatchdog(WatchdogStage::LoraAckWait);
  const uint32_t startMs = millis();
  while (millis() - startMs < AppConfig::kLoraFragmentAckTimeoutMs)
  {
    processIncomingWireFrames();
    if (g_lastAck.valid &&
        g_lastAck.ackSourceNodeId == AppConfig::kGatewayNodeId &&
        g_lastAck.targetNodeId == targetNodeId &&
        g_lastAck.messageId == messageId &&
        g_lastAck.fragmentIndex == fragmentIndex)
    {
      g_lastAck.valid = false;
      return true;
    }
    delay(2);
    yield();
  }

  ++g_fragmentAckTimeouts;
  return false;
}

uint16_t allocateMessageId()
{
  const uint16_t result = g_nextMessageId;
  ++g_nextMessageId;
  if (g_nextMessageId == 0U)
  {
    g_nextMessageId = 1U;
  }
  return result == 0U ? 1U : result;
}

bool nodeUplinkRequiresAck(uint16_t sourceNodeId)
{
#if APP_ROLE == APP_ROLE_SENSOR_NODE && APP_UPLINK == APP_UPLINK_LORA_TO_GATEWAY
  return sourceNodeId != AppConfig::kGatewayNodeId;
#else
  (void)sourceNodeId;
  return false;
#endif
}

void refreshRssiDiagnosticsIfSafe()
{
  if (!AppConfig::kLoraModuleSupportsRssi ||
      !AppConfig::kEnableAs32RssiDiagnostics ||
      g_totalRxWireFrames == 0U ||
      g_totalRxWireFrames == g_lastRssiQueryWireFrameCount)
  {
    return;
  }

  // Read-only RSSI replies share the radio UART with application data. Only
  // query after a complete transaction, with no UART/parser bytes pending.
  if (g_rxLength != 0U ||
      SerialLoRa.available() > 0 ||
      digitalRead(AppConfig::kLoraAuxPin) == LOW ||
      isLoraReceiveTransactionActive())
  {
    return;
  }

  const uint32_t sampledWireFrameCount = g_totalRxWireFrames;
  AS32Config::RssiReadings readings = {};
  const bool queried = AS32Config::queryRssi(
      SerialLoRa,
      AppConfig::kLoraAuxPin,
      readings);

  g_lastRssiQueryWireFrameCount = sampledWireFrameCount;
  if (!queried)
  {
    ++g_rssiQueryFailures;
    return;
  }

  ++g_rssiQuerySuccesses;
  if (readings.dataValid)
  {
    g_lastDataRssiValid = true;
    g_lastDataRssiDbm = readings.dataDbm;
    g_lastDataRssiRaw = readings.dataRaw;
  }
  if (readings.environmentValid)
  {
    g_lastEnvironmentRssiValid = true;
    g_lastEnvironmentRssiDbm = readings.environmentDbm;
    g_lastEnvironmentRssiRaw = readings.environmentRaw;
  }
}
}

void initializeLoraLink()
{
  pinMode(AppConfig::kLoraMd0Pin, OUTPUT);
  pinMode(AppConfig::kLoraMd1Pin, OUTPUT);
  pinMode(AppConfig::kLoraAuxPin, INPUT);

  AS32Config::printConfigSummary(SerialMon);
  AS32Config::applyConfigurationIfEnabled(
      SerialLoRa,
      SerialMon,
      AppConfig::kLoraMd0Pin,
      AppConfig::kLoraMd1Pin,
      AppConfig::kLoraAuxPin);

  digitalWrite(AppConfig::kLoraMd0Pin, LOW);
  digitalWrite(AppConfig::kLoraMd1Pin, LOW);
  delay(5);

  SerialLoRa.begin(AS32Config::kUartBaudRate, AS32Config::kSerialMode);
  delay(100);

  SerialMon.print("AS32 LoRa V1 reliable transport ready: network=0x");
  printHexWord(AppConfig::kLoraNetworkId);
  SerialMon.print(" RX=");
  SerialMon.print(AppConfig::kLoraRxPin);
  SerialMon.print(" TX=");
  SerialMon.print(AppConfig::kLoraTxPin);
  SerialMon.print(" baud=");
  SerialMon.println(AS32Config::kUartBaudRate);
  SerialMon.print("LoRa transport: wire_max=");
  SerialMon.print(kMaxWireFrameLength);
  SerialMon.print(" direct_payload=");
  SerialMon.print(kMaxWirePayloadLength);
  SerialMon.print(" fragment_data=");
  SerialMon.print(kFragmentDataLength);
  SerialMon.print(" UART_RX=");
  SerialMon.print(SERIAL_RX_BUFFER_SIZE);
  SerialMon.print(" UART_TX=");
  SerialMon.println(SERIAL_TX_BUFFER_SIZE);
  if (!AppConfig::kLoraModuleSupportsRssi)
  {
    SerialMon.println(
        "RSSI: unsupported by E32-TTL-100 UART firmware; dBm queries disabled");
  }
  serviceHardwareWatchdog();
}

void serviceLoraInput()
{
  processIncomingWireFrames();
}

bool isLoraReceiveTransactionActive()
{
  expireReassemblyContexts();
  const uint32_t now = millis();
  for (size_t i = 0; i < AppConfig::kLoraReassemblyContextCount; ++i)
  {
    const ReassemblyContext& context = g_reassembly[i];
    if (context.active &&
        now - context.lastUpdateMs < AppConfig::kLoraTransactionPriorityMs)
    {
      return true;
    }
  }
  return false;
}

bool isLoraIdleForPowerDown()
{
  processIncomingWireFrames();

  if (g_rxLength != 0U ||
      g_pendingCount != 0U ||
      SerialLoRa.available() > 0 ||
      digitalRead(AppConfig::kLoraAuxPin) == LOW)
  {
    return false;
  }

  for (size_t i = 0; i < AppConfig::kLoraReassemblyContextCount; ++i)
  {
    if (g_reassembly[i].active)
    {
      return false;
    }
  }

  return true;
}

bool prepareLoraForPowerDown(uint32_t timeoutMs)
{
  const uint32_t startMs = millis();
  while (!isLoraIdleForPowerDown())
  {
    // A completed command must return to pollLoraCommands() for processing;
    // never hide queued application data by entering sleep here.
    if (g_pendingCount != 0U || millis() - startMs >= timeoutMs)
    {
      return false;
    }

    serviceHardwareWatchdog();
    delay(2);
    yield();
  }

  SerialLoRa.flush();
  if (!AS32Config::waitForAuxHigh(AppConfig::kLoraAuxPin, timeoutMs))
  {
    return false;
  }

  // E32/AS32 Mode 3: M0=1, M1=1. The radio cannot receive RF data in this
  // mode, which is why this is used only after the command window closes.
  digitalWrite(AppConfig::kLoraMd0Pin, HIGH);
  digitalWrite(AppConfig::kLoraMd1Pin, HIGH);
  delay(10);
  if (!AS32Config::waitForAuxHigh(AppConfig::kLoraAuxPin, timeoutMs))
  {
    digitalWrite(AppConfig::kLoraMd0Pin, LOW);
    digitalWrite(AppConfig::kLoraMd1Pin, LOW);
    delay(10);
    return false;
  }

  SerialLoRa.end();
  return true;
}

bool prepareLoraForWakeOnRadio(uint32_t timeoutMs)
{
  if (!isLoraIdleForPowerDown()) return false;
  SerialLoRa.flush();
  if (!AS32Config::waitForAuxHigh(AppConfig::kLoraAuxPin, timeoutMs)) return false;
  // E32 Mode 2: M1=1, M0=0. RF listening remains possible; UART TX is off.
  digitalWrite(AppConfig::kLoraMd0Pin, LOW);
  digitalWrite(AppConfig::kLoraMd1Pin, HIGH);
  delay(5);
  if (!AS32Config::waitForAuxHigh(AppConfig::kLoraAuxPin, timeoutMs))
  {
    digitalWrite(AppConfig::kLoraMd1Pin, LOW);
    return false;
  }
  SerialLoRa.end();
  return true;
}

bool resumeLoraFromWakeOnRadio(uint32_t timeoutMs)
{
  // AUX may be low because the wake probe is being delivered. Wait for the
  // radio to finish it before changing mode; the probe is deliberately lost.
  if (!AS32Config::waitForAuxHigh(AppConfig::kLoraAuxPin, timeoutMs)) return false;
  SerialLoRa.begin(AS32Config::kUartBaudRate, AS32Config::kSerialMode);
  digitalWrite(AppConfig::kLoraMd1Pin, LOW);
  digitalWrite(AppConfig::kLoraMd0Pin, LOW);
  delay(5);
  return AS32Config::waitForAuxHigh(AppConfig::kLoraAuxPin, timeoutMs);
}

bool sendLoraWakeCommand(LoraPayloadType type, const uint8_t* payload, size_t length)
{
#if APP_ROLE == APP_ROLE_LORA_GATEWAY && APP_LORA_GATEWAY_WOR_TX
  if (type != LoraPayloadType::Command && type != LoraPayloadType::BroadcastCommand)
    return false;
  if (!AS32Config::waitForAuxHigh(AppConfig::kLoraAuxPin,
                                 AppConfig::kLoraTxCompleteTimeoutMs)) return false;
  // Mode 1 prefixes both the probe and command with the configured WOR
  // preamble. The probe buys time to restore the STM32 clock and UART.
  digitalWrite(AppConfig::kLoraMd0Pin, HIGH);
  digitalWrite(AppConfig::kLoraMd1Pin, LOW);
  delay(5);
  const bool probeSent = sendLoraFrame(LoraPayloadType::WakeProbe,
                                      AppConfig::kGatewayNodeId, nullptr, 0U);
  if (probeSent)
  {
    serviceHardwareWatchdog();
    delay(250);
  }
  const bool sent = probeSent && sendLoraFrame(type, AppConfig::kGatewayNodeId,
                                              payload, length);
  AS32Config::waitForAuxHigh(AppConfig::kLoraAuxPin,
                             AppConfig::kLoraTxCompleteTimeoutMs);
  digitalWrite(AppConfig::kLoraMd0Pin, LOW);
  delay(5);
  return sent;
#else
  return sendLoraFrame(type, AppConfig::kGatewayNodeId, payload, length);
#endif
}

void forceLoraPowerDownPins()
{
  pinMode(AppConfig::kLoraMd0Pin, OUTPUT);
  pinMode(AppConfig::kLoraMd1Pin, OUTPUT);
  pinMode(AppConfig::kLoraAuxPin, INPUT);
  digitalWrite(AppConfig::kLoraMd0Pin, HIGH);
  digitalWrite(AppConfig::kLoraMd1Pin, HIGH);
}

bool sendLoraFrame(
    LoraPayloadType type,
    uint16_t sourceNodeId,
    const uint8_t* payload,
    size_t payloadLength)
{
  serviceHardwareWatchdog();
  if ((payload == nullptr && payloadLength > 0U) ||
      payloadLength > sizeof(LoraFrame::payload) ||
      !isApplicationType(type))
  {
    SerialMon.println("LoRa send failed: invalid logical payload");
    return false;
  }

  const bool requireAck = nodeUplinkRequiresAck(sourceNodeId);
  const bool useFragments = requireAck || payloadLength > kMaxWirePayloadLength;
  if (!useFragments)
  {
    const bool transmitted = transmitWireFrame(
            type,
            sourceNodeId,
            payload,
            payloadLength,
            AppConfig::kLoraFinalPacketGuardMs,
            true);
    serviceHardwareWatchdog();
    if (!transmitted)
    {
      return false;
    }

    ++g_totalTxFrames;
    SerialMon.print("LoRa V1 logical message sent: fragments=1 payload=");
    SerialMon.println(payloadLength);
    return true;
  }

  const uint16_t messageId = allocateMessageId();
  const uint16_t logicalCrc = crc16Ccitt(payload, payloadLength);
  const uint8_t fragmentCount = static_cast<uint8_t>(payloadLength == 0U
      ? 1U
      : (payloadLength + kFragmentDataLength - 1U) / kFragmentDataLength);

  SerialMon.print("LoRa TX logical message: source=");
  SerialMon.print(sourceNodeId);
  SerialMon.print(" message=");
  SerialMon.print(messageId);
  SerialMon.print(" type=");
  SerialMon.print(static_cast<uint8_t>(type));
  SerialMon.print(" payload=");
  SerialMon.print(payloadLength);
  SerialMon.print(" fragments=");
  SerialMon.print(fragmentCount);
  SerialMon.print(" crc=0x");
  printHexWord(logicalCrc);
  SerialMon.println();

  for (uint8_t fragmentIndex = 0U;
       fragmentIndex < fragmentCount;
       ++fragmentIndex)
  {
    serviceHardwareWatchdog();
    const size_t fragmentOffset =
        static_cast<size_t>(fragmentIndex) * kFragmentDataLength;
    const size_t remaining = fragmentOffset < payloadLength
        ? payloadLength - fragmentOffset
        : 0U;
    const size_t chunkLength = remaining < kFragmentDataLength
        ? remaining
        : kFragmentDataLength;

    uint8_t fragmentPayload[kMaxWirePayloadLength];
    fragmentPayload[0] = static_cast<uint8_t>(type);
    fragmentPayload[1] = static_cast<uint8_t>((messageId >> 8) & 0xFFU);
    fragmentPayload[2] = static_cast<uint8_t>(messageId & 0xFFU);
    fragmentPayload[3] = fragmentIndex;
    fragmentPayload[4] = fragmentCount;
    fragmentPayload[5] = static_cast<uint8_t>((payloadLength >> 8) & 0xFFU);
    fragmentPayload[6] = static_cast<uint8_t>(payloadLength & 0xFFU);
    fragmentPayload[7] = static_cast<uint8_t>((logicalCrc >> 8) & 0xFFU);
    fragmentPayload[8] = static_cast<uint8_t>(logicalCrc & 0xFFU);
    if (chunkLength > 0U)
    {
      memcpy(
          fragmentPayload + kFragmentHeaderLength,
          payload + fragmentOffset,
          chunkLength);
    }
    const size_t fragmentPayloadLength =
        kFragmentHeaderLength + chunkLength;

    const uint8_t attempts = requireAck
        ? AppConfig::kLoraFragmentMaxAttempts
        : 1U;
    bool fragmentDelivered = false;
    for (uint8_t attempt = 1U; attempt <= attempts; ++attempt)
    {
      // Each ACK wait is bounded to 12 seconds, below the 25-second IWDG
      // deadline. Refresh only between attempts, never inside the wait loop.
      serviceHardwareWatchdog();
      SerialMon.print("LoRa TX fragment: message=");
      SerialMon.print(messageId);
      SerialMon.print(" part=");
      SerialMon.print(fragmentIndex + 1U);
      SerialMon.print('/');
      SerialMon.print(fragmentCount);
      SerialMon.print(" data=");
      SerialMon.print(chunkLength);
      SerialMon.print(" attempt=");
      SerialMon.print(attempt);
      SerialMon.print('/');
      SerialMon.println(attempts);

      g_lastAck.valid = false;
      const bool hasNextFragment = fragmentIndex + 1U < fragmentCount;
      const uint32_t guardMs = requireAck
          ? AppConfig::kLoraFinalPacketGuardMs
          : (hasNextFragment
              ? AppConfig::kLoraInterPacketGuardMs
              : AppConfig::kLoraFinalPacketGuardMs);
      const bool transmitted = transmitWireFrame(
              LoraPayloadType::TransportFragment,
              sourceNodeId,
              fragmentPayload,
              fragmentPayloadLength,
              guardMs,
              true);
      serviceHardwareWatchdog();
      if (!transmitted)
      {
        continue;
      }

      const bool acknowledged = !requireAck ||
          waitForFragmentAck(sourceNodeId, messageId, fragmentIndex);
      serviceHardwareWatchdog();
      if (acknowledged)
      {
        fragmentDelivered = true;
        if (requireAck && hasNextFragment)
        {
          // The ACK proves that the gateway received this part. Give both
          // half-duplex AS32 modules a quiet turnaround interval before the
          // next data fragment starts.
          delay(AppConfig::kLoraPostAckGuardMs);
          serviceHardwareWatchdog();
        }
        break;
      }

      if (attempt < attempts)
      {
        ++g_fragmentRetries;
        const uint32_t jitter = static_cast<uint32_t>(
            (sourceNodeId * 37U + messageId * 17U +
             fragmentIndex * 53U + attempt * 97U) % 251U);
        const uint32_t backoffMs =
            AppConfig::kLoraFragmentRetryBackoffMs + jitter;
        SerialMon.print("LoRa fragment ACK timeout; retrying after ");
        SerialMon.print(backoffMs);
        SerialMon.println(" ms");
        delay(backoffMs);
        serviceHardwareWatchdog();
      }
    }

    if (!fragmentDelivered)
    {
      SerialMon.print("LoRa logical send failed: message=");
      SerialMon.print(messageId);
      SerialMon.print(" part=");
      SerialMon.println(fragmentIndex + 1U);
      return false;
    }
  }

  ++g_totalTxFrames;
  SerialMon.print("LoRa V1 logical message sent: message=");
  SerialMon.print(messageId);
  SerialMon.print(" fragments=");
  SerialMon.print(fragmentCount);
  SerialMon.print(" payload=");
  SerialMon.println(payloadLength);
  serviceHardwareWatchdog();
  return true;
}

bool receiveLoraFrame(LoraFrame& frame)
{
  processIncomingWireFrames();
  return dequeuePendingFrame(frame);
}

void printLoraDiagnostics()
{
  refreshRssiDiagnosticsIfSafe();

  SerialMon.print("LoRa diag: raw=");
  SerialMon.print(g_totalRawBytes);
  SerialMon.print(" buffer=");
  SerialMon.print(g_rxLength);
  SerialMon.print(" noise=");
  SerialMon.print(g_noiseDrops);
  SerialMon.print(" version=");
  SerialMon.print(g_versionDrops);
  SerialMon.print(" network=");
  SerialMon.print(g_networkDrops);
  SerialMon.print(" length=");
  SerialMon.print(g_lengthDrops);
  SerialMon.print(" crc=");
  SerialMon.print(g_crcDrops);
  SerialMon.print(" overflow=");
  SerialMon.print(g_overflowDrops);
  SerialMon.print(" timeout=");
  SerialMon.print(g_timeoutDrops);
  SerialMon.print(" frag_drop=");
  SerialMon.print(g_fragmentDrops);
  SerialMon.print(" frag_timeout=");
  SerialMon.print(g_fragmentTimeoutDrops);
  SerialMon.print(" queue_drop=");
  SerialMon.print(g_pendingDrops);
  SerialMon.print(" rx_frames=");
  SerialMon.print(g_totalRxFrames);
  SerialMon.print(" tx_frames=");
  SerialMon.print(g_totalTxFrames);
  SerialMon.print(" wire_rx=");
  SerialMon.print(g_totalRxWireFrames);
  SerialMon.print(" wire_tx=");
  SerialMon.print(g_totalTxWireFrames);
  SerialMon.print(" ack_rx=");
  SerialMon.print(g_fragmentAcksRx);
  SerialMon.print(" ack_tx=");
  SerialMon.print(g_fragmentAcksTx);
  SerialMon.print(" retries=");
  SerialMon.print(g_fragmentRetries);
  SerialMon.print(" ack_timeout=");
  SerialMon.print(g_fragmentAckTimeouts);
  SerialMon.print(" tx_bytes=");
  SerialMon.print(g_totalTxBytes);
  if (!AppConfig::kLoraModuleSupportsRssi)
  {
    SerialMon.println(
        " last_rx_rssi=UNSUPPORTED ambient_rssi=UNSUPPORTED"
        " rssi_note=E32-TTL-100_has_no_UART_RSSI");
    return;
  }
  SerialMon.print(" last_rx_rssi=");
  if (g_lastDataRssiValid)
  {
    SerialMon.print(g_lastDataRssiDbm);
    SerialMon.print(" dBm(raw=");
    SerialMon.print(g_lastDataRssiRaw);
    SerialMon.print(')');
  }
  else
  {
    SerialMon.print("N/A dBm");
  }
  SerialMon.print(" ambient_rssi=");
  if (g_lastEnvironmentRssiValid)
  {
    SerialMon.print(g_lastEnvironmentRssiDbm);
    SerialMon.print(" dBm(raw=");
    SerialMon.print(g_lastEnvironmentRssiRaw);
    SerialMon.print(')');
  }
  else
  {
    SerialMon.print("N/A dBm");
  }
  SerialMon.print(" rssi_ok=");
  SerialMon.print(g_rssiQuerySuccesses);
  SerialMon.print(" rssi_fail=");
  SerialMon.println(g_rssiQueryFailures);
}

void printLoraFrameSummary(const LoraFrame& frame, const char* prefix)
{
  SerialMon.print(prefix);
  SerialMon.print(" type=");
  SerialMon.print(static_cast<uint8_t>(frame.type));
  SerialMon.print(" source=");
  SerialMon.print(frame.sourceNodeId);
  SerialMon.print(" payload=");
  SerialMon.print(frame.payloadLength);
  SerialMon.println(" bytes");
}
