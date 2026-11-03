/** @file PacketCodec.cpp @brief Protobuf encoding and AES-CBC wire-envelope processing. */
#define APP_LOG_MODULE "CODEC"
#include "../platform/DebugLog.h"
#include "PacketCodec.h"

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

const byte g_legacyAesIv[AppConfig::kIvLength] = 
{
    0x21, 0x43, 0x65, 0x87,
    0x09, 0xBA, 0xDC, 0xFE,
    0x11, 0x22, 0x33, 0x44,
    0x55, 0x66, 0x77, 0x88
};

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
    return true;
}

bool decodeEncryptedCommandPayload(
    const uint8_t* payload,
    size_t payloadLength,
    CMD_Message& command)
{
    if (payloadLength < 2 || payloadLength > AppConfig::kCodecBufferSize) 
    {
        APP_DEBUG_PRINTLN("Invalid payload length");
        return false;
    }

    const uint8_t protocolVersion = payload[0];
    if (protocolVersion != AppConfig::kProtocolVersion) {
        APP_DEBUG_PRINTLN("Unsupported protocol version");
        return false;
    }

    uint8_t encrypted[AppConfig::kCodecBufferSize];
    byte packetIv[AppConfig::kIvLength];
    size_t encryptedOffset = 1;
    size_t encodedOffset = 0;

    if (protocolVersion == AppConfig::kProtocolVersion) {
        if (payloadLength < (1 + AppConfig::kIvLength + AppConfig::kAesBlockSize)) {
            APP_DEBUG_PRINTLN("Invalid v2 payload length");
            return false;
        }

        memcpy(packetIv, payload + 1, AppConfig::kIvLength);
        encryptedOffset += AppConfig::kIvLength;
    } else {
        memcpy(packetIv, g_legacyAesIv, AppConfig::kIvLength);
        encodedOffset = AppConfig::kIvLength;
    }

    const size_t encryptedLength = payloadLength - encryptedOffset;
    memcpy(encrypted, payload + encryptedOffset, encryptedLength);

    uint8_t decrypted[AppConfig::kCodecBufferSize];
    const int decryptedLength = decryptBuffer(encrypted, static_cast<int>(encryptedLength), decrypted, packetIv);
    if (decryptedLength <= 0) {
        APP_LOG_ERROR("Decrypt FAILED");
        return false;
    }

    const uint8_t padding = decrypted[decryptedLength - 1];
    if (padding == 0 || padding > AppConfig::kAesBlockSize) {
        APP_DEBUG_PRINTLN("Invalid padding");
        return false;
    }

    for (int i = decryptedLength - padding; i < decryptedLength; ++i) {
        if (decrypted[i] != padding) {
            APP_DEBUG_PRINTLN("Corrupted padding");
            return false;
        }
    }

    const size_t unpaddedLength = static_cast<size_t>(decryptedLength - padding);
    if (unpaddedLength <= encodedOffset) {
        APP_DEBUG_PRINTLN("Missing message body");
        return false;
    }

    const size_t dataLength = unpaddedLength - encodedOffset;
    pb_istream_t stream = pb_istream_from_buffer(decrypted + encodedOffset, dataLength);

    command = CMD_Message_init_zero;
    if (!pb_decode(&stream, CMD_Message_fields, &command)) {
        APP_LOG_ERROR("CMD decode FAILED");
        return false;
    }

    return true;
}
