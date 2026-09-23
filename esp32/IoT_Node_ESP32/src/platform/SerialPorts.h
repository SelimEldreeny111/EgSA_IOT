#ifndef ESP32_SERIAL_PORTS_H
#define ESP32_SERIAL_PORTS_H

#include <Arduino.h>

// ESP32 UART ownership is selected at compile time from APP_ROLE/APP_UPLINK:
//   UART0: USB debug monitor
//   UART1: external modem, or RS485 in a LoRa-only sensor node
//   UART2: LoRa, or RS485 in a direct-MQTT sensor node
// Some references intentionally alias an inactive interface. The AppConfig
// role checks guarantee that two active peripherals never own one UART.
extern HardwareSerial& SerialMon;
extern HardwareSerial& SerialAT;
extern HardwareSerial& SerialRs485;
extern HardwareSerial& SerialLoRa;

void beginDebugSerial(uint32_t baudRate = 115200UL);
void beginModemSerial(uint32_t baudRate, uint32_t serialMode = SERIAL_8N1);
void beginRs485Serial(uint32_t baudRate, uint32_t serialMode = SERIAL_8N1);
void beginLoraSerial(uint32_t baudRate, uint32_t serialMode = SERIAL_8N1);

void endModemSerial();
void endRs485Serial();
void endLoraSerial();

#endif
