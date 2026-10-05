/** @file RemoteWakeCycle.h @brief Rollover-safe reachable-idle and WAKE timers. */
#ifndef REMOTE_WAKE_CYCLE_H
#define REMOTE_WAKE_CYCLE_H

#include <stdint.h>

/** @brief Hardware-independent, rollover-safe reachable-idle policy.
 * CPU/UART sleep and watchdog servicing belong to PowerManager, not this class.
 * Legacy periodic work stays active until transmission succeeds. Schedule-driven
 * work stays active only while due/busy; sampling and sending are independent.
 * A WAKE lease expires
 * independently of telemetry success, but never interrupts an in-flight send.
 */
class RemoteWakeCycle
{
public:
  enum class Transition : uint8_t { None, EnteredIdle, PeriodicWake, ScheduledWake };

  /** @brief Initialize the legacy cycle or idle schedule-driven policy.
   * @param nowMs Monotonic millis snapshot; unsigned subtraction handles rollover.
   * @param idleMs Reachable-idle interval between automatic measurement cycles.
   * @param commandWindowMs Active command window after a successful periodic send.
   * @param useAppSchedule True selects due/busy application events, not idleMs.
   */
  void begin(uint32_t nowMs, uint32_t idleMs, uint32_t commandWindowMs,
             bool useAppSchedule = false)
  {
    idleDurationMs_ = idleMs;
    commandWindowMs_ = commandWindowMs;
    useAppSchedule_ = useAppSchedule;
    startPeriodic(nowMs);
    if (useAppSchedule_) active_ = false; // Caller supplies initial due work.
  }

  /** @brief Replace the current phase with a bounded, server-requested active lease.
   * @param nowMs Monotonic millis snapshot when the command is applied.
   * @param seconds 0 selects defaultSeconds; otherwise 1..86400 is required.
   * @param defaultSeconds Valid configured lease, used when seconds is zero.
   * @return False on invalid duration, preserving the complete existing phase.
   */
  bool requestWake(uint32_t nowMs, uint64_t seconds, uint32_t defaultSeconds)
  {
    if (seconds > 86400ULL) return false;
    const uint32_t resolved = seconds == 0U ? defaultSeconds : static_cast<uint32_t>(seconds);
    if (resolved == 0U || resolved > 86400U) return false;
    active_ = true;
    commandLease_ = true;
    deadlineArmed_ = true;
    phaseStartedMs_ = nowMs;
    activeDurationMs_ = resolved * 1000UL;
    return true;
  }

  /** @brief Arm the periodic command window once; never extend a WAKE lease. */
  void telemetryDelivered(uint32_t nowMs)
  {
    // Repeated reports must not extend a command lease or the command window.
    if (useAppSchedule_ || !active_ || commandLease_ || deadlineArmed_) return;
    deadlineArmed_ = true;
    phaseStartedMs_ = nowMs;
    activeDurationMs_ = commandWindowMs_;
  }

  /** @brief Advance timers without cancelling an outstanding radio transaction.
   * @param nowMs Current rollover-safe monotonic time.
   * @param transportIdle False while transmission/response work is outstanding.
   * @param applicationDue A sample or Status deadline is due; schedule mode only.
   * @param applicationBusy An unfinished sensor cycle; schedule mode only.
   * @return EnteredIdle, PeriodicWake, ScheduledWake, or None without a transition.
   * ScheduledWake never requests forced sampling or transmission.
   */
  Transition advance(uint32_t nowMs, bool transportIdle,
                     bool applicationDue = false, bool applicationBusy = false)
  {
    if (useAppSchedule_)
    {
      if (commandLease_ && nowMs - phaseStartedMs_ >= activeDurationMs_)
      {
        commandLease_ = false;
        deadlineArmed_ = false;
      }
      const bool shouldRun = commandLease_ || applicationDue || applicationBusy || !transportIdle;
      if (shouldRun && !active_)
      {
        active_ = true;
        return Transition::ScheduledWake;
      }
      if (!shouldRun && active_)
      {
        active_ = false;
        return Transition::EnteredIdle;
      }
      return Transition::None;
    }
    if (active_)
    {
      if (deadlineArmed_ && nowMs - phaseStartedMs_ >= activeDurationMs_ && transportIdle)
      {
        active_ = false;
        phaseStartedMs_ = nowMs;
        return Transition::EnteredIdle;
      }
    }
    else if (nowMs - phaseStartedMs_ >= idleDurationMs_)
    {
      startPeriodic(nowMs);
      return Transition::PeriodicWake;
    }
    return Transition::None;
  }

  /** @brief Whether scheduled sensor/Status work is currently allowed. */
  bool active() const { return active_; }
  /** @brief Rounded-up active seconds remaining, or 0 for idle/unarmed/expired. */
  uint32_t remainingSeconds(uint32_t nowMs) const
  {
    if (!active_ || !deadlineArmed_) return 0U;
    const uint32_t elapsed = nowMs - phaseStartedMs_;
    if (elapsed >= activeDurationMs_) return 0U;
    return (activeDurationMs_ - elapsed + 999UL) / 1000UL;
  }

private:
  /** @brief Reset periodic policy so a failed report cannot put the node to sleep. */
  void startPeriodic(uint32_t nowMs)
  {
    active_ = true;
    commandLease_ = false;
    deadlineArmed_ = false;
    phaseStartedMs_ = nowMs;
    activeDurationMs_ = 0U;
  }
  bool active_ = true;
  bool useAppSchedule_ = false;
  bool commandLease_ = false;
  bool deadlineArmed_ = false;
  uint32_t phaseStartedMs_ = 0U;
  uint32_t idleDurationMs_ = 0U;
  uint32_t commandWindowMs_ = 0U;
  uint32_t activeDurationMs_ = 0U;
};

#endif
