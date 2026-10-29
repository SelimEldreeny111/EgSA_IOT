/**
 * @file LoraLink.h
 * @brief E32/AS32 LoRa transport framing, receive service, and power control.
 */
#ifndef LORA_LINK_H
#define LORA_LINK_H

#include <stddef.h>
#include <stdint.h>

#include "../config/AppConfig.h"

enum class LoraPayloadType : uint8_t
{
  StatusTelemetry = 1,
  Command = 2,
  Ack = 3,
  BroadcastCommand = 4,
  SystemTelemetry = 5,
  WakeProbe = 6,  // Mode-1 preamble/probe wakes a Stop-mode node before CMD
  TransportFragment = 0xF0,
  TransportFragmentAck = 0xF1,
};

/** @brief Decoded LoRa frame with source identity and bounded payload buffer. */
struct LoraFrame
{
  LoraPayloadType type;
  uint16_t sourceNodeId;
  uint8_t payload[AppConfig::kCodecBufferSize];
  size_t payloadLength;
};

/** @brief Initialize module pins, serial settings, and link state. */
void initializeLoraLink();
/** @brief Consume incoming UART bytes and advance frame/fragment processing. */
void serviceLoraInput();
/** @brief Query whether a multi-part receive transaction is in progress. @return True while the receiver owns an incomplete transaction. */
bool isLoraReceiveTransactionActive();
/** @brief Check whether the link can safely enter its configured sleep mode. @return True only when no in-flight work requires the radio. */
bool isLoraIdleForPowerDown();
/** @brief Quiesce the radio within a deadline. @param timeoutMs Maximum wait for in-flight work and AUX readiness. @return True if radio sleep preparation succeeded. */
bool prepareLoraForPowerDown(uint32_t timeoutMs);
/** Enter E32 Mode 2; retain UART RX so arming does not discard received data. */
bool prepareLoraForWakeOnRadio(uint32_t timeoutMs);
/** Return from E32 Mode 2 to normal bidirectional Mode 0. */
bool resumeLoraFromWakeOnRadio(uint32_t timeoutMs);
/** Gateway Mode-1 probe followed by the actual command. */
bool sendLoraWakeCommand(LoraPayloadType type, const uint8_t* payload, size_t length);
void forceLoraPowerDownPins();
/** @brief Frame and transmit an application payload, fragmenting when required. @param type Payload classification. @param sourceNodeId Claimed source node identity. @param payload Payload bytes. @param payloadLength Byte count. @return True only after the transport accepts the complete frame. */
bool sendLoraFrame(LoraPayloadType type, uint16_t sourceNodeId, const uint8_t* payload, size_t payloadLength);
/** @brief Retrieve a completed received frame. @param frame Receives frame fields and payload. @return True when a complete frame was available. */
bool receiveLoraFrame(LoraFrame& frame);
/** @brief Print a concise frame diagnostic. @param frame Frame to describe. @param prefix Label placed before the frame details. */
void printLoraFrameSummary(const LoraFrame& frame, const char* prefix);
/** @brief Print current module/link counters and RSSI diagnostics. */
void printLoraDiagnostics();

#endif
