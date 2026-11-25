#pragma once
#include "Client.h"
#include <deque>
#include <functional>
#include <sstream>
class TinyGsm {
public:
    explicit TinyGsm(Stream&) {}
    bool init() { return true; }
    bool isNetworkConnected() { return true; }
    bool isGprsConnected() { return gprsConnected; }
    bool poweroff() { return true; }
    bool gprsConnected=true, registrationSuccess=false, gprsSuccess=false, joinSuccess=false;
    int registrationCalls=0, gprsCalls=0, joinCalls=0;
    std::vector<std::string> joinedSsids;
    bool waitForNetwork(uint32_t) { ++registrationCalls; return registrationSuccess; }
    bool gprsConnect(const char*,const char*,const char*) { ++gprsCalls; return gprsSuccess; }
    bool networkConnect(const char* ssid,const char*) {
        ++joinCalls; joinedSsids.emplace_back(ssid); return joinSuccess;
    }
    int getSignalQuality() { return 20; }
    std::vector<std::string> atCommands;
    int atFailure = -1, secureConnectCalls = 0, secureTimeout = 0, securePort = 0;
    std::string secureHost;
    bool secureConnectSuccess = true;
    template<class... Args> void sendAT(const Args&... args) {
        std::ostringstream text;
        int parts[] = {0, ((text << args), 0)...};
        (void)parts;
        atCommands.push_back(text.str());
    }
    int waitResponse(uint32_t timeout) {
        return timeout == 1000 && static_cast<int>(atCommands.size()) != atFailure ? 1 : 0;
    }
};
class TinyGsmClient:public Client {
protected:
    bool sock_connected=true;
public:
    explicit TinyGsmClient(TinyGsm&) {}
    int sendLimit=-1, writes=0, stops=0, connects=0;
    bool& live=sock_connected;
    std::function<int()> pendingInput;
    std::vector<std::vector<uint8_t>> sent;
    std::deque<uint8_t> rx;
    std::function<void(const std::vector<uint8_t>&)> onSend;
    int connect(IPAddress,uint16_t) override { live=true; return 1; }
    int connect(const char*,uint16_t) override { ++connects; live=true; return 1; }
    int connect(const char* host,uint16_t port,int) { return TinyGsmClient::connect(host,port); }
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
class TinyGsmClientSecure : public TinyGsmClient {
public:
    explicit TinyGsmClientSecure(TinyGsm& modem) : TinyGsmClient(modem), modem_(modem) {}
    int connect(const char* host, uint16_t port, int timeout) {
        ++modem_.secureConnectCalls;
        modem_.secureHost = host;
        modem_.securePort = port;
        modem_.secureTimeout = timeout;
        live = modem_.secureConnectSuccess;
        return live;
    }
    void stop(uint32_t) { TinyGsmClient::stop(); }
private:
    TinyGsm& modem_;
};
