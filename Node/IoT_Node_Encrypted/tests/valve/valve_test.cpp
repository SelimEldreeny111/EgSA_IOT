// Include the actual driver to simulate reset of its private runtime state.
#include "../../src/devices/ValveController.cpp"
#include <array>
#include <cassert>
#include <iostream>
#include <stdexcept>
#include <string>

uint32_t testNow = 0, flushCount = 0, failFlush = 0, foregroundStall = 0;
uint32_t resumeLatency = 0;
bool missingTimer = false, immediateTimer = false, interruptReset = false;
std::vector<PinEvent> pinEvents;
std::array<uint8_t, 512> flash, image;
HardwareSerial SerialMon;
AppRuntimeState runtime;
namespace AppConfig {
bool kEnableOpenCloseNodeOutput = true, kValvePolarityConfirmed = true, kValveOpenAin1High = true;
// TEST FIXTURE durations only; these are NOT Uflow commissioning specifications.
uint32_t kValveOpenPulseMs = 60, kValveClosePulseMs = 80, kValveMinIntervalMs = 1000;
}
AppRuntimeState& appState() { return runtime; }
uint32_t millis() { return testNow; }
uint32_t micros() { return testNow * 1000U; }
void digitalWrite(uint32_t pin, uint8_t value) { pinEvents.push_back({pin, value, testNow, false}); }
void pinMode(uint32_t pin, uint8_t value) { pinEvents.push_back({pin, value, testNow, true}); }
void eeprom_buffer_fill() { image = flash; }
uint8_t eeprom_buffered_read_byte(uint32_t i) { return image.at(i); }
void eeprom_buffered_write_byte(uint32_t i, uint8_t value) { image.at(i) = value; }
void eeprom_buffer_flush() { if (++flushCount != failFlush) flash = image; }
void delay(uint32_t ms) {
    if (interruptReset) throw std::runtime_error("simulated reset DURING pulse");
    const uint32_t end = testNow + ms + foregroundStall;
    if (!missingTimer && timer().running && int32_t(end - timer().due) >= 0) {
        testNow = timer().due; timer().callback();
    }
    testNow = end;
}
void reboot() {
    initialized = pulsed = busy = pulseComplete = false;
    timer().pause(); timer().detachInterrupt(); runtime.nodeStatus = 0;
    interruptReset = false; pinEvents.clear();
    initializeValveSafetyPins(); initializeValveController();
}
void assertOff() {
    for (auto pin : {AppConfig::kOpenCloseNodeGpio, AppConfig::kValveAin1Pin, AppConfig::kValveAin2Pin}) {
        uint32_t value = 99;
        for (auto e : pinEvents) if (!e.mode && e.pin == pin) value = e.value;
        assert(value == LOW);
    }
}
uint32_t highPulses() {
    uint32_t result = 0;
    for (auto e : pinEvents) if (!e.mode && e.pin == AppConfig::kOpenCloseNodeGpio && e.value == HIGH) ++result;
    return result;
}
void assertPulse(uint32_t duration, bool ain1High) {
    bool powered = false; uint32_t began = 0, in1 = 0, in2 = 0;
    for (auto e : pinEvents) {
        if (e.mode) continue;
        if (e.pin == AppConfig::kValveAin1Pin) { assert(!powered); in1 = e.value; }
        if (e.pin == AppConfig::kValveAin2Pin) { assert(!powered); in2 = e.value; }
        if (e.pin == AppConfig::kOpenCloseNodeGpio && e.value == HIGH) {
            assert(!powered && in1 != in2 && (in1 == HIGH) == ain1High);
            powered = true; began = e.at;
        } else if (e.pin == AppConfig::kOpenCloseNodeGpio && powered) {
            assert(e.at - began == duration); powered = false;
        }
    }
    assert(!powered); assertOff();
}
int main(int argc, char** argv) {
    assert(argc == 2); const std::string name = argv[1];
    flash.fill(0xFF); image = flash;
    if (name == "open_close" || name == "inverted") {
        // Nonblank neighbors detect accidental erasure of credentials,
        // accumulator/counter bytes, or other shared EEPROM records.
        for (size_t i = 0; i < flash.size(); ++i)
            if (i < 212 || i >= 232) flash[i] = uint8_t(i * 37U + 0x5AU);
    }
    if (name == "disabled") AppConfig::kEnableOpenCloseNodeOutput = false;
    reboot();
    assert(runtime.nodeStatus == 2 && flushCount == 0);
    if (name == "disabled") {
        assert(pinEvents.empty()); assert(!commandValve(true));
        assert(pinEvents.empty() && flushCount == 0);
    } else if (name == "uncommissioned") {
        AppConfig::kValvePolarityConfirmed = false;
        assert(!commandValve(true));
        AppConfig::kValvePolarityConfirmed = true; AppConfig::kValveOpenPulseMs = 0;
        assert(!commandValve(false));
        AppConfig::kValveOpenPulseMs = 60; AppConfig::kValveClosePulseMs = 0;
        assert(!commandValve(true)); assert(highPulses() == 0 && flushCount == 0); assertOff();
    } else if (name == "open_close" || name == "inverted") {
        AppConfig::kValveOpenAin1High = name != "inverted";
        const auto before = flash;
        assert(commandValve(true)); assert(runtime.nodeStatus == 1 && flushCount == 2);
        assertPulse(60, AppConfig::kValveOpenAin1High);
        assert(commandValve(true)); assert(highPulses() == 1 && flushCount == 2);
        assert(!commandValve(false)); assert(runtime.nodeStatus == 1 && highPulses() == 1);
        testNow += 1000; pinEvents.clear();
        assert(commandValve(false)); assert(runtime.nodeStatus == 0 && flushCount == 4);
        assertPulse(80, !AppConfig::kValveOpenAin1High);
        for (size_t i = 0; i < flash.size(); ++i)
            if (i < 212 || i >= 232) assert(flash[i] == before[i]);
        reboot(); assert(runtime.nodeStatus == 0 && highPulses() == 0);
        assert(commandValve(false)); assert(highPulses() == 0 && flushCount == 4);
    } else if (name == "restore_open") {
        assert(commandValve(true)); reboot(); assert(runtime.nodeStatus == 1 && highPulses() == 0);
    } else if (name == "interrupted") {
        interruptReset = true; bool reset = false;
        try { commandValve(true); } catch (const std::runtime_error&) { reset = true; }
        assert(reset && highPulses() == 1 && flushCount == 1);
        reboot(); assert(runtime.nodeStatus == 2 && highPulses() == 0); assertOff();
    } else if (name == "corruption") {
        assert(commandValve(true)); flash[228] ^= 1U;
        reboot(); assert(runtime.nodeStatus == 2 && highPulses() == 0);
    } else if (name == "pre_write_failure") {
        failFlush = 1; assert(!commandValve(true));
        assert(runtime.nodeStatus == 3 && highPulses() == 0); assertOff();
    } else if (name == "post_write_failure") {
        failFlush = 2; assert(commandValve(true)); assert(runtime.nodeStatus == 1);
        assertPulse(60, true); reboot(); assert(runtime.nodeStatus == 2);
    } else if (name == "missing_timer") {
        missingTimer = true; assert(!commandValve(true));
        assert(runtime.nodeStatus == 3 && testNow == 60); assertOff();
        reboot(); assert(runtime.nodeStatus == 2);
    } else if (name == "premature_timer") {
        immediateTimer = true; assert(!commandValve(true));
        assert(runtime.nodeStatus == 3 && highPulses() == 0); assertOff();
    } else if (name == "arm_latency") {
        resumeLatency = 3; assert(commandValve(true));
        assert(runtime.nodeStatus == 1 && testNow == 63); assertPulse(60, true);
    } else if (name == "foreground_stall") {
        foregroundStall = 300; assert(commandValve(true));
        assert(runtime.nodeStatus == 1 && testNow > 60); assertPulse(60, true);
    } else if (name == "millis_wrap") {
        testNow = UINT32_MAX - 20; assert(commandValve(true)); assertPulse(60, true);
        assert(!commandValve(false)); testNow += 1000; assert(commandValve(false));
    } else assert(false);
    std::cout << "PASS actual TB6612 valve: " << name << '\n';
}
