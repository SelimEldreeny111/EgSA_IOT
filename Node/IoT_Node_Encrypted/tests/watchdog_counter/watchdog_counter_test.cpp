// Compile real Watchdog.cpp + persistent storage; each process simulates one boot.
#include "../../src/platform/Watchdog.h"
#include "../../src/platform/WatchdogResetCounter.h"
#include "../../src/platform/PowerResetCounter.h"
#include "../../src/platform/ResetCause.h"
#include "fakes/IWatchdog.h"
#include <array>
#include <cassert>
#include <cstring>
#include <iostream>
#include <string>

HardwareSerial SerialMon;
FakeWatchdog IWatchdog;
bool testWatchdogEnabled=true;
FakeRcc testRcc;
FakeRcc* RCC=&testRcc;
bool testStandbyWake=false;
static std::array<uint8_t,512> flash, buffer;
static bool failWrite=false;
static int flushes=0;
void eeprom_buffer_fill() { buffer=flash; }
uint8_t eeprom_buffered_read_byte(uint32_t a) { return buffer.at(a); }
void eeprom_buffered_write_byte(uint32_t a,uint8_t v) { buffer.at(a)=v; }
void eeprom_buffer_flush() { ++flushes; if(!failWrite) flash=buffer; }

static void seed(uint32_t count, size_t address=192, uint32_t magic=0x57444331U) {
    uint32_t words[5]={magic,1U,count,~count,0};
    const uint8_t* bytes=reinterpret_cast<const uint8_t*>(words);
    uint32_t hash=2166136261U;
    for(size_t i=0;i<16;i++) hash=(hash^bytes[i])*16777619U;
    words[4]=hash;
    memcpy(flash.data()+address,words,sizeof(words));
}
int main(int argc,char** argv) {
    assert(argc==2);
    const std::string scenario=argv[1];
    flash.fill(0xFF);
    uint32_t expected=0;
    int expectedFlushes=0;
    bool expectedHealthy=true, expectedInvalid=false;
    uint32_t expectedPower=0U;
    if(scenario=="power_on" || scenario=="brownout" || scenario=="pin_reset" ||
       scenario=="software_reset" || scenario=="standby_wake" || scenario=="mixed_iwdg_power" ||
       scenario=="clear_wdt" || scenario=="clear_power" || scenario=="clear_failure" || scenario=="clear_power_failure" ||
       scenario=="power_saturation" || scenario=="power_corrupt" || scenario=="power_write_failure") {
        seed(7); seed(12,232,0x50574331U); expected=7; expectedPower=12;
        if(scenario=="power_on" || scenario=="brownout" || scenario=="power_write_failure") {
            testRcc.CSR=scenario=="brownout" ? ResetCause::Brownout : ResetCause::PowerOn | ResetCause::Pin;
            expectedPower=13; expectedFlushes=1;
            failWrite=scenario=="power_write_failure";
        } else if(scenario=="pin_reset") testRcc.CSR=ResetCause::Pin;
        else if(scenario=="software_reset") testRcc.CSR=ResetCause::PowerOn | ResetCause::Software;
        else if(scenario=="standby_wake") {
            testRcc.CSR=ResetCause::PowerOn; testStandbyWake=true;
            captureHardwareResetCause(); testStandbyWake=false; // Real PowerManager clears this.
        } else if(scenario=="mixed_iwdg_power") {
            testRcc.CSR=ResetCause::Iwdg | ResetCause::PowerOn;
            IWatchdog.reset=true; expected=8; expectedFlushes=1;
        } else if(scenario=="power_saturation") {
            seed(UINT32_MAX,232,0x50574331U); expectedPower=UINT32_MAX;
            testRcc.CSR=ResetCause::PowerOn;
        } else if(scenario=="power_corrupt") {
            flash[240]^=1; testRcc.CSR=ResetCause::PowerOn;
            expectedPower=1; expectedFlushes=1;
        }
    }
    else if(scenario=="normal_existing") { seed(7); expected=7; }
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
    assert(powerResetCount()==expectedPower);
    assert(RCC->CSR==0U); // Clear sticky causes on normal/POR boots too.
    assert(WatchdogResetCounter::storageHealthy()==expectedHealthy);
    assert(WatchdogResetCounter::recoveredInvalidRecord()==expectedInvalid);
    assert(flushes==expectedFlushes);
    assert(IWatchdog.captures==1);
    if(!failWrite && expectedFlushes && expected!=7U) {
        uint32_t stored; memcpy(&stored,flash.data()+200,4); assert(stored==expected);
    }
    for(size_t i=0;i<flash.size();i++)
        if((i<192 || i>=212) && (i<232 || i>=252)) assert(flash[i]==before[i]);
    // Repeated application initialization must not consume/count another reset.
    IWatchdog.reset=true;
    initializeHardwareWatchdog();
    WatchdogResetCounter::initialize(true);
    assert(hardwareWatchdogResetCount()==expected && flushes==expectedFlushes && IWatchdog.captures==1);
    assert(powerResetCount()==expectedPower);
    if(scenario=="clear_wdt" || scenario=="clear_power" || scenario=="clear_failure" || scenario=="clear_power_failure") {
        const auto originalFlash=flash;
        failWrite=scenario=="clear_failure" || scenario=="clear_power_failure";
        const bool cleared=(scenario=="clear_power" || scenario=="clear_power_failure")
            ? PowerResetCounter::clear() : WatchdogResetCounter::clear();
        assert(cleared!=failWrite);
        assert(hardwareWatchdogResetCount()==(scenario=="clear_wdt" ? 0U : expected));
        assert(powerResetCount()==(scenario=="clear_power" ? 0U : expectedPower));
        if(failWrite) assert(flash==originalFlash);
        else {
            const size_t clearedAddress=scenario=="clear_wdt" ? 192U : 232U;
            uint32_t storedCount=UINT32_MAX;
            memcpy(&storedCount,flash.data()+clearedAddress+8U,4U);
            assert(storedCount==0U);
            for(size_t index=0;index<flash.size();++index)
                if(index<clearedAddress || index>=clearedAddress+20U)
                    assert(flash[index]==originalFlash[index]);
            const int savedFlushes=flushes;
            if(scenario=="clear_wdt") assert(WatchdogResetCounter::clear());
            else assert(PowerResetCounter::clear());
            assert(flushes==savedFlushes); // Verified-zero clear does not wear flash.
        }
        if(scenario=="clear_power_failure") assert(!PowerResetCounter::storageHealthy());
    }
    if(scenario=="power_write_failure") assert(!PowerResetCounter::storageHealthy());
    if(scenario=="power_corrupt") assert(PowerResetCounter::recoveredInvalidRecord());
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
