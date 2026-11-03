/** @file LoraLink.cpp @brief LoRa UART framing, addressing, receive, transmit, and link diagnostics. */
#define APP_LOG_MODULE "LORA"
#include "../platform/DebugLog.h"
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
constexpr uint16_t kMaxFragmentMaskBits = 32U;

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
  uint32_t receivedMask;
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

/** @brief Calculate the CCITT CRC used to reject corrupted LoRa wire frames. */
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

/** @brief Print one byte as two hexadecimal digits. */
void printHexByte(uint8_t value)
{
  if (value < 0x10U)
  {
    APP_DEBUG_PRINT('0');
  }
  APP_DEBUG_PRINT(value, HEX);
}

/** @brief Print a 16-bit word as four hexadecimal digits. */
void printHexWord(uint16_t value)
{
  printHexByte(static_cast<uint8_t>((value >> 8) & 0xFFU));
  printHexByte(static_cast<uint8_t>(value & 0xFFU));
}

/** @brief Print a zero-padded hexadecimal buffer offset. */
void printHexOffset(size_t value)
{
  if (value < 0x1000U)
  {
    APP_DEBUG_PRINT('0');
  }
  if (value < 0x0100U)
  {
    APP_DEBUG_PRINT('0');
  }
  if (value < 0x0010U)
  {
    APP_DEBUG_PRINT('0');
  }
  APP_DEBUG_PRINT(static_cast<unsigned long>(value), HEX);
}

/** @brief Dump a labeled byte buffer in 16-byte rows for diagnostics. */
void printRawBytes(const char* label, const uint8_t* data, size_t length)
{
  (void)label;
  APP_DEBUG_PRINT(label);
  APP_DEBUG_PRINT(" (");
  APP_DEBUG_PRINT(length);
  APP_DEBUG_PRINTLN(" bytes):");

  for (size_t i = 0; i < length; ++i)
  {
    if ((i % 16U) == 0U)
    {
      APP_DEBUG_PRINT("  ");
      printHexOffset(i);
      APP_DEBUG_PRINT(':');
    }

    APP_DEBUG_PRINT(' ');
    printHexByte(data[i]);

    if ((i % 16U) == 15U || i + 1U == length)
    {
      APP_DEBUG_PRINTLN();
    }
  }
}

/** @brief Print interpreted wire-header fields and the expected CRC. */
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
  (void)label; (void)version; (void)type; (void)sourceNodeId;
  (void)payloadLength; (void)totalLength;
  APP_DEBUG_PRINT(label);
  APP_DEBUG_PRINT(": version=");
  APP_DEBUG_PRINT(version);
  APP_DEBUG_PRINT(" network=0x");
  printHexWord(networkId);
  APP_DEBUG_PRINT(" type=");
  APP_DEBUG_PRINT(static_cast<uint8_t>(type));
  APP_DEBUG_PRINT(" source=");
  APP_DEBUG_PRINT(sourceNodeId);
  APP_DEBUG_PRINT(" payload=");
  APP_DEBUG_PRINT(payloadLength);
  APP_DEBUG_PRINT(" total=");
  APP_DEBUG_PRINT(totalLength);
  APP_DEBUG_PRINT(" crc=0x");
  printHexWord(crc);
  APP_DEBUG_PRINTLN();
}

/** @brief Print the first buffered RX bytes to help diagnose framing errors. */
void printRxPrefix()
{
  APP_DEBUG_PRINT("LoRa RX prefix:");
  const size_t count = g_rxLength < kDiagnosticPrefixLength
      ? g_rxLength
      : kDiagnosticPrefixLength;
  for (size_t i = 0; i < count; ++i)
  {
    APP_DEBUG_PRINT(' ');
    printHexByte(g_rxBuffer[i]);
  }
  APP_DEBUG_PRINTLN();
}

/** @brief Distinguish application frames from internal fragment transport types. */
bool isApplicationType(LoraPayloadType type)
{
  return type == LoraPayloadType::StatusTelemetry ||
         type == LoraPayloadType::Command ||
         type == LoraPayloadType::Ack ||
         type == LoraPayloadType::BroadcastCommand ||
         type == LoraPayloadType::SystemTelemetry ||
         type == LoraPayloadType::WakeProbe;
}

/** @brief Return the compiled node or gateway radio identity. */
uint16_t localRadioNodeId()
{
#if APP_ROLE == APP_ROLE_LORA_GATEWAY
  return AppConfig::kGatewayNodeId;
#else
  return AppConfig::kNodeId;
#endif
}

/** @brief Remove consumed or rejected bytes from the RX assembly buffer. */
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

/** @brief Infer total frame length from a valid buffered wire header. */
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

/** @brief Drop an unfinished wire frame after the RX assembly timeout. */
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

  APP_DEBUG_PRINT("LoRa RX wire timeout: buffered=");
  APP_DEBUG_PRINT(g_rxLength);
  const size_t expectedLength = expectedBufferedFrameLength();
  if (expectedLength > 0U)
  {
    APP_DEBUG_PRINT(" expected=");
    APP_DEBUG_PRINT(expectedLength);
  }
  APP_DEBUG_PRINT(" idle_ms=");
  APP_DEBUG_PRINTLN(idleMs);
  if (AppConfig::kEnableLoraErrorHexLogs)
  {
    printRawBytes("LoRa RX incomplete wire data", g_rxBuffer, g_rxLength);
  }

  ++g_timeoutDrops;
  g_rxLength = 0U;
  g_lastRxByteMs = 0U;
}

/** @brief Drain hardware UART bytes into the software frame buffer. */
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
      APP_DEBUG_PRINTLN("LoRa software RX buffer overflow; resyncing");
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

/** @brief Transmit every UART byte within a bounded write window. */
bool writeLoraUartReliably(const uint8_t* data, size_t length)
{
  const uint32_t startMs = millis();
  for (size_t i = 0; i < length; ++i)
  {
    while (SerialLoRa.availableForWrite() <= 0)
    {
      if (millis() - startMs >= AppConfig::kLoraUartWriteTimeoutMs)
      {
        APP_DEBUG_PRINT("LoRa send failed: UART TX timeout after ");
        APP_DEBUG_PRINT(i);
        APP_DEBUG_PRINT('/');
        APP_DEBUG_PRINT(length);
        APP_DEBUG_PRINTLN(" bytes");
        return false;
      }
      yield();
    }

    if (SerialLoRa.write(data[i]) != 1U)
    {
      APP_DEBUG_PRINT("LoRa send failed: UART rejected byte index ");
      APP_DEBUG_PRINTLN(i);
      return false;
    }
  }

  SerialLoRa.flush();
  return true;
}

/** @brief Wait for the AS32 AUX busy cycle, then apply a post-send guard. */
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
    APP_LOG_ERROR("LoRa send failed: AS32 AUX remained busy");
    return false;
  }

  if (!sawBusy)
  {
    APP_DEBUG_PRINTLN("LoRa TX AUX busy pulse not observed; safety guard applied");
  }

  delay(guardMs);
  return true;
}

/** @brief Encode one bounded wire frame, append CRC, and wait for radio completion. */
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
    APP_LOG_ERROR("LoRa wire send failed: invalid payload length");
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
    APP_LOG_ERROR("LoRa wire send failed: frame exceeds safe AS32 limit");
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
    APP_LOG_ERROR("LoRa wire send failed: AS32 AUX was not ready");
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

/** @brief Resynchronize RX bytes and validate one complete header, payload, and CRC. */
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
    APP_DEBUG_PRINT("LoRa wire dropped: unsupported version received=");
    APP_DEBUG_PRINTLN(g_rxBuffer[2]);
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
    APP_DEBUG_PRINT("LoRa wire dropped: wrong network ID received=0x");
    printHexWord(networkId);
    APP_DEBUG_PRINT(" expected=0x");
    printHexWord(AppConfig::kLoraNetworkId);
    APP_DEBUG_PRINTLN();
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
    APP_DEBUG_PRINT("LoRa wire dropped: payload exceeds safe limit length=");
    APP_DEBUG_PRINTLN(payloadLength);
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
    APP_DEBUG_PRINT("LoRa wire dropped: CRC mismatch received=0x");
    printHexWord(receivedCrc);
    APP_DEBUG_PRINT(" calculated=0x");
    printHexWord(calculatedCrc);
    APP_DEBUG_PRINTLN();
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

/** @brief Queue a complete application frame, reporting overflow drops. */
bool enqueuePendingFrame(const LoraFrame& frame)
{
  if (g_pendingCount >= AppConfig::kLoraPendingFrameCount)
  {
    APP_DEBUG_PRINTLN("LoRa pending application queue full; frame dropped");
    ++g_pendingDrops;
    return false;
  }

  const size_t tail =
      (g_pendingHead + g_pendingCount) % AppConfig::kLoraPendingFrameCount;
  g_pendingFrames[tail] = frame;
  ++g_pendingCount;
  return true;
}

/** @brief Take the oldest complete application frame from the pending queue. */
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

/** @brief Clear all state for one partially reassembled logical message. */
void resetReassemblyContext(ReassemblyContext& context)
{
  memset(&context, 0, sizeof(context));
}

/** @brief Reuse or select a bounded context for a fragmented logical message. */
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
          APP_DEBUG_PRINTLN("LoRa fragment metadata changed inside one message; dropped");
          ++g_fragmentDrops;
          return nullptr;
        }

        APP_DEBUG_PRINT("LoRa reassembly restarted after node reset: source=");
        APP_DEBUG_PRINT(sourceNodeId);
        APP_DEBUG_PRINT(" message=");
        APP_DEBUG_PRINTLN(messageId);
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
    APP_DEBUG_PRINT("LoRa reassembly context replaced: source=");
    APP_DEBUG_PRINT(selected->sourceNodeId);
    APP_DEBUG_PRINT(" message=");
    APP_DEBUG_PRINTLN(selected->messageId);
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

/** @brief Release incomplete logical messages after their fragment timeout. */
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

    APP_DEBUG_PRINT("LoRa fragment assembly timeout: source=");
    APP_DEBUG_PRINT(context.sourceNodeId);
    APP_DEBUG_PRINT(" message=");
    APP_DEBUG_PRINT(context.messageId);
    APP_DEBUG_PRINT(" mask=0x");
    APP_DEBUG_PRINT(context.receivedMask, HEX);
    APP_DEBUG_PRINTLN();
    ++g_fragmentTimeoutDrops;
    resetReassemblyContext(context);
  }
}

/** @brief Acknowledge one received fragment to the sending node. */
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

  APP_DEBUG_PRINT("LoRa TX fragment ACK: target=");
  APP_DEBUG_PRINT(targetNodeId);
  APP_DEBUG_PRINT(" message=");
  APP_DEBUG_PRINT(messageId);
  APP_DEBUG_PRINT(" part=");
  APP_DEBUG_PRINTLN(fragmentIndex + 1U);

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

/** @brief Validate and record a received transport-fragment ACK. */
void handleFragmentAck(const LoraFrame& wireFrame)
{
  if (wireFrame.payloadLength != kAckPayloadLength)
  {
    APP_DEBUG_PRINTLN("LoRa fragment ACK dropped: invalid length");
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

  APP_DEBUG_PRINT("LoRa RX fragment ACK: from=");
  APP_DEBUG_PRINT(g_lastAck.ackSourceNodeId);
  APP_DEBUG_PRINT(" target=");
  APP_DEBUG_PRINT(g_lastAck.targetNodeId);
  APP_DEBUG_PRINT(" message=");
  APP_DEBUG_PRINT(g_lastAck.messageId);
  APP_DEBUG_PRINT(" part=");
  APP_DEBUG_PRINTLN(g_lastAck.fragmentIndex + 1U);
}

/** @brief Validate, store, and reassemble fragments into an application frame. */
bool handleFragmentFrame(const LoraFrame& wireFrame, LoraFrame& completedFrame)
{
  if (wireFrame.payloadLength < kFragmentHeaderLength)
  {
    APP_DEBUG_PRINTLN("LoRa fragment dropped: metadata is incomplete");
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
    APP_DEBUG_PRINT("LoRa fragment dropped: invalid metadata source=");
    APP_DEBUG_PRINT(wireFrame.sourceNodeId);
    APP_DEBUG_PRINT(" message=");
    APP_DEBUG_PRINT(messageId);
    APP_DEBUG_PRINT(" part=");
    APP_DEBUG_PRINT(fragmentIndex + 1U);
    APP_DEBUG_PRINT('/');
    APP_DEBUG_PRINTLN(fragmentCount);
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

  const uint32_t fragmentBit = uint32_t(1) << fragmentIndex;
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

  APP_DEBUG_PRINT(duplicate ? "LoRa RX duplicate fragment: source="
                            : "LoRa RX fragment: source=");
  APP_DEBUG_PRINT(wireFrame.sourceNodeId);
  APP_DEBUG_PRINT(" message=");
  APP_DEBUG_PRINT(messageId);
  APP_DEBUG_PRINT(" part=");
  APP_DEBUG_PRINT(fragmentIndex + 1U);
  APP_DEBUG_PRINT('/');
  APP_DEBUG_PRINT(fragmentCount);
  APP_DEBUG_PRINT(" data=");
  APP_DEBUG_PRINT(chunkLength);
  APP_DEBUG_PRINT(" mask=0x");
  APP_DEBUG_PRINT(context->receivedMask, HEX);
  APP_DEBUG_PRINTLN();

#if APP_ROLE == APP_ROLE_LORA_GATEWAY
  if (wireFrame.sourceNodeId != AppConfig::kGatewayNodeId)
  {
    sendFragmentAck(wireFrame.sourceNodeId, messageId, fragmentIndex);
  }
#endif

  const uint32_t completeMask = fragmentCount == 32U ? UINT32_MAX :
      (uint32_t(1) << fragmentCount) - 1U;
  if (context->receivedMask != completeMask ||
      context->bytesReceived != context->totalLength)
  {
    return false;
  }

  const uint16_t calculatedLogicalCrc =
      crc16Ccitt(context->payload, context->totalLength);
  if (calculatedLogicalCrc != context->logicalCrc)
  {
    APP_DEBUG_PRINT("LoRa logical message dropped: CRC mismatch source=");
    APP_DEBUG_PRINT(context->sourceNodeId);
    APP_DEBUG_PRINT(" message=");
    APP_DEBUG_PRINT(context->messageId);
    APP_DEBUG_PRINT(" received=0x");
    printHexWord(context->logicalCrc);
    APP_DEBUG_PRINT(" calculated=0x");
    printHexWord(calculatedLogicalCrc);
    APP_DEBUG_PRINTLN();
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

  APP_LOG_INFO("rx_complete source=%u message=%u type=%s fragments=%u bytes=%u logical_crc=verified",
      context->sourceNodeId, context->messageId,
      WiotDebug::frameName(static_cast<uint8_t>(context->originalType)),
      context->fragmentCount, context->totalLength);

  resetReassemblyContext(*context);
  return true;
}

/** @brief Route a validated wire frame to ACK handling or the application queue. */
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
      APP_DEBUG_PRINT("LoRa wire dropped: unknown payload type=");
      APP_DEBUG_PRINTLN(static_cast<uint8_t>(wireFrame.type));
      ++g_fragmentDrops;
      return;
    }
    logicalFrame = wireFrame;
  }

  ++g_totalRxFrames;
  enqueuePendingFrame(logicalFrame);
}

/** @brief Drain UART bytes and repeatedly parse all complete wire frames. */
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

/** @brief Poll incoming frames until the expected fragment ACK or timeout. */
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

/** @brief Allocate a nonzero wrapping identifier for fragmented messages. */
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

/** @brief Decide whether this sensor-node uplink requires gateway ACKs. */
bool nodeUplinkRequiresAck(uint16_t sourceNodeId)
{
#if APP_ROLE == APP_ROLE_SENSOR_NODE && APP_UPLINK == APP_UPLINK_LORA_TO_GATEWAY
  return sourceNodeId != AppConfig::kGatewayNodeId;
#else
  (void)sourceNodeId;
  return false;
#endif
}

/** @brief Query module RSSI only when no frame transaction is active. */
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

  APP_DEBUG_ONLY(AS32Config::printConfigSummary(SerialMon));
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

  APP_DEBUG_PRINT("AS32 LoRa V1 reliable transport ready: network=0x");
  printHexWord(AppConfig::kLoraNetworkId);
  APP_DEBUG_PRINT(" RX=");
  APP_DEBUG_PRINT(AppConfig::kLoraRxPin);
  APP_DEBUG_PRINT(" TX=");
  APP_DEBUG_PRINT(AppConfig::kLoraTxPin);
  APP_DEBUG_PRINT(" baud=");
  APP_DEBUG_PRINTLN(AS32Config::kUartBaudRate);
  APP_DEBUG_PRINT("LoRa transport: wire_max=");
  APP_DEBUG_PRINT(kMaxWireFrameLength);
  APP_DEBUG_PRINT(" direct_payload=");
  APP_DEBUG_PRINT(kMaxWirePayloadLength);
  APP_DEBUG_PRINT(" fragment_data=");
  APP_DEBUG_PRINT(kFragmentDataLength);
  APP_DEBUG_PRINT(" UART_RX=");
  APP_DEBUG_PRINT(SERIAL_RX_BUFFER_SIZE);
  APP_DEBUG_PRINT(" UART_TX=");
  APP_DEBUG_PRINTLN(SERIAL_TX_BUFFER_SIZE);
  if (!AppConfig::kLoraModuleSupportsRssi)
  {
    APP_DEBUG_PRINTLN(
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

  // Timed Standby loses the UART state; WOR Stop keeps it (see below).
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
  // Keep RX enabled through the receive-arming boundary. HardwareSerial::end()
  // discards its RX ring; that would hide a packet received during the mode
  // transition. F401 Stop gates the UART peripheral clock automatically.
  return true;
}

bool resumeLoraFromWakeOnRadio(uint32_t timeoutMs)
{
  // AUX may be low because the wake probe is being delivered. Wait for the
  // radio to finish it before changing mode. The first probe may have been
  // missed while the STM32/UART clocks were stopped; the actual command follows.
  if (!AS32Config::waitForAuxHigh(AppConfig::kLoraAuxPin, timeoutMs)) return false;
  // The WOR path keeps this UART initialized. Do not reset its RX ring here;
  // bytes received before Stop or after clock restoration must reach the parser.
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
  APP_LOG_INFO("downlink_wake_begin mode=1 probe_then_command bytes=%lu", static_cast<unsigned long>(length));
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
  APP_LOG_INFO("downlink_wake_complete probe=%u command=%u mode_restored=0 node_execution=unconfirmed", probeSent, sent);
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
    APP_LOG_ERROR("LoRa send failed: invalid logical payload");
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
    APP_LOG_INFO("tx_complete source=%u type=%s fragments=1 bytes=%lu stage=radio_write_accepted peer_receipt=unconfirmed",
        sourceNodeId, WiotDebug::frameName(static_cast<uint8_t>(type)), static_cast<unsigned long>(payloadLength));
    return true;
  }

  const uint16_t messageId = allocateMessageId();
  const uint16_t logicalCrc = crc16Ccitt(payload, payloadLength);
  const uint8_t fragmentCount = static_cast<uint8_t>(payloadLength == 0U
      ? 1U
      : (payloadLength + kFragmentDataLength - 1U) / kFragmentDataLength);

  APP_LOG_INFO("tx_begin source=%u message=%u type=%s bytes=%lu fragments=%u ack_required=%u crc=0x%04X",
      sourceNodeId, messageId, WiotDebug::frameName(static_cast<uint8_t>(type)),
      static_cast<unsigned long>(payloadLength), fragmentCount, requireAck, logicalCrc);

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
      // Each ACK wait is bounded to 12 seconds, below the 30-second IWDG
      // deadline. Refresh only between attempts, never inside the wait loop.
      serviceHardwareWatchdog();
      APP_LOG_INFO("tx_fragment message=%u part=%u/%u bytes=%lu attempt=%u/%u",
          messageId, fragmentIndex + 1U, fragmentCount,
          static_cast<unsigned long>(chunkLength), attempt, attempts);

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
        APP_LOG_WARN("tx_retry message=%u part=%u reason=fragment_ack_timeout backoff_ms=%lu",
            messageId, fragmentIndex + 1U, static_cast<unsigned long>(backoffMs));
        delay(backoffMs);
        serviceHardwareWatchdog();
      }
    }

    if (!fragmentDelivered)
    {
      APP_LOG_ERROR("tx_failed source=%u message=%u part=%u/%u reason=fragment_attempts_exhausted",
          sourceNodeId, messageId, fragmentIndex + 1U, fragmentCount);
      return false;
    }
  }

  ++g_totalTxFrames;
  APP_LOG_INFO("tx_complete source=%u message=%u type=%s fragments=%u bytes=%lu stage=transport_acknowledged server_receipt=unconfirmed",
      sourceNodeId, messageId, WiotDebug::frameName(static_cast<uint8_t>(type)),
      fragmentCount, static_cast<unsigned long>(payloadLength));
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

  APP_DEBUG_PRINT("LoRa diag: raw=");
  APP_DEBUG_PRINT(g_totalRawBytes);
  APP_DEBUG_PRINT(" buffer=");
  APP_DEBUG_PRINT(g_rxLength);
  APP_DEBUG_PRINT(" noise=");
  APP_DEBUG_PRINT(g_noiseDrops);
  APP_DEBUG_PRINT(" version=");
  APP_DEBUG_PRINT(g_versionDrops);
  APP_DEBUG_PRINT(" network=");
  APP_DEBUG_PRINT(g_networkDrops);
  APP_DEBUG_PRINT(" length=");
  APP_DEBUG_PRINT(g_lengthDrops);
  APP_DEBUG_PRINT(" crc=");
  APP_DEBUG_PRINT(g_crcDrops);
  APP_DEBUG_PRINT(" overflow=");
  APP_DEBUG_PRINT(g_overflowDrops);
  APP_DEBUG_PRINT(" timeout=");
  APP_DEBUG_PRINT(g_timeoutDrops);
  APP_DEBUG_PRINT(" frag_drop=");
  APP_DEBUG_PRINT(g_fragmentDrops);
  APP_DEBUG_PRINT(" frag_timeout=");
  APP_DEBUG_PRINT(g_fragmentTimeoutDrops);
  APP_DEBUG_PRINT(" queue_drop=");
  APP_DEBUG_PRINT(g_pendingDrops);
  APP_DEBUG_PRINT(" rx_frames=");
  APP_DEBUG_PRINT(g_totalRxFrames);
  APP_DEBUG_PRINT(" tx_frames=");
  APP_DEBUG_PRINT(g_totalTxFrames);
  APP_DEBUG_PRINT(" wire_rx=");
  APP_DEBUG_PRINT(g_totalRxWireFrames);
  APP_DEBUG_PRINT(" wire_tx=");
  APP_DEBUG_PRINT(g_totalTxWireFrames);
  APP_DEBUG_PRINT(" ack_rx=");
  APP_DEBUG_PRINT(g_fragmentAcksRx);
  APP_DEBUG_PRINT(" ack_tx=");
  APP_DEBUG_PRINT(g_fragmentAcksTx);
  APP_DEBUG_PRINT(" retries=");
  APP_DEBUG_PRINT(g_fragmentRetries);
  APP_DEBUG_PRINT(" ack_timeout=");
  APP_DEBUG_PRINT(g_fragmentAckTimeouts);
  APP_DEBUG_PRINT(" tx_bytes=");
  APP_DEBUG_PRINT(g_totalTxBytes);
  if (!AppConfig::kLoraModuleSupportsRssi)
  {
    APP_DEBUG_PRINTLN(
        " last_rx_rssi=UNSUPPORTED ambient_rssi=UNSUPPORTED"
        " rssi_note=E32-TTL-100_has_no_UART_RSSI");
    return;
  }
  APP_DEBUG_PRINT(" last_rx_rssi=");
  if (g_lastDataRssiValid)
  {
    APP_DEBUG_PRINT(g_lastDataRssiDbm);
    APP_DEBUG_PRINT(" dBm(raw=");
    APP_DEBUG_PRINT(g_lastDataRssiRaw);
    APP_DEBUG_PRINT(')');
  }
  else
  {
    APP_DEBUG_PRINT("N/A dBm");
  }
  APP_DEBUG_PRINT(" ambient_rssi=");
  if (g_lastEnvironmentRssiValid)
  {
    APP_DEBUG_PRINT(g_lastEnvironmentRssiDbm);
    APP_DEBUG_PRINT(" dBm(raw=");
    APP_DEBUG_PRINT(g_lastEnvironmentRssiRaw);
    APP_DEBUG_PRINT(')');
  }
  else
  {
    APP_DEBUG_PRINT("N/A dBm");
  }
  APP_DEBUG_PRINT(" rssi_ok=");
  APP_DEBUG_PRINT(g_rssiQuerySuccesses);
  APP_DEBUG_PRINT(" rssi_fail=");
  APP_DEBUG_PRINTLN(g_rssiQueryFailures);
}

void printLoraFrameSummary(const LoraFrame& frame, const char* prefix)
{
  (void)frame; (void)prefix;
  APP_LOG_INFO("%s source=%u type=%s(%u) bytes=%lu",
      prefix, frame.sourceNodeId, WiotDebug::frameName(static_cast<uint8_t>(frame.type)),
      static_cast<unsigned>(frame.type), static_cast<unsigned long>(frame.payloadLength));
}
