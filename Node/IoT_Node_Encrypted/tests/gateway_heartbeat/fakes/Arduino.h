#pragma once
#include <stdint.h>
#include <stddef.h>
#define HIGH 1
class HardwareSerial {};
extern uint32_t testTick;
inline uint32_t millis() { return testTick; }
inline int digitalRead(uint32_t) { return HIGH; }
