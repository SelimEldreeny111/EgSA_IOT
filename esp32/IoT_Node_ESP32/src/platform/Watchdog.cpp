#include "Watchdog.h"

#include "../config/AppConfig.h"

#include <esp_err.h>
#include <esp_system.h>
#include <esp_task_wdt.h>

extern HardwareSerial& SerialMon;

namespace
{
bool g_previousResetWasWatchdog = false;
bool g_watchdogStarted = false;

bool isWatchdogResetReason(esp_reset_reason_t reason)
{
    return reason == ESP_RST_TASK_WDT ||
        reason == ESP_RST_INT_WDT ||
        reason == ESP_RST_WDT;
}

esp_task_wdt_config_t makeWatchdogConfig(uint32_t timeoutMs)
{
    esp_task_wdt_config_t config = {};
    config.timeout_ms = timeoutMs;
    // Monitor the Arduino loop task explicitly. Do not subscribe idle tasks;
    // radio/network libraries may legitimately occupy a core for short bursts.
    config.idle_core_mask = 0U;
    config.trigger_panic = true;
    return config;
}
}

void initializeHardwareWatchdog()
{
    g_previousResetWasWatchdog = isWatchdogResetReason(esp_reset_reason());

    if (!AppConfig::kEnableHardwareWatchdog)
    {
        return;
    }

    const esp_task_wdt_config_t config =
        makeWatchdogConfig(AppConfig::kWatchdogTimeoutMs);

    esp_err_t configureResult = esp_task_wdt_reconfigure(&config);
    if (configureResult == ESP_ERR_INVALID_STATE)
    {
        configureResult = esp_task_wdt_init(&config);
    }

    if (configureResult != ESP_OK)
    {
        return;
    }

    esp_err_t taskStatus = esp_task_wdt_status(nullptr);
    if (taskStatus == ESP_ERR_NOT_FOUND)
    {
        taskStatus = esp_task_wdt_add(nullptr);
    }
    g_watchdogStarted = taskStatus == ESP_OK;
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
        SerialMon.println("ERROR: ESP32 task watchdog did not start");
        return;
    }

    SerialMon.print("ESP32 task watchdog: armed, timeout=");
    SerialMon.print(AppConfig::kWatchdogTimeoutMs);
    SerialMon.println(" ms");
    if (g_previousResetWasWatchdog)
    {
        SerialMon.println("RESET CAUSE: ESP32 watchdog timeout");
    }
    else
    {
        SerialMon.println("Reset cause: not an ESP32 watchdog timeout");
    }
}

void serviceHardwareWatchdog()
{
    if (g_watchdogStarted)
    {
        (void)esp_task_wdt_reset();
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
        // Shorten the active TWDT and deliberately stop servicing the loop
        // task so the next boot records a watchdog reset cause.
        const esp_task_wdt_config_t config =
            makeWatchdogConfig(AppConfig::kWatchdogForcedResetTimeoutMs);
        (void)esp_task_wdt_reconfigure(&config);
    }

    SerialMon.println();
    SerialMon.println("******** SYSTEM RESET REQUESTED ********");
    SerialMon.print("Reason: ");
    SerialMon.println(reason == nullptr ? "unspecified watchdog recovery" : reason);
    SerialMon.flush();

    if (!g_watchdogStarted)
    {
        esp_restart();
    }

    while (true)
    {
        delay(1000);
    }
}

bool previousResetWasHardwareWatchdog()
{
    return g_previousResetWasWatchdog;
}
