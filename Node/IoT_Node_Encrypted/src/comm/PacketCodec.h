/**
 * @file PacketCodec.h
 * @brief Nanopb serialization and AES-CBC project frame handling.
 *
 * The codec owns the project-specific version/IV/ciphertext envelope. It does
 * not select MQTT or LoRa routing. This frame has no message authentication
 * tag; successful decryption alone does not prove the sender's identity.
 */
#ifndef PACKET_CODEC_H
#define PACKET_CODEC_H

#include <stddef.h>
#include <stdint.h>

#include "../third_party/nanopb/pb.h"
#include "../generated/sensor.pb.h"
/**
 * @brief Serialize a protobuf message and wrap it in an encrypted frame.
 * @param fields Nanopb descriptor for the supplied message type.
 * @param srcStruct Address of the concrete message object.
 * @param output Caller-owned ciphertext frame buffer.
 * @param outputSize Capacity of @p output in bytes.
 * @param outputLength Receives the complete frame length on success.
 * @return True only if serialization, padding, and encryption all succeed.
 */
bool encodeEncryptedMessage(
    const pb_msgdesc_t* fields,
    const void* srcStruct,
    uint8_t* output,
    size_t outputSize,
    size_t& outputLength);

/**
 * @brief Validate, decrypt, and parse an incoming command frame.
 * @param payload Complete encrypted project frame.
 * @param payloadLength Frame size in bytes.
 * @param command Receives the decoded command on success.
 * @return True if the frame and protobuf command are valid.
 */
bool decodeEncryptedCommandPayload(
    const uint8_t* payload,
    size_t payloadLength,
    CMD_Message& command);

#endif
