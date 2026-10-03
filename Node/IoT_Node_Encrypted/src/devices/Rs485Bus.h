#ifndef RS485_BUS_H
#define RS485_BUS_H

// Initialize the one shared Modbus RTU bus before any sensor driver calls
// ModbusMaster::begin(). Safe to call more than once.
void initializeRs485Bus();
void rs485PreTransmission();
void rs485PostTransmission();
/** @brief Attach the node's foreground-only command pump for Modbus wait gaps. */
void setRs485CommandService(void (*service)());
/** @brief Rate-limited Modbus idle hook; never touches the RS485 receive bytes. */
void rs485ServiceCommands();

#endif
