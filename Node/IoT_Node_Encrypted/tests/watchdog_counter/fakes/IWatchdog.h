#pragma once
#include <stdint.h>
struct FakeWatchdog {
    bool reset=false, enabled=false;
    int captures=0, starts=0, reloads=0;
    bool isReset(bool clear) { ++captures; const bool r=reset; if(clear) reset=false; return r; }
    void begin(uint32_t) { ++starts; enabled=true; }
    bool isEnabled() { return enabled; }
    void reload() { ++reloads; }
    void set(uint32_t) {}
};
extern FakeWatchdog IWatchdog;
