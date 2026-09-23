#ifndef TELEMETRY_PAYLOAD_H
#define TELEMETRY_PAYLOAD_H

#include <stddef.h>
#include <stdint.h>

bool buildEncryptedStatusPayload(uint8_t *payload, size_t payloadCapacity, size_t &payloadLength);

#endif
