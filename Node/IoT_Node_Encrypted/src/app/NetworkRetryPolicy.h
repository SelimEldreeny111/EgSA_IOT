/** @file NetworkRetryPolicy.h @brief Two network-failure budgets separated by one modem reset. */
#ifndef NETWORK_RETRY_POLICY_H
#define NETWORK_RETRY_POLICY_H
#include <stdint.h>

/** @brief Count failed physical joins/registration-plus-GPRS attempts, not MQTT failures.
 * @note A modem reset does not clear the policy. Network success or controller
 * boot starts a fresh first stage. The caller executes the returned action.
 */
class NetworkRetryPolicy {
public:
    /** @brief Recovery action for the caller after a returned network failure. */
    enum class Action : uint8_t { Retry, ResetModem, ResetControllerAndModem };
    /** @brief Start a first-stage budget. @param retriesPerStage Validated configuration limit, 1..100. */
    explicit NetworkRetryPolicy(uint8_t retriesPerStage) : limit_(retriesPerStage) {}
    /** @brief Count one failure. @return The recovery action required at this threshold. */
    Action failedAttempt() {
        if (failures_ < limit_) ++failures_;
        if (failures_ < limit_) return Action::Retry;
        if (secondStage_) return Action::ResetControllerAndModem;
        secondStage_ = true;
        failures_ = 0U;
        return Action::ResetModem;
    }
    /** @brief Clear both stages after a usable network connection succeeds. */
    void connected() { failures_ = 0U; secondStage_ = false; }
    /** @return Failures in the current stage; saturates at the configured limit. */
    uint8_t failures() const { return failures_; }
    /** @return One before modem-only reset, two afterwards until connection success. */
    uint8_t stage() const { return secondStage_ ? 2U : 1U; }
private:
    const uint8_t limit_;
    uint8_t failures_ = 0U;
    bool secondStage_ = false;
};
#endif
