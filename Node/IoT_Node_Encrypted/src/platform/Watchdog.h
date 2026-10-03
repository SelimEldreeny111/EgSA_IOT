#ifndef HARDWARE_WATCHDOG_H
#define HARDWARE_WATCHDOG_H

#include <Arduino.h>

// The stage is stored in STM32 SRAM that is not initialized at reset. If the
// IWDG fires, the next boot can report which operation was active. Stages are
// deliberately broad: they diagnose the subsystem without storing pointers or
// private data in the crash record.
enum class WatchdogStage : uint8_t
{
    Unknown = 0,
    Boot,
    Setup,
    MainLoop,
    ModemInitialization,
    WifiJoin,
    WifiModemRestart,
    OperatorInput,
    GsmRegistration,
    GprsAttach,
    MqttStatus,
    MqttConnect,
    MqttService,
    MqttPublish,
    FlowMeterRead,
    HndaRead,
    SondasRead,
    LoraTransmit,
    LoraAckWait,
    PowerTransition,
    DeliberateReset,
    SelfTestAfterSetup,
    SelfTestMainLoop,
    // Append new values so previous firmware's persisted stage IDs stay valid.
    SupmeaPeriodCalculation,
    SupmeaBackupStorage,
    SupmeaFlashStorage,
    RtcSynchronization
};

enum class WatchdogSelfTestPoint : uint8_t
{
    AfterSetup = 1,
    MainLoop = 2
};

// Starts the STM32 independent watchdog and captures the previous reset cause.
// Call this at the very beginning of setup(), before any modem operation.
void initializeHardwareWatchdog();

// Prints the captured reset cause once SerialMon is initialized.
void reportHardwareWatchdogStatus();

// Reload only at explicit application progress checkpoints. Never call this
// from inside an unknown or unbounded blocking operation.
void serviceHardwareWatchdog();

// Records the active stage and reloads the IWDG. Call this immediately before
// a bounded operation to give it one complete watchdog window. On return, the
// caller must record/service the next verified progress stage.
void serviceHardwareWatchdog(WatchdogStage stage);

// Records a diagnostic stage without reloading the IWDG.
void markHardwareWatchdogStage(WatchdogStage stage);

// Intentional long delays may use this function. It services the watchdog in
// short steps, but a stalled delay/tick implementation still causes a reset.
void watchdogDelay(uint32_t durationMs);

// Requests a fast IWDG reset while preserving the watchdog-reset cause flag.
[[noreturn]] void forceHardwareWatchdogReset(const char* reason);

// Optional controlled hang used to prove that the global watchdog resets code
// outside the network retry path. It is disabled in production configuration.
void runHardwareWatchdogSelfTest(WatchdogSelfTestPoint point);

bool previousResetWasHardwareWatchdog();

/** @brief Cumulative IWDG reset count, retained in flash; normal boots do not increment. */
uint32_t hardwareWatchdogResetCount();

/** @brief Prevent nested idle callbacks from feeding/hiding a stuck operation.
 * Service is restored on scope exit, but the watchdog is not reloaded there.
 */
class HardwareWatchdogServicePause {
public:
    HardwareWatchdogServicePause();
    ~HardwareWatchdogServicePause();
    HardwareWatchdogServicePause(const HardwareWatchdogServicePause&) = delete;
    HardwareWatchdogServicePause& operator=(const HardwareWatchdogServicePause&) = delete;
};

#endif
