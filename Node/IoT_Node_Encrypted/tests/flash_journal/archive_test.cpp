/** @file archive_test.cpp @brief Real driver, journal and transfer service over a deterministic SPI chip model. */
#include "fakes/ArchiveConfig.h"
#include "fakes/SPI.h"
#include "../../src/storage/TelemetryArchive.h"
#include "../../src/storage/S25Fl064l.h"
#include "../../src/third_party/nanopb/pb_encode.h"
#include "../../src/third_party/nanopb/pb_decode.h"
#include <cassert>
#include <cstring>
#include <algorithm>
#include <iostream>
#include <string>
namespace FlashModel {
std::vector<uint8_t> memory(8388608,255),transaction;
uint32_t address=0,id=0x016017,now=0;
unsigned busy=0;
bool enabled=false,asleep=false,writeProtect=false;
void start(){transaction.clear();address=0;}
uint8_t transfer(uint8_t b){
    transaction.push_back(b);size_t i=transaction.size()-1;
    const uint8_t c=transaction[0];
    if(asleep&&c!=0xAB)return 255;
    if(c==0x9F&&i>0&&i<4)return uint8_t(id>>(8*(3-i)));
    if(c==0x05&&i>0){unsigned was=busy;if(busy)--busy;return (was?1:0)|(enabled?2:0);}
    if(c==0x07&&i>0)return 0;
    if((c==0x13||c==0x12||c==0x21)&&i>0&&i<=4)address=(address<<8)|b;
    if(c==0x13&&i>=5){assert(!busy);assert(address<memory.size());return memory[address++];}
    return 255;
}
void end(){
    const uint8_t c=transaction[0];
    if(c==0xAB){asleep=false;return;}
    if(asleep)return;
    if(c==0x06){if(!busy&&!writeProtect)enabled=true;return;}
    if(c==0xB9){assert(!busy);asleep=true;return;}
    if(c==0x12||c==0x21){
        assert(!busy&&enabled);enabled=false;
        if(c==0x21){assert(!(address&4095));std::fill(memory.begin()+address,memory.begin()+address+4096,255);busy=3;}
        else {assert(transaction.size()>5);assert(transaction.size()-5<=256-(address&255));
            for(size_t i=5;i<transaction.size();++i){assert((memory[address]&transaction[i])==transaction[i]);memory[address++]&=transaction[i];}busy=2;}
    }
}
}
HardwareSerial SerialMon;
AppRuntimeState state;
uint32_t epoch=1800000000U,dayKey=20261030;
bool trusted=true;
uint32_t millis(){return FlashModel::now;}
void digitalWrite(uint32_t,int){}
void pinMode(uint32_t,int){}
void delayMicroseconds(unsigned){}
AppRuntimeState& appState(){return state;}
uint32_t getEpochTime(){return epoch;}
bool isRtcTrusted(){return trusted;}
bool getCalendarPeriodKeys(uint32_t,CalendarPeriodKeys& key){key.day=dayKey;return trusted;}
void populateSensorPayloadFields(Telemetry& t,const AppRuntimeState&){
    t.flow_rate=12.5;t.battery_voltage=3.7;t.active_sensor_count=4;t.sensor_mask=15;
    t.soil_moisture=45;t.ec_moisture=55;t.has_secondary_flow_meter=true;
    t.secondary_flow_meter.flow_rate=35;t.flow_live_valid=true;
}
// Keep nanopb real; omit only transport encryption to inspect emitted frames.
bool encodeEncryptedMessage(const pb_msgdesc_t* fields,const void* t,uint8_t* out,size_t capacity,size_t& n){
    pb_ostream_t stream=pb_ostream_from_buffer(out,capacity);
    bool ok=pb_encode(&stream,fields,t);n=stream.bytes_written;return ok;
}
void steps(unsigned n=25000){while(n--){++FlashModel::now;TelemetryArchive::step();}}
CMD_Message cmd(uint32_t id,uint32_t request=1,uint64_t argument=0){
    CMD_Message c=CMD_Message_init_zero;c.node_id=2;c.cmd_id=id;c.request_id=request;c.cmd_data=argument;return c;
}
Telemetry status(){Telemetry t=Telemetry_init_zero;TelemetryArchive::reply(cmd(10),t,true);return t;}
void format(){
    TelemetryArchive::begin();assert(status().flash_log.state==2);
    assert(TelemetryArchive::handle(cmd(9),false));steps();
    assert(status().flash_log.state==4&&status().flash_log.clear_sectors_remaining==0);
}
Telemetry packet(){
    uint8_t bytes[640];size_t n=0;assert(TelemetryArchive::packet(bytes,sizeof(bytes),n));
    Telemetry t=Telemetry_init_zero;pb_istream_t stream=pb_istream_from_buffer(bytes,n);
    assert(pb_decode(&stream,Telemetry_fields,&t));return t;
}
void ack(const Telemetry& t){assert(TelemetryArchive::handle(cmd(14,t.history.request_id,
    (uint64_t(t.history.phase)<<32)|t.history.index),false));}
int main(int argc,char** argv){
    assert(argc==2);std::string scenario=argv[1];
    if(scenario=="driver"){
        using namespace WiotStorage;
        S25Fl064l chip(7,6,5,4,4000000,0x016017);assert(chip.begin());
        uint8_t v[3]={1,2,3},out[3];assert(!chip.program(255,v,3));assert(!chip.erase(1));
        assert(chip.program(0x701234,v,3));assert(!chip.sleep());assert(!chip.read(0,out,3));
        while(chip.poll()==Poll::Busy)++FlashModel::now;
        assert(chip.read(0x701234,out,3)&&!std::memcmp(v,out,3));
        assert(chip.sleep()&&FlashModel::asleep);assert(chip.read(0x701234,out,3)&&!FlashModel::asleep);
        assert(chip.erase(0x701000));FlashModel::busy=100;FlashModel::now+=1001;
        assert(chip.poll()==Poll::Failed);assert(!chip.program(0,v,3));
        FlashModel::id=0;assert(!chip.begin());
    }else if(scenario=="missing"){
        FlashModel::id=0;TelemetryArchive::begin();assert(status().flash_log.state==1);
        assert(!TelemetryArchive::handle(cmd(9),false));assert(TelemetryArchive::prepareSleep());
        FlashModel::id=0x016017;steps(5001);assert(status().flash_log.state==2);
    }else{
        format();assert(!TelemetryArchive::handle(cmd(9,2),true));
        trusted=false;TelemetryArchive::capture();assert(!TelemetryArchive::handle(cmd(9,2),false));trusted=true;
        TelemetryArchive::capture();assert(TelemetryArchive::writePending());assert(!TelemetryArchive::prepareSleep());
        steps();epoch+=10;TelemetryArchive::capture();steps();
        assert(status().flash_log.record_count==2&&status().flash_log.dropped_samples==1);
        Status_Message s=Status_Message_init_zero;assert(TelemetryArchive::storedStatus(s));
        assert(s.timestamp==epoch&&s.stored_sample&&s.sample_sequence==2&&s.secondary_flow_meter.flow_rate==35);
        assert(TelemetryArchive::prepareSleep()&&FlashModel::asleep);TelemetryArchive::resume();assert(!FlashModel::asleep);
        if(scenario=="capture"){
            Telemetry t=Telemetry_init_zero;auto c=cmd(11,12);assert(TelemetryArchive::handle(c,false));TelemetryArchive::reply(c,t,true);
            assert(t.history.kind==1&&t.history.sequence==2&&t.command_ack_success);
            auto clear=cmd(9,13);assert(TelemetryArchive::handle(clear,false));steps();
            assert(status().flash_log.record_count==0&&status().flash_log.generation==2);
            TelemetryArchive::capture();steps();assert(TelemetryArchive::handle(clear,false));steps();
            assert(status().flash_log.record_count==1); // Duplicate clear never clears a later sample.
        }else if(scenario=="download"||scenario=="timeout"||scenario=="cancel"||scenario=="retention"||scenario=="resume"||scenario=="empty"){
            auto request=cmd(12,25,scenario=="resume"?(uint64_t(1)<<32)|2:0);
            if(scenario=="empty")dayKey=20261031;
            assert(TelemetryArchive::handle(request,false));assert(TelemetryArchive::handle(request,false));
            assert(TelemetryArchive::transferring());
            assert(!TelemetryArchive::handle(cmd(12,26),false));steps();
            if(scenario=="download"){epoch+=10;TelemetryArchive::capture();steps();assert(status().flash_log.record_count==3);}
            auto first=packet();assert(first.history.request_id==25);
            if(scenario=="empty"){assert(first.history.phase==3&&first.history.result==1);TelemetryArchive::published(true);ack(first);}
            else{
                assert(first.history.phase==2&&first.history.sequence==(scenario=="resume"?2U:1U));
                TelemetryArchive::published(true);
                assert(!TelemetryArchive::handle(cmd(14,24,(uint64_t(2)<<32)|1),false));
                uint8_t bytes[640];size_t n=0;assert(!TelemetryArchive::packet(bytes,sizeof(bytes),n));
                if(scenario=="cancel"){assert(TelemetryArchive::handle(cmd(13,26),false));auto end=packet();assert(end.history.result==4);TelemetryArchive::published(true);ack(end);}
                else if(scenario=="retention"){epoch+=86400;steps();auto end=packet();assert(end.history.result==5);TelemetryArchive::published(true);ack(end);assert(status().flash_log.record_count==0);}
                else if(scenario=="timeout"){
                    for(unsigned i=0;i<2;++i){FlashModel::now+=60000;steps(1);auto retry=packet();assert(retry.history.sequence==first.history.sequence);TelemetryArchive::published(false);}
                    FlashModel::now+=60000;steps(1);auto end=packet();assert(end.history.result==6);TelemetryArchive::published(true);ack(end);
                }else{
                    ack(first);steps();
                    if(scenario!="resume"){auto second=packet();assert(second.history.sequence==2&&second.history.index==2&&second.history.total==2);TelemetryArchive::published(true);ack(second);steps();}
                    auto end=packet();assert(end.history.phase==3&&end.history.result==0);TelemetryArchive::published(true);ack(end);
                }
            }
            assert(!TelemetryArchive::blocking());
            assert(!TelemetryArchive::transferring());
        }else assert(false);
    }
    std::cout<<"PASS flash driver/archive "<<scenario<<"\n";
}
