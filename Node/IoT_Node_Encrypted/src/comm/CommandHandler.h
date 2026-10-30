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
  CMD_OPEN_CLOSE_NODE = 5,
  CMD_REMOTE_WAKE = 6, // data: active seconds, 0=configured default, max=86400
  CMD_CLEAR_POWER_RESETS = 7, // direct node only; data=0, nonzero request_id
  CMD_CLEAR_WDT_RESETS = 8,   // direct node only; data=0, nonzero request_id
  CMD_CLEAR_FLASH = 9,
  CMD_FLASH_STATUS = 10,
  CMD_FLASH_LAST = 11,
  CMD_FLASH_TODAY = 12,
  CMD_FLASH_CANCEL = 13,
  CMD_HISTORY_ACK = 14
};

/** @brief Shared SIM/WiFi/LoRa automatic-reply policy; GOSTM always responds.
 * @param commandId Decoded command identifier.
 * @param ackRepliesEnabled Compile-time application ACK setting.
 * @return True for explicit telemetry requests or enabled action ACKs.
 */
constexpr bool shouldSendCommandTelemetryReply(uint32_t commandId, bool ackRepliesEnabled)
{
  return commandId != CMD_HISTORY_ACK && (commandId == CMD_GET_TELEMETRY ||
      commandId == CMD_FLASH_STATUS || commandId == CMD_FLASH_LAST ||
      commandId == CMD_FLASH_TODAY || ackRepliesEnabled);
}

/** @brief Apply an addressed command. @param cmd Decoded command. @param isBroadcastTopic True for company broadcast. @return True only when successfully applied. */
bool handleCommand(const CMD_Message& cmd, bool isBroadcastTopic);
/** @brief Apply a WAKE lease before constructing its reply. @param cmd Decoded WAKE. @param isBroadcastTopic True for company broadcast. @return True when accepted. */
bool handleRemoteWakeCommand(const CMD_Message& cmd, bool isBroadcastTopic);
/** @brief Encode a Telemetry/ACK using the latest cached sensor state.
 * @param cmd Request and correlation fields, or null for legacy telemetry.
 * @param payload Output buffer of at least AppConfig::kCodecBufferSize bytes.
 * @param payloadLength Receives the encoded frame length.
 * @param commandApplied Application success reported in correlated ACK fields.
 * @return True when the encrypted reply is built, not when delivered.
 */
bool handleGetTelemetryCommand(const CMD_Message* cmd, uint8_t* payload,
                               size_t& payloadLength, bool commandApplied = true);

#endif
