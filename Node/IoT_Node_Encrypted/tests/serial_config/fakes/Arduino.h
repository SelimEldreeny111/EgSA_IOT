#pragma once
#include <cstdint>
#include <deque>
#include <sstream>

#define PC13 45
enum { PA0, PA4, PA5, PA6, PA7, PA8, PA9, PA10, PA11, PA12, PB0, PB1, PB2, PB7, PB8, PB9, PB15, HEX=16 };
struct SoftwareReset {};
[[noreturn]] inline void NVIC_SystemReset() { throw SoftwareReset{}; }

class HardwareSerial {
public:
    unsigned baud = 0;
    std::deque<char> input;
    std::ostringstream output;
    void begin(unsigned baudRate) { baud = baudRate; }
    int available() const { return input.size(); }
    int read() { int byte = input.front(); input.pop_front(); return byte; }
    template<class T> void print(const T& value) { output << value; }
    void print(uint8_t value) { output << unsigned(value); }
    void print(uint16_t value, int) { output << std::hex << value << std::dec; }
    template<class T> void println(const T& value) { print(value); println(); }
    void println() { output << '\n'; }
    void flush() {}
};

uint32_t millis();
void delay(uint32_t ms);
