/** @file WatchdogResetCounter.cpp
 * @brief Versioned flash-backed reset counter sharing the buffered EEPROM sector.
 */
#include "WatchdogResetCounter.h"
#include "../config/AppConfig.h"
#include <EEPROM.h>
#include <cstring>

namespace {
constexpr uint32_t kMagic = 0x57444331UL; // WDC1
constexpr uint32_t kVersion = 1U;
struct Record {
    uint32_t magic, version, count, invertedCount, checksum;
};
static_assert(sizeof(Record) == 20U, "Reset-counter storage layout changed");
static_assert(AppConfig::kWatchdogCounterEepromAddress >= 112,
    "Reset counter overlaps WiFi credentials");
static_assert(AppConfig::kWatchdogCounterEepromAddress >=
    AppConfig::kFlowAccumulatorEepromAddress + 56,
    "Reset counter overlaps Supmea checkpoint");
static_assert(AppConfig::kWatchdogCounterEepromAddress + sizeof(Record) <= E2END + 1U,
    "Reset counter exceeds EEPROM emulation capacity");
bool initialized = false;
bool healthy = true;
bool invalidRecord = false;
uint32_t count = 0U;

/** @brief FNV-1a integrity check over the fixed-width record payload. */
uint32_t checksum(const Record& record) {
    const uint8_t* bytes = reinterpret_cast<const uint8_t*>(&record);
    uint32_t hash = 2166136261UL;
    for (size_t i = 0; i < sizeof(Record) - sizeof(record.checksum); ++i) {
        hash = (hash ^ bytes[i]) * 16777619UL;
    }
    return hash;
}
Record readRecord() {
    Record record = {};
    uint8_t* bytes = reinterpret_cast<uint8_t*>(&record);
    eeprom_buffer_fill();
    for (size_t i = 0; i < sizeof(record); ++i) {
        bytes[i] = eeprom_buffered_read_byte(AppConfig::kWatchdogCounterEepromAddress + i);
    }
    return record;
}
bool valid(const Record& record) {
    return record.magic == kMagic && record.version == kVersion &&
        record.invertedCount == ~record.count && record.checksum == checksum(record);
}
bool blank(const Record& record) {
    const uint8_t* bytes = reinterpret_cast<const uint8_t*>(&record);
    bool allZero = true, allErased = true;
    for (size_t i = 0; i < sizeof(record); ++i) {
        allZero &= bytes[i] == 0U;
        allErased &= bytes[i] == 0xFFU;
    }
    return allZero || allErased;
}
/** @brief One buffered commit preserving credentials and the flow checkpoint.
 * @warning Shared-sector erase is not power-fail atomic. Verification detects
 * a failed write; recovery from corruption starts a new count and logs a warning.
 */
bool save(uint32_t newCount) {
    Record record = {kMagic, kVersion, newCount, ~newCount, 0U};
    record.checksum = checksum(record);
    const uint8_t* bytes = reinterpret_cast<const uint8_t*>(&record);
    eeprom_buffer_fill();
    for (size_t i = 0; i < sizeof(record); ++i) {
        eeprom_buffered_write_byte(AppConfig::kWatchdogCounterEepromAddress + i, bytes[i]);
    }
    eeprom_buffer_flush();
    const Record verified = readRecord();
    return memcmp(&record, &verified, sizeof(record)) == 0;
}
}

void WatchdogResetCounter::initialize(bool watchdogReset) {
    if (initialized) return; // Do not consume the same boot/reset flag twice.
    initialized = true;
    const Record record = readRecord();
    const bool recordValid = valid(record);
    invalidRecord = !recordValid && !blank(record);
    count = recordValid ? record.count : 0U;
    if (watchdogReset && count != UINT32_MAX) {
        ++count;
        healthy = save(count);
    }
}
uint32_t WatchdogResetCounter::value() { return count; }
bool WatchdogResetCounter::clear() {
    if (!initialized) return false;
    const Record stored = readRecord();
    if (!(valid(stored) && stored.count == 0U) && !save(0U)) {
        healthy = false;
        return false;
    }
    count = 0U;
    healthy = true;
    invalidRecord = false;
    return true;
}
bool WatchdogResetCounter::storageHealthy() { return healthy; }
bool WatchdogResetCounter::recoveredInvalidRecord() { return invalidRecord; }
