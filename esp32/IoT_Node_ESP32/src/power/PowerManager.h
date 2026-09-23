#ifndef POWER_MANAGER_H
#define POWER_MANAGER_H

// Must be called at the very start of setup(), before the watchdog is armed.
// It releases retained GPIO levels and validates the last ESP32 deep-sleep
// wake record before normal peripheral initialization.
void powerManagerEarlyBoot();

// Called after normal setup. It reports every component policy and, in
// controller POWER_DOWN mode, makes the first periodic sample immediately due.
void initializePowerManagerAfterSetup();

// Periodic mode stops new sensor and telemetry work after one successful
// telemetry delivery, while keeping the selected command transport alive.
bool powerManagerAllowsSensorWork();

// Report the outcome of the scheduled LoRa or MQTT telemetry attempt. A
// successful delivery opens the configured command-receive window.
void notifyPowerManagerTelemetryResult(bool delivered);

// Advances the non-blocking command-window/sleep state machine.
void servicePowerManager();

#endif
