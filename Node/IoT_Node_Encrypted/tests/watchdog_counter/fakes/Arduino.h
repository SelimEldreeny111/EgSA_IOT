#pragma once
#include <stdint.h>
struct HardwareSerial {
    template<class T> void print(T) {}
    template<class T> void println(T) {}
    void println() {}
    void flush() {}
};
inline void delay(uint32_t) {}
inline void noInterrupts() {}
inline void NVIC_SystemReset() {}
inline void __WFI() {}
inline void __NOP() {}
