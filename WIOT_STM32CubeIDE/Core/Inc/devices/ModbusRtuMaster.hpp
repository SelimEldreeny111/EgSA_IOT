#ifndef WIOT_MODBUS_RTU_MASTER_HPP
#define WIOT_MODBUS_RTU_MASTER_HPP

#include "main.h"
#include "platform/Stm32Platform.hpp"

#include <cstddef>
#include <cstdint>

enum class ModbusResult : uint8_t
{
  Ok = 0,
  InvalidArgument = 1,
  TransmitFailed = 2,
  Timeout = 3,
  InvalidSlave = 4,
  InvalidFunction = 5,
  InvalidLength = 6,
  CrcError = 7,
  ExceptionBase = 0x80
};

class ModbusRtuMaster
{
public:
  ModbusRtuMaster(UART_HandleTypeDef &uart, const Platform::GpioPin &directionPin);
  ModbusResult readHoldingRegisters(
      uint8_t slave,
      uint16_t startAddress,
      uint16_t count,
      uint16_t *registers,
      uint32_t timeoutMs = 350U);

private:
  static uint16_t crc16(const uint8_t *data, size_t length);
  UART_HandleTypeDef &uart_;
  const Platform::GpioPin &directionPin_;
  uint32_t lastTransactionMs_;
};

extern ModbusRtuMaster ModbusBus;

#endif
