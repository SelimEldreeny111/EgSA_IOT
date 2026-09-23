/*
 * AS32_Config.h
 *
 * Central AS32-TTL-1W-C configuration selector.
 *
 * Change the AS32_* selection macros below, compile/upload the same settings
 * to both radios, and test. The resulting module command is:
 *
 *   C0 ADDH ADDL SPEED CHAN OPTION
 *
 * The AS32 only accepts configuration commands in sleep/config mode:
 * MD0=HIGH and MD1=HIGH. Normal transparent mode is MD0=LOW and MD1=LOW.
 */

#ifndef AS32_CONFIG_H
#define AS32_CONFIG_H

#include <Arduino.h>
#include <string.h>

// ---------------------------------------------------------------------------
// Available AS32 config values
// ---------------------------------------------------------------------------

#define AS32_CMD_WRITE_SAVE       0xC0
#define AS32_CMD_READ_CONFIG      0xC1
#define AS32_CMD_WRITE_TEMPORARY  0xC2

#define AS32_UART_PARITY_8N1      0x00
#define AS32_UART_PARITY_8O1      0x01
#define AS32_UART_PARITY_8E1      0x02
#define AS32_UART_PARITY_8N1_ALT  0x03

#define AS32_UART_BAUD_1200       0x00
#define AS32_UART_BAUD_2400       0x01
#define AS32_UART_BAUD_4800       0x02
#define AS32_UART_BAUD_9600       0x03
#define AS32_UART_BAUD_19200      0x04
#define AS32_UART_BAUD_38400      0x05
#define AS32_UART_BAUD_57600      0x06
#define AS32_UART_BAUD_115200     0x07

#define AS32_AIR_RATE_0K3         0x00
#define AS32_AIR_RATE_1K2         0x01
#define AS32_AIR_RATE_2K4         0x02
#define AS32_AIR_RATE_4K8         0x03
#define AS32_AIR_RATE_9K6         0x04
#define AS32_AIR_RATE_19K2        0x05

#define AS32_TRANSPARENT_MODE     0x00
#define AS32_FIXED_POINT_MODE     0x01

#define AS32_IO_OPEN_DRAIN        0x00
#define AS32_IO_PUSH_PULL         0x01

#define AS32_WAKE_250MS           0x00
#define AS32_WAKE_500MS           0x01
#define AS32_WAKE_750MS           0x02
#define AS32_WAKE_1000MS          0x03
#define AS32_WAKE_1250MS          0x04
#define AS32_WAKE_1500MS          0x05
#define AS32_WAKE_1750MS          0x06
#define AS32_WAKE_2000MS          0x07

#define AS32_TX_POWER_MAX         0x00
#define AS32_TX_POWER_HIGH        0x01
#define AS32_TX_POWER_MEDIUM      0x02
#define AS32_TX_POWER_LOW         0x03

// ---------------------------------------------------------------------------
// User selection area
// ---------------------------------------------------------------------------

// Set to 1 when you want the firmware to write this configuration to the AS32
// module at boot. Leave 0 if the module has already been configured manually.
#ifndef AS32_AUTO_APPLY_CONFIG
#define AS32_AUTO_APPLY_CONFIG 0
#endif

// Use AS32_CMD_WRITE_SAVE for permanent storage, or AS32_CMD_WRITE_TEMPORARY
// for temporary testing until the module loses power.
#ifndef AS32_CONFIG_WRITE_COMMAND
#define AS32_CONFIG_WRITE_COMMAND AS32_CMD_WRITE_SAVE
#endif

// These describe the module's current UART settings before writing a new config.
// The working standalone AS32 Ping/Pong test leaves the modules already set to
// UART 9600. Production firmware does not write or read AS32 configuration.
#ifndef AS32_CURRENT_CONFIG_UART_BAUD_CODE
#define AS32_CURRENT_CONFIG_UART_BAUD_CODE AS32_UART_BAUD_9600
#endif

#ifndef AS32_CURRENT_CONFIG_UART_PARITY_CODE
#define AS32_CURRENT_CONFIG_UART_PARITY_CODE AS32_UART_PARITY_8N1
#endif

// Desired radio/module configuration.
#ifndef AS32_ADDRESS_HIGH
#define AS32_ADDRESS_HIGH 0x00
#endif

#ifndef AS32_ADDRESS_LOW
#define AS32_ADDRESS_LOW 0x00
#endif

// Valid values are integer MHz from 410 to 441.
#ifndef AS32_FREQUENCY_MHZ
#define AS32_FREQUENCY_MHZ 433
#endif

#ifndef AS32_UART_PARITY_CODE
#define AS32_UART_PARITY_CODE AS32_UART_PARITY_8N1
#endif

#ifndef AS32_UART_BAUD_CODE
#define AS32_UART_BAUD_CODE AS32_UART_BAUD_9600
#endif

#ifndef AS32_AIR_RATE_CODE
#define AS32_AIR_RATE_CODE AS32_AIR_RATE_2K4
#endif

#ifndef AS32_TRANSMISSION_MODE
#define AS32_TRANSMISSION_MODE AS32_TRANSPARENT_MODE
#endif

#ifndef AS32_IO_MODE
#define AS32_IO_MODE AS32_IO_PUSH_PULL
#endif

#ifndef AS32_WAKE_TIME_CODE
#define AS32_WAKE_TIME_CODE AS32_WAKE_250MS
#endif

#ifndef AS32_TX_POWER_CODE
#define AS32_TX_POWER_CODE AS32_TX_POWER_MAX
#endif

// ---------------------------------------------------------------------------
// Validation
// ---------------------------------------------------------------------------

#if AS32_FREQUENCY_MHZ < 410 || AS32_FREQUENCY_MHZ > 441
#error "AS32_FREQUENCY_MHZ must be an integer from 410 to 441"
#endif

#if AS32_UART_PARITY_CODE < 0 || AS32_UART_PARITY_CODE > 3
#error "AS32_UART_PARITY_CODE must be AS32_UART_PARITY_8N1/8O1/8E1/8N1_ALT"
#endif

#if AS32_CURRENT_CONFIG_UART_PARITY_CODE < 0 || AS32_CURRENT_CONFIG_UART_PARITY_CODE > 3
#error "AS32_CURRENT_CONFIG_UART_PARITY_CODE must be AS32_UART_PARITY_8N1/8O1/8E1/8N1_ALT"
#endif

#if AS32_UART_BAUD_CODE < 0 || AS32_UART_BAUD_CODE > 7
#error "AS32_UART_BAUD_CODE must be one of AS32_UART_BAUD_*"
#endif

#if AS32_CURRENT_CONFIG_UART_BAUD_CODE < 0 || AS32_CURRENT_CONFIG_UART_BAUD_CODE > 7
#error "AS32_CURRENT_CONFIG_UART_BAUD_CODE must be one of AS32_UART_BAUD_*"
#endif

#if AS32_AIR_RATE_CODE < 0 || AS32_AIR_RATE_CODE > 5
#error "AS32_AIR_RATE_CODE must be AS32_AIR_RATE_0K3 through AS32_AIR_RATE_19K2"
#endif

#if AS32_TRANSMISSION_MODE < 0 || AS32_TRANSMISSION_MODE > 1
#error "AS32_TRANSMISSION_MODE must be AS32_TRANSPARENT_MODE or AS32_FIXED_POINT_MODE"
#endif

#if AS32_IO_MODE < 0 || AS32_IO_MODE > 1
#error "AS32_IO_MODE must be AS32_IO_OPEN_DRAIN or AS32_IO_PUSH_PULL"
#endif

#if AS32_WAKE_TIME_CODE < 0 || AS32_WAKE_TIME_CODE > 7
#error "AS32_WAKE_TIME_CODE must be one of AS32_WAKE_*"
#endif

#if AS32_TX_POWER_CODE < 0 || AS32_TX_POWER_CODE > 3
#error "AS32_TX_POWER_CODE must be one of AS32_TX_POWER_*"
#endif

namespace AS32Config
{
constexpr uint8_t kCommand = static_cast<uint8_t>(AS32_CONFIG_WRITE_COMMAND);
constexpr uint8_t kAddressHigh = static_cast<uint8_t>(AS32_ADDRESS_HIGH);
constexpr uint8_t kAddressLow = static_cast<uint8_t>(AS32_ADDRESS_LOW);
constexpr uint8_t kChannel = static_cast<uint8_t>(AS32_FREQUENCY_MHZ - 410);
constexpr uint16_t kFrequencyMhz = static_cast<uint16_t>(AS32_FREQUENCY_MHZ);

constexpr uint8_t kSpeedByte =
    static_cast<uint8_t>(((AS32_UART_PARITY_CODE & 0x03) << 6) |
                         ((AS32_UART_BAUD_CODE & 0x07) << 3) |
                         (AS32_AIR_RATE_CODE & 0x07));

constexpr uint8_t kOptionByte =
    static_cast<uint8_t>(((AS32_TRANSMISSION_MODE & 0x01) << 7) |
                         ((AS32_IO_MODE & 0x01) << 6) |
                         ((AS32_WAKE_TIME_CODE & 0x07) << 3) |
                         (AS32_TX_POWER_CODE & 0x03));

constexpr uint8_t kConfigCommand[6] = {
    kCommand,
    kAddressHigh,
    kAddressLow,
    kSpeedByte,
    kChannel,
    kOptionByte
};

constexpr uint8_t kReadConfigCommand[3] = {
    AS32_CMD_READ_CONFIG,
    AS32_CMD_READ_CONFIG,
    AS32_CMD_READ_CONFIG
};

// AS32-TTL-1W V3-only diagnostic commands. These are not part of the
// E32-TTL-100 command set and must only be called when
// AppConfig::kLoraModuleSupportsRssi is true. The AS32 V3 module returns one
// unsigned magnitude byte for each RSSI query; e.g. 87 represents -87 dBm.
constexpr uint8_t kReadDataRssiCommand[6] = {
    0xAF, 0xAF, 0x73, 0x00, 0xAF, 0xF3
};
constexpr uint8_t kReadEnvironmentRssiCommand[6] = {
    0xAF, 0xAF, 0x74, 0x00, 0xAF, 0xF4
};

struct RssiReadings
{
  bool dataValid;
  int16_t dataDbm;
  uint8_t dataRaw;
  bool environmentValid;
  int16_t environmentDbm;
  uint8_t environmentRaw;
};

constexpr uint32_t baudRateFromCode(uint8_t code)
{
  return code == AS32_UART_BAUD_1200 ? 1200UL :
         code == AS32_UART_BAUD_2400 ? 2400UL :
         code == AS32_UART_BAUD_4800 ? 4800UL :
         code == AS32_UART_BAUD_9600 ? 9600UL :
         code == AS32_UART_BAUD_19200 ? 19200UL :
         code == AS32_UART_BAUD_38400 ? 38400UL :
         code == AS32_UART_BAUD_57600 ? 57600UL :
         115200UL;
}

constexpr uint32_t serialModeFromParity(uint8_t code)
{
  return code == AS32_UART_PARITY_8O1 ? SERIAL_8O1 :
         code == AS32_UART_PARITY_8E1 ? SERIAL_8E1 :
         SERIAL_8N1;
}

constexpr uint32_t kUartBaudRate = baudRateFromCode(AS32_UART_BAUD_CODE);
constexpr uint32_t kSerialMode = serialModeFromParity(AS32_UART_PARITY_CODE);
constexpr uint32_t kCurrentConfigBaudRate = baudRateFromCode(AS32_CURRENT_CONFIG_UART_BAUD_CODE);
constexpr uint32_t kCurrentConfigSerialMode = serialModeFromParity(AS32_CURRENT_CONFIG_UART_PARITY_CODE);
constexpr bool kAutoApplyConfig = AS32_AUTO_APPLY_CONFIG != 0;

inline void printHexByte(Print& out, uint8_t value)
{
  if (value < 0x10)
  {
    out.print('0');
  }
  out.print(value, HEX);
}

inline void printConfigSummary(Print& out)
{
  out.print("AS32 config: freq=");
  out.print(kFrequencyMhz);
  out.print("MHz channel=0x");
  printHexByte(out, kChannel);
  out.print(" uart=");
  out.print(kUartBaudRate);
  out.print(" speed=0x");
  printHexByte(out, kSpeedByte);
  out.print(" option=0x");
  printHexByte(out, kOptionByte);
  out.print(" command=");
  for (size_t i = 0; i < sizeof(kConfigCommand); ++i)
  {
    if (i > 0)
    {
      out.print(' ');
    }
    printHexByte(out, kConfigCommand[i]);
  }
  out.println();
}

inline bool waitForAuxHigh(uint32_t auxPin, uint32_t timeoutMs)
{
  const uint32_t startMs = millis();
  while (digitalRead(auxPin) == LOW)
  {
    if (millis() - startMs >= timeoutMs)
    {
      return false;
    }
    delay(1);
  }
  delay(3);
  return true;
}

inline void drainSerial(HardwareSerial& radioSerial)
{
  while (radioSerial.available() > 0)
  {
    radioSerial.read();
  }
}

inline size_t readResponseBytes(
    HardwareSerial& radioSerial,
    uint8_t* response,
    size_t responseCapacity,
    uint32_t timeoutMs)
{
  const uint32_t startMs = millis();
  size_t responseLength = 0;
  while (millis() - startMs < timeoutMs)
  {
    while (radioSerial.available() > 0)
    {
      const int c = radioSerial.read();
      if (c >= 0 && responseLength < responseCapacity)
      {
        response[responseLength++] = static_cast<uint8_t>(c);
      }
    }
  }
  return responseLength;
}

inline size_t readResponseUntilIdle(
    HardwareSerial& radioSerial,
    uint8_t* response,
    size_t responseCapacity,
    uint32_t firstByteTimeoutMs,
    uint32_t idleTimeoutMs)
{
  const uint32_t startMs = millis();
  uint32_t lastByteMs = 0U;
  size_t responseLength = 0U;

  while (true)
  {
    while (radioSerial.available() > 0)
    {
      const int value = radioSerial.read();
      if (value >= 0 && responseLength < responseCapacity)
      {
        response[responseLength++] = static_cast<uint8_t>(value);
      }
      lastByteMs = millis();
    }

    if (responseLength > 0U)
    {
      if (millis() - lastByteMs >= idleTimeoutMs)
      {
        break;
      }
    }
    else if (millis() - startMs >= firstByteTimeoutMs)
    {
      break;
    }
    delay(1);
    yield();
  }

  return responseLength;
}

inline bool decodeRssiResponse(
    const uint8_t* response,
    size_t responseLength,
    uint8_t& raw,
    int16_t& dbm)
{
  // A valid AS32 V3 RSSI reply is exactly one magnitude byte. Values above
  // 200 dB are rejected so command echoes/noise cannot look like valid RSSI.
  if (responseLength != 1U || response[0] == 0U || response[0] > 200U)
  {
    return false;
  }

  raw = response[0];
  dbm = -static_cast<int16_t>(raw);
  return true;
}

inline bool queryRssi(
    HardwareSerial& radioSerial,
    uint32_t auxPin,
    RssiReadings& readings)
{
  readings = {false, 0, 0, false, 0, 0};

  // Unlike configuration commands 1..10, AS32 V3 commands 11 and 12 are
  // valid in normal/power-saving mode. Keep MD0/MD1 untouched so an RSSI
  // diagnostic never closes the gateway receiver.
  if (!waitForAuxHigh(auxPin, 50U) || radioSerial.available() > 0)
  {
    return false;
  }

  uint8_t response[8] = {};
  radioSerial.write(kReadDataRssiCommand, sizeof(kReadDataRssiCommand));
  radioSerial.flush();
  size_t responseLength = readResponseUntilIdle(
      radioSerial, response, sizeof(response), 30U, 3U);
  readings.dataValid = decodeRssiResponse(
      response, responseLength, readings.dataRaw, readings.dataDbm);

  if (!waitForAuxHigh(auxPin, 30U) || radioSerial.available() > 0)
  {
    return readings.dataValid;
  }

  memset(response, 0, sizeof(response));
  radioSerial.write(
      kReadEnvironmentRssiCommand,
      sizeof(kReadEnvironmentRssiCommand));
  radioSerial.flush();
  responseLength = readResponseUntilIdle(
      radioSerial, response, sizeof(response), 30U, 3U);
  readings.environmentValid = decodeRssiResponse(
      response,
      responseLength,
      readings.environmentRaw,
      readings.environmentDbm);

  return readings.dataValid || readings.environmentValid;
}

inline void printResponse(Print& debug, const uint8_t* response, size_t responseLength)
{
  if (responseLength == 0)
  {
    debug.print(" none");
    return;
  }

  for (size_t i = 0; i < responseLength; ++i)
  {
    debug.print(' ');
    printHexByte(debug, response[i]);
  }
}

inline bool isValidAs32ConfigResponse(const uint8_t* response, size_t responseLength)
{
  if (responseLength < 6)
  {
    return false;
  }

  return response[0] == AS32_CMD_WRITE_SAVE ||
         response[0] == AS32_CMD_READ_CONFIG ||
         response[0] == AS32_CMD_WRITE_TEMPORARY;
}

inline bool isAtModemTextResponse(const uint8_t* response, size_t responseLength)
{
  if (responseLength >= 2 && response[0] == 'O' && response[1] == 'K')
  {
    return true;
  }

  if (responseLength >= 5 &&
      response[0] == 'E' &&
      response[1] == 'R' &&
      response[2] == 'R' &&
      response[3] == 'O' &&
      response[4] == 'R')
  {
    return true;
  }

  return false;
}

inline bool writeConfigAtBaud(
    HardwareSerial& radioSerial,
    Print& debug,
    uint32_t baudRate,
    uint32_t serialMode)
{
  uint8_t response[16];

  radioSerial.end();
  radioSerial.begin(baudRate, serialMode);
  delay(30);
  drainSerial(radioSerial);

  debug.print("AS32 config try at UART ");
  debug.print(baudRate);
  debug.print(" response:");

  radioSerial.write(kConfigCommand, sizeof(kConfigCommand));
  radioSerial.flush();

  const size_t responseLength = readResponseBytes(
      radioSerial,
      response,
      sizeof(response),
      500);
  printResponse(debug, response, responseLength);
  if (isAtModemTextResponse(response, responseLength))
  {
    debug.print("  <-- AT modem response, not AS32");
  }
  debug.println();

  return isValidAs32ConfigResponse(response, responseLength);
}

inline bool readConfigAtBaud(
    HardwareSerial& radioSerial,
    Print& debug,
    uint32_t baudRate,
    uint32_t serialMode,
    const char* label)
{
  uint8_t response[16];

  radioSerial.end();
  radioSerial.begin(baudRate, serialMode);
  delay(30);
  drainSerial(radioSerial);

  debug.print("AS32 ");
  debug.print(label);
  debug.print(" readback at UART ");
  debug.print(baudRate);
  debug.print(":");

  radioSerial.write(kReadConfigCommand, sizeof(kReadConfigCommand));
  radioSerial.flush();

  const size_t responseLength = readResponseBytes(
      radioSerial,
      response,
      sizeof(response),
      500);
  printResponse(debug, response, responseLength);
  if (isAtModemTextResponse(response, responseLength))
  {
    debug.print("  <-- AT modem response, not AS32");
  }
  debug.println();

  return isValidAs32ConfigResponse(response, responseLength);
}

inline bool applyConfigurationIfEnabled(
    HardwareSerial& radioSerial,
    Print& debug,
    uint32_t md0Pin,
    uint32_t md1Pin,
    uint32_t auxPin)
{
  if (!kAutoApplyConfig)
  {
    debug.println("AS32 auto-config disabled; using preconfigured module settings.");
    return true;
  }

  debug.println("AS32 auto-config enabled.");
  digitalWrite(md0Pin, HIGH);
  digitalWrite(md1Pin, HIGH);
  delay(10);

  if (!waitForAuxHigh(auxPin, 1000))
  {
    debug.println("AS32 auto-config warning: AUX did not become HIGH before command.");
  }

  bool configured = writeConfigAtBaud(
      radioSerial,
      debug,
      kCurrentConfigBaudRate,
      kCurrentConfigSerialMode);

  if (!configured && kCurrentConfigBaudRate != kUartBaudRate)
  {
    debug.println("AS32 did not answer at saved-config UART; trying runtime UART as fallback.");
    configured = writeConfigAtBaud(
        radioSerial,
        debug,
        kUartBaudRate,
        kSerialMode);
  }

  if (!configured)
  {
    debug.println("AS32 WARNING: no config response. Check TX/RX pins, MD0/MD1 pins, common GND, and AS32 power.");
  }

  readConfigAtBaud(
      radioSerial,
      debug,
      kUartBaudRate,
      kSerialMode,
      "runtime");

  digitalWrite(md0Pin, LOW);
  digitalWrite(md1Pin, LOW);
  delay(10);
  waitForAuxHigh(auxPin, 1000);
  return true;
}
}

#endif
