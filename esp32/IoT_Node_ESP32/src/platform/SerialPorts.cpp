#include "SerialPorts.h"

#include "../config/AppConfig.h"

namespace
{
HardwareSerial g_uart1(1);
HardwareSerial g_uart2(2);

void beginMappedSerial(
    HardwareSerial& serial,
    uint32_t baudRate,
    uint32_t serialMode,
    int8_t rxPin,
    int8_t txPin)
{
  // ESP32 buffer sizes must be selected before begin(). Reapply them after
  // every end()/begin() cycle used by modem wake and LoRa configuration.
  serial.setRxBufferSize(AppConfig::kSerialRxBufferSize);
  serial.setTxBufferSize(AppConfig::kSerialTxBufferSize);
  serial.begin(baudRate, serialMode, rxPin, txPin);
}
}

HardwareSerial& SerialMon = Serial;
HardwareSerial& SerialAT = g_uart1;

#if APP_HAS_IP_UPLINK
HardwareSerial& SerialRs485 = g_uart2;
#else
HardwareSerial& SerialRs485 = g_uart1;
#endif

HardwareSerial& SerialLoRa = g_uart2;

void beginDebugSerial(uint32_t baudRate)
{
  SerialMon.begin(
      baudRate,
      SERIAL_8N1,
      AppConfig::kDebugRxPin,
      AppConfig::kDebugTxPin);
}

void beginModemSerial(uint32_t baudRate, uint32_t serialMode)
{
  beginMappedSerial(
      SerialAT,
      baudRate,
      serialMode,
      AppConfig::kModemRxPin,
      AppConfig::kModemTxPin);
}

void beginRs485Serial(uint32_t baudRate, uint32_t serialMode)
{
  beginMappedSerial(
      SerialRs485,
      baudRate,
      serialMode,
      AppConfig::kRs485RxPin,
      AppConfig::kRs485TxPin);
}

void beginLoraSerial(uint32_t baudRate, uint32_t serialMode)
{
  beginMappedSerial(
      SerialLoRa,
      baudRate,
      serialMode,
      AppConfig::kLoraRxPin,
      AppConfig::kLoraTxPin);
}

void endModemSerial()
{
  SerialAT.end();
}

void endRs485Serial()
{
  SerialRs485.end();
}

void endLoraSerial()
{
  SerialLoRa.end();
}
