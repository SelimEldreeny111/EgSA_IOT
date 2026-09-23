#include "comm/PacketCodec.hpp"

#include "AES.h"
#include "config/AppConfig.hpp"
#include "config/AppSecrets.hpp"
#include "main.h"
#include "pb_decode.h"
#include "pb_encode.h"
#include "platform/Stm32Platform.hpp"

#include <cstring>

namespace
{
AES aes;

const uint8_t aesKey[AppConfig::kAesBlockSize] = WIOT_AES_KEY_BYTES;

uint32_t nextRandomWord()
{
  static uint32_t state = 0U;
  if (state == 0U)
  {
    state = HAL_GetUIDw0() ^ HAL_GetUIDw1() ^ HAL_GetUIDw2() ^
            DWT->CYCCNT ^ (HAL_GetTick() * 0x9E3779B9UL);
    if (state == 0U) state = 0xA5C31F27UL;
  }
  state ^= state << 13;
  state ^= state >> 17;
  state ^= state << 5;
  state += DWT->CYCCNT;
  return state;
}

void generatePacketIv(uint8_t *iv)
{
  for (size_t index = 0U; index < AppConfig::kIvLength; index += 4U)
  {
    const uint32_t word = nextRandomWord();
    iv[index] = static_cast<uint8_t>(word);
    iv[index + 1U] = static_cast<uint8_t>(word >> 8);
    iv[index + 2U] = static_cast<uint8_t>(word >> 16);
    iv[index + 3U] = static_cast<uint8_t>(word >> 24);
  }
}

bool cryptCbc(
    bool encrypt,
    const uint8_t *input,
    size_t length,
    uint8_t *output,
    const uint8_t *iv)
{
  if (length == 0U || (length % AppConfig::kAesBlockSize) != 0U)
  {
    return false;
  }
  uint8_t workingIv[AppConfig::kIvLength];
  std::memcpy(workingIv, iv, sizeof(workingIv));
  if (aes.set_key(aesKey, sizeof(aesKey)) != 0U)
  {
    return false;
  }
  const byte result = encrypt
      ? aes.cbc_encrypt(input, output, static_cast<int>(length / 16U), workingIv)
      : aes.cbc_decrypt(input, output, static_cast<int>(length / 16U), workingIv);
  aes.clean();
  return result == 0U;
}
}

bool encodeEncryptedMessage(
    const pb_msgdesc_t *fields,
    const void *source,
    uint8_t *output,
    size_t outputSize,
    size_t &outputLength)
{
  outputLength = 0U;
  uint8_t encoded[AppConfig::kCodecBufferSize]{};
  pb_ostream_t stream = pb_ostream_from_buffer(encoded, sizeof(encoded));
  if (!pb_encode(&stream, fields, source))
  {
    SerialMon.println("Protobuf encode failed");
    return false;
  }

  const size_t padding = AppConfig::kAesBlockSize -
                         (stream.bytes_written % AppConfig::kAesBlockSize);
  const size_t encryptedLength = stream.bytes_written + padding;
  if (encryptedLength > sizeof(encoded) ||
      1U + AppConfig::kIvLength + encryptedLength > outputSize)
  {
    SerialMon.println("Encrypted codec buffer overflow");
    return false;
  }
  std::memset(encoded + stream.bytes_written, static_cast<int>(padding), padding);

  uint8_t iv[AppConfig::kIvLength];
  generatePacketIv(iv);
  output[0] = AppConfig::kProtocolVersion;
  std::memcpy(output + 1U, iv, sizeof(iv));
  if (!cryptCbc(true, encoded, encryptedLength,
                output + 1U + AppConfig::kIvLength, iv))
  {
    SerialMon.println("AES-128-CBC encryption failed");
    return false;
  }
  outputLength = 1U + AppConfig::kIvLength + encryptedLength;
  return true;
}

bool decodeEncryptedCommandPayload(
    const uint8_t *payload,
    size_t payloadLength,
    CMD_Message &command)
{
  if (payload == nullptr ||
      payloadLength < 1U + AppConfig::kIvLength + AppConfig::kAesBlockSize ||
      payloadLength > AppConfig::kCodecBufferSize ||
      payload[0] != AppConfig::kProtocolVersion)
  {
    SerialMon.println("Invalid encrypted command envelope");
    return false;
  }

  const uint8_t *iv = payload + 1U;
  const uint8_t *ciphertext = payload + 1U + AppConfig::kIvLength;
  const size_t ciphertextLength = payloadLength - 1U - AppConfig::kIvLength;
  if ((ciphertextLength % AppConfig::kAesBlockSize) != 0U)
  {
    return false;
  }

  uint8_t plain[AppConfig::kCodecBufferSize]{};
  if (!cryptCbc(false, ciphertext, ciphertextLength, plain, iv))
  {
    SerialMon.println("AES-128-CBC decryption failed");
    return false;
  }
  const uint8_t padding = plain[ciphertextLength - 1U];
  if (padding == 0U || padding > AppConfig::kAesBlockSize || padding > ciphertextLength)
  {
    SerialMon.println("Invalid PKCS#7 padding");
    return false;
  }
  for (size_t index = ciphertextLength - padding; index < ciphertextLength; ++index)
  {
    if (plain[index] != padding) return false;
  }

  command = CMD_Message_init_zero;
  pb_istream_t stream = pb_istream_from_buffer(plain, ciphertextLength - padding);
  if (!pb_decode(&stream, CMD_Message_fields, &command))
  {
    SerialMon.println("Command protobuf decode failed");
    return false;
  }
  return true;
}
