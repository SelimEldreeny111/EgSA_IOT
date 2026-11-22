// Exercise the actual Supmea driver and ModbusMaster against two wire responses.
#include "../../src/devices/SupmeaSensor.h"
#include <cassert>
#include <deque>
#include <iostream>
#include <utility>
#include <vector>

uint32_t testNow = 100;
bool tickOnMillis = true;
HardwareSerial SerialMon;
void serviceHardwareWatchdog() {}

class SupmeaStream : public Stream
{
public:
    using Block = std::pair<uint16_t, uint16_t>;
    std::vector<Block> reads;
    std::deque<uint8_t> incoming;
    std::vector<uint8_t> request;
    bool liveResponseEnabled = true;

    size_t write(uint8_t value) override { request.push_back(value); return 1; }
    int available() override { return static_cast<int>(incoming.size()); }
    int peek() override { return incoming.empty() ? -1 : incoming.front(); }
    int read() override
    {
        const int value = peek();
        if (value >= 0) incoming.pop_front();
        return value;
    }

    void flush() override
    {
        assert(request.size() == 8 && request[0] == 2 && request[1] == 3);
        const uint16_t start = word(request[2], request[3]);
        const uint16_t count = word(request[4], request[5]);
        request.clear();
        reads.emplace_back(start, count);

        std::vector<uint8_t> frame{2, 3, static_cast<uint8_t>(count * 2)};
        if (start == 90 && count == 6) {
            // 1250.75, 25.25, 1225.5 m³
            frame.insert(frame.end(), {0x44, 0x9C, 0x58, 0x00, 0x41, 0xCA, 0, 0, 0x44, 0x99, 0x30, 0x00});
        } else {
            assert(start == 98 && count == 4);
            if (!liveResponseEnabled) return;
            // 35.0 m³/h, 1.25 m/s
            frame.insert(frame.end(), {0x42, 0x0C, 0, 0, 0x3F, 0xA0, 0, 0});
        }
        uint16_t crc = 0xFFFF;
        for (uint8_t value : frame) crc = crc16_update(crc, value);
        frame.push_back(lowByte(crc));
        frame.push_back(highByte(crc));
        incoming.assign(frame.begin(), frame.end());
    }
};

static SupmeaStream bus;
void configureRs485Modbus(ModbusMaster& sensor, uint8_t address) { sensor.begin(address, bus); }

int main()
{
    using Blocks = std::vector<SupmeaStream::Block>;
    initializeSupmeaSensor();
    assert((bus.reads == Blocks{{98, 4}}));
    bus.reads.clear();

    const SupmeaSensorData sample = readSupmeaSensor();
    assert((bus.reads == Blocks{{90, 6}, {98, 4}}));
    assert(sample.isValid && sample.totalsValid && sample.liveValid);
    assert(sample.forwardTotalM3 == 1250.75f && sample.reverseTotalM3 == 25.25f && sample.netTotalM3 == 1225.5f);
    assert(sample.flowRate == 35.0f && sample.velocityMps == 1.25f);

    bus.reads.clear();
    bus.liveResponseEnabled = false;
    const SupmeaSensorData partial = readSupmeaSensor();
    assert((bus.reads == Blocks{{90, 6}, {98, 4}, {98, 4}}));
    assert(partial.totalsValid && partial.forwardTotalM3 == 1250.75f);
    assert(!partial.liveValid && partial.liveResult == ModbusMaster::ku8MBResponseTimedOut);
    std::cout << "PASS Supmea polls only totals, flow rate and velocity\n";
}
