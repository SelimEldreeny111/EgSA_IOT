/** @file ValveController.cpp @brief Fail-inhibited latching-coil control and persistence. */
#include "ValveController.h"
#include "../config/AppConfig.h"
#include "../app/AppState.h"
#include <Arduino.h>
#include <EEPROM.h>
#include <HardwareTimer.h>
#include <cstring>

extern HardwareSerial SerialMon;
namespace {
constexpr uint32_t kMagic = 0x564C5631UL; // VLV1
constexpr uint32_t kVersion = 1U;
/** @brief Shared-sector record: only complete commands or Unknown are stored. */
struct Record { uint32_t magic, version, state, invertedState, checksum; };
static_assert(sizeof(Record) == 20U, "Valve storage format changed");
static_assert(AppConfig::kValveEepromAddress >= AppConfig::kWatchdogCounterEepromAddress + 20U,
    "Valve overlaps watchdog counter");
static_assert(AppConfig::kValveEepromAddress >= AppConfig::kFlowAccumulatorEepromAddress + 56U,
    "Valve overlaps Supmea checkpoint");
static_assert(AppConfig::kValveEepromAddress + sizeof(Record) <= E2END + 1U,
    "Valve record exceeds EEPROM capacity");
/** @brief Lazily reserve TIM10 only when a commissioned valve is actuated. */
HardwareTimer& timer() { static HardwareTimer instance(TIM10); return instance; }
volatile bool pulseComplete = false;
bool initialized = false;
bool pulsed = false;
bool busy = false;
uint32_t lastPulseEndMs = 0U;

/** @brief Disable the bridge first; direction changes always occur in standby. */
void disableBridge() {
    digitalWrite(AppConfig::kOpenCloseNodeGpio, LOW);
    digitalWrite(AppConfig::kValveAin1Pin, LOW);
    digitalWrite(AppConfig::kValveAin2Pin, LOW);
}
/** @brief TIM10 cutoff; no logging, flash access, network calls or WDT service. */
void finishPulseInterrupt() {
    disableBridge();
    timer().pause();
    pulseComplete = true;
}
/** @brief FNV-1a integrity check over the fixed-width payload. */
uint32_t checksum(const Record& record) {
    uint32_t hash = 2166136261UL;
    const uint8_t* bytes = reinterpret_cast<const uint8_t*>(&record);
    for (size_t i = 0; i < sizeof(record) - sizeof(record.checksum); ++i)
        hash = (hash ^ bytes[i]) * 16777619UL;
    return hash;
}
/** @brief Read the buffered EEPROM image without modifying other records. */
Record readRecord() {
    Record record = {};
    eeprom_buffer_fill();
    uint8_t* bytes = reinterpret_cast<uint8_t*>(&record);
    for (size_t i = 0; i < sizeof(record); ++i)
        bytes[i] = eeprom_buffered_read_byte(AppConfig::kValveEepromAddress + i);
    return record;
}
/** @brief Persist one state and verify it; bridge must already be disabled.
 * @warning STM32 emulation erases a shared sector; this is not power-fail atomic.
 * Other EEPROM records are preserved in the buffered image, but a supply loss
 * during sector erase/program can invalidate them too. Two commits are needed
 * per direction change; high-cycle valves should use a wear-safe external store.
 */
bool persist(ValveState state) {
    const uint32_t value = static_cast<uint32_t>(state);
    Record record = {kMagic, kVersion, value, ~value, 0U};
    record.checksum = checksum(record);
    const uint8_t* bytes = reinterpret_cast<const uint8_t*>(&record);
    eeprom_buffer_fill();
    for (size_t i = 0; i < sizeof(record); ++i)
        eeprom_buffered_write_byte(AppConfig::kValveEepromAddress + i, bytes[i]);
    eeprom_buffer_flush();
    const Record actual = readRecord();
    return memcmp(&record, &actual, sizeof(record)) == 0;
}
/** @brief Actuation requires a free pin set and explicit supplier commissioning. */
bool commissioned() {
    return AppConfig::kEnableOpenCloseNodeOutput &&
        AppConfig::kValvePolarityConfirmed && AppConfig::kValveOpenPulseMs != 0U &&
        AppConfig::kValveClosePulseMs != 0U;
}
}

void initializeValveSafetyPins() {
    if (!AppConfig::kEnableOpenCloseNodeOutput) return;
    // Load output latches low before selecting output mode (no high glitch).
    disableBridge();
    pinMode(AppConfig::kOpenCloseNodeGpio, OUTPUT);
    pinMode(AppConfig::kValveAin1Pin, OUTPUT);
    pinMode(AppConfig::kValveAin2Pin, OUTPUT);
    disableBridge();
}

void initializeValveController() {
    if (initialized) return;
    initialized = true;
    initializeValveSafetyPins();
    appState().nodeStatus = static_cast<uint8_t>(ValveState::Unknown);
    if (AppConfig::kEnableOpenCloseNodeOutput) {
        const Record record = readRecord();
        if (record.magic == kMagic && record.version == kVersion &&
            record.state <= static_cast<uint32_t>(ValveState::Unknown) &&
            record.invertedState == ~record.state && record.checksum == checksum(record))
            appState().nodeStatus = static_cast<uint8_t>(record.state);
    }
    SerialMon.println(commissioned() ?
        "Valve: TB6612FNG ready; state is commanded, NOT position feedback" :
        "Valve: actuation INHIBITED (disabled/pin conflict/pulse/polarity not commissioned)");
}

bool commandValve(bool open) {
    if (!initialized) initializeValveController();
    if (!commissioned() || busy) {
        SerialMon.println("VALVE rejected: not commissioned/available");
        return false;
    }
    const ValveState target = open ? ValveState::Open : ValveState::Closed;
    if (appState().nodeStatus == static_cast<uint8_t>(target)) return true;
    if (pulsed && millis() - lastPulseEndMs < AppConfig::kValveMinIntervalMs) {
        SerialMon.println("VALVE rejected: minimum switching interval");
        return false;
    }
    busy = true;
    disableBridge();
    appState().nodeStatus = static_cast<uint8_t>(ValveState::Unknown);
    // Commit Unknown BEFORE energizing: an interrupted pulse cannot restore
    // the previous command as though it still represented the latch position.
    if (!persist(ValveState::Unknown)) {
        appState().nodeStatus = static_cast<uint8_t>(ValveState::Fault);
        busy = false;
        SerialMon.println("VALVE rejected: pre-pulse storage verification failed");
        return false;
    }
    HardwareTimer& pulseTimer = timer();
    pulseTimer.pause();
    pulseTimer.detachInterrupt();
    pulseTimer.setInterruptPriority(1U, 0U);
    const uint32_t pulseMs = open ? AppConfig::kValveOpenPulseMs : AppConfig::kValveClosePulseMs;
    pulseTimer.setOverflow(pulseMs * 1000U, MICROSEC_FORMAT);
    pulseTimer.refresh();
    pulseTimer.setCount(0U);
    pulseComplete = false;
    pulseTimer.attachInterrupt(finishPulseInterrupt); // clears stale update flag
    const bool ain1High = open == AppConfig::kValveOpenAin1High;
    digitalWrite(AppConfig::kValveAin1Pin, ain1High ? HIGH : LOW);
    digitalWrite(AppConfig::kValveAin2Pin, ain1High ? LOW : HIGH);
    // Arm the cutoff BEFORE enabling power. If an ISR has already fired, do
    // not energize. A short critical section prevents the check/write race.
    pulseTimer.resume();
    noInterrupts();
    const bool energized = !pulseComplete;
    if (energized) digitalWrite(AppConfig::kOpenCloseNodeGpio, HIGH);
    interrupts();
    // Start the foreground fallback after arming/enabling, so HAL timer
    // setup latency cannot cause an early false timeout of a healthy pulse.
    const uint32_t startUs = micros();
    // Do not add an energized grace period if the interrupt fails. The
    // foreground fallback disables power at its first deadline check.
    while (!pulseComplete && micros() - startUs < pulseMs * 1000U) delay(1U);
    disableBridge();
    pulseTimer.pause();
    pulseTimer.detachInterrupt();
    lastPulseEndMs = millis();
    pulsed = true;
    busy = false;
    if (!pulseComplete || !energized) {
        appState().nodeStatus = static_cast<uint8_t>(ValveState::Fault);
        SerialMon.println("VALVE failed: pulse cutoff timeout; latch state unknown");
        return false;
    }
    // Storage failure AFTER a completed pulse cannot honestly be reported as
    // an unexecuted command. Keep the completed RAM state, ACK success, and
    // log that the next reset can recover Unknown instead of this command.
    appState().nodeStatus = static_cast<uint8_t>(target);
    if (!persist(target)) SerialMon.println("VALVE WARNING: pulse completed; state not durably saved");
    SerialMon.println(open ? "Valve OPEN/ON command completed; bridge OFF" :
        "Valve CLOSED/OFF command completed; bridge OFF");
    return true;
}
