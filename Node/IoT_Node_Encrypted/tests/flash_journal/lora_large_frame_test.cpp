/** @file lora_large_frame_test.cpp @brief Production reassembly beyond the former 16-fragment limit. */
#include "fakes/LoraConfig.h"
#include "../../src/radio/LoraLink.cpp"
#include <cassert>
#include <vector>
#include <iostream>
HardwareSerial SerialMon,SerialLoRa;
uint32_t nowMs=0;
uint32_t millis(){return nowMs;}
void delay(unsigned ms){nowMs+=ms;}
void yield(){++nowMs;}
void digitalWrite(uint32_t,int){}
void pinMode(uint32_t,int){}
int digitalRead(uint32_t){return HIGH;}
void serviceHardwareWatchdog(){}
void serviceHardwareWatchdog(WatchdogStage){}
void reassemble(size_t length,bool corrupt=false){
    for(auto& context:g_reassembly)resetReassemblyContext(context);
    std::vector<uint8_t> original(length);
    for(size_t i=0;i<length;++i)original[i]=uint8_t(i*37);
    const uint16_t crc=crc16Ccitt(original.data(),length);
    const uint8_t count=uint8_t((length+26)/27);
    LoraFrame result={};bool complete=false;
    for(uint8_t i=0;i<count;++i){
        LoraFrame fragment={};fragment.sourceNodeId=2;fragment.type=LoraPayloadType::TransportFragment;
        const size_t offset=size_t(i)*27,chunk=std::min(size_t(27),length-offset);
        fragment.payload[0]=uint8_t(LoraPayloadType::SystemTelemetry);
        fragment.payload[1]=0;fragment.payload[2]=1;fragment.payload[3]=i;fragment.payload[4]=count;
        fragment.payload[5]=uint8_t(length>>8);fragment.payload[6]=uint8_t(length);
        fragment.payload[7]=uint8_t(crc>>8);fragment.payload[8]=uint8_t(crc);
        memcpy(fragment.payload+9,original.data()+offset,chunk);fragment.payloadLength=9+chunk;
        if(corrupt&&i==count-1)fragment.payload[9]^=1;
        complete=handleFragmentFrame(fragment,result);
        if(i+1<count){assert(!complete);assert(!handleFragmentFrame(fragment,result));} // duplicate is harmless
    }
    assert(complete==!corrupt);
    if(complete){assert(result.payloadLength==length);assert(!memcmp(result.payload,original.data(),length));}
}
int main(){
    reassemble(433); // 17 fragments: first size that broke the old uint16 mask
    reassemble(577); // largest currently generated encrypted Telemetry
    reassemble(640); // complete configured logical capacity, 24 fragments
    reassemble(640,true);
    LoraFrame invalid={},result={};invalid.payloadLength=9;
    invalid.payload[0]=uint8_t(LoraPayloadType::SystemTelemetry);invalid.payload[2]=1;
    invalid.payload[3]=32;invalid.payload[4]=33;
    assert(!handleFragmentFrame(invalid,result));
    std::cout<<"PASS production LoRa 17/22/24-fragment reassembly, duplicates, CRC and bounds\n";
}
