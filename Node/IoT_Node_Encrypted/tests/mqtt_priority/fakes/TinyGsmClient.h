#pragma once
#include "Client.h"
#include <deque>
#include <functional>
class TinyGsm {
public:
    explicit TinyGsm(HardwareSerial&) {}
    bool init() { return true; }
    bool isNetworkConnected() { return true; }
    int getSignalQuality() { return 20; }
};
class TinyGsmClient:public Client {
protected:
    bool sock_connected=true;
public:
    explicit TinyGsmClient(TinyGsm&) {}
    int sendLimit=-1, writes=0, stops=0;
    bool& live=sock_connected;
    std::function<int()> pendingInput;
    std::vector<std::vector<uint8_t>> sent;
    std::deque<uint8_t> rx;
    std::function<void(const std::vector<uint8_t>&)> onSend;
    int connect(IPAddress,uint16_t) override { live=true; return 1; }
    int connect(const char*,uint16_t) override { live=true; return 1; }
    void stop() override { ++stops; live=false; }
    uint8_t connected() override { return live; }
    operator bool() override { return live; }
    int available() override { return int(rx.size())+(pendingInput?pendingInput():0); }
    int read() override { if(rx.empty()) return -1; int b=rx.front(); rx.pop_front(); return b; }
    int peek() override { return rx.empty()?-1:int(rx.front()); }
    void flush() override {}
    size_t write(uint8_t b) override { return write(&b,1); }
    size_t write(const uint8_t* bytes,size_t length) override {
        ++writes;
        const size_t accepted=sendLimit<0?length:std::min(length,size_t(sendLimit));
        sent.emplace_back(bytes,bytes+accepted);
        if(onSend && accepted==length) onSend(sent.back());
        return accepted;
    }
};
