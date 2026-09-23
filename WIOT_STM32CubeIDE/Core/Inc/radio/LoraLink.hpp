#ifndef LORA_LINK_H
#define LORA_LINK_H

#include <stddef.h>
#include <stdint.h>

enum class LoraPayloadType : uint8_t
{
  StatusTelemetry = 1,
  Command = 2,
  Ack = 3,
  BroadcastCommand = 4,
  SystemTelemetry = 5,
  TransportFragment = 0xF0,
  TransportFragmentAck = 0xF1,
};

struct LoraFrame
{
  LoraPayloadType type;
  uint16_t sourceNodeId;
  uint8_t payload[256];
  size_t payloadLength;
};

void initializeLoraLink();
void serviceLoraInput();
bool isLoraReceiveTransactionActive();
bool sendLoraFrame(LoraPayloadType type, uint16_t sourceNodeId, const uint8_t* payload, size_t payloadLength);
bool receiveLoraFrame(LoraFrame& frame);
void printLoraFrameSummary(const LoraFrame& frame, const char* prefix);
void printLoraDiagnostics();

#endif
