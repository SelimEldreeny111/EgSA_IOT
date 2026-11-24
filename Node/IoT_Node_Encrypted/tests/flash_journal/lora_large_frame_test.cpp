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
    LoraFrame last={};
    for(uint8_t i=0;i<count;++i){
        LoraFrame fragment={};fragment.sourceNodeId=2;fragment.type=LoraPayloadType::TransportFragment;
        const size_t offset=size_t(i)*27,chunk=std::min(size_t(27),length-offset);
        fragment.payload[0]=uint8_t(LoraPayloadType::SystemTelemetry);
        static uint8_t nextId=1;
        fragment.payload[1]=0;fragment.payload[2]=nextId;fragment.payload[3]=i;fragment.payload[4]=count;
        fragment.payload[5]=uint8_t(length>>8);fragment.payload[6]=uint8_t(length);
        fragment.payload[7]=uint8_t(crc>>8);fragment.payload[8]=uint8_t(crc);
        memcpy(fragment.payload+9,original.data()+offset,chunk);fragment.payloadLength=9+chunk;
        last=fragment;
        if(corrupt&&i==count-1)fragment.payload[9]^=1;
        const auto prior=g_fragmentAcksTx;
        processWireFrame(fragment);
        assert(g_fragmentAcksTx-prior == ((corrupt && i==count-1) ? 0U : 1U));
        if(i+1<count) { processWireFrame(fragment); assert(g_pendingCount==0); }
        else ++nextId;
    }
    LoraFrame result={};
    assert(dequeuePendingFrame(result)==!corrupt);
    if(!corrupt){
        assert(result.payloadLength==length && !memcmp(result.payload,original.data(),length));
        const auto prior=g_fragmentAcksTx;
        processWireFrame(last); // Lost final transport ACK, same LoRa message.
        assert(g_fragmentAcksTx==prior+1U && !dequeuePendingFrame(result));
    }
}
/** Wrap test data in a real transport-fragment header for the gateway parser. */
LoraFrame makeFragment(uint16_t source, uint8_t message, const std::vector<uint8_t>& body, uint8_t index)
{
    LoraFrame frame{};
    frame.sourceNodeId = source;
    frame.type = LoraPayloadType::TransportFragment;
    const uint16_t crc = crc16Ccitt(body.data(), body.size());
    const size_t offset = index * kFragmentDataLength;
    const size_t length = std::min(body.size() - offset, kFragmentDataLength);
    frame.payload[0] = uint8_t(LoraPayloadType::SystemTelemetry);
    frame.payload[2] = message;
    frame.payload[3] = index;
    frame.payload[4] = uint8_t((body.size() + kFragmentDataLength - 1) / kFragmentDataLength);
    frame.payload[5] = uint8_t(body.size() >> 8);
    frame.payload[6] = uint8_t(body.size());
    frame.payload[7] = uint8_t(crc >> 8);
    frame.payload[8] = uint8_t(crc);
    memcpy(frame.payload + kFragmentHeaderLength, body.data() + offset, length);
    frame.payloadLength = kFragmentHeaderLength + length;
    return frame;
}

void checkInterleavedAndFullQueue()
{
    const std::vector<uint8_t> a(52, 0x54), b(51, 0xAE), c(43, 0xB0);
    processWireFrame(makeFragment(1, 42, a, 0));
    processWireFrame(makeFragment(2, 42, b, 0)); // Same message ID on separate nodes.
    processWireFrame(makeFragment(2, 42, b, 1));
    processWireFrame(makeFragment(1, 42, a, 1));
    assert(g_pendingCount == 2);

    processWireFrame(makeFragment(1, 43, c, 0));
    const auto last = makeFragment(1, 43, c, 1);
    const auto before = g_fragmentAcksTx;
    processWireFrame(last);
    assert(g_pendingCount == 2 && g_fragmentAcksTx == before);
    LoraFrame frame{};
    assert(dequeuePendingFrame(frame) && frame.sourceNodeId == 2 && frame.payloadLength == b.size());
    assert(!memcmp(frame.payload, b.data(), b.size()));
    processWireFrame(last); // Now capacity is available for the same completed frame.
    assert(g_fragmentAcksTx == before + 1 && g_pendingCount == 2);
    processWireFrame(last); // Simulate loss of the final ACK.
    assert(g_fragmentAcksTx == before + 2 && g_pendingCount == 2);
    assert(dequeuePendingFrame(frame) && frame.sourceNodeId == 1 && frame.payloadLength == a.size());
    assert(!memcmp(frame.payload, a.data(), a.size()));
    assert(dequeuePendingFrame(frame) && frame.sourceNodeId == 1 && frame.payloadLength == c.size());
    assert(!memcmp(frame.payload, c.data(), c.size()));
    assert(!dequeuePendingFrame(frame));
}
int main(){
    reassemble(433); // 17 fragments: first size that broke the old uint16 mask
    reassemble(577); // largest currently generated encrypted Telemetry
    reassemble(640); // complete configured logical capacity, 24 fragments
    reassemble(640,true);
    checkInterleavedAndFullQueue();
    std::cout<<"PASS separate LoRa node reassembly, full-queue backpressure and lost final ACK\n";
    LoraFrame invalid={},result={};invalid.payloadLength=9;
    invalid.payload[0]=uint8_t(LoraPayloadType::SystemTelemetry);invalid.payload[2]=1;
    invalid.payload[3]=32;invalid.payload[4]=33;
    assert(!handleFragmentFrame(invalid,result));
    std::cout<<"PASS production LoRa 17/22/24-fragment reassembly, duplicates, CRC and bounds\n";
#ifdef WIOT_TEST_WIRE_TRANSCRIPT
    // The diagnostic policy must never change fragment ACKs on the radio UART.
    std::cout<<"wire_bytes="<<SerialLoRa.tx.size()<<'\n';
    for(uint8_t value:SerialLoRa.tx)std::cout<<std::hex<<unsigned(value)<<' ';
    std::cout<<'\n';
#endif
}
