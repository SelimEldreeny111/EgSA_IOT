#pragma once
#include <cstdint>
enum { TIM10 = 10, MICROSEC_FORMAT = 1 };
extern uint32_t testNow;
extern uint32_t resumeLatency;
extern bool missingTimer, immediateTimer;
class HardwareTimer {
public:
    explicit HardwareTimer(int) {}
    bool running = false;
    uint32_t duration = 0U, due = 0U;
    void (*callback)() = nullptr;
    void pause() { running = false; }
    void detachInterrupt() { callback = nullptr; }
    void setInterruptPriority(uint32_t, uint32_t) {}
    void setOverflow(uint32_t us, int) { duration = us / 1000U; }
    void refresh() {}
    void setCount(uint32_t) {}
    void attachInterrupt(void (*fn)()) { callback = fn; }
    void resume() {
        testNow += resumeLatency;
        due = testNow + duration; running = true;
        if (immediateTimer && callback) callback();
    }
};
