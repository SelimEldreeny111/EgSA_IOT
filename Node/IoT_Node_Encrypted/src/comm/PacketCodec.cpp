/** @file PacketCodec.cpp @brief Protobuf encoding and AES-CBC wire-envelope processing. */
#define APP_LOG_MODULE "CODEC"
#include "../platform/DebugLog.h"
#include "PacketCodec.h"
#include "ReplyDiagnostics.h"

#include <Arduino.h>
#include <AESLib.h>
#include <string.h>

#include "../config/AppConfig.h"
#include "../config/AppSecrets.h"
#include "../third_party/nanopb/pb_decode.h"
#include "../third_party/nanopb/pb_encode.h"

extern HardwareSerial SerialMon;

namespace {
constexpr size_t kMaximumPaddedProtobufSize =
    ((SENSOR_PB_H_MAX_SIZE / AppConfig::kAesBlockSize) + 1U) *
    AppConfig::kAesBlockSize;
constexpr size_t kMaximumEncryptedEnvelopeSize =
    1U + AppConfig::kIvLength + kMaximumPaddedProtobufSize;
static_assert(
    kMaximumEncryptedEnvelopeSize <= AppConfig::kCodecBufferSize,
    "kCodecBufferSize is too small for the largest protobuf AES envelope");

AESLib g_aesLib;

byte g_aesKey[AppConfig::kAesBlockSize] = WIOT_AES_KEY_BYTES;

/**
 * @brief Derive the outgoing CBC IV from runtime timer and counter values.
 * @warning This derivation is not a cryptographically secure random generator;
 *          do not treat the envelope as providing authenticated encryption.
 */
void generatePacketIv(byte* iv)
{
    static uint32_t packetCounter = 0;
    const uint32_t nowMicros = micros();
    const uint32_t nowMillis = millis();
    const uintptr_t stackAddr = reinterpret_cast<uintptr_t>(&packetCounter);

    for (size_t i = 0; i < AppConfig::kIvLength; ++i) 
    {
        const uint32_t mix =
            nowMicros +
            (nowMillis << (i % 5)) +
            (packetCounter * 0x9E3779B9UL) +
            static_cast<uint32_t>(stackAddr >> ((i % sizeof(uintptr_t)) * 8)) +
            static_cast<uint32_t>(i * 0x45U);
        iv[i] = static_cast<byte>((mix >> ((i % 4) * 8)) & 0xFF);
    }

    ++packetCounter;
}

/** @brief Encrypt a buffer with AESLib, copying the IV because the library mutates it. */
int encryptBuffer(uint8_t* input, int length, uint8_t* output, const byte* iv)
{
    byte ivCopy[AppConfig::kIvLength];
    memcpy(ivCopy, iv, sizeof(ivCopy));

    return g_aesLib.encrypt(input, length, output, g_aesKey, sizeof(g_aesKey), ivCopy);
}

/** @brief Decrypt a buffer with AESLib, preserving the caller's IV. */
int decryptBuffer(uint8_t* input, int length, uint8_t* output, const byte* iv)
{
    byte ivCopy[AppConfig::kIvLength];
    memcpy(ivCopy, iv, sizeof(ivCopy));

    return g_aesLib.decrypt(input, length, output, g_aesKey, sizeof(g_aesKey), ivCopy);
}
}

bool encodeEncryptedMessage(
    const pb_msgdesc_t* fields,
    const void* srcStruct,
    uint8_t* output,
    size_t outputSize,
    size_t& outputLength)
{
    uint8_t encoded[AppConfig::kCodecBufferSize];
    pb_ostream_t stream = pb_ostream_from_buffer(encoded, sizeof(encoded));

    if (!pb_encode(&stream, fields, srcStruct)) 
    {
        APP_LOG_ERROR("Encode FAILED");
        return false;
    }

    byte packetIv[AppConfig::kIvLength];
    generatePacketIv(packetIv);

    uint8_t plain[AppConfig::kCodecBufferSize];
    memcpy(plain, encoded, stream.bytes_written);

    size_t totalLength = stream.bytes_written;
    size_t padding = AppConfig::kAesBlockSize - (totalLength % AppConfig::kAesBlockSize);
    if (padding == 0) {
        padding = AppConfig::kAesBlockSize;
    }

    if (totalLength + padding > sizeof(plain)) 
    {
        APP_DEBUG_PRINTLN("Plain buffer overflow");
        return false;
    }

    for (size_t i = 0; i < padding; ++i) 
    {
        plain[totalLength + i] = static_cast<uint8_t>(padding);
    }
    totalLength += padding;

    uint8_t encrypted[AppConfig::kCodecBufferSize];
    const int encryptedLength = encryptBuffer(plain, static_cast<int>(totalLength), encrypted, packetIv);
    if (encryptedLength <= 0) {
        APP_LOG_ERROR("Encrypt FAILED");
        return false;
    }

    if (static_cast<size_t>(encryptedLength + AppConfig::kIvLength + 1) > outputSize) 
    {
        APP_DEBUG_PRINTLN("Output buffer too small");
        return false;
    }

    output[0] = AppConfig::kProtocolVersion;
    memcpy(output + 1, packetIv, AppConfig::kIvLength);
    memcpy(output + 1 + AppConfig::kIvLength, encrypted, encryptedLength);
    outputLength = static_cast<size_t>(encryptedLength + AppConfig::kIvLength + 1);
#if APP_DEBUG_FULL_ENABLED
    if (fields == Telemetry_fields) {
        logReplyData("TX", *static_cast<const Telemetry*>(srcStruct), output, outputLength);
    }
#endif
    return true;
}

namespace {
/** @brief Unwrap the current version/IV/CBC envelope and decode a protobuf. */
bool decodeEncryptedMessage(const uint8_t* payload, size_t payloadLength,
                            const pb_msgdesc_t* fields, void* message)
{
    constexpr size_t envelopeHeaderSize = 1U + AppConfig::kIvLength;
    if (!payload || payloadLength < envelopeHeaderSize + AppConfig::kAesBlockSize ||
        payloadLength > AppConfig::kCodecBufferSize) {
        APP_DEBUG_PRINTLN("Invalid encrypted payload length");
        return false;
    }
    if (payload[0] != AppConfig::kProtocolVersion) {
        APP_DEBUG_PRINTLN("Unsupported protocol version");
        return false;
    }
    const size_t encryptedLength = payloadLength - envelopeHeaderSize;
    if (encryptedLength % AppConfig::kAesBlockSize != 0) {
        APP_DEBUG_PRINTLN("Invalid encrypted block length");
        return false;
    }

    uint8_t encrypted[AppConfig::kCodecBufferSize];
    memcpy(encrypted, payload + envelopeHeaderSize, encryptedLength);
    uint8_t decrypted[AppConfig::kCodecBufferSize];
    const int decryptedLength = decryptBuffer(
        encrypted, static_cast<int>(encryptedLength), decrypted, payload + 1);
    if (decryptedLength <= 0 || static_cast<size_t>(decryptedLength) > encryptedLength) {
        APP_DEBUG_PRINTLN("Decrypt FAILED");
        return false;
    }

    const uint8_t padding = decrypted[decryptedLength - 1];
    if (padding == 0 || padding > AppConfig::kAesBlockSize || padding >= decryptedLength) {
        APP_DEBUG_PRINTLN("Invalid padding or empty message body");
        return false;
    }
    const int dataLength = decryptedLength - padding;
    for (int i = dataLength; i < decryptedLength; ++i) {
        if (decrypted[i] != padding) {
            APP_DEBUG_PRINTLN("Corrupted padding");
            return false;
        }
    }

    pb_istream_t stream = pb_istream_from_buffer(decrypted, static_cast<size_t>(dataLength));
    return pb_decode(&stream, fields, message);
}
}

bool decodeEncryptedCommandPayload(const uint8_t* payload, size_t payloadLength,
                                   CMD_Message& command)
{
    command = CMD_Message_init_zero;
    return decodeEncryptedMessage(payload, payloadLength, CMD_Message_fields, &command);
}

bool decodeEncryptedTelemetryPayload(const uint8_t* payload, size_t payloadLength,
                                     Telemetry& telemetry)
{
    telemetry = Telemetry_init_zero;
    return decodeEncryptedMessage(payload, payloadLength, Telemetry_fields, &telemetry);
}
