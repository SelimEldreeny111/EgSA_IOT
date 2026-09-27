/**
 * @file Watchdog.h
 * @brief STM32 independent-watchdog lifecycle and progress checkpoints.
 */
#ifndef HARDWARE_WATCHDOG_H
#define HARDWARE_WATCHDOG_H

#include <Arduino.h>

/**
 * @brief Capture the previous reset cause and start the STM32 IWDG.
 * @pre Call near the start of setup(), before any potentially blocking modem work.
 */
void initializeHardwareWatchdog();

/** @brief Print the captured reset cause after SerialMon is initialized. */
void reportHardwareWatchdogStatus();

/**
 * @brief Reload IWDG at an explicit application progress checkpoint.
 * @warning Do not call from an unknown or unbounded blocking operation; that
 * would hide the very stall the watchdog is intended to detect.
 */
void serviceHardwareWatchdog();

/** @brief Delay in short, watchdog-serviced steps. @param durationMs Requested intentional wait in milliseconds. */
void watchdogDelay(uint32_t durationMs);

/** @brief Stop making progress and allow a prompt IWDG reset. @param reason Diagnostic explanation printed before reset. */
[[noreturn]] void forceHardwareWatchdogReset(const char* reason);

/** @brief Query the reset-cause flag captured at boot. @return True if the previous reset came from IWDG. */
bool previousResetWasHardwareWatchdog();

#endif
