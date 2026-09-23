#ifndef HARDWARE_WATCHDOG_H
#define HARDWARE_WATCHDOG_H

#include <Arduino.h>

// Starts the STM32 independent watchdog and captures the previous reset cause.
// Call this at the very beginning of setup(), before any modem operation.
void initializeHardwareWatchdog();

// Prints the captured reset cause once SerialMon is initialized.
void reportHardwareWatchdogStatus();

// Reload only at explicit application progress checkpoints. Never call this
// from inside an unknown or unbounded blocking operation.
void serviceHardwareWatchdog();

// Intentional long delays may use this function. It services the watchdog in
// short steps, but a stalled delay/tick implementation still causes a reset.
void watchdogDelay(uint32_t durationMs);

// Requests a fast IWDG reset while preserving the watchdog-reset cause flag.
[[noreturn]] void forceHardwareWatchdogReset(const char* reason);

bool previousResetWasHardwareWatchdog();

#endif
