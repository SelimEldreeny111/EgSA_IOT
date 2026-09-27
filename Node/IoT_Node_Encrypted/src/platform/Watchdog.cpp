/** @file Watchdog.cpp @brief Independent watchdog setup, servicing, and reset reporting. */
#include "Watchdog.h"

#include "../config/AppConfig.h"

#include <IWatchdog.h>

extern HardwareSerial SerialMon;

namespace
{
bool g_previousResetWasWatchdog = false;
bool g_watchdogStarted = false;
}

void initializeHardwareWatchdog()
{
    g_previousResetWasWatchdog = IWatchdog.isReset(true);

    if (!AppConfig::kEnableHardwareWatchdog)
    {
        return;
    }

    IWatchdog.begin(AppConfig::kWatchdogTimeoutUs);
    g_watchdogStarted = IWatchdog.isEnabled();
}

void reportHardwareWatchdogStatus()
{
    if (!AppConfig::kEnableHardwareWatchdog)
    {
        SerialMon.println("Hardware watchdog: disabled by configuration");
        return;
    }

    if (!g_watchdogStarted)
    {
        SerialMon.println("ERROR: hardware watchdog did not start (check timeout range)");
        return;
    }

    SerialMon.print("Hardware watchdog: armed, timeout=");
    SerialMon.print(AppConfig::kWatchdogTimeoutUs / 1000UL);
    SerialMon.println(" ms");
    if (g_previousResetWasWatchdog)
    {
        SerialMon.println("RESET CAUSE: independent hardware watchdog timeout");
    }
    else
    {
        SerialMon.println("Reset cause: power-on/software reset (not IWDG)");
    }
}

void serviceHardwareWatchdog()
{
    if (g_watchdogStarted)
    {
        IWatchdog.reload();
    }
}

void watchdogDelay(uint32_t durationMs)
{
    constexpr uint32_t kServiceSliceMs = 100UL;
    while (durationMs > 0UL)
    {
        const uint32_t sliceMs = durationMs < kServiceSliceMs
            ? durationMs
            : kServiceSliceMs;
        delay(sliceMs);
        durationMs -= sliceMs;
        serviceHardwareWatchdog();
    }
}

[[noreturn]] void forceHardwareWatchdogReset(const char* reason)
{
    if (g_watchdogStarted)
    {
        // Shorten the already-running IWDG so this reset is fast and the next
        // boot can identify it using the hardware watchdog reset flag.
        IWatchdog.set(AppConfig::kWatchdogForcedResetTimeoutUs);
    }

    SerialMon.println();
    SerialMon.println("******** SYSTEM RESET REQUESTED ********");
    SerialMon.print("Reason: ");
    SerialMon.println(reason == nullptr ? "unspecified watchdog recovery" : reason);
    SerialMon.flush();

    if (!g_watchdogStarted)
    {
        NVIC_SystemReset();
    }

    noInterrupts();
    while (true)
    {
        __WFI();
    }
}

bool previousResetWasHardwareWatchdog()
{
    return g_previousResetWasWatchdog;
}
