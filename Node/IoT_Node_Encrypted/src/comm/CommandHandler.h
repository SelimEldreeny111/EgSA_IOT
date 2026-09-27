/**
 * @file CommandHandler.h
 * @brief Decode and apply node commands received through MQTT or LoRa.
 */
#ifndef COMMAND_HANDLER_H
#define COMMAND_HANDLER_H

#include "../generated/sensor.pb.h"
#include <stddef.h>
#include <stdint.h>

/** @brief On-wire command identifiers shared with the server schema. */
enum CMD_ID : uint8_t {
  CMD_SET_SAMPLING_PERIOD = 1,
  CMD_SET_TRANSMISSION_PERIOD = 2,
  CMD_SYNC_RTC = 3,
  CMD_GET_TELEMETRY = 4,
  CMD_OPEN_CLOSE_NODE = 5
};

/**
 * @brief Validate and execute a decoded command for this node.
 * @param cmd Decoded command protobuf.
 * @param isBroadcastTopic Whether routing used the company broadcast topic.
 */
void handleCommand(const CMD_Message& cmd, bool isBroadcastTopic);
/**
 * @brief Build the encrypted telemetry reply requested by GOSTM.
 * @param cmd Request command, used to validate the addressed node.
 * @param payload Caller-owned output buffer for the encoded reply.
 * @param payloadLength Receives the produced frame length in bytes; the
 * caller must provide a buffer of at least AppConfig::kCodecBufferSize.
 * @return True when a valid encrypted reply was produced.
 */
bool handleGetTelemetryCommand(const CMD_Message* cmd, uint8_t* payload, size_t& payloadLength);

#endif
