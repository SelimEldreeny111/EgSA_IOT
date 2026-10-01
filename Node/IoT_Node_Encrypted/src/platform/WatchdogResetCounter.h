/** @file WatchdogResetCounter.h
 * @brief Durable, saturating count of boots caused by the STM32 IWDG.
 */
#ifndef WATCHDOG_RESET_COUNTER_H
#define WATCHDOG_RESET_COUNTER_H
#include <stdint.h>

namespace WatchdogResetCounter {
/** @brief Load the record and count this boot at most once.
 * @param watchdogReset Captured hardware IWDG reset flag, before clearing flags.
 * @note Writes flash only after an IWDG reset, not on normal/sleep boots.
 */
void initialize(bool watchdogReset);
/** @return Number of IWDG resets; saturates at UINT32_MAX. */
uint32_t value();
/** @return False if the last flash commit failed readback verification. */
bool storageHealthy();
/** @return True if an existing record failed validation (count restarted at zero). */
bool recoveredInvalidRecord();
}
#endif
