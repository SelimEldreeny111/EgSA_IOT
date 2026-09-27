/**
 * @file PowerManager.h
 * @brief Coordinated component power policy and RTC-standby state machine.
 */
#ifndef POWER_MANAGER_H
#define POWER_MANAGER_H
/**
 * @brief Complete a validated pending standby request before IWDG startup.
 *
 * A valid request enters STM32 Standby and does not return. Invalid, expired,
 * or completed requests are cleared without entering sleep.
 * @pre Call before initializeHardwareWatchdog().
 */
void powerManagerEarlyBoot();

/** @brief Report the selected component policies and initialize cycle timing. */
void initializePowerManagerAfterSetup();

/** @brief Check whether a new acquisition cycle may start. @return False while the post-delivery command window or standby transition is active. */
bool powerManagerAllowsSensorWork();

/** @brief Report a scheduled telemetry outcome to the sleep FSM. @param delivered True only after confirmed LoRa or MQTT delivery. */
void notifyPowerManagerTelemetryResult(bool delivered);

/** @brief Advance the non-blocking command window and standby preparation. */
void servicePowerManager();

#endif
