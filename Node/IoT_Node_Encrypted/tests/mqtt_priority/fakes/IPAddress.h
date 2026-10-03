#pragma once
#include <stdint.h>
struct IPAddress {
    IPAddress()=default;
    IPAddress(uint8_t*) {}
    IPAddress(uint8_t,uint8_t,uint8_t,uint8_t) {}
};
