#ifndef COMMAND_HANDLER_H
#define COMMAND_HANDLER_H

#include "../generated/sensor.pb.h"
#include <stddef.h>
#include <stdint.h>

enum CMD_ID : uint8_t {
  CMD_SET_SAMPLING_PERIOD = 1,
  CMD_SET_TRANSMISSION_PERIOD = 2,
  CMD_SYNC_RTC = 3,
  CMD_GET_TELEMETRY = 4,
  CMD_OPEN_CLOSE_NODE = 5
};

void handleCommand(const CMD_Message& cmd, bool isBroadcastTopic);
bool handleGetTelemetryCommand(const CMD_Message* cmd, uint8_t* payload, size_t& payloadLength);

#endif
