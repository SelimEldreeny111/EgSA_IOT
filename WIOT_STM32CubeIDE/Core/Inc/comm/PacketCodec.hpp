#ifndef WIOT_PACKET_CODEC_HPP
#define WIOT_PACKET_CODEC_HPP

#include "generated/sensor.pb.h"
#include "pb.h"

#include <cstddef>
#include <cstdint>

bool encodeEncryptedMessage(
    const pb_msgdesc_t *fields,
    const void *source,
    uint8_t *output,
    size_t outputSize,
    size_t &outputLength);

bool decodeEncryptedCommandPayload(
    const uint8_t *payload,
    size_t payloadLength,
    CMD_Message &command);

#endif
