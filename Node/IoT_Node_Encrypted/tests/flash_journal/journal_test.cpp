#include "../../src/storage/TelemetryJournal.h"
#include <vector>
#include <cassert>
#include <iostream>
using namespace WiotStorage;
struct FakeNor : NorFlash {
    std::vector<uint8_t> bytes;
    unsigned ticks=0,mutations=0,cut=0;
    bool failed=false,readFailure=false;
    explicit FakeNor(unsigned sectors=8):bytes(sectors*4096,255){}
    bool begin() override {ticks=0;failed=false;return true;}
    bool read(uint32_t a,uint8_t* p,size_t n) override {
        if(ticks||failed||readFailure||a+n>bytes.size())return false;
        memcpy(p,&bytes[a],n);return true;
    }
    bool program(uint32_t a,const uint8_t* p,size_t n) override {
        assert(n && n<=256-(a&255));assert(!ticks);
        if(failed||a+n>bytes.size())return false;
        ++mutations;const size_t count=cut==mutations?n/2:n;
        for(size_t i=0;i<count;++i){assert((bytes[a+i]&p[i])==p[i]);bytes[a+i]&=p[i];}
        if(cut==mutations){failed=true;return false;}ticks=1;return true;
    }
    bool erase(uint32_t a) override {
        assert(!(a&4095));assert(!ticks);++mutations;
        const size_t count=cut==mutations?2048:4096;
        std::fill(bytes.begin()+a,bytes.begin()+a+count,255);
        if(cut==mutations){failed=true;return false;}ticks=1;return true;
    }
    Poll poll() override {if(failed)return Poll::Failed;if(ticks){--ticks;return Poll::Busy;}return Poll::Ready;}
    uint32_t jedec() const override{return 0x016017;}
    bool sleep() override{return !ticks;}
    bool wake() override{return true;}
};
constexpr uint32_t Now=1800000000;
constexpr uint32_t DefaultRetention = 86400U;
void settle(TelemetryJournal& j,uint32_t t=Now){for(unsigned i=0;i<2000;++i)j.step(t,true);}
void initialize(TelemetryJournal& j){assert(j.begin());assert(j.info().state==State::Unformatted);assert(j.requestClear(11,Now,true));settle(j);assert(j.ready());}
void appendOne(TelemetryJournal& j,uint8_t v,uint32_t t=Now){assert(j.append(&v,1,t,20261030));settle(j,t);}
int main(){
    {FakeNor f;TelemetryJournal j(f,f.bytes.size(),2,DefaultRetention);initialize(j);appendOne(j,42);
     Record r;assert(j.latest(r)&&r.payload[0]==42&&r.sequence==1);assert(j.info().records==1);
     TelemetryJournal reboot(f,f.bytes.size(),2,DefaultRetention);assert(reboot.begin());settle(reboot);assert(reboot.latest(r)&&r.payload[0]==42);
     assert(!reboot.requestClear(12,Now,false));assert(reboot.requestClear(11,Now,true));settle(reboot);assert(reboot.info().records==1);
     assert(reboot.requestClear(12,Now,true));settle(reboot);assert(!reboot.latest(r)&&reboot.info().generation==2);}
    {FakeNor f;TelemetryJournal j(f,f.bytes.size(),2,DefaultRetention);initialize(j);appendOne(j,7);settle(j,Now-1);assert(j.info().records==1);
     settle(j,Now+86399);assert(j.info().records==1);settle(j,Now+86400);assert(j.info().records==0&&j.info().generation==2);
     TelemetryJournal reboot(f,f.bytes.size(),2,DefaultRetention);assert(reboot.begin());settle(reboot,Now+86401);assert(reboot.info().generation==2);}
    // A different firmware setting uses the existing start and needs no reformat.
    {
        FakeNor flash;
        TelemetryJournal original(flash, flash.bytes.size(), 2, DefaultRetention);
        initialize(original);
        appendOne(original, 42);
        TelemetryJournal updated(flash, flash.bytes.size(), 2, 300U);
        assert(updated.begin());
        settle(updated, Now + 299U);
        assert(updated.info().startedEpoch == Now && updated.expiry() == Now + 300U);
        assert(updated.info().records == 1);
        updated.step(Now + 300U, false);
        assert(!updated.busy() && updated.info().records == 1);
        settle(updated, Now + 300U);
        assert(updated.info().records == 0 && updated.info().generation == 2);
        assert(updated.expiry() == Now + 600U);
    }
    // A deadline beyond the RTC calendar must not wrap into an early erase.
    {
        FakeNor flash;
        TelemetryJournal journal(flash, flash.bytes.size(), 2, UINT32_MAX);
        initialize(journal);
        appendOne(journal, 7);
        assert(journal.expiry() == 0 && journal.info().records == 1);
        assert(journal.requestClear(12, Now + 300U, true));
        settle(journal, Now + 300U);
        assert(journal.info().records == 0 && journal.info().generation == 2);
    }
    {FakeNor f(4);TelemetryJournal j(f,f.bytes.size(),2,DefaultRetention);initialize(j);
     for(unsigned i=0;i<14;++i)appendOne(j,uint8_t(i));assert(j.info().state==State::Full);uint8_t v=55;assert(!j.append(&v,1,Now,20261030));}
    unsigned cuts=0;
    // Measure real mutating transitions first, then cut each one. Clear includes
    // metadata commit, old-sector erasure and the durable sweep-complete update.
    for(bool clear : {false,true}) {
        FakeNor seed;TelemetryJournal initial(seed,seed.bytes.size(),2,DefaultRetention);initialize(initial);
        for(unsigned i=0;i<7;++i)appendOne(initial,uint8_t(i+1));
        FakeNor probe=seed;probe.mutations=0;
        TelemetryJournal control(probe,probe.bytes.size(),2,DefaultRetention);assert(control.begin());settle(control);
        if(clear)assert(control.requestClear(22,Now,true));else assert(control.append((const uint8_t*)"X",1,Now,20261030));
        settle(control);const unsigned transitions=probe.mutations;assert(transitions>=6);
        for(unsigned cut=1;cut<=transitions;++cut) {
            FakeNor f=seed;f.mutations=0;f.cut=cut;
            TelemetryJournal j(f,f.bytes.size(),2,DefaultRetention);assert(j.begin());settle(j);
            if(clear)assert(j.requestClear(22,Now,true));else assert(j.append((const uint8_t*)"X",1,Now,20261030));
            settle(j);assert(f.failed);++cuts;f.cut=0;
            TelemetryJournal reboot(f,f.bytes.size(),2,DefaultRetention);assert(reboot.begin());settle(reboot);
            assert(reboot.info().generation==1||reboot.info().generation==2);
            Record r;
            if(clear){if(reboot.latest(r))assert(r.payload[0]==7&&reboot.info().generation==1);}
            else {assert(reboot.latest(r));assert(r.payload[0]==7||r.payload[0]=='X');appendOne(reboot,11);assert(reboot.latest(r)&&r.payload[0]==11);}
        }
    }
    // Corrupt committed data is quarantined and its slot is never reused.
    {FakeNor f;TelemetryJournal j(f,f.bytes.size(),2,DefaultRetention);initialize(j);appendOne(j,1);appendOne(j,2);
     f.bytes[2*4096+512+32]^=1;
     TelemetryJournal reboot(f,f.bytes.size(),2,DefaultRetention);assert(reboot.begin());settle(reboot);
     assert(reboot.info().records==1&&reboot.info().corrupt==1&&reboot.occupiedSlots()==2);
     Record r;assert(!reboot.readRecord(1,r)&&reboot.latest(r)&&r.sequence==2);
     appendOne(reboot,3);assert(reboot.latest(r)&&r.sequence==3);}
    // All-sector wrap, queue bounds, geometry/node isolation, and I/O failure.
    {FakeNor f(4);TelemetryJournal j(f,f.bytes.size(),2,DefaultRetention);initialize(j);
     for(unsigned i=0;i<14;++i)appendOne(j,uint8_t(i));assert(j.requestClear(23,Now,true));settle(j);
     for(unsigned i=0;i<14;++i)appendOne(j,uint8_t(i+1));
     TelemetryJournal reboot(f,f.bytes.size(),2,DefaultRetention);assert(reboot.begin());settle(reboot);assert(reboot.info().records==14);
     TelemetryJournal other(f,f.bytes.size(),3,DefaultRetention);assert(other.begin());assert(other.info().state==State::Unformatted);
     TelemetryJournal bad(f,f.bytes.size()-1,2,DefaultRetention);assert(!bad.begin());
     uint8_t v=1;assert(!j.requestClear(24,0xFFFFFFFF,true));assert(!j.append(&v,1,Now,20261030));}
    {FakeNor f;TelemetryJournal j(f,f.bytes.size(),2,DefaultRetention);initialize(j);uint8_t v=1;
     for(unsigned i=0;i<4;++i)assert(j.append(&v,1,Now,20261030));assert(!j.append(&v,1,Now,20261030));
     settle(j);assert(j.info().records==4&&j.info().dropped==1);
     f.readFailure=true;assert(j.append(&v,1,Now,20261030));settle(j);assert(j.info().state==State::Fault);}
    // Clear arriving during a record operation must not underflow or re-label the old sample.
    {FakeNor f;TelemetryJournal j(f,f.bytes.size(),2,DefaultRetention);initialize(j);uint8_t v=9;assert(j.append(&v,1,Now,20261030));j.step(Now,true);
     assert(j.requestClear(55,Now,true));settle(j);assert(j.info().records==0&&!j.busy());}
    // A fresh record can allocate a sector after its header page was swept.
    // Reclamation must re-read that header instead of erasing the new payload.
    {FakeNor f;TelemetryJournal j(f,f.bytes.size(),2,DefaultRetention);assert(j.begin());assert(j.requestClear(1,Now,true));
     for(unsigned i=0;i<100&&!j.ready();++i)j.step(Now,true);assert(j.ready());
     j.step(Now,true); // Blank header inspected; sweep is about to visit the first record slot.
     uint8_t v=77;assert(j.append(&v,1,Now,20261030));settle(j);
     Record r;assert(j.latest(r)&&r.payload[0]==77&&j.info().records==1);
     TelemetryJournal reboot(f,f.bytes.size(),2,DefaultRetention);assert(reboot.begin());settle(reboot);
     assert(reboot.latest(r)&&r.payload[0]==77);}
    std::cout<<"PASS journal recovery, retention, full, CRC, queue, I/O and "<<cuts<<" mutating power-cut transitions\n";
}
