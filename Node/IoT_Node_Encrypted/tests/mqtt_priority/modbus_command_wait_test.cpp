// Actual ModbusMaster: a command callback must not consume the sensor timeout.
#include "../../src/third_party/ModbusMaster/ModbusMaster.h"
#include <cassert>
#include <deque>
#include <iostream>
#include <string>
uint32_t testNow=100;
bool tickOnMillis=true;
static bool commandDone=false;
static int commandCalls=0;
class SensorStream:public Stream {
public:
    bool respond=true, badCrc=false, tx=false;
    std::deque<uint8_t> rx;
    size_t write(uint8_t) override { tx=true; return 1; }
    int available() override { return tx && commandDone?int(rx.size()):0; }
    int read() override { if(!available()) return -1; int b=rx.front(); rx.pop_front(); return b; }
    int peek() override { return available()?int(rx.front()):-1; }
    void flush() override {
        if(!respond) return;
        const uint8_t payload[]={1,3,2,0,123};
        uint16_t crc=0xFFFF;
        for(uint8_t b:payload) { rx.push_back(b); crc=crc16_update(crc,b); }
        rx.push_back(uint8_t(crc)); rx.push_back(uint8_t(crc>>8)^(badCrc?1:0));
    }
};
static void commandService() {
    if(!commandDone) { testNow+=3000; commandDone=true; ++commandCalls; }
}
int main(int argc,char** argv) {
    assert(argc==2);
    const std::string scenario=argv[1];
    SensorStream stream;
    stream.respond=scenario!="offline"; stream.badCrc=scenario=="bad_crc";
    ModbusMaster sensor; sensor.begin(1,stream); sensor.idle(commandService);
    const uint8_t result=sensor.readHoldingRegisters(0,1);
    assert(commandCalls==1);
    if(scenario=="response_after_command") {
        assert(result==sensor.ku8MBSuccess && sensor.getResponseBuffer(0)==123);
    } else if(scenario=="bad_crc") assert(result==sensor.ku8MBInvalidCRC);
    else { assert(scenario=="offline" && result==sensor.ku8MBResponseTimedOut); assert(testNow<7000); }
    std::cout<<"PASS Modbus "<<scenario<<'\n';
}
