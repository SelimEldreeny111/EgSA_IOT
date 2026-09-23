#ifndef WIOT_STM32_PLATFORM_HPP
#define WIOT_STM32_PLATFORM_HPP

#include "main.h"

#include <cstddef>
#include <cstdint>

namespace Platform
{
constexpr int Decimal = 10;
constexpr int Hexadecimal = 16;

struct GpioPin
{
  GPIO_TypeDef *port;
  uint16_t pin;
};

enum class UartFrameFormat : uint8_t
{
  Data8N1,
  Data8E1,
  Data8O1
};

uint32_t millis();
uint32_t micros();
void delayMs(uint32_t delay);
void delayUs(uint32_t delay);
void yield();

void configureOutput(const GpioPin &pin, GPIO_PinState initialState);
void configureInput(const GpioPin &pin, uint32_t pull = GPIO_NOPULL);
void gpioWrite(const GpioPin &pin, GPIO_PinState state);
GPIO_PinState gpioRead(const GpioPin &pin);

class Print
{
public:
  virtual ~Print() = default;
  virtual size_t write(const uint8_t *data, size_t length) = 0;
  size_t write(uint8_t value) { return write(&value, 1U); }

  void print(const char *value);
  void print(char value);
  void print(bool value);
  void print(int value, int base = Decimal);
  void print(unsigned value, int base = Decimal);
  void print(long value, int base = Decimal);
  void print(unsigned long value, int base = Decimal);
  void print(long long value, int base = Decimal);
  void print(unsigned long long value, int base = Decimal);
  void print(float value, int digits = 2);
  void print(double value, int digits = 2);
  void println();

  template <typename T>
  void println(const T &value)
  {
    print(value);
    println();
  }

  template <typename T>
  void println(const T &value, int format)
  {
    print(value, format);
    println();
  }

  int printf(const char *format, ...);
};

class UartPort : public Print
{
public:
  static constexpr size_t RxCapacity = 1024U;

  UartPort();
  void attach(UART_HandleTypeDef *handle, bool enableInterruptRx = true);
  void end();
  bool begin(uint32_t baudRate, UartFrameFormat format = UartFrameFormat::Data8N1);
  int available() const;
  int availableForWrite() const;
  int read();
  size_t write(const uint8_t *data, size_t length) override;
  using Print::write;
  void flush();
  void clearRx();
  UART_HandleTypeDef *handle() const { return handle_; }
  void handleRxComplete();
  void recoverRx();

private:
  void startRx();
  UART_HandleTypeDef *handle_;
  volatile uint16_t head_;
  volatile uint16_t tail_;
  bool interruptRx_;
  uint8_t rxByte_;
  uint8_t rxBuffer_[RxCapacity];
};

void initializePortsForRole();
void dispatchRxComplete(UART_HandleTypeDef *handle);
void dispatchUartError(UART_HandleTypeDef *handle);
}

extern Platform::UartPort SerialMon;
extern Platform::UartPort SerialLoRa;
extern Platform::UartPort SerialAt;

#endif
