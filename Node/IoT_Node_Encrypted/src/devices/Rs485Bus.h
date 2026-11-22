/**
 * @file Rs485Bus.h
 * @brief Shared Modbus RTU serial port and half-duplex transceiver direction.
 */
#ifndef RS485_BUS_H
#define RS485_BUS_H

#include <stdint.h>

class ModbusMaster;

/** @brief Initialize Serial1 as 8N1 and put the RS485 driver in receive mode. Safe to call repeatedly. */
void initializeRs485Bus();
/** @brief Bind a sensor client to the shared UART, half-duplex direction and diagnostics. */
void configureRs485Modbus(ModbusMaster& sensor, uint8_t address);
/** @brief Assert DE and enforce a minimum silent interval before transmission. */
void rs485PreTransmission();
/** @brief Release DE after transmission and record the bus-idle timestamp. */
void rs485PostTransmission();
/** @brief Attach the node's foreground-only command pump for Modbus wait gaps. */
void setRs485CommandService(void (*service)());
/** @brief Rate-limited Modbus idle hook; never touches the RS485 receive bytes. */
void rs485ServiceCommands();

#endif
