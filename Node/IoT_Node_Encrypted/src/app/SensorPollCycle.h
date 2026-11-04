/** @file SensorPollCycle.h
 * @brief One sensor per foreground pass; pending commands can pause a cycle.
 */
#ifndef SENSOR_POLL_CYCLE_H
#define SENSOR_POLL_CYCLE_H
#include <stdint.h>
class SensorPollCycle {
public:
    enum class Sensor : uint8_t { None=0, Tuf=1, Supmea=2, Hnda=3, Sondas=4 };
    void begin() { next_ = 1U; }
    bool active() const { return next_ != 0U; }
    // Give a due report the completed snapshot before another poll can occupy
    // the loop. This also leaves time for its queued flash write to commit.
    bool shouldBegin(bool sampleDue, bool reportDue) const {
        return sampleDue && !active() && !(reportDue && snapshotPendingReport_);
    }
    void reportAttempted() { snapshotPendingReport_ = false; }
    Sensor next(bool tuf, bool supmea, bool hnda, bool sondas) {
        const bool enabled[4] = {tuf, supmea, hnda, sondas};
        while (next_ && next_ <= 4U && !enabled[next_ - 1U]) ++next_;
        if (next_ > 4U) {
            next_ = 0U;
            snapshotPendingReport_ = true;
        }
        return static_cast<Sensor>(next_);
    }
    void completed() { if (next_) ++next_; }
private:
    uint8_t next_ = 0U;
    bool snapshotPendingReport_ = false;
};
#endif
