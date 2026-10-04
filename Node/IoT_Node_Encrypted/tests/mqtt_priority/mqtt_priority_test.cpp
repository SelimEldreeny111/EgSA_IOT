#include "../../src/comm/MQTT.h"
#include "../../src/comm/CommandHandler.h"
#include "../../src/comm/VerifiedBufferedClient.h"
#include "../../src/comm/PriorityPublishQueue.h"
#include "../../src/app/SensorPollCycle.h"
#include <cassert>
#include <iostream>
#include <stdexcept>

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
static int networkConnectCalls=0;
void serviceHardwareWatchdog() {}
void serviceHardwareWatchdog(WatchdogStage) {}
void watchdogDelay(uint32_t ms) { delay(ms); }
[[noreturn]] void forceHardwareWatchdogReset(const char*) { throw std::runtime_error("controller reset"); }
bool connectNetwork() { ++networkConnectCalls; return true; }
bool decodeEncryptedCommandPayload(const uint8_t* bytes,size_t length,CMD_Message& cmd) {
    if(length!=3) return false;
    cmd.node_id=bytes[0]; cmd.cmd_id=bytes[1]; cmd.request_id=bytes[2]; return true;
}
bool handleCommand(const CMD_Message&,bool) { ++applied; return true; }
bool handleRemoteWakeCommand(const CMD_Message&,bool) { ++applied; return true; }
bool handleGetTelemetryCommand(const CMD_Message* cmd,uint8_t* out,size_t& length,bool) {
    out[0]=uint8_t(cmd->cmd_id); out[1]=uint8_t(cmd->request_id); length=2; return true;
}
bool buildEncryptedStatusPayload(uint8_t* out,size_t,size_t& length) {
    out[0]=99; length=1; return true;
}
int main(int argc,char** argv) {
    assert(argc==2);
    const std::string scenario=argv[1];
    gsmClient.pendingInput=[] { return int(mqtt.incoming.size()); };
    initializeMqttClient();
    if(scenario=="subscribe_failure") {
        mqtt.failSubscribe=true; assert(!ensureMqttConnection()); assert(mqtt.state()!=0);
    } else {
        assert(ensureMqttConnection());
        if(scenario=="gprs_recovery" || scenario=="broker_only") {
            const int previousNetworkCalls=networkConnectCalls;
            mqtt.disconnect(); testNow+=4000;
            modem.gprsConnected=scenario!="gprs_recovery";
            assert(ensureMqttConnection());
#if defined(USE_SIM800)
            assert(networkConnectCalls-previousNetworkCalls==(scenario=="gprs_recovery"?1:0));
#else
            assert(networkConnectCalls==previousNetworkCalls);
#endif
        } else if(scenario=="success") {
            assert(triggerAsyncPublish()); asyncPublishStep();
            assert(takeAsyncPublishResult()==AsyncPublishResult::Success);
            assert(mqtt.attemptedTopics.back()==kMqttPublishTopicStatus);
            assert(gsmClient.sent.back()==std::vector<uint8_t>({0x30,99}));
        } else if(scenario=="zero_write" || scenario=="partial_write") {
            assert(triggerAsyncPublish()); gsmClient.sendLimit=scenario=="zero_write"?0:1;
            asyncPublishStep(); assert(takeAsyncPublishResult()==AsyncPublishResult::Failure);
            assert(mqtt.state()!=0 && gsmClient.stops==1 && !isAsyncPublishBusy());
        } else if(scenario=="command_priority") {
            assert(triggerAsyncPublish());
            mqtt.incoming.push_back({kMqttCommandTopic,{1,CMD_OPEN_CLOSE_NODE,42}});
            beginMqttCommandPriorityPass(); assert(applied==1 && mqttCommandWorkPending());
            assert(!triggerAsyncPublish());
            asyncPublishStep();
            assert(mqtt.attemptedTopics.size()==1 && mqtt.attemptedTopics[0]==kMqttPublishTopicTlm);
            assert(gsmClient.sent.back()==std::vector<uint8_t>({0x30,CMD_OPEN_CLOSE_NODE,42}));
            assert(takeAsyncPublishResult()==AsyncPublishResult::Failure); // stale queued Status discarded
            beginMqttCommandPriorityPass(); assert(!mqttCommandWorkPending());
            assert(triggerAsyncPublish()); asyncPublishStep();
            assert(takeAsyncPublishResult()==AsyncPublishResult::Success);
        } else if(scenario=="receive_during_pending_send") {
            assert(triggerAsyncPublish());
            mqtt.incoming.push_back({kMqttCommandTopic,{1,CMD_GET_TELEMETRY,43}});
            serviceMqttPriorityCommands(); assert(mqttCommandWorkPending());
            asyncPublishStep(); assert(mqtt.attemptedTopics.back()==kMqttPublishTopicTlm);
        } else if(scenario=="ack_retry") {
            mqtt.incoming.push_back({kMqttCommandTopic,{1,CMD_SET_SAMPLING_PERIOD,44}});
            beginMqttCommandPriorityPass(); gsmClient.sendLimit=0; asyncPublishStep();
            assert(isAsyncPublishBusy() && applied==1 && mqtt.state()!=0);
            gsmClient.sendLimit=-1; testNow+=4000; assert(ensureMqttConnection());
            beginMqttCommandPriorityPass(); asyncPublishStep();
            assert(!isAsyncPublishBusy() && applied==1);
            assert(gsmClient.sent.back()==std::vector<uint8_t>({0x30,CMD_SET_SAMPLING_PERIOD,44}));
        } else if(scenario=="queue_backpressure") {
            for(uint8_t i=1;i<=5;i++) mqtt.incoming.push_back({kMqttCommandTopic,{1,CMD_OPEN_CLOSE_NODE,i}});
            for(int i=0;i<5;i++) serviceMqttPriorityCommands();
            assert(applied==4 && mqtt.incoming.size()==1); // do not apply a command whose ACK cannot be stored
            asyncPublishStep(); serviceMqttPriorityCommands(); assert(applied==5);
            while(isAsyncPublishBusy()) asyncPublishStep();
            assert(mqtt.attemptedTopics.size()==5);
        } else if(scenario=="idle_empty") {
            const int calls=mqtt.loopCalls;
            serviceMqttPriorityCommands(); assert(mqtt.loopCalls==calls);
            beginMqttCommandPriorityPass(); assert(mqtt.loopCalls==calls+1);
        } else if(scenario=="foreign_node") {
            mqtt.incoming.push_back({kMqttCommandTopic,{2,CMD_OPEN_CLOSE_NODE,42}});
            beginMqttCommandPriorityPass(); assert(applied==0 && !isAsyncPublishBusy());
        } else if(scenario=="modem_recovery" || scenario=="controller_recovery") {
            assert(triggerAsyncPublish());
            mqtt.incoming.push_back({kMqttCommandTopic,{1,CMD_OPEN_CLOSE_NODE,48}});
            beginMqttCommandPriorityPass();
            testPinEvents().clear();
            tickOnMillis=true; // ESP firmware-version query uses a bounded millis loop.
            if(scenario=="modem_recovery") {
                resetMqttTransportForNetworkRecovery();
                tickOnMillis=false;
                assert(isAsyncPublishBusy()); // Correlated reply survives modem-only reset.
                assert(ensureMqttConnection());
                beginMqttCommandPriorityPass(); asyncPublishStep();
                assert(mqtt.attemptedTopics.back()==kMqttPublishTopicTlm);
                assert(!isAsyncPublishBusy());
            } else {
                bool reset=false;
                try { resetModemAndControllerForNetworkFailure(); }
                catch(const std::runtime_error&) { reset=true; }
                tickOnMillis=false; assert(reset);
            }
#if defined(USE_SIM800)
            const uint32_t pin=AppConfig::kSimResetPin, pulse=AppConfig::kSimResetPulseMs;
            bool openDrain=false;
            for(const auto& e:testPinEvents()) if(e.mode && e.pin==pin && e.value==OUTPUT_OPEN_DRAIN) openDrain=true;
            assert(openDrain);
#else
            const uint32_t pin=AppConfig::kEspResetPin, pulse=AppConfig::kEspResetPulseMs;
#endif
            bool lowSeen=false, released=false; uint32_t lowAt=0;
            for(const auto& e:testPinEvents()) {
                if(e.mode || e.pin!=pin) continue;
                if(e.value==LOW) { lowSeen=true; lowAt=e.at; }
                else if(lowSeen) { assert(e.at-lowAt>=pulse); released=true; }
            }
            assert(lowSeen && released);
        } else assert(false);
    }
    assert(SerialAT.rawWrites==0); // UART parsing/sending belongs to TinyGSM, never a raw publisher
    SensorPollCycle cycle;
    cycle.begin(); assert(cycle.next(true,true,true,true)==SensorPollCycle::Sensor::Tuf);
    cycle.completed(); assert(cycle.next(true,true,true,true)==SensorPollCycle::Sensor::Supmea);
    // A command priority pass does not advance the staged poll cursor.
    assert(cycle.next(true,true,true,true)==SensorPollCycle::Sensor::Supmea);
    cycle.completed(); cycle.completed(); cycle.completed();
    assert(cycle.next(true,true,true,true)==SensorPollCycle::Sensor::None && !cycle.active());
    cycle.begin(); assert(cycle.next(false,false,false,true)==SensorPollCycle::Sensor::Sondas);
    cycle.completed(); assert(cycle.next(false,false,false,true)==SensorPollCycle::Sensor::None);
    cycle.begin(); assert(cycle.next(false,false,false,false)==SensorPollCycle::Sensor::None);
    std::cout<<"PASS "<<scenario<<'\n';
}
