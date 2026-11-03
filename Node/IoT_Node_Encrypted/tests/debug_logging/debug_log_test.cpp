/** @file debug_log_test.cpp @brief Prove silent calls do not evaluate arguments or touch UART. */
#define APP_LOG_MODULE "TEST"
#include "../../src/platform/DebugLog.h"
#include "Arduino.h"
#include <cassert>
#include <iostream>
#include <string>
HardwareSerial SerialMon;
uint32_t clockReads=0;
uint32_t millis() { ++clockReads; return 1234; }
void completePartialLine();
int main() {
    unsigned effects=0;
    APP_DEBUG_BEGIN(115200);
    APP_DEBUG_PRINT("unique_debug_string_7f93a: ");
    APP_DEBUG_PRINT(++effects);
    APP_DEBUG_PRINTLN();
    APP_DEBUG_PRINTLN("first\nsecond\r\n");
    APP_DEBUG_WRITE('x'); APP_DEBUG_WRITE('\n');
    APP_LOG_INFO("event request=%u", ++effects);
    APP_LOG_WARN("warn"); APP_LOG_ERROR("error");
    APP_DEBUG_ONLY(++effects);
    APP_DEBUG_PRINTF("printf_bridge %u", effects);
    const uint8_t bytes[]={0x45,0x47,0x01};
    APP_DEBUG_HEX("optional_hex", bytes, (++effects, sizeof(bytes)));
    (void)bytes;
    APP_DEBUG_PRINT("partial "); completePartialLine();
    APP_DEBUG_FLUSH();
#if APP_ENABLE_DEBUG
    assert(effects==(APP_DEBUG_RAW_FRAMES?4U:3U));
    assert(SerialMon.begins==1 && SerialMon.flushes==1 && clockReads>0);
    const std::string text=SerialMon.output.str();
    assert(text.find("[tick_ms=1234][INFO][TEST] unique_debug_string_7f93a: 1\n")!=std::string::npos);
    assert(text.find("[tick_ms=1234][INFO][TEST] first\n[tick_ms=1234][INFO][TEST] second\n")!=std::string::npos);
    assert(text.find("[tick_ms=1234][WARN][TEST] warn\n")!=std::string::npos);
    assert(text.find("[tick_ms=1234][ERROR][TEST] error\n")!=std::string::npos);
    assert(text.find("[tick_ms=1234][INFO][TEST] partial complete\n[tick_ms=1234][WARN][RADIO] cross_module_event\n")!=std::string::npos);
    assert((text.find("optional_hex")!=std::string::npos)==bool(APP_DEBUG_RAW_FRAMES));
    assert(std::string(WiotDebug::Decimal64(UINT64_MAX).text)=="18446744073709551615");
    assert(std::string(WiotDebug::Decimal64(0).text)=="0");
    APP_LOG_INFO("%s",std::string(600,'a').c_str());
    assert(SerialMon.output.str().find(" [truncated]\n")!=std::string::npos);
    for(uint32_t id=1;id<=14;++id) assert(std::string(WiotDebug::commandName(id))!="UNKNOWN");
#else
    assert(effects==0 && clockReads==0);
    assert(SerialMon.begins==0 && SerialMon.flushes==0 && SerialMon.writes==0);
    assert(SerialMon.output.str().empty());
#endif
    std::cout<<"PASS debug policy: enabled="<<APP_ENABLE_DEBUG<<" raw="<<APP_DEBUG_RAW_FRAMES<<'\n';
}
