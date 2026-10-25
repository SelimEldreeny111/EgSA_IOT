/** @file PowerResetCounter.h @brief Separate durable power-on/brownout counter. */
#ifndef WIOT_POWER_RESET_COUNTER_H
#define WIOT_POWER_RESET_COUNTER_H
#include <stdint.h>
namespace PowerResetCounter {
/** @brief Load storage and increment once only for classified power-on/brownout. */
void initialize(bool powerReset);
/** @return Saturating count (RAM count if a commit failed). */
uint32_t value();
/** @brief Persist and verify zero; failure retains the previous RAM value. */
bool clear();
/** @return Last storage-operation health. */
bool storageHealthy();
/** @return Whether a corrupt record was rejected at startup. */
bool recoveredInvalidRecord();
}
#endif
