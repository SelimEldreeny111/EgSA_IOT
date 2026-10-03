// Compile real Watchdog.cpp + persistent storage; each process simulates one boot.
#include "../../src/platform/Watchdog.h"
#include "../../src/platform/WatchdogResetCounter.h"
#include "fakes/IWatchdog.h"
#include <array>
#include <cassert>
#include <cstring>
#include <iostream>
#include <string>

HardwareSerial SerialMon;
FakeWatchdog IWatchdog;
bool testWatchdogEnabled=true;
static std::array<uint8_t,512> flash, buffer;
static bool failWrite=false;
static int flushes=0;
void eeprom_buffer_fill() { buffer=flash; }
uint8_t eeprom_buffered_read_byte(uint32_t a) { return buffer.at(a); }
void eeprom_buffered_write_byte(uint32_t a,uint8_t v) { buffer.at(a)=v; }
void eeprom_buffer_flush() { ++flushes; if(!failWrite) flash=buffer; }

static void seed(uint32_t count) {
    uint32_t words[5]={0x57444331U,1U,count,~count,0};
    const uint8_t* bytes=reinterpret_cast<const uint8_t*>(words);
    uint32_t hash=2166136261U;
    for(size_t i=0;i<16;i++) hash=(hash^bytes[i])*16777619U;
    words[4]=hash;
    memcpy(flash.data()+192,words,sizeof(words));
}
int main(int argc,char** argv) {
    assert(argc==2);
    const std::string scenario=argv[1];
    flash.fill(0xFF);
    uint32_t expected=0;
    int expectedFlushes=0;
    bool expectedHealthy=true, expectedInvalid=false;
    if(scenario=="normal_existing") { seed(7); expected=7; }
    else if(scenario=="watchdog_existing" || scenario=="disabled_watchdog" || scenario=="preserve_shared_records") {
        seed(7); IWatchdog.reset=true; expected=8; expectedFlushes=1;
        if(scenario=="disabled_watchdog") testWatchdogEnabled=false;
    }
    else if(scenario=="first_watchdog") { IWatchdog.reset=true; expected=1; expectedFlushes=1; }
    else if(scenario=="saturation") { seed(UINT32_MAX); IWatchdog.reset=true; expected=UINT32_MAX; }
    else if(scenario=="corrupt_normal" || scenario=="corrupt_watchdog") {
        seed(7); flash[200]^=0x01; expectedInvalid=true;
        if(scenario=="corrupt_watchdog") { IWatchdog.reset=true; expected=1; expectedFlushes=1; }
    }
    else if(scenario=="write_failure") {
        seed(7); failWrite=true; IWatchdog.reset=true; expected=8; expectedFlushes=1; expectedHealthy=false;
    }
    else assert(scenario=="first_normal" || scenario=="duplicate_init");
    if(scenario=="preserve_shared_records") {
        for(size_t i=0;i<192;i++) flash[i]=uint8_t(i);
        for(size_t i=212;i<512;i++) flash[i]=uint8_t(i);
    }
    const auto before=flash;
    initializeHardwareWatchdog();
    assert(hardwareWatchdogResetCount()==expected);
    assert(WatchdogResetCounter::storageHealthy()==expectedHealthy);
    assert(WatchdogResetCounter::recoveredInvalidRecord()==expectedInvalid);
    assert(flushes==expectedFlushes);
    assert(IWatchdog.captures==1);
    if(!failWrite && expectedFlushes) {
        uint32_t stored; memcpy(&stored,flash.data()+200,4); assert(stored==expected);
    }
    for(size_t i=0;i<flash.size();i++) if(i<192 || i>=212) assert(flash[i]==before[i]);
    // Repeated application initialization must not consume/count another reset.
    IWatchdog.reset=true;
    initializeHardwareWatchdog();
    WatchdogResetCounter::initialize(true);
    assert(hardwareWatchdogResetCount()==expected && flushes==expectedFlushes && IWatchdog.captures==1);
    reportHardwareWatchdogStatus();
    const int reloads=IWatchdog.reloads;
    {
        const HardwareWatchdogServicePause outer;
        serviceHardwareWatchdog();
        {
            const HardwareWatchdogServicePause inner;
            serviceHardwareWatchdog(WatchdogStage::MqttService);
        }
        serviceHardwareWatchdog();
        assert(IWatchdog.reloads==reloads);
    }
    serviceHardwareWatchdog();
    assert(IWatchdog.reloads==reloads+(testWatchdogEnabled?1:0));
    std::cout << "PASS " << scenario << '\n';
}
