/** @file TelemetryJournal.h @brief CRC/commit-last telemetry log with durable 24-hour generations. */
#ifndef WIOT_TELEMETRY_JOURNAL_H
#define WIOT_TELEMETRY_JOURNAL_H
#include "NorFlash.h"
#include <string.h>
namespace WiotStorage {
/** @brief Acquisition metadata; payload is a serialized sample, never a command ACK. */
struct Record {
    uint32_t sequence=0, epoch=0, day=0;
    uint16_t length=0;
    uint8_t payload[472] = {};
};
/** @brief Public journal status and explicit failure states. */
enum class State : uint8_t { Disabled, Missing, Unformatted, Recovering, Ready, Full, Fault };
/** @brief Generation geometry/counters; occupiedSlots also includes torn record slots. */
struct Info {
    State state=State::Disabled;
    uint32_t capacity=0, maximumRecords=0, records=0, generation=0, lastSequence=0;
    uint32_t startedEpoch=0, dropped=0, corrupt=0, clearRemaining=0, lastClearRequest=0;
    bool writing=false;
};
/** @brief Fixed-memory journal. Call step repeatedly; flash waits are represented as states. */
class TelemetryJournal {
public:
    static constexpr uint32_t Sector=4096, Slot=512, SlotsPerSector=7, Retention=86400;
    /** @brief Bind exclusive flash ownership and immutable geometry/node identity.
     * @param flash NOR implementation. @param bytes Physical capacity. @param node Payload owner. */
    TelemetryJournal(NorFlash& flash, uint32_t bytes, uint32_t node);
    /** @brief Select the newest valid metadata copy, then recover cooperatively.
     * @return True for identified flash, including Unformatted; never auto-formats unknown data. */
    bool begin();
    /** @brief Advance one bounded state-machine phase, including retention/sweep.
     * @param epoch Current UTC seconds. @param trusted Whether time may drive automatic erase. */
    void step(uint32_t epoch, bool trusted);
    /** @brief Copy a complete sample into the four-entry queue.
     * @param payload Canonical protobuf. @param length 1..472 bytes.
     * @param epoch Acquisition UTC seconds. @param day Node-local YYYYMMDD key.
     * @return Accepted in RAM, not yet durable; queue/full/unavailable failures count as drops. */
    bool append(const uint8_t* payload, uint16_t length, uint32_t epoch, uint32_t day);
    /** @brief Queue a durable generation change; abandon queued old-generation samples after any current write.
     * @param requestId Most recent manual request ID, or zero for automatic expiry.
     * @param epoch New retention start. @param trusted Required valid time authority.
     * @return Accepted, or true for the latest durable duplicate; completion is asynchronous. */
    bool requestClear(uint32_t requestId, uint32_t epoch, bool trusted);
    /** @brief Read and CRC-check one current-generation slot while idle.
     * @param sequence Generation-relative physical slot ID; gaps are legal.
     * @param record Decoded result. @return False for busy, holes, corruption or I/O failure. */
    bool readRecord(uint32_t sequence, Record& record);
    /** @brief Read the last known committed slot. @param record Output sample. */
    bool latest(Record& record);
    /** @brief Return cached geometry/state/counters; no SPI transaction. */
    const Info& info() const { return info_; }
    /** @brief Pending write/queue/recovery/clear; background read-only sweeping alone is not busy. */
    bool busy() const;
    /** @brief Ready and Full both permit retained-record reads. */
    bool ready() const { return info_.state==State::Ready || info_.state==State::Full; }
    /** @brief Persisted batch start + 86,400 seconds; zero before recovery completes. */
    uint32_t expiry() const { return ready() ? info_.startedEpoch+Retention : 0; }
    /** @brief Consumed physical slots, including torn records that must not be reused. */
    uint32_t occupiedSlots() const { return next_; }
private:
    enum class Op : uint8_t { Idle, MetaErase, MetaBody, MetaCommit, AllocateErase,
        SectorBody, SectorCommit, RecordPage1, RecordPage2, RecordCommit, SweepErase };
    NorFlash& flash_;
    Info info_;
    uint32_t node_, dataSectors_, revision_=0, metaCopy_=1, startSector_=0, next_=0, latest_=0;
    uint32_t scan_=0, sweep_=0, sweepPage_=0, operationAddress_=0;
    bool sweeping_=false, changingGeneration_=false, pendingClear_=false;
    uint32_t pendingRequest_=0, pendingEpoch_=0;
    uint8_t meta_[48]={}, buffer_[512]={};
    Record pending_[4];
    uint8_t queueHead_=0, queueCount_=0;
    Op op_=Op::Idle;
    /** @brief Map a physical sequence through the generation's rotated sector origin. */
    uint32_t dataAddress(uint32_t sequence) const;
    /** @brief Check metadata magic/version/identity/geometry/CRC/commit. */
    bool validMeta(const uint8_t* data) const;
    /** @brief Check sector ownership and logical ordinal for the current generation. */
    bool validSector(const uint8_t* data, uint32_t ordinal) const;
    /** @brief Read/verify one record; an SPI I/O failure latches Fault. */
    bool decodeRecord(uint32_t sequence, Record& record);
    /** @brief Erase the alternate metadata copy and start commit-last update. */
    bool issueMeta(bool newGeneration, uint32_t epoch, uint32_t request);
    /** @brief Activate verified metadata after boot or completed commit. */
    void activateMeta();
    /** @brief Scan one slot/sector skip and rebuild count/latest/consumed position. */
    void recoverOne();
    /** @brief Poll once and issue the next program/verify/commit phase. */
    void advanceOperation();
    /** @brief Inspect/reclaim old data without erasing active-generation sectors. */
    void sweepOne();
    /** @brief Latch terminal I/O failure and account for abandoned queued samples. */
    void fail();
    /** @brief Abandon queued samples without changing committed record count. */
    void dropPending();
};
/** @brief Stable little-endian record helpers, independent of compiler struct layout. */
uint32_t read32(const uint8_t* p);
/** @brief Write one uint32 in the stable on-flash little-endian representation. */
void write32(uint8_t* p, uint32_t value);
/** @brief IEEE reflected CRC32, initial/final XOR FFFFFFFF; accidental-corruption check only. */
uint32_t crc32(const uint8_t* p, size_t size);
}
#endif
