#ifndef PACKET_CODEC_H
#define PACKET_CODEC_H

#include <stddef.h>
#include <stdint.h>

#include "../third_party/nanopb/pb.h"
#include "../generated/sensor.pb.h"
bool encodeEncryptedMessage(
    const pb_msgdesc_t* fields,
    const void* srcStruct,
    uint8_t* output,
    size_t outputSize,
    size_t& outputLength);

bool decodeEncryptedCommandPayload(
    const uint8_t* payload,
    size_t payloadLength,
    CMD_Message& command);

#endif
