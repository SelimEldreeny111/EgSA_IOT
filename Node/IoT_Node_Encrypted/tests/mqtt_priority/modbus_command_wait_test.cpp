// Actual ModbusMaster: a command callback must not consume the sensor timeout.
#include "../../src/third_party/ModbusMaster/ModbusMaster.h"
#include <cassert>
#include <deque>
#include <iostream>
#include <string>
#include <vector>
uint32_t testNow=100;
bool tickOnMillis=true;
static bool commandDone=false;
static int commandCalls=0;
class SensorStream:public Stream {
public:
    bool tx=false;
    std::vector<uint8_t> reply;
    std::deque<uint8_t> rx;
    size_t write(uint8_t) override { tx=true; return 1; }
    int available() override { return tx && commandDone?int(rx.size()):0; }
    int read() override { if(!available()) return -1; int b=rx.front(); rx.pop_front(); return b; }
    int peek() override { return available()?int(rx.front()):-1; }
    void flush() override {
        rx.assign(reply.begin(), reply.end());
    }
};
static void commandService() {
    if(!commandDone) { testNow+=3000; commandDone=true; ++commandCalls; }
}
static unsigned responseCalls = 0;
static uint8_t observedResult = 0;
static std::vector<uint8_t> observedBytes;

static void observeResponse(uint8_t unit, uint8_t function, uint8_t result,
                            const uint8_t* bytes, uint8_t length)
{
    assert(unit == 1 && function == 3);
    ++responseCalls;
    observedResult = result;
    observedBytes.assign(bytes, bytes + length);
}

int main(int argc,char** argv) {
    assert(argc==2);
    const std::string scenario=argv[1];
    SensorStream stream;
    ModbusMaster sensor; sensor.begin(1,stream); sensor.idle(commandService);
    constexpr uint8_t registerValue = 123;
    stream.reply = {0x01, 0x03, 0x02, 0x00, registerValue, 0xF8, 0x67};
    size_t capturedLength = stream.reply.size();
    uint8_t expectedResult = sensor.ku8MBSuccess;
    if (scenario == "bad_crc") {
        stream.reply.back() ^= 1;
        expectedResult = sensor.ku8MBInvalidCRC;
    } else if (scenario == "offline" || scenario == "truncated") {
        capturedLength = scenario == "offline" ? 0 : 4;
        stream.reply.resize(capturedLength);
        expectedResult = sensor.ku8MBResponseTimedOut;
    } else if (scenario == "exception") {
        stream.reply = {0x01, 0x83, 0x02, 0xC0, 0xF1};
        capturedLength = stream.reply.size();
        expectedResult = sensor.ku8MBIllegalDataAddress;
    } else if (scenario == "wrong_unit") {
        stream.reply = {0x02, 0x03, 0x02, 0x00, registerValue, 0xBC, 0x67};
        capturedLength = 5; // The parser stops as soon as it rejects the unit.
        expectedResult = sensor.ku8MBInvalidSlaveID;
    } else {
        assert(scenario == "response_after_command");
    }

    sensor.onResponse(observeResponse);
    const uint8_t result=sensor.readHoldingRegisters(0,1);
    assert(commandCalls==1);
    assert(result == expectedResult && observedResult == expectedResult);
    assert(responseCalls == 1);
    assert(observedBytes == std::vector<uint8_t>(stream.reply.begin(), stream.reply.begin() + capturedLength));
    if (result == sensor.ku8MBSuccess) assert(sensor.getResponseBuffer(0) == registerValue);
    if (result == sensor.ku8MBResponseTimedOut) assert(testNow < 7000);
    std::cout<<"PASS Modbus "<<scenario<<'\n';
}
