#pragma once
#include <cstdint>
#include <vector>
#define LOW 0U
#define HIGH 1U
#define OUTPUT 1U
struct HardwareSerial {
 template<class T> void print(T) {} template<class T> void print(T,int) {}
 template<class T> void println(T) {} void println() {}
};
struct PinEvent { uint32_t pin, value, at; bool mode; };
extern uint32_t testNow;
extern std::vector<PinEvent> pinEvents;
uint32_t millis();
uint32_t micros();
void delay(uint32_t ms);
void digitalWrite(uint32_t pin, uint8_t value);
void pinMode(uint32_t pin, uint8_t mode);
inline void noInterrupts() {}
inline void interrupts() {}
