/**
 * @file Watchdog.h
 * @brief STM32 independent-watchdog lifecycle and progress checkpoints.
 */
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

/** @brief Capture reset cause, persist IWDG count and arm IWDG before modem setup. */
void initializeHardwareWatchdog();

/** @brief Print the captured reset cause after SerialMon is initialized. */
void reportHardwareWatchdogStatus();

/**
 * @brief Reload IWDG at an explicit application progress checkpoint.
 * @warning Do not call from an unknown or unbounded blocking operation; that
 * would hide the very stall the watchdog is intended to detect.
 */
void serviceHardwareWatchdog();

/** @brief Record a stage and reload IWDG unless service is paused.
 * @param stage Diagnostic operation about to run, at a verified checkpoint.
 */
void serviceHardwareWatchdog(WatchdogStage stage);

/** @brief Record a stage without feeding IWDG. @param stage Active operation. */
void markHardwareWatchdogStage(WatchdogStage stage);

/** @brief Intentional bounded delay with foreground watchdog checkpoints.
 * @param durationMs Requested wait; a stalled tick/delay still causes reset.
 */
void watchdogDelay(uint32_t durationMs);

/** @brief Stop making progress and allow a prompt IWDG reset. @param reason Diagnostic explanation printed before reset. */
[[noreturn]] void forceHardwareWatchdogReset(const char* reason);

/** @brief Optional deliberate stall, disabled in production.
 * @param point Requested setup/main-loop fault-injection point.
 */
void runHardwareWatchdogSelfTest(WatchdogSelfTestPoint point);

/** @brief Query the reset cause captured at boot. @return True for IWDG reset. */
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
