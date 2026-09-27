/**
 * @file TelemetryPayload.h
 * @brief Shared encrypted status-payload builder for LoRa and MQTT paths.
 */
#ifndef TELEMETRY_PAYLOAD_H
#define TELEMETRY_PAYLOAD_H

#include <stddef.h>
#include <stdint.h>

/**
 * @brief Snapshot runtime measurements into an encrypted status frame.
 * @param payload Caller-owned frame buffer.
 * @param payloadCapacity Available output bytes.
 * @param payloadLength Receives the encoded frame size on success.
 * @return True if a complete status frame fits and was encoded.
 */
bool buildEncryptedStatusPayload(uint8_t* payload, size_t payloadCapacity, size_t& payloadLength);

#endif
