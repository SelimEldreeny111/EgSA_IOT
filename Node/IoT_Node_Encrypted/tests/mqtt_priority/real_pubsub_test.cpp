// Actual installed PubSubClient: MQTT wire, command callback and keepalive.
#include "../../src/comm/MQTT.h"
#include "../../src/comm/CommandHandler.h"
#include <cassert>
#include <iostream>
uint32_t testNow=5000;
bool tickOnMillis=false;
HardwareSerial SerialMon,SerialAT;
extern PubSubClient mqtt;
#include "../../src/comm/CachedTinyGsmClient.h"
extern CachedTinyGsmClient gsmClient;
const char kMqttServer[]="test",kMqttClientId[]="test-client";
const char kMqttCommandTopic[]="EgSA/Test/1/CMD",kMqttBroadcastTopic[]="EgSA/Test/BroadCast/CMD";
const char kMqttPublishTopicStatus[]="EgSA/Test/1/Status",kMqttPublishTopicTlm[]="EgSA/Test/1/Telemetry";
static int applied=0;
void serviceHardwareWatchdog() {}
void serviceHardwareWatchdog(WatchdogStage) {}
void watchdogDelay(uint32_t ms) { delay(ms); }
bool connectNetwork() { return true; }
bool decodeEncryptedCommandPayload(const uint8_t* b,size_t n,CMD_Message& cmd) {
    if(n!=3) return false;
    cmd.node_id=b[0]; cmd.cmd_id=b[1]; cmd.request_id=b[2]; return true;
}
bool handleCommand(const CMD_Message&,bool) { ++applied; return true; }
bool handleRemoteWakeCommand(const CMD_Message&,bool) { ++applied; return true; }
bool handleGetTelemetryCommand(const CMD_Message* cmd,uint8_t* b,size_t& n,bool) {
    b[0]=uint8_t(cmd->cmd_id); b[1]=uint8_t(cmd->request_id); n=2; return true;
}
bool buildEncryptedStatusPayload(uint8_t* b,size_t,size_t& n) { b[0]=99; n=1; return true; }
static std::string topic(const std::vector<uint8_t>& wire) {
    assert(wire.size()>4 && wire[0]==0x30 && !(wire[1]&0x80));
    const size_t length=(size_t(wire[2])<<8)|wire[3];
    assert(4+length<=wire.size());
    return std::string(wire.begin()+4,wire.begin()+4+length);
}
int main() {
    gsmClient.live=false;
    gsmClient.onSend=[](const std::vector<uint8_t>& wire) {
        assert(!wire.empty());
        if(wire[0]==0x10) for(uint8_t b:{0x20,0x02,0x00,0x00}) gsmClient.rx.push_back(b);
        if(wire[0]==0xC0) { gsmClient.rx.push_back(0xD0); gsmClient.rx.push_back(0); }
        if(wire[0]==0x82) {
            const uint8_t ack[]={0x90,3,wire[2],wire[3],0};
            for(uint8_t b:ack) gsmClient.rx.push_back(b);
        }
    };
    initializeMqttClient(); assert(ensureMqttConnection());
    // Consume subscription ACKs, then send >2 keepalive windows of Status.
    serviceMqttPriorityCommands(); serviceMqttPriorityCommands();
    for(int i=0;i<12;i++) {
        testNow+=10000; beginMqttCommandPriorityPass();
        assert(triggerAsyncPublish()); asyncPublishStep();
        assert(takeAsyncPublishResult()==AsyncPublishResult::Success && mqtt.connected());
        const auto& wire=gsmClient.sent.back(); assert(topic(wire)==kMqttPublishTopicStatus && wire.back()==99);
    }
    assert(gsmClient.stops==0);
    const std::string cmdTopic=kMqttCommandTopic;
    std::vector<uint8_t> command={0x30,uint8_t(2+cmdTopic.size()+3),0,uint8_t(cmdTopic.size())};
    command.insert(command.end(),cmdTopic.begin(),cmdTopic.end());
    command.insert(command.end(),{1,CMD_OPEN_CLOSE_NODE,42});
    for(uint8_t b:command) gsmClient.rx.push_back(b);
    assert(triggerAsyncPublish());
    beginMqttCommandPriorityPass(); assert(applied==1 && mqttCommandWorkPending());
    asyncPublishStep(); assert(topic(gsmClient.sent.back())==kMqttPublishTopicTlm);
    assert(gsmClient.sent.back().back()==42);
    beginMqttCommandPriorityPass();
    assert(triggerAsyncPublish()); gsmClient.sendLimit=1; asyncPublishStep();
    assert(takeAsyncPublishResult()==AsyncPublishResult::Failure && !mqtt.connected());
    assert(SerialAT.rawWrites==0);
    std::cout<<"PASS real PubSubClient: MQTT wire, receive/ACK priority, 120s keepalive, partial-write failure\n";
}
