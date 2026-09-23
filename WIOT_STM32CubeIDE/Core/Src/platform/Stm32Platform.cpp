#include "platform/Stm32Platform.hpp"

#include "config/AppConfig.hpp"

#include <cstdarg>
#include <cstdio>
#include <cstring>

Platform::UartPort SerialMon;
Platform::UartPort SerialLoRa;
Platform::UartPort SerialAt;

namespace Platform
{
constexpr size_t UartPort::RxCapacity;

uint32_t millis()
{
  return HAL_GetTick();
}

uint32_t micros()
{
  if ((DWT->CTRL & DWT_CTRL_CYCCNTENA_Msk) == 0U)
  {
    return millis() * 1000UL;
  }
  return DWT->CYCCNT / (SystemCoreClock / 1000000UL);
}

void delayMs(uint32_t delay)
{
  HAL_Delay(delay);
}

void delayUs(uint32_t delay)
{
  const uint32_t cyclesPerMicrosecond = SystemCoreClock / 1000000UL;
  const uint32_t start = DWT->CYCCNT;
  const uint32_t target = delay * cyclesPerMicrosecond;
  while ((DWT->CYCCNT - start) < target)
  {
    __NOP();
  }
}

void yield()
{
  __NOP();
}

void configureOutput(const GpioPin &pin, GPIO_PinState initialState)
{
  HAL_GPIO_WritePin(pin.port, pin.pin, initialState);
  GPIO_InitTypeDef init{};
  init.Pin = pin.pin;
  init.Mode = GPIO_MODE_OUTPUT_PP;
  init.Pull = GPIO_NOPULL;
  init.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(pin.port, &init);
}

void configureInput(const GpioPin &pin, uint32_t pull)
{
  GPIO_InitTypeDef init{};
  init.Pin = pin.pin;
  init.Mode = GPIO_MODE_INPUT;
  init.Pull = pull;
  HAL_GPIO_Init(pin.port, &init);
}

void gpioWrite(const GpioPin &pin, GPIO_PinState state)
{
  HAL_GPIO_WritePin(pin.port, pin.pin, state);
}

GPIO_PinState gpioRead(const GpioPin &pin)
{
  return HAL_GPIO_ReadPin(pin.port, pin.pin);
}

void Print::print(const char *value)
{
  if (value != nullptr)
  {
    write(reinterpret_cast<const uint8_t *>(value), std::strlen(value));
  }
}

void Print::print(char value)
{
  write(static_cast<uint8_t>(value));
}

void Print::print(bool value)
{
  print(value ? "true" : "false");
}

template <typename T>
static void printInteger(Print &output, T value, int base, bool signedValue)
{
  char buffer[32];
  if (base == Hexadecimal)
  {
    std::snprintf(buffer, sizeof(buffer), "%llX", static_cast<unsigned long long>(value));
  }
  else if (signedValue)
  {
    std::snprintf(buffer, sizeof(buffer), "%lld", static_cast<long long>(value));
  }
  else
  {
    std::snprintf(buffer, sizeof(buffer), "%llu", static_cast<unsigned long long>(value));
  }
  output.print(buffer);
}

void Print::print(int value, int base) { printInteger(*this, value, base, true); }
void Print::print(unsigned value, int base) { printInteger(*this, value, base, false); }
void Print::print(long value, int base) { printInteger(*this, value, base, true); }
void Print::print(unsigned long value, int base) { printInteger(*this, value, base, false); }
void Print::print(long long value, int base) { printInteger(*this, value, base, true); }
void Print::print(unsigned long long value, int base) { printInteger(*this, value, base, false); }

void Print::print(float value, int digits)
{
  print(static_cast<double>(value), digits);
}

void Print::print(double value, int digits)
{
  if (digits < 0)
  {
    digits = 0;
  }
  if (digits > 6)
  {
    digits = 6;
  }
  if (value != value)
  {
    print("nan");
    return;
  }
  if (value < 0.0)
  {
    print('-');
    value = -value;
  }
  if (value > 4294967295.0)
  {
    print("overflow");
    return;
  }
  uint32_t integerPart = static_cast<uint32_t>(value);
  uint32_t scale = 1U;
  for (int index = 0; index < digits; ++index) scale *= 10U;
  uint32_t fraction = static_cast<uint32_t>((value - integerPart) * scale + 0.5);
  if (fraction >= scale && scale > 1U)
  {
    fraction = 0U;
    ++integerPart;
  }
  print(static_cast<unsigned long>(integerPart));
  if (digits == 0) return;
  print('.');
  uint32_t divisor = scale / 10U;
  while (divisor > 1U && fraction < divisor)
  {
    print('0');
    divisor /= 10U;
  }
  print(static_cast<unsigned long>(fraction));
}

void Print::println()
{
  static const uint8_t newline[] = {'\r', '\n'};
  write(newline, sizeof(newline));
}

int Print::printf(const char *format, ...)
{
  char buffer[256];
  va_list arguments;
  va_start(arguments, format);
  const int written = std::vsnprintf(buffer, sizeof(buffer), format, arguments);
  va_end(arguments);
  if (written > 0)
  {
    const size_t length = static_cast<size_t>(written) < sizeof(buffer)
        ? static_cast<size_t>(written)
        : sizeof(buffer) - 1U;
    write(reinterpret_cast<const uint8_t *>(buffer), length);
  }
  return written;
}

UartPort::UartPort()
    : handle_(nullptr), head_(0U), tail_(0U), interruptRx_(true), rxByte_(0U), rxBuffer_{}
{
}

void UartPort::attach(UART_HandleTypeDef *handle, bool enableInterruptRx)
{
  handle_ = handle;
  interruptRx_ = enableInterruptRx;
  clearRx();
  startRx();
}

void UartPort::end()
{
  if (handle_ != nullptr)
  {
    (void)HAL_UART_Abort(handle_);
    (void)HAL_UART_DeInit(handle_);
  }
}

bool UartPort::begin(uint32_t baudRate, UartFrameFormat format)
{
  if (handle_ == nullptr)
  {
    return false;
  }

  HAL_UART_AbortReceive(handle_);
  handle_->Init.BaudRate = baudRate;
  handle_->Init.WordLength = format == UartFrameFormat::Data8N1
      ? UART_WORDLENGTH_8B
      : UART_WORDLENGTH_9B;
  handle_->Init.Parity = format == UartFrameFormat::Data8E1
      ? UART_PARITY_EVEN
      : (format == UartFrameFormat::Data8O1 ? UART_PARITY_ODD : UART_PARITY_NONE);
  handle_->Init.StopBits = UART_STOPBITS_1;
  handle_->Init.Mode = UART_MODE_TX_RX;
  handle_->Init.HwFlowCtl = UART_HWCONTROL_NONE;
  handle_->Init.OverSampling = UART_OVERSAMPLING_16;
  if (HAL_UART_Init(handle_) != HAL_OK)
  {
    return false;
  }
  clearRx();
  startRx();
  return true;
}

int UartPort::available() const
{
  return static_cast<int>((head_ + RxCapacity - tail_) % RxCapacity);
}

int UartPort::availableForWrite() const
{
  return handle_ == nullptr || handle_->gState != HAL_UART_STATE_READY ? 0 : 1;
}

int UartPort::read()
{
  if (tail_ == head_)
  {
    return -1;
  }
  const uint8_t value = rxBuffer_[tail_];
  tail_ = static_cast<uint16_t>((tail_ + 1U) % RxCapacity);
  return value;
}

size_t UartPort::write(const uint8_t *data, size_t length)
{
  if (handle_ == nullptr || data == nullptr || length == 0U)
  {
    return 0U;
  }
  const HAL_StatusTypeDef result = HAL_UART_Transmit(
      handle_, const_cast<uint8_t *>(data), static_cast<uint16_t>(length), 3000U);
  return result == HAL_OK ? length : 0U;
}

void UartPort::flush()
{
  if (handle_ != nullptr)
  {
    while (__HAL_UART_GET_FLAG(handle_, UART_FLAG_TC) == RESET)
    {
    }
  }
}

void UartPort::clearRx()
{
  __disable_irq();
  head_ = 0U;
  tail_ = 0U;
  __enable_irq();
}

void UartPort::startRx()
{
  if (handle_ != nullptr && interruptRx_)
  {
    (void)HAL_UART_Receive_IT(handle_, &rxByte_, 1U);
  }
}

void UartPort::handleRxComplete()
{
  const uint16_t next = static_cast<uint16_t>((head_ + 1U) % RxCapacity);
  if (next != tail_)
  {
    rxBuffer_[head_] = rxByte_;
    head_ = next;
  }
  startRx();
}

void UartPort::recoverRx()
{
  if (handle_ != nullptr && interruptRx_)
  {
    __HAL_UART_CLEAR_OREFLAG(handle_);
    startRx();
  }
}

void initializePortsForRole()
{
  SerialMon.attach(&huart2, true);
#if APP_ROLE == APP_ROLE_LORA_GATEWAY
  SerialLoRa.attach(&huart1, true);
  SerialAt.attach(&huart6, true);
#else
  SerialLoRa.attach(&huart6, true);
#endif
}

void dispatchRxComplete(UART_HandleTypeDef *handle)
{
  if (SerialMon.handle() == handle) SerialMon.handleRxComplete();
  if (SerialLoRa.handle() == handle) SerialLoRa.handleRxComplete();
  if (SerialAt.handle() == handle) SerialAt.handleRxComplete();
}

void dispatchUartError(UART_HandleTypeDef *handle)
{
  if (SerialMon.handle() == handle) SerialMon.recoverRx();
  if (SerialLoRa.handle() == handle) SerialLoRa.recoverRx();
  if (SerialAt.handle() == handle) SerialAt.recoverRx();
}
}

extern "C" void HAL_UART_RxCpltCallback(UART_HandleTypeDef *handle)
{
  Platform::dispatchRxComplete(handle);
}

extern "C" void HAL_UART_ErrorCallback(UART_HandleTypeDef *handle)
{
  Platform::dispatchUartError(handle);
}
