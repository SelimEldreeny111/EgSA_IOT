/** @file TelemetryJournal.cpp @brief Cooperative persistent NOR journal; no chip erase or busy loops. */
#include "TelemetryJournal.h"
#include <limits.h>
namespace WiotStorage {
namespace {
constexpr uint32_t MetaMagic=0x574D5431, SectorMagic=0x57535431, RecordMagic=0x57524331;
constexpr uint32_t Commit=0x434D4954, Version=1;
constexpr uint32_t LastRtcEpoch = 4102444799UL; // STM32RTC calendar ends in 2099.
bool erased(const uint8_t* p, size_t n) { while(n--) if(*p++!=0xFF) return false; return true; }
}
uint32_t read32(const uint8_t* p) { return uint32_t(p[0])|(uint32_t(p[1])<<8)|(uint32_t(p[2])<<16)|(uint32_t(p[3])<<24); }
void write32(uint8_t* p,uint32_t v) { for(unsigned i=0;i<4;++i) p[i]=uint8_t(v>>(i*8)); }
uint32_t crc32(const uint8_t* p,size_t n) {
    uint32_t c=0xFFFFFFFF;
    while(n--) { c^=*p++; for(unsigned i=0;i<8;++i)c=(c>>1)^(0xEDB88320U & (0U-(c&1U))); }
    return ~c;
}
TelemetryJournal::TelemetryJournal(NorFlash& f, uint32_t bytes, uint32_t node, uint32_t retentionSeconds)
    : flash_(f), retentionSeconds_(retentionSeconds), node_(node) {
    info_.capacity=bytes; dataSectors_=bytes/Sector>2 ? bytes/Sector-2 : 0;
    info_.maximumRecords=dataSectors_*SlotsPerSector;
}
bool TelemetryJournal::validMeta(const uint8_t* p) const {
    return read32(p)==MetaMagic && read32(p+4)==Version && read32(p+8)!=0 &&
        read32(p+12)!=0 && read32(p+20)==info_.capacity && read32(p+24)<dataSectors_ && read32(p+28)==node_ &&
        read32(p+40)==crc32(p,40) && read32(p+44)==Commit;
}
bool TelemetryJournal::begin() {
    if (!dataSectors_ || info_.capacity%Sector || !flash_.begin()) {info_.state=State::Missing;return false;}
    uint8_t a[48],b[48];
    if(!flash_.read(0,a,48)||!flash_.read(Sector,b,48)){fail();return false;}
    const bool av=validMeta(a),bv=validMeta(b);
    if(!av&&!bv){info_.state=State::Unformatted;return true;}
    metaCopy_=bv&&(!av||read32(b+8)>read32(a+8))?1:0;
    memcpy(meta_,metaCopy_?b:a,48); activateMeta();
    info_.state=State::Recovering; scan_=0; return true;
}
void TelemetryJournal::activateMeta() {
    revision_=read32(meta_+8); info_.generation=read32(meta_+12);
    info_.startedEpoch=read32(meta_+16); startSector_=read32(meta_+24);
    info_.lastClearRequest=read32(meta_+32); sweeping_=read32(meta_+36)!=0;
    sweep_=sweepPage_=0; info_.clearRemaining=sweeping_?dataSectors_:0;
}
uint32_t TelemetryJournal::dataAddress(uint32_t seq) const {
    const uint32_t ordinal=(seq-1)/SlotsPerSector;
    return (2+(startSector_+ordinal)%dataSectors_)*Sector+Slot+((seq-1)%SlotsPerSector)*Slot;
}
bool TelemetryJournal::validSector(const uint8_t* p,uint32_t ordinal) const {
    return read32(p)==SectorMagic && read32(p+4)==Version &&
        read32(p+8)==info_.generation && read32(p+12)==ordinal &&
        read32(p+16)==node_ && read32(p+20)==crc32(p,20) && read32(p+24)==Commit;
}
bool TelemetryJournal::decodeRecord(uint32_t seq,Record& r) {
    if(!seq||seq>info_.maximumRecords)return false;
    const uint32_t base=dataAddress(seq)&~(Sector-1);
    uint8_t header[28];
    if(!flash_.read(base,header,sizeof(header))){fail();return false;}
    if(!validSector(header,(seq-1)/SlotsPerSector))return false;
    if(!flash_.read(dataAddress(seq),buffer_,Slot)){fail();return false;}
    const uint32_t length=read32(buffer_+20);
    if(read32(buffer_)!=RecordMagic || read32(buffer_+4)!=Version ||
        read32(buffer_+8)!=seq || length>sizeof(r.payload) || !length ||
        read32(buffer_+508)!=Commit || read32(buffer_+504)!=crc32(buffer_,504))return false;
    r.sequence=seq;r.epoch=read32(buffer_+12);r.day=read32(buffer_+16);r.length=uint16_t(length);
    memcpy(r.payload,buffer_+32,r.length);return true;
}
bool TelemetryJournal::readRecord(uint32_t seq,Record& r) {
    return ready() && !busy() && seq<=next_ && decodeRecord(seq,r);
}
bool TelemetryJournal::latest(Record& r) {return latest_ && readRecord(latest_,r);}
bool TelemetryJournal::busy() const {return op_!=Op::Idle || info_.state==State::Recovering || pendingClear_ || queueCount_!=0;}
void TelemetryJournal::fail(){info_.state=State::Fault;info_.writing=false;op_=Op::Idle;dropPending();}
void TelemetryJournal::dropPending(){info_.dropped+=queueCount_;queueCount_=0;queueHead_=0;}
bool TelemetryJournal::append(const uint8_t* p,uint16_t n,uint32_t epoch,uint32_t day) {
    if(!p||!n||n>sizeof(Record::payload)||!ready()||queueCount_==4||pendingClear_||
        next_+queueCount_>=info_.maximumRecords){++info_.dropped;return false;}
    Record& r=pending_[(queueHead_+queueCount_)%4];r.length=n;r.epoch=epoch;r.day=day;
    memcpy(r.payload,p,n);++queueCount_;return true;
}
uint32_t TelemetryJournal::expiry() const {
    if (!ready() || !retentionSeconds_ || info_.startedEpoch > LastRtcEpoch ||
        retentionSeconds_ > LastRtcEpoch - info_.startedEpoch) return 0;
    return info_.startedEpoch + retentionSeconds_;
}
bool TelemetryJournal::requestClear(uint32_t id,uint32_t epoch,bool trusted) {
    if(!trusted || epoch<1704067200U || epoch>LastRtcEpoch || info_.state==State::Missing || info_.state==State::Disabled ||
        info_.state==State::Fault || revision_==UINT32_MAX || info_.generation==UINT32_MAX)return false;
    if(id && id==info_.lastClearRequest)return true;
    if(pendingClear_)return id==pendingRequest_;
    pendingClear_=true;pendingRequest_=id;pendingEpoch_=epoch;
    return true;
}
bool TelemetryJournal::issueMeta(bool change,uint32_t epoch,uint32_t request) {
    changingGeneration_=change;
    const uint32_t nextStart=change&&info_.generation ? (startSector_+next_/SlotsPerSector+1)%dataSectors_:startSector_;
    memset(meta_,0xFF,sizeof(meta_));
    write32(meta_,MetaMagic);write32(meta_+4,Version);write32(meta_+8,revision_+1);
    write32(meta_+12,info_.generation+(change?1:0));
    write32(meta_+16,change?epoch:info_.startedEpoch);write32(meta_+20,info_.capacity);
    write32(meta_+24,nextStart);write32(meta_+28,node_);
    write32(meta_+32,request?request:info_.lastClearRequest);
    write32(meta_+36,change?1:0);write32(meta_+40,crc32(meta_,40));
    metaCopy_=1-metaCopy_;operationAddress_=metaCopy_*Sector;
    if(!flash_.erase(operationAddress_)){fail();return false;}
    op_=Op::MetaErase;info_.writing=true;return true;
}
void TelemetryJournal::advanceOperation() {
    const Poll status=flash_.poll();
    if(status==Poll::Busy)return;
    if(status==Poll::Failed){fail();return;}
    const Op previous=op_;
    switch(previous){
    case Op::MetaErase:
        if(!flash_.program(operationAddress_,meta_,44)){fail();return;}op_=Op::MetaBody;return;
    case Op::MetaBody:{
        uint8_t check[44];if(!flash_.read(operationAddress_,check,44)||memcmp(check,meta_,44)){fail();return;}
        uint8_t marker[4];write32(marker,Commit);
        if(!flash_.program(operationAddress_+44,marker,4)){fail();return;}op_=Op::MetaCommit;return;}
    case Op::MetaCommit:{
        uint8_t check[48];if(!flash_.read(operationAddress_,check,48)||!validMeta(check)){fail();return;}
        memcpy(meta_,check,48);activateMeta();
        if(changingGeneration_){next_=latest_=0;info_.records=info_.lastSequence=0;pendingClear_=false;info_.state=State::Ready;}
        op_=Op::Idle;info_.writing=false;return;}
    case Op::AllocateErase:
        memset(buffer_,0xFF,28);write32(buffer_,SectorMagic);write32(buffer_+4,Version);
        write32(buffer_+8,info_.generation);write32(buffer_+12,next_/SlotsPerSector);
        write32(buffer_+16,node_);write32(buffer_+20,crc32(buffer_,20));
        if(!flash_.program(operationAddress_,buffer_,24)){fail();return;}op_=Op::SectorBody;return;
    case Op::SectorBody:{
        uint8_t marker[4];write32(marker,Commit);
        if(!flash_.program(operationAddress_+24,marker,4)){fail();return;}op_=Op::SectorCommit;return;}
    case Op::SectorCommit:
        op_=Op::Idle;info_.writing=false;return;
    case Op::RecordPage1:
        if(!flash_.program(operationAddress_+256,buffer_+256,252)){fail();return;}op_=Op::RecordPage2;return;
    case Op::RecordPage2:{
        uint8_t check[256];
        if(!flash_.read(operationAddress_,check,256)||memcmp(check,buffer_,256)||
            !flash_.read(operationAddress_+256,check,252)||memcmp(check,buffer_+256,252)){fail();return;}
        uint8_t marker[4];write32(marker,Commit);
        if(!flash_.program(operationAddress_+508,marker,4)){fail();return;}op_=Op::RecordCommit;return;}
    case Op::RecordCommit:{
        Record check;
        if(!decodeRecord(next_+1,check)){fail();return;}
        ++next_;latest_=next_;++info_.records;info_.lastSequence=latest_;
        queueHead_=(queueHead_+1)%4;--queueCount_;
        if(next_==info_.maximumRecords)info_.state=State::Full;
        op_=Op::Idle;info_.writing=false;return;}
    case Op::SweepErase:
        ++sweep_;sweepPage_=0;info_.clearRemaining=dataSectors_-sweep_;
        op_=Op::Idle;info_.writing=false;return;
    default:return;
    }
}
void TelemetryJournal::recoverOne() {
    if(scan_>=info_.maximumRecords){info_.state=next_>=info_.maximumRecords?State::Full:State::Ready;return;}
    const uint32_t seq=++scan_,address=dataAddress(seq),ordinal=(seq-1)/SlotsPerSector;
    uint8_t h[28];if(!flash_.read(address&~(Sector-1),h,28)){fail();return;}
    if(!validSector(h,ordinal)){scan_=(ordinal+1)*SlotsPerSector;return;}
    if(!flash_.read(address,buffer_,Slot)){fail();return;}
    if(erased(buffer_,Slot))return;
    next_=seq;
    Record r;if(decodeRecord(seq,r)){++info_.records;latest_=seq;info_.lastSequence=seq;}
    else ++info_.corrupt;
}
void TelemetryJournal::sweepOne() {
    if(sweep_>=dataSectors_){sweeping_=false;info_.clearRemaining=0;issueMeta(false,info_.startedEpoch,info_.lastClearRequest);return;}
    const uint32_t address=(sweep_+2)*Sector;
    uint8_t header[28];
    if(!flash_.read(address,header,sizeof(header))){fail();return;}
    // Allocation may have reused this sector between sweep pages. Revalidate
    // ownership on EVERY pass, not only page zero, before considering erase.
    if(read32(header)==SectorMagic && read32(header+8)==info_.generation &&
        read32(header+20)==crc32(header,20) && read32(header+24)==Commit){
        ++sweep_;sweepPage_=0;info_.clearRemaining=dataSectors_-sweep_;return;
    }
    if(!flash_.read(address+sweepPage_*Slot,buffer_,Slot)){fail();return;}
    if(!erased(buffer_,Slot)){
        operationAddress_=address;if(!flash_.erase(address)){fail();return;}
        op_=Op::SweepErase;info_.writing=true;return;
    }
    if(++sweepPage_==Sector/Slot){++sweep_;sweepPage_=0;info_.clearRemaining=dataSectors_-sweep_;}
}
void TelemetryJournal::step(uint32_t epoch,bool trusted) {
    if(op_!=Op::Idle){advanceOperation();return;}
    if(info_.state==State::Fault||info_.state==State::Missing||info_.state==State::Disabled)return;
    if(pendingClear_){dropPending();issueMeta(true,pendingEpoch_,pendingRequest_);return;}
    if(info_.state==State::Recovering){recoverOne();return;}
    if(!ready())return;
    const uint32_t deadline = expiry();
    if (trusted && deadline && epoch >= deadline) {
        requestClear(0, epoch, true);
        return;
    }
    if(queueCount_){
        if(next_>=info_.maximumRecords){dropPending();info_.state=State::Full;return;}
        const uint32_t address=dataAddress(next_+1);
        if(next_%SlotsPerSector==0){
            uint8_t h[28];if(!flash_.read(address&~(Sector-1),h,28)){fail();return;}
            if(!validSector(h,next_/SlotsPerSector)){
                operationAddress_=address&~(Sector-1);
                if(!flash_.erase(operationAddress_)){fail();return;}op_=Op::AllocateErase;info_.writing=true;return;
            }
        }
        const Record& r=pending_[queueHead_];
        memset(buffer_,0xFF,Slot);write32(buffer_,RecordMagic);write32(buffer_+4,Version);
        write32(buffer_+8,next_+1);write32(buffer_+12,r.epoch);write32(buffer_+16,r.day);
        write32(buffer_+20,r.length);memcpy(buffer_+32,r.payload,r.length);
        write32(buffer_+504,crc32(buffer_,504));operationAddress_=address;
        if(!flash_.program(address,buffer_,256)){fail();return;}op_=Op::RecordPage1;info_.writing=true;return;
    }
    if(sweeping_)sweepOne();
}
}
