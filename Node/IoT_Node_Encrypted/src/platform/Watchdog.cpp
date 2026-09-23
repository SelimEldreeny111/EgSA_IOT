#include "Watchdog.h"

#include "../config/AppConfig.h"

#include <IWatchdog.h>

extern HardwareSerial SerialMon;

namespace
{
constexpr uint32_t kPersistentStageMagic = 0x57445431UL; // "WDT1"

struct PersistentWatchdogStage
{
    uint32_t magic;
    uint32_t stage;
    uint32_t invertedStage;
};

// STM32duino's linker keeps .noinit out of the C/C++ zero-initialization
// pass. SRAM survives an IWDG/NVIC reset, while the magic/inverse pair rejects
// random content after a cold power-on.
__attribute__((section(".noinit"))) volatile PersistentWatchdogStage g_persistentStage;

bool g_previousResetWasWatchdog = false;
bool g_watchdogStarted = false;
WatchdogStage g_previousWatchdogStage = WatchdogStage::Unknown;

bool isKnownStage(uint32_t rawStage)
{
    return rawStage <= static_cast<uint32_t>(WatchdogStage::SelfTestMainLoop);
}

bool persistentStageIsValid()
{
    return g_persistentStage.magic == kPersistentStageMagic &&
        g_persistentStage.invertedStage == ~g_persistentStage.stage &&
        isKnownStage(g_persistentStage.stage);
}

void storeStage(WatchdogStage stage)
{
    const uint32_t rawStage = static_cast<uint32_t>(stage);

    // Invalidate first so an interrupt/reset between writes cannot turn a
    // partially updated record into a valid crash report.
    g_persistentStage.magic = 0U;
    g_persistentStage.stage = rawStage;
    g_persistentStage.invertedStage = ~rawStage;
    g_persistentStage.magic = kPersistentStageMagic;
}

const char* stageName(WatchdogStage stage)
{
    switch (stage)
    {
    case WatchdogStage::Boot: return "boot";
    case WatchdogStage::Setup: return "application setup";
    case WatchdogStage::MainLoop: return "main superloop";
    case WatchdogStage::ModemInitialization: return "modem initialization";
    case WatchdogStage::WifiJoin: return "ESP8266 WiFi join";
    case WatchdogStage::WifiModemRestart: return "ESP8266 restart";
    case WatchdogStage::OperatorInput: return "operator WiFi input";
    case WatchdogStage::GsmRegistration: return "SIM800 network registration";
    case WatchdogStage::GprsAttach: return "SIM800 GPRS attach";
    case WatchdogStage::MqttStatus: return "MQTT/socket status";
    case WatchdogStage::MqttConnect: return "MQTT connection";
    case WatchdogStage::MqttService: return "MQTT service loop";
    case WatchdogStage::MqttPublish: return "MQTT publish";
    case WatchdogStage::FlowMeterRead: return "flow-meter Modbus read";
    case WatchdogStage::HndaRead: return "HNDA Modbus read";
    case WatchdogStage::SondasRead: return "Sondas Modbus read";
    case WatchdogStage::LoraTransmit: return "LoRa transmit";
    case WatchdogStage::LoraAckWait: return "LoRa ACK wait";
    case WatchdogStage::PowerTransition: return "power-mode transition";
    case WatchdogStage::DeliberateReset: return "deliberate recovery reset";
    case WatchdogStage::SelfTestAfterSetup: return "watchdog self-test after setup";
    case WatchdogStage::SelfTestMainLoop: return "watchdog self-test in main loop";
    case WatchdogStage::Unknown:
    default:
        return "unknown/not recorded";
    }
}

WatchdogStage selfTestStage(WatchdogSelfTestPoint point)
{
    return point == WatchdogSelfTestPoint::AfterSetup
        ? WatchdogStage::SelfTestAfterSetup
        : WatchdogStage::SelfTestMainLoop;
}
}

void initializeHardwareWatchdog()
{
    g_previousResetWasWatchdog = IWatchdog.isReset(true);
    if (g_previousResetWasWatchdog && persistentStageIsValid())
    {
        g_previousWatchdogStage =
            static_cast<WatchdogStage>(g_persistentStage.stage);
    }
    else
    {
        g_previousWatchdogStage = WatchdogStage::Unknown;
    }

    storeStage(WatchdogStage::Boot);

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
        SerialMon.print("Last watchdog stage: ");
        SerialMon.println(stageName(g_previousWatchdogStage));
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

void serviceHardwareWatchdog(WatchdogStage stage)
{
    markHardwareWatchdogStage(stage);
    serviceHardwareWatchdog();
}

void markHardwareWatchdogStage(WatchdogStage stage)
{
    storeStage(stage);
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
    markHardwareWatchdogStage(WatchdogStage::DeliberateReset);

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

void runHardwareWatchdogSelfTest(WatchdogSelfTestPoint point)
{
    if (!g_watchdogStarted ||
        AppConfig::kWatchdogSelfTestMode != static_cast<uint8_t>(point))
    {
        return;
    }

    const WatchdogStage requestedStage = selfTestStage(point);
    if (g_previousResetWasWatchdog &&
        g_previousWatchdogStage == requestedStage)
    {
        SerialMon.print("WATCHDOG SELF-TEST PASS: reset recovered from ");
        SerialMon.println(stageName(requestedStage));
        return;
    }

    SerialMon.println();
    SerialMon.print("WATCHDOG SELF-TEST: deliberately blocking at ");
    SerialMon.println(stageName(requestedStage));
    SerialMon.print("Expected reset after approximately ");
    SerialMon.print(AppConfig::kWatchdogTimeoutUs / 1000000UL);
    SerialMon.println(" seconds");
    SerialMon.flush();

    serviceHardwareWatchdog(requestedStage);
    while (true)
    {
        // SysTick/interrupts remain enabled. No application checkpoint reloads
        // the independent watchdog, so hardware must reset the controller.
        __NOP();
    }
}

bool previousResetWasHardwareWatchdog()
{
    return g_previousResetWasWatchdog;
}
