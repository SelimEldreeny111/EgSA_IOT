#ifndef POWER_MANAGER_H
#define POWER_MANAGER_H
#include <stdint.h>
// Must be called at the very start of setup(), before the IWDG is armed.
// A valid pending sleep request enters STM32 Standby and does not return.
// Invalid, expired, and completed requests are cleared safely.
void powerManagerEarlyBoot();

// Called after normal setup. It reports every component policy and, in
// low-power controller modes, makes the first periodic sample immediately due.
void initializePowerManagerAfterSetup();

// Periodic mode stops new sensor and telemetry work after one successful
// telemetry delivery, while keeping the selected command transport alive.
bool powerManagerAllowsSensorWork();

// Report the outcome of the scheduled LoRa or MQTT telemetry attempt. A
// successful delivery opens the configured command-receive window.
void notifyPowerManagerTelemetryResult(bool delivered);

// Advances the non-blocking command-window/sleep state machine.
void servicePowerManager();

/** @brief Accept a timed WAKE lease in REMOTE_WAKE, RTC_QUEUED or LORA_WOR_STOP.
 * Queued mode accepts it only while awake; it cannot interrupt Standby.
 * @param seconds 1..86400 seconds, or 0 for the compile-time default.
 * @param requestId Nonzero correlation ID; an active identical retry is re-ACKed
 * without timer extension. 0 is the legacy/manual non-deduplicated command.
 * @return false for unsupported mode, invalid duration or rejected duplicate;
 * the existing phase is not changed.
 */
bool requestRemoteWake(uint64_t seconds, uint32_t requestId = 0U);

// Reachable-idle still services the radio, MQTT keepalive and watchdog.
bool powerManagerShouldRunApplication();
// WFI only: UART/SysTick clocks stay enabled; no Standby/reset or ISR watchdog feed.
void powerManagerIdleCpu();

// Wire modes: 1=NORMAL, 2=RTC_PERIODIC, 3=REMOTE_WAKE, 4=RTC_QUEUED,
// 5=LORA_WOR_STOP (0=legacy unknown). These differ from config macro values.
uint32_t powerManagerMode();
// Wire values: state 1=ACTIVE, 2=REACHABLE_IDLE (0=legacy unknown).
uint32_t powerManagerState();
// Rounded-up seconds remaining at the time of query, not an arrival guarantee.
uint32_t powerManagerWakeRemainingSeconds();
// Last accepted WAKE ID retained in RAM; not durable replay protection.
uint32_t powerManagerWakeRequestId();

#endif
