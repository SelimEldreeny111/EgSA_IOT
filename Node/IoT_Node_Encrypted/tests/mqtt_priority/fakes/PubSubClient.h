#pragma once
#include "Client.h"
#include <cassert>
#include <deque>
class PubSubClient {
public:
    explicit PubSubClient(Client& client):client_(&client) {}
    void setClient(Client& c) { client_=&c; }
    void setServer(const char*,uint16_t) {}
    void setCallback(void (*fn)(char*,byte*,unsigned)) { callback=fn; }
    void setKeepAlive(uint16_t) {}
    void setSocketTimeout(uint16_t) {}
    bool setBufferSize(uint16_t) { return true; }
    bool connect(const char*) { state_=client_->connect("test",1883)?0:-2; return state_==0; }
    bool connected() { return state_==0 && client_->connected(); }
    int state() const { return state_; }
    bool subscribe(const char*) {
        const uint8_t b=0x82; return !failSubscribe && client_->write(&b,1)==1;
    }
    void disconnect() { state_=-1; client_->stop(); }
    bool publish(const char* topic,const uint8_t* payload,size_t size) {
        assert(!inCallback); // production callbacks must enqueue, never publish recursively
        if(!connected()) return false;
        attemptedTopics.emplace_back(topic);
        const uint8_t header=0x30;
        return client_->write(&header,1)==1 && client_->write(payload,size)==size;
    }
    struct Incoming { std::string topic; std::vector<uint8_t> payload; };
    std::deque<Incoming> incoming;
    std::vector<std::string> attemptedTopics;
    bool failSubscribe=false, inCallback=false;
    int loopCalls=0;
    void loop() {
        ++loopCalls;
        if(!connected() || incoming.empty()) return;
        Incoming next=incoming.front(); incoming.pop_front();
        inCallback=true;
        callback(&next.topic[0],next.payload.data(),unsigned(next.payload.size()));
        inCallback=false;
    }
private:
    Client* client_;
    int state_=-1;
    void (*callback)(char*,byte*,unsigned)=nullptr;
};
