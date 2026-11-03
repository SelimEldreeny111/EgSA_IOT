#pragma once
#include <stdint.h>
#include <stddef.h>
#include <vector>
struct HardwareSerial {
 std::vector<uint8_t> tx;
 template<class T> void print(const T&) {} template<class T> void print(const T&,int) {}
 template<class T> void println(const T&) {} void println() {}
 void begin(unsigned,int){} void end(){} int available(){return 0;} int read(){return -1;}
 int availableForWrite(){return 512;} size_t write(uint8_t value){tx.push_back(value);return 1;} void flush(){}
};
constexpr int HIGH=1,LOW=0,OUTPUT=1,HEX=16,MSBFIRST=1,SPI_MODE0=0,INPUT=0;
uint32_t millis();
void digitalWrite(uint32_t,int);
void pinMode(uint32_t,int);
void delayMicroseconds(unsigned);

int digitalRead(uint32_t);
void delay(unsigned);
void yield();
