#include "devices/ModbusRtuMaster.hpp"

#include "config/AppConfig.hpp"

#include <cstring>

ModbusRtuMaster ModbusBus(huart1, AppConfig::kRs485DirectionPin);

ModbusRtuMaster::ModbusRtuMaster(
    UART_HandleTypeDef &uart,
    const Platform::GpioPin &directionPin)
    : uart_(uart), directionPin_(directionPin), lastTransactionMs_(0U)
{
}

uint16_t ModbusRtuMaster::crc16(const uint8_t *data, size_t length)
{
  uint16_t crc = 0xFFFFU;
  for (size_t index = 0U; index < length; ++index)
  {
    crc ^= data[index];
    for (uint8_t bit = 0U; bit < 8U; ++bit)
    {
      crc = (crc & 1U) != 0U
          ? static_cast<uint16_t>((crc >> 1U) ^ 0xA001U)
          : static_cast<uint16_t>(crc >> 1U);
    }
  }
  return crc;
}

ModbusResult ModbusRtuMaster::readHoldingRegisters(
    uint8_t slave,
    uint16_t startAddress,
    uint16_t count,
    uint16_t *registers,
    uint32_t timeoutMs)
{
  if (slave == 0U || count == 0U || count > 32U || registers == nullptr)
  {
    return ModbusResult::InvalidArgument;
  }

  const uint32_t quietElapsed = Platform::millis() - lastTransactionMs_;
  if (quietElapsed < 5U) Platform::delayMs(5U - quietElapsed);

  uint8_t request[8] = {
      slave,
      0x03U,
      static_cast<uint8_t>(startAddress >> 8U),
      static_cast<uint8_t>(startAddress),
      static_cast<uint8_t>(count >> 8U),
      static_cast<uint8_t>(count),
      0U,
      0U};
  const uint16_t requestCrc = crc16(request, 6U);
  request[6] = static_cast<uint8_t>(requestCrc);
  request[7] = static_cast<uint8_t>(requestCrc >> 8U);

  __HAL_UART_FLUSH_DRREGISTER(&uart_);
  __HAL_UART_CLEAR_OREFLAG(&uart_);
  Platform::gpioWrite(directionPin_, GPIO_PIN_SET);
  Platform::delayUs(50U);
  const HAL_StatusTypeDef transmitResult =
      HAL_UART_Transmit(&uart_, request, sizeof(request), 100U);
  while (__HAL_UART_GET_FLAG(&uart_, UART_FLAG_TC) == RESET) {}
  Platform::delayUs(50U);
  Platform::gpioWrite(directionPin_, GPIO_PIN_RESET);
  lastTransactionMs_ = Platform::millis();
  if (transmitResult != HAL_OK) return ModbusResult::TransmitFailed;

  uint8_t response[69]{};
  size_t responseLength = 0U;
  size_t expectedLength = 0U;
  const uint32_t start = Platform::millis();
  while (Platform::millis() - start < timeoutMs && responseLength < sizeof(response))
  {
    uint8_t value = 0U;
    if (HAL_UART_Receive(&uart_, &value, 1U, 5U) == HAL_OK)
    {
      response[responseLength++] = value;
      if (responseLength == 3U)
      {
        expectedLength = (response[1] & 0x80U) != 0U
            ? 5U
            : static_cast<size_t>(5U + response[2]);
        if (expectedLength > sizeof(response)) return ModbusResult::InvalidLength;
      }
      if (expectedLength != 0U && responseLength >= expectedLength) break;
    }
  }
  lastTransactionMs_ = Platform::millis();

  if (expectedLength == 0U || responseLength < expectedLength) return ModbusResult::Timeout;
  if (response[0] != slave) return ModbusResult::InvalidSlave;
  const uint16_t receivedCrc = static_cast<uint16_t>(response[expectedLength - 2U]) |
                               static_cast<uint16_t>(response[expectedLength - 1U] << 8U);
  if (crc16(response, expectedLength - 2U) != receivedCrc) return ModbusResult::CrcError;
  if ((response[1] & 0x80U) != 0U)
  {
    return static_cast<ModbusResult>(
        static_cast<uint8_t>(ModbusResult::ExceptionBase) | response[2]);
  }
  if (response[1] != 0x03U) return ModbusResult::InvalidFunction;
  if (response[2] != count * 2U) return ModbusResult::InvalidLength;

  for (uint16_t index = 0U; index < count; ++index)
  {
    registers[index] = static_cast<uint16_t>(response[3U + index * 2U] << 8U) |
                       response[4U + index * 2U];
  }
  return ModbusResult::Ok;
}
