/** @file Watchdog.cpp @brief Independent watchdog setup, servicing, and reset reporting. */
#include "Watchdog.h"
#include "WatchdogResetCounter.h"
#include "PowerResetCounter.h"
#include "ResetCause.h"

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
bool g_resetCauseCaptured = false;
bool g_previousResetWasPower = false;
bool g_resumedFromStandby = false;
uint32_t g_resetFlags = 0U;
bool g_watchdogStarted = false;
bool g_watchdogInitialized = false;
uint32_t g_watchdogServicePauseDepth = 0U;
WatchdogStage g_previousWatchdogStage = WatchdogStage::Unknown;

bool isKnownStage(uint32_t rawStage)
{
    return rawStage <= static_cast<uint32_t>(WatchdogStage::ResetCounterStorage);
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
    case WatchdogStage::SupmeaPeriodCalculation: return "Supmea RTC consumption calculation";
    case WatchdogStage::SupmeaBackupStorage: return "Supmea RTC backup snapshot";
    case WatchdogStage::SupmeaFlashStorage: return "Supmea flash checkpoint";
    case WatchdogStage::RtcSynchronization: return "RTC STIME synchronization";
    case WatchdogStage::ResetCounterStorage: return "reset counter clear/storage";
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

void captureHardwareResetCause()
{
    if (g_resetCauseCaptured) return;
    g_resetCauseCaptured = true;
    __HAL_RCC_PWR_CLK_ENABLE();
    g_resetFlags = RCC->CSR;
    g_resumedFromStandby = __HAL_PWR_GET_FLAG(PWR_FLAG_SB) != RESET;
    static_assert(RCC_CSR_PORRSTF == ResetCause::PowerOn &&
                  RCC_CSR_BORRSTF == ResetCause::Brownout &&
                  RCC_CSR_IWDGRSTF == ResetCause::Iwdg &&
                  RCC_CSR_SFTRSTF == ResetCause::Software &&
                  RCC_CSR_WWDGRSTF == ResetCause::Wwdg &&
                  RCC_CSR_LPWRRSTF == ResetCause::LowPower,
                  "Reset classifier must match STM32F401 RCC flags");
}

void initializeHardwareWatchdog()
{
    if (g_watchdogInitialized) return;
    g_watchdogInitialized = true;
    captureHardwareResetCause();
    g_previousResetWasWatchdog = IWatchdog.isReset(false);
    g_previousResetWasPower = !g_previousResetWasWatchdog &&
        ResetCause::isPowerReset(g_resetFlags, g_resumedFromStandby);
    // IWatchdog.isReset(true) clears flags only when an IWDG flag is set.
    // Clear all causes now so a sticky POR cannot count a later NRST as power.
    __HAL_RCC_CLEAR_RESET_FLAGS();
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
        WatchdogResetCounter::initialize(g_previousResetWasWatchdog);
        PowerResetCounter::initialize(g_previousResetWasPower);
        return;
    }

    IWatchdog.begin(AppConfig::kWatchdogTimeoutUs);
    g_watchdogStarted = IWatchdog.isEnabled();
    // Protect the bounded EEPROM commit with the normal watchdog timeout.
    // Never feed inside an erase/program operation that might have stalled.
    WatchdogResetCounter::initialize(g_previousResetWasWatchdog);
    serviceHardwareWatchdog();
    PowerResetCounter::initialize(g_previousResetWasPower);
    serviceHardwareWatchdog();
}

void reportHardwareWatchdogStatus()
{
    SerialMon.print("Cumulative WDT resets: ");
    SerialMon.println(hardwareWatchdogResetCount());
    SerialMon.print("Cumulative power-on/brownout resets: ");
    SerialMon.println(powerResetCount());
    if (PowerResetCounter::recoveredInvalidRecord())
        SerialMon.println("WARNING: power counter record invalid; counting restarted at zero");
    if (!PowerResetCounter::storageHealthy())
        SerialMon.println("ERROR: power counter flash verification failed; current count is RAM-only");
    if (WatchdogResetCounter::recoveredInvalidRecord())
        SerialMon.println("WARNING: WDT counter record invalid; counting restarted at zero");
    if (!WatchdogResetCounter::storageHealthy())
        SerialMon.println("ERROR: WDT counter flash verification failed; current count is RAM-only");
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
        SerialMon.println(g_previousResetWasPower
            ? "RESET CAUSE: power-on/brownout"
            : (g_resumedFromStandby ? "Reset cause: Standby wake (not counted)"
                                  : "Reset cause: software/pin/other reset (not counted)"));
    }
}

void serviceHardwareWatchdog()
{
    if (g_watchdogStarted && g_watchdogServicePauseDepth == 0U)
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
    if (g_watchdogServicePauseDepth == 0U) storeStage(stage);
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

uint32_t hardwareWatchdogResetCount()
{
    return WatchdogResetCounter::value();
}

HardwareWatchdogServicePause::HardwareWatchdogServicePause()
{
    ++g_watchdogServicePauseDepth;
}

uint32_t powerResetCount() { return PowerResetCounter::value(); }
HardwareWatchdogServicePause::~HardwareWatchdogServicePause()
{
    --g_watchdogServicePauseDepth;
}
