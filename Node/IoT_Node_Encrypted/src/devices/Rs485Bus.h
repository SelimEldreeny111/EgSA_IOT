/**
 * @file Rs485Bus.h
 * @brief Shared Modbus RTU serial port and half-duplex transceiver direction.
 */
#ifndef RS485_BUS_H
#define RS485_BUS_H

/** @brief Initialize Serial1 as 8N1 and put the RS485 driver in receive mode. Safe to call repeatedly. */
void initializeRs485Bus();
/** @brief Assert DE and enforce a minimum silent interval before transmission. */
void rs485PreTransmission();
/** @brief Release DE after transmission and record the bus-idle timestamp. */
void rs485PostTransmission();

#endif
