#pragma once
#include <stdint.h>
#include <stddef.h>
#include <sstream>
struct HardwareSerial {
    std::ostringstream output;
    unsigned begins=0, flushes=0, writes=0;
    void begin(unsigned) { ++begins; }
    void flush() { ++flushes; }
    template<class T> void print(const T& value) { ++writes; output<<value; }
    template<class T> void print(const T& value,int) { print(value); }
    void println() { ++writes; output<<'\n'; }
};
uint32_t millis();
