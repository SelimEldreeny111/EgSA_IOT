#ifndef TEST_AVAILABILITY_ARDUINO_H
#define TEST_AVAILABILITY_ARDUINO_H
#include <cstddef>
#include <cstdint>
class HardwareSerial {
public:
    template<class T> void print(const T&) {}
    template<class T> void print(const T&, int) {}
    template<class T> void println(const T&) {}
    void println() {}
};
#endif
