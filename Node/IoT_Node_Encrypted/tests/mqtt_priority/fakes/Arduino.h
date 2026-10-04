#pragma once
#include <stdint.h>
#include <stddef.h>
#include <algorithm>
#include <string>
#include <vector>
#include <cstring>
#include <cstdlib>
using boolean=bool;
#define PROGMEM
#define pgm_read_byte_near(p) (*(const uint8_t*)(p))
using byte=uint8_t;
#define HEX 16
#define HIGH 1
#define LOW 0
#define OUTPUT 1
#define OUTPUT_OPEN_DRAIN 2
#define SERIAL_8N1 0
#define lowByte(x) ((uint8_t)((x)&0xFF))
#define highByte(x) ((uint8_t)(((x)>>8)&0xFF))
#define bitRead(x,b) (((x)>>(b))&1U)
#define bitWrite(x,b,v) ((v)?((x)|=(1UL<<(b))):((x)&=~(1UL<<(b))))
extern uint32_t testNow;
extern bool tickOnMillis;
inline uint32_t millis() { if(tickOnMillis) ++testNow; return testNow; }
inline uint32_t micros() { return millis()*1000U; }
inline void delay(uint32_t ms) { testNow+=ms; }
inline void delayMicroseconds(uint32_t) {}
struct TestPinEvent { bool mode; uint32_t pin; uint8_t value; uint32_t at; };
inline std::vector<TestPinEvent>& testPinEvents() { static std::vector<TestPinEvent> events; return events; }
inline void pinMode(uint32_t pin,uint8_t mode) { testPinEvents().push_back({true,pin,mode,testNow}); }
inline void digitalWrite(uint32_t pin,uint8_t value) { testPinEvents().push_back({false,pin,value,testNow}); }
inline uint16_t word(uint16_t value) { return value; }
inline uint16_t word(uint8_t high,uint8_t low) { return (uint16_t(high)<<8)|low; }
inline void yield() { ++testNow; }
class Print {
public:
    virtual ~Print()=default;
    virtual size_t write(uint8_t)=0;
    virtual size_t write(const uint8_t* bytes,size_t size) {
        size_t n=0; while(n<size) n+=write(bytes[n]); return n;
    }
};
class Stream:public Print {
public:
    virtual ~Stream()=default;
    virtual int available()=0;
    virtual int read()=0;
    virtual int peek()=0;
    virtual void flush()=0;
    virtual size_t write(uint8_t)=0;
    virtual size_t write(const uint8_t* bytes,size_t size) {
        size_t n=0; while(n<size) n+=write(bytes[n]); return n;
    }
};
class HardwareSerial:public Stream {
public:
    int rawWrites=0;
    void begin(uint32_t,uint32_t=0) {}
    void end() {}
    int available() override { return 0; }
    int read() override { return -1; }
    int peek() override { return -1; }
    void flush() override {}
    size_t write(uint8_t) override { ++rawWrites; return 1; }
    using Stream::write;
    template<class T> void print(T) {}
    template<class T> void print(T,int) {}
    template<class T> void println(T) {}
    void println() {}
};
