#pragma once
#include <stdint.h>
#include <stddef.h>
#define HIGH 1
#include <cstdio>
#include <string>
class HardwareSerial {
public:
    std::string text;
    void print(const char* value) { text += value; }
    void print(char value) { text += value; }
    void print(unsigned long value) { text += std::to_string(value); }
    void print(float value, int digits) {
        char formatted[64];
        std::snprintf(formatted, sizeof(formatted), "%.*f", digits, value);
        text += formatted;
    }
    void println() { text += '\n'; }
    void begin(unsigned long) {}
};
extern uint32_t testTick;
inline uint32_t millis() { return testTick; }
inline int digitalRead(uint32_t) { return HIGH; }
