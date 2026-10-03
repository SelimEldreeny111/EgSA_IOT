#pragma once
#include "Arduino.h"
#include "IPAddress.h"
class Client:public Stream {
public:
    using Stream::read;
    virtual int connect(IPAddress,uint16_t)=0;
    virtual int connect(const char*,uint16_t)=0;
    virtual void stop()=0;
    virtual uint8_t connected()=0;
    virtual operator bool()=0;
    virtual int read(uint8_t* bytes,size_t size) {
        size_t n=0; while(n<size && available()) bytes[n++]=static_cast<uint8_t>(read()); return int(n);
    }
};
