/** @file TelemetryArchive.cpp @brief One bounded journal/history step per loop; command traffic has priority. */
#include "TelemetryArchive.h"
#if APP_ENABLE_SPI_FLASH && APP_ROLE == APP_ROLE_SENSOR_NODE
#include "TelemetryJournal.h"
#include "S25Fl064l.h"
#include "../app/AppState.h"
#include "../comm/SensorPayloadMapper.h"
#include "../comm/PacketCodec.h"
#include "../devices/RTC.h"
#include "../third_party/nanopb/pb_encode.h"
#include "../third_party/nanopb/pb_decode.h"
#include <Arduino.h>
extern HardwareSerial SerialMon;
namespace TelemetryArchive {
namespace {
using namespace WiotStorage;
S25Fl064l chip(AppConfig::kFlashMosiPin,AppConfig::kFlashMisoPin,AppConfig::kFlashSckPin,
    AppConfig::kFlashCsPin,AppConfig::kFlashSpiHz,AppConfig::kFlashExpectedJedec);
TelemetryJournal journal(chip,AppConfig::kFlashCapacityBytes,AppConfig::kNodeId);
uint32_t skipped=0,lastProbe=0; ///< RAM diagnostics and missing-chip retry deadline.
bool initialized=false;
/** @brief Stop-and-wait transfer states; only packet()/published() perform a send attempt. */
enum class Transfer : uint8_t { Idle, Count, Read, SendRecord, SendEnd, WaitRecord, WaitEnd };
/** @brief Frozen day/end sequence plus the single retained in-flight record. */
struct Download {
    Transfer state=Transfer::Idle;
    uint32_t request=0,generation=0,day=0,end=0,first=1,cursor=1,total=0,index=0;
    uint32_t result=0,lastAttempt=0;
    uint64_t argument=0;
    uint8_t attempts=0;
    Record record;
} download;

/** @brief Refuse default/untrusted time and clocks behind the persisted batch start. */
bool timeUsable(){return isRtcTrusted()&&(!journal.ready()||getEpochTime()>=journal.info().startedEpoch);}
/** @brief Permit reads only from the recovered, unexpired, trusted generation. */
bool retained(){return journal.ready()&&timeUsable()&&getEpochTime()<journal.expiry();}
/** @brief Preserve the transfer identity while preparing a terminal result. */
void finish(uint32_t result){download.result=result;download.attempts=0;download.state=Transfer::SendEnd;}
/** @brief Decode a CRC-verified canonical sample and check its node identity. */
bool decode(const Record& record,Telemetry& telemetry){
    telemetry=Telemetry_init_zero;
    pb_istream_t in=pb_istream_from_buffer(record.payload,record.length);
    return pb_decode(&in,Telemetry_fields,&telemetry)&&telemetry.node_id==AppConfig::kNodeId;
}
/** @brief Build explicit record-slot capacity, persistence and health metadata. */
void describe(FlashLogInfo& info){
    const Info& s=journal.info();info=FlashLogInfo_init_zero;
    info.state=uint32_t(s.state);info.jedec_id=chip.jedec();info.capacity_bytes=s.capacity;
    info.maximum_records=s.maximumRecords;info.usable_bytes=s.maximumRecords*512U;
    info.used_bytes=journal.occupiedSlots()*512U;info.free_bytes=info.usable_bytes-info.used_bytes;
    info.record_count=s.records;info.generation=s.generation;info.latest_sequence=s.lastSequence;
    info.retention_started_epoch=s.startedEpoch;info.next_clear_epoch=journal.expiry();
    info.clear_sectors_remaining=s.clearRemaining;info.dropped_samples=s.dropped+skipped;
    info.corrupt_records=s.corrupt;info.busy=journal.busy();info.rtc_trusted=timeUsable();
}
/** @brief Attach frozen request/generation/index/count data to a record or control packet. */
void history(Telemetry& t,uint32_t kind,uint32_t phase,uint32_t result,bool ack){
    t.has_history=true;t.history=HistoryInfo_init_zero;
    t.history.request_id=download.request;t.history.generation=download.generation;
    t.history.sequence=phase==2?download.record.sequence:0;t.history.index=download.index;
    t.history.total=download.total;t.history.day_key=download.day;t.history.kind=kind;
    t.history.phase=phase;t.history.result=result;t.history.ack_required=ack;
}
}
void begin(){
    initialized=true;lastProbe=millis();journal.begin();
    SerialMon.print("SPI flash JEDEC=0x");SerialMon.print(chip.jedec(),HEX);
    SerialMon.print(" state=");SerialMon.println(uint32_t(journal.info().state));
    if(journal.info().state==State::Unformatted)SerialMon.println("Flash log requires direct CLEAR_FLASH after STIME; existing data is not auto-formatted");
}
void capture(){
    if(!initialized||!timeUsable()||!retained()){++skipped;return;}
    Telemetry t=Telemetry_init_zero;
    AppRuntimeState& state=appState();state.lastTimestamp=getEpochTime();
    t.node_id=AppConfig::kNodeId;t.timestamp=state.lastTimestamp;
    t.sampling_rate=state.samplingPeriodMs;t.Transmission_rate=state.transmissionPeriodMs;
    populateSensorPayloadFields(t,state);t.sample_time_valid=true;
    CalendarPeriodKeys day={};if(!getCalendarPeriodKeys(state.lastTimestamp,day)){++skipped;return;}
    uint8_t encoded[472];pb_ostream_t out=pb_ostream_from_buffer(encoded,sizeof(encoded));
    if(!pb_encode(&out,Telemetry_fields,&t)){++skipped;return;}
    journal.append(encoded,uint16_t(out.bytes_written),state.lastTimestamp,day.day);
}
bool storedStatus(Status_Message& s){
    Record record;Telemetry t;
    if(!retained()||!journal.latest(record)||!decode(record,t))return false;
    s=Status_Message_init_zero;
#define COPY(field) s.field=t.field
    COPY(node_id);COPY(sensor_id);COPY(timestamp);COPY(battery_voltage);COPY(flow_rate);COPY(velocity);
    COPY(flow_rate_per_day);COPY(flow_rate_per_month);COPY(flow_rate_per_year);COPY(node_status);
    COPY(soil_temperature);COPY(soil_moisture);COPY(soil_moisture_temp_valid);COPY(ec_temperature);
    COPY(ec_moisture);COPY(electrical_conductivity);COPY(soil_moisture_temp_ec_valid);
    COPY(active_sensor_count);COPY(sensor_mask);COPY(flow_meter_type);COPY(flow_period_source);
    COPY(flow_live_valid);COPY(flow_period_totals_valid);COPY(flow_cumulative_totals_valid);COPY(rtc_valid);
    COPY(forward_total_liters);COPY(reverse_total_liters);COPY(net_total_liters);COPY(flow_period_quality);
    COPY(flow_meter_alarm_flags);COPY(has_secondary_flow_meter);COPY(secondary_flow_meter);
    COPY(power_mode);COPY(power_state);COPY(wake_remaining_seconds);COPY(wdt_reset_count);COPY(power_reset_count);
#undef COPY
    s.sample_sequence=record.sequence;s.sample_time_valid=true;s.stored_sample=true;
    return true;
}
bool handle(const CMD_Message& cmd,bool broadcast){
    if(broadcast||cmd.node_id!=AppConfig::kNodeId||!command(cmd.cmd_id))return false;
    if(cmd.cmd_id==Ack){
        const uint32_t phase=uint32_t(cmd.cmd_data>>32),index=uint32_t(cmd.cmd_data);
        if(cmd.request_id!=download.request||index!=download.index)return false;
        if(phase==2&&download.state==Transfer::WaitRecord){download.state=Transfer::Read;download.attempts=0;return true;}
        if(phase==3&&download.state==Transfer::WaitEnd){download=Download();return true;}
        return false;
    }
    if(cmd.cmd_id==Clear){
        if(cmd.cmd_data!=0||cmd.request_id==0)return false;
        const bool accepted=journal.requestClear(cmd.request_id,getEpochTime(),isRtcTrusted());
        if(accepted&&download.state!=Transfer::Idle)finish(4);
        return accepted;
    }
    if(cmd.cmd_id==Status)return cmd.cmd_data==0;
    if(cmd.cmd_id==Last)return cmd.cmd_data==0&&retained()&&!journal.busy()&&journal.info().records>0;
    if(cmd.cmd_id==Cancel){
        if(cmd.cmd_data!=0)return false;
        if(download.state!=Transfer::Idle)finish(4);
        return true;
    }
    if(cmd.cmd_id==Today){
        if(!cmd.request_id||!retained())return false;
        if(download.state!=Transfer::Idle)return cmd.request_id==download.request&&cmd.cmd_data==download.argument;
        const uint32_t generation=uint32_t(cmd.cmd_data>>32),cursor=uint32_t(cmd.cmd_data);
        if(cmd.cmd_data && (generation!=journal.info().generation||cursor==0||cursor>journal.info().lastSequence+1))return false;
        CalendarPeriodKeys day={};if(!getCalendarPeriodKeys(getEpochTime(),day))return false;
        download=Download();download.request=cmd.request_id;download.argument=cmd.cmd_data;
        download.generation=journal.info().generation;download.end=journal.info().lastSequence;
        download.first=cmd.cmd_data?cursor:1;download.cursor=download.first;download.day=day.day;
        download.state=Transfer::Count;return true;
    }
    return false;
}
void reply(const CMD_Message& cmd,Telemetry& t,bool applied){
    if(!command(cmd.cmd_id)||cmd.cmd_id==Ack)return;
    if(cmd.cmd_id==Last){
        Record record;Telemetry saved;
        if(applied&&journal.latest(record)&&decode(record,saved)){
            t=saved;t.sample_sequence=record.sequence;t.stored_sample=true;
            t.has_history=true;t.history=HistoryInfo_init_zero;
            t.history.kind=1;t.history.phase=2;t.history.total=1;t.history.index=1;
            t.history.request_id=cmd.request_id;t.history.generation=journal.info().generation;
            t.history.sequence=record.sequence;t.history.day_key=record.day;
        }else{
            t=Telemetry_init_zero;t.node_id=AppConfig::kNodeId;
            t.has_history=true;t.history.kind=1;t.history.phase=3;
            t.history.result=!timeUsable()?3:journal.info().state==State::Fault?7:
                journal.busy()?8:journal.info().records==0&&retained()?1:2;
            t.history.request_id=cmd.request_id;
            applied=false;
        }
    }
    t.has_flash_log=true;describe(t.flash_log);
    if(cmd.cmd_id==Today){
        t.has_history=true;t.history=HistoryInfo_init_zero;t.history.request_id=cmd.request_id;
        t.history.generation=journal.info().generation;t.history.kind=2;t.history.phase=1;
        t.history.result=applied?0:(!timeUsable()?3:8);
    }
    t.command_ack_request_id=cmd.request_id;t.command_ack_cmd_id=cmd.cmd_id;t.command_ack_success=applied;
}
void step(){
    if(!initialized)return;
    if(journal.info().state==State::Missing&&millis()-lastProbe>=5000U){lastProbe=millis();journal.begin();}
    journal.step(getEpochTime(),isRtcTrusted());
    if(download.state==Transfer::Idle)return;
    if((download.state==Transfer::WaitEnd||download.state==Transfer::SendEnd)){
        // Terminal cancellation/error survives retention changes until delivered/timeout.
    }else if(journal.info().state==State::Fault){finish(7);
    }else if(!retained()||journal.info().generation!=download.generation){finish(5);}
    if(download.state==Transfer::WaitRecord||download.state==Transfer::WaitEnd){
        if(millis()-download.lastAttempt>=AppConfig::kFlashHistoryAckTimeoutMs){
            if(download.attempts>=AppConfig::kFlashHistoryMaxAttempts){
                if(download.state==Transfer::WaitEnd)download=Download();else finish(6);
            }else download.state=download.state==Transfer::WaitRecord?Transfer::SendRecord:Transfer::SendEnd;
        }
        return;
    }
    if(journal.busy())return;
    if(download.state==Transfer::Count){
        if(download.cursor>download.end){download.cursor=download.first;download.state=Transfer::Read;return;}
        Record r;if(journal.readRecord(download.cursor++,r)&&r.day==download.day)++download.total;
    }else if(download.state==Transfer::Read){
        if(download.cursor>download.end){finish(download.total?0:1);return;}
        if(journal.readRecord(download.cursor++,download.record)&&download.record.day==download.day){
            ++download.index;download.attempts=0;download.state=Transfer::SendRecord;
        }
    }
}
bool packet(uint8_t* data,size_t capacity,size_t& length){
    Telemetry t=Telemetry_init_zero;t.node_id=AppConfig::kNodeId;
    if(download.state==Transfer::SendRecord){
        if(!decode(download.record,t)){finish(7);return false;}
        t.sample_sequence=download.record.sequence;t.stored_sample=true;
        history(t,2,2,0,true);
    }else if(download.state==Transfer::SendEnd){
        history(t,2,3,download.result,true);t.has_flash_log=true;describe(t.flash_log);
    }else return false;
    if(!encodeEncryptedMessage(Telemetry_fields,&t,data,capacity,length)){finish(7);return false;}
    return true;
}
void published(bool success){
    (void)success; // Local acceptance is not server persistence; only CMD14 advances the cursor.
    if(download.state==Transfer::SendRecord)download.state=Transfer::WaitRecord;
    else if(download.state==Transfer::SendEnd)download.state=Transfer::WaitEnd;
    else return;
    download.lastAttempt=millis();++download.attempts;
}
bool writePending(){return initialized&&journal.busy();}
bool blocking(){return initialized&&(journal.busy()||download.state!=Transfer::Idle);}
bool transferring(){return initialized&&download.state!=Transfer::Idle;}
bool maintenanceDue(uint32_t epoch){return initialized&&journal.ready()&&isRtcTrusted()&&epoch>=journal.expiry();}
uint32_t expiry(){return initialized?journal.expiry():0;}
bool prepareSleep(){return !blocking()&&(journal.info().state==State::Missing||journal.info().state==State::Fault||chip.sleep());}
void resume(){if(initialized)chip.wake();}
}
#endif
