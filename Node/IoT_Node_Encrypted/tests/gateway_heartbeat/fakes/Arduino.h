#pragma once
#include <stdint.h>
#include <stddef.h>
#define HIGH 1
#include <string>
class HardwareSerial {
public:
    std::string text;
    void print(const char* value) { text += value; }
    void print(char value) { text += value; }
    void print(unsigned long value) { text += std::to_string(value); }
    void println() { text += '\n'; }
    void begin(unsigned long) {}
};
extern uint32_t testTick;
inline uint32_t millis() { return testTick; }
inline int digitalRead(uint32_t) { return HIGH; }
