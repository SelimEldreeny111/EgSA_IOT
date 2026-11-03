/** @file IoT_Node.cpp @brief Sensor-node startup and configuration initialization. */
/* ================== INCLUDES ================== */
#define APP_LOG_MODULE "BOOT"
#include "../platform/DebugLog.h"
#include "../config/AppConfig.h"
#include "IoT_Node.h"
#include "FlowMeterManager.h"
#include "NetworkRetryPolicy.h"
#include "../devices/BatteryMonitor.h"
#include "../devices/HndaSensor.h"
#include "../devices/Rs485Bus.h"
#include "../devices/SondasSensor.h"
#include "../devices/ValveController.h"
#include "../platform/Watchdog.h"
#include "../radio/LoraLink.h"

#include <EEPROM.h>
#include <string.h>

/* =================================== SERIAL ======================================= */
extern HardwareSerial SerialMon;   // Debug
extern HardwareSerial SerialAT;    // SIM800 or WIFI 

#define WIFI_RETRY_INTERVAL 5000
#define WIFI_MAX_RETRIES    2

#define GPRS_RETRY_INTERVAL 5000
#define GPRS_MAX_RETRIES    5

namespace
{
NetworkRetryPolicy g_networkRetryPolicy(AppConfig::kNetworkRetriesPerStage);

/** @brief Clear the consecutive network-failure counter after a successful connection. */
bool recordNetworkConnectionSuccess()
{
    if (g_networkRetryPolicy.failures() != 0U || g_networkRetryPolicy.stage() != 1U)
    {
        APP_DEBUG_PRINTLN("[NETWORK] Connected; retry recovery cleared (stage 1, 0 failures)");
    }
    g_networkRetryPolicy.connected();
    serviceHardwareWatchdog();
    return true;
}

/** @brief Count one failed physical attempt and execute the two-stage recovery policy. */
bool recordNetworkConnectionFailure()
{
    // Print before advancing so a threshold is shown as stage 1 attempt 10/10,
    // not the freshly initialized stage 2 attempt 0/10.
    APP_DEBUG_PRINT("[NETWORK] Failed attempt, stage ");
    APP_DEBUG_PRINT(g_networkRetryPolicy.stage());
    APP_DEBUG_PRINT(": ");
    APP_DEBUG_PRINT(g_networkRetryPolicy.failures() + 1U);
    APP_DEBUG_PRINT('/');
    APP_DEBUG_PRINTLN(AppConfig::kNetworkRetriesPerStage);
    const NetworkRetryPolicy::Action action = g_networkRetryPolicy.failedAttempt();
    if (action == NetworkRetryPolicy::Action::ResetModem)
    {
        resetMqttTransportForNetworkRecovery();
    }
    else if (action == NetworkRetryPolicy::Action::ResetControllerAndModem)
    {
        resetModemAndControllerForNetworkFailure();
    }

    serviceHardwareWatchdog();
    return false;
}
}

#if defined(USE_ESP8266)
namespace {
constexpr uint32_t kWifiCredentialMagic = 0x57494649UL; // "WIFI"
constexpr uint8_t kWifiCredentialVersion = 1;
constexpr size_t kWifiSsidMaxLength = 32;
constexpr size_t kWifiPasswordMaxLength = 64;
constexpr int kWifiCredentialEepromAddress = 0;
constexpr uint32_t kWifiSerialInputTimeoutMs = 180000UL;
bool g_wifiProvisioningPromptUsed = false;

/** @brief Versioned, checksummed EEPROM copy of a previously working Wi-Fi network. */
struct StoredWifiCredentials
{
    uint32_t magic;
    uint8_t version;
    char ssid[kWifiSsidMaxLength + 1];
    char password[kWifiPasswordMaxLength + 1];
    uint32_t checksum;
};

/** @brief Compute the stored-credential FNV-style checksum, excluding the checksum field. */
uint32_t calculateCredentialChecksum(const StoredWifiCredentials& credentials)
{
    const uint8_t* bytes = reinterpret_cast<const uint8_t*>(&credentials);
    const size_t length = sizeof(StoredWifiCredentials) - sizeof(credentials.checksum);
    uint32_t hash = 2166136261UL;

    for (size_t i = 0; i < length; ++i)
    {
        hash ^= bytes[i];
        hash *= 16777619UL;
    }

    return hash;
}

/** @brief Open the EEPROM abstraction on platforms requiring explicit initialization. */
void beginCredentialStore()
{
#if defined(ESP8266) || defined(ESP32)
    EEPROM.begin(sizeof(StoredWifiCredentials));
#endif
}

/** @brief Commit pending EEPROM writes where the platform requires it. */
void commitCredentialStore()
{
#if defined(ESP8266) || defined(ESP32)
    EEPROM.commit();
#endif
}

/** @brief Load a fallback network only if its magic, version, and checksum pass validation. */
bool loadSavedWifiCredentials(StoredWifiCredentials& credentials)
{
    if (!AppConfig::kEnableWifiCredentialStore)
    {
        return false;
    }

    beginCredentialStore();
    EEPROM.get(kWifiCredentialEepromAddress, credentials);

    if (credentials.magic != kWifiCredentialMagic ||
        credentials.version != kWifiCredentialVersion ||
        credentials.checksum != calculateCredentialChecksum(credentials) ||
        credentials.ssid[0] == '\0')
    {
        return false;
    }

    credentials.ssid[kWifiSsidMaxLength] = '\0';
    credentials.password[kWifiPasswordMaxLength] = '\0';
    return true;
}

/** @brief Compare both SSID and password with the stored fallback pair. */
bool wifiCredentialsMatch(const StoredWifiCredentials& credentials, const char* ssid, const char* password)
{
    return strcmp(credentials.ssid, ssid) == 0 && strcmp(credentials.password, password) == 0;
}

/** @brief Persist a connected network and verify the EEPROM write by reading it back. */
bool saveWifiCredentials(const char* ssid, const char* password)
{
    if (!AppConfig::kEnableWifiCredentialStore)
    {
        APP_DEBUG_PRINTLN("WiFi credential storage disabled; using configured credentials for this boot.");
        return false;
    }

    if (ssid == nullptr || password == nullptr ||
        strlen(ssid) == 0 ||
        strlen(ssid) > kWifiSsidMaxLength ||
        strlen(password) > kWifiPasswordMaxLength)
    {
        return false;
    }

    StoredWifiCredentials savedCredentials = {};
    if (loadSavedWifiCredentials(savedCredentials) &&
        wifiCredentialsMatch(savedCredentials, ssid, password))
    {
        return true;
    }

    StoredWifiCredentials credentials = {};
    credentials.magic = kWifiCredentialMagic;
    credentials.version = kWifiCredentialVersion;
    strncpy(credentials.ssid, ssid, kWifiSsidMaxLength);
    strncpy(credentials.password, password, kWifiPasswordMaxLength);
    credentials.checksum = calculateCredentialChecksum(credentials);

    beginCredentialStore();
    EEPROM.put(kWifiCredentialEepromAddress, credentials);
    commitCredentialStore();

    StoredWifiCredentials verifiedCredentials = {};
    EEPROM.get(kWifiCredentialEepromAddress, verifiedCredentials);
    const bool verified =
        verifiedCredentials.magic == kWifiCredentialMagic &&
        verifiedCredentials.version == kWifiCredentialVersion &&
        verifiedCredentials.checksum == calculateCredentialChecksum(verifiedCredentials) &&
        wifiCredentialsMatch(verifiedCredentials, ssid, password);
    if (!verified)
    {
        APP_LOG_ERROR("WiFi credential flash verification FAILED.");
        return false;
    }

    APP_DEBUG_PRINTLN("WiFi credentials saved and verified in flash.");
    return true;
}

/** @brief Try one Wi-Fi credential source with bounded retries and watchdog-safe delays. */
bool connectWifiWithCredentials(const char* source, const char* ssid, const char* password)
{
    for (int retryCount = 0; retryCount < WIFI_MAX_RETRIES; ++retryCount)
    {
        serviceHardwareWatchdog(WatchdogStage::WifiJoin);
        APP_DEBUG_PRINT("Connecting to ");
        APP_DEBUG_PRINT(source);
        APP_DEBUG_PRINT(" WiFi SSID: ");
        APP_DEBUG_PRINTLN(ssid);

        const bool connected = modem.networkConnect(ssid, password);
        // The modem call returned normally. Refresh here so the next bounded
        // retry receives a full watchdog window. A call that never returns is
        // deliberately not refreshed and resets the MCU.
        serviceHardwareWatchdog();
        if (connected)
        {
            APP_DEBUG_PRINT(source);
            APP_DEBUG_PRINTLN(" WiFi connected");
            return true;
        }

        APP_LOG_ERROR("WiFi join failed");
        recordNetworkConnectionFailure();
        watchdogDelay(WIFI_RETRY_INTERVAL);
    }

    return false;
}

/** @brief Save the active Wi-Fi network as fallback and report storage failures. */
bool saveConnectedWifiAsFallback(const char* source, const char* ssid, const char* password)
{
    if (saveWifiCredentials(ssid, password))
    {
        APP_DEBUG_PRINT("Saved ");
        APP_DEBUG_PRINT(source);
        APP_DEBUG_PRINTLN(" WiFi as the flash fallback network.");
        return true;
    }

    APP_DEBUG_PRINT("Connected to ");
    APP_DEBUG_PRINT(source);
    APP_DEBUG_PRINTLN(" WiFi, but could not save it as the flash fallback.");
    return false;
}

/** @brief Read a bounded serial-console line while keeping the watchdog alive. */
bool readSerialLine(char* buffer, size_t bufferSize, uint32_t timeoutMs, bool allowEmpty)
{
#if APP_ENABLE_DEBUG
    if (buffer == nullptr || bufferSize == 0)
    {
        return false;
    }

    size_t index = 0;
    const uint32_t startMs = millis();
    buffer[0] = '\0';
    serviceHardwareWatchdog(WatchdogStage::OperatorInput);

    while (millis() - startMs < timeoutMs)
    {
        while (SerialMon.available() > 0)
        {
            const char c = static_cast<char>(SerialMon.read());
            if (c == '\r' || c == '\n')
            {
                buffer[index] = '\0';
                return allowEmpty || index > 0;
            }

            if (index < bufferSize - 1)
            {
                buffer[index++] = c;
            }
        }

        watchdogDelay(10);
    }

    buffer[index] = '\0';
    return allowEmpty || index > 0;
#else
    (void)buffer; (void)bufferSize; (void)timeoutMs; (void)allowEmpty;
    return false;
#endif
}

/** @brief Prompt for an SSID and optional password after automatic networks fail. */
bool promptForWifiCredentials(char* ssid, size_t ssidSize, char* password, size_t passwordSize)
{
#if APP_ENABLE_DEBUG
    APP_DEBUG_PRINTLN();
    APP_DEBUG_PRINTLN("Configured and saved fallback WiFi networks are not connected.");
    APP_DEBUG_PRINTLN("Enter new fallback WiFi credentials in the serial monitor.");
    APP_DEBUG_PRINTLN("Credentials are stored in flash only after a successful connection.");
    APP_DEBUG_PRINT("SSID (max ");
    APP_DEBUG_PRINT(kWifiSsidMaxLength);
    APP_DEBUG_PRINTLN(" chars):");

    if (!readSerialLine(ssid, ssidSize, kWifiSerialInputTimeoutMs, false))
    {
        APP_LOG_WARN("No SSID entered before timeout.");
        return false;
    }

    if (strlen(ssid) > kWifiSsidMaxLength)
    {
        APP_DEBUG_PRINTLN("SSID is too long.");
        return false;
    }

    APP_DEBUG_PRINT("Password (max ");
    APP_DEBUG_PRINT(kWifiPasswordMaxLength);
    APP_DEBUG_PRINTLN(" chars, send blank line for open WiFi):");

    readSerialLine(password, passwordSize, kWifiSerialInputTimeoutMs, true);

    if (strlen(password) > kWifiPasswordMaxLength)
    {
        APP_DEBUG_PRINTLN("Password is too long.");
        return false;
    }

    return true;
#else
    (void)ssid; (void)ssidSize; (void)password; (void)passwordSize;
    return false;
#endif
}

}
#endif

bool connectNetwork()
{
#if defined(USE_SIM800)
    int retryCount = 0;
    while (retryCount < GPRS_MAX_RETRIES)
    {
        serviceHardwareWatchdog(WatchdogStage::GsmRegistration);
        APP_DEBUG_PRINTLN("Connecting to GSM network.......");
        const bool networkReady = modem.waitForNetwork(10000);
        serviceHardwareWatchdog();
        if (!networkReady)
        {
            APP_LOG_ERROR("Network FAILED, retrying......");
            recordNetworkConnectionFailure();
            retryCount++;
            watchdogDelay(GPRS_RETRY_INTERVAL);
            continue;
        }

        APP_DEBUG_PRINTLN("Network connected, connecting GPRS...");
        serviceHardwareWatchdog(WatchdogStage::GprsAttach);
        const bool gprsReady =
            modem.gprsConnect(kApn, kNetworkUser, kNetworkPassword);
        serviceHardwareWatchdog();
        if (!gprsReady)
        {
            APP_LOG_ERROR("GPRS FAILED, retrying...");
            recordNetworkConnectionFailure();
            retryCount++;
            watchdogDelay(GPRS_RETRY_INTERVAL);
            continue;
        }

        APP_DEBUG_PRINTLN("GPRS Connected");
        return recordNetworkConnectionSuccess();
    }

    APP_LOG_ERROR("GPRS connection failed after retries!");
    return false; // Each failed inner attempt was already counted.

#elif defined(USE_ESP8266)
    // Connection priority is intentional:
    //   1. Credentials compiled into AppConfig.cpp.
    //   2. Independently stored fallback credentials in EEPROM/flash.
    //   3. One operator-provisioned fallback through the serial monitor.
    // A successful configured connection must not overwrite the saved
    // fallback; otherwise both choices become identical after the first boot.
    APP_DEBUG_PRINTLN("WiFi priority: configured firmware -> saved flash fallback -> operator fallback.");

    if (connectWifiWithCredentials("configured firmware", kWifiSsid, kWifiPassword))
    {
        APP_DEBUG_PRINTLN("Configured WiFi connected; saved flash fallback remains unchanged.");
        return recordNetworkConnectionSuccess();
    }

    APP_DEBUG_PRINTLN("Configured firmware WiFi is not connected.");

    StoredWifiCredentials savedCredentials = {};
    if (loadSavedWifiCredentials(savedCredentials))
    {
        APP_DEBUG_PRINTLN("Fallback WiFi credentials found in flash.");
        if (wifiCredentialsMatch(savedCredentials, kWifiSsid, kWifiPassword))
        {
            APP_DEBUG_PRINTLN("Saved fallback matches configured WiFi; duplicate attempt skipped.");
        }
        else if (connectWifiWithCredentials(
                     "saved flash fallback",
                     savedCredentials.ssid,
                     savedCredentials.password))
        {
            return recordNetworkConnectionSuccess();
        }
        else
        {
            APP_LOG_ERROR("Saved flash fallback WiFi failed.");
        }
    }
    else
    {
        APP_DEBUG_PRINTLN("No valid fallback WiFi credentials found in flash.");
    }

    char userSsid[kWifiSsidMaxLength + 1] = {};
    char userPassword[kWifiPasswordMaxLength + 1] = {};
    if (g_wifiProvisioningPromptUsed)
    {
        APP_DEBUG_PRINTLN("WiFi provisioning prompt already used this boot; automatic retry will continue later.");
        return false; // No new physical network attempt in this branch.
    }

    g_wifiProvisioningPromptUsed = true;
    if (!promptForWifiCredentials(userSsid, sizeof(userSsid), userPassword, sizeof(userPassword)))
    {
        APP_DEBUG_PRINTLN("WiFi credential entry cancelled or timed out.");
        return false; // Operator timeout/cancellation is not a failed modem join.
    }

    if (connectWifiWithCredentials("operator fallback", userSsid, userPassword))
    {
        saveConnectedWifiAsFallback("operator fallback", userSsid, userPassword);
        return recordNetworkConnectionSuccess();
    }

    APP_LOG_ERROR("WiFi connection failed after configured, saved fallback, and operator credentials.");
    return false; // Credential attempts already counted their individual failures.

#else
    #error "No network module defined!"
#endif
}

void setup_Init()
{
    AppRuntimeState& state = appState();

    APP_DEBUG_BEGIN(115200);
    APP_LOG_INFO("boot role=SENSOR node=%u topics=%s debug=enabled raw_frames=%u command_ack=%u",
        AppConfig::kNodeId, kMqttCompanyTopicPrefix, APP_DEBUG_RAW_FRAMES, APP_ENABLE_COMMAND_ACK_REPLIES);
    watchdogDelay(1000);
    reportHardwareWatchdogStatus();
    serviceHardwareWatchdog(WatchdogStage::Setup);

    ///////////////////////////////////////////////////////////////////////////
    ///////////////////////////////////////////////////////////////////////////
    APP_DEBUG_PRINTLN("===============      Setup Initialization     ================");
    APP_DEBUG_PRINTLN("==============================================================");
    APP_DEBUG_PRINTLN("\n=========== EgSA IOT Water Monitoring project  ============="); //STM32 + GSM/WiFi + MQTT + Protobuf

    initializeValveController();
    refreshEnabledSensorSummary();
    initializeBatteryMonitor();
    refreshBatteryVoltage();
    APP_DEBUG_PRINT("Battery voltage: ");
    APP_DEBUG_PRINT(state.batteryVoltage, 2);
    APP_DEBUG_PRINTLN(" V");
    serviceHardwareWatchdog(WatchdogStage::Setup);

    initializeRtc();
    if (!isRtcTimeSet())
    {
        setRtcEpoch(AppConfig::kDefaultRtcEpoch);
        APP_DEBUG_PRINTLN("RTC initial time set to 2024-01-01 00:00:00");
    }
    else
    {
        printRtcDateTime();
    }
    serviceHardwareWatchdog(WatchdogStage::Setup);

    ///////////////////////////////////////////////////////////////////////////
    ///////////////////////////////////////////////////////////////////////////
    #if APP_HAS_LORA
    initializeLoraLink();
    serviceHardwareWatchdog(WatchdogStage::Setup);
    #endif

    #if APP_HAS_IP_UPLINK
    initializeMqttTransport();
    serviceHardwareWatchdog();

    if (!connectNetwork())
    {
        APP_LOG_ERROR("Network initialization failed, entering safe mode.");
    }

    initializeMqttClient();
    serviceHardwareWatchdog();
    #endif

    ///////////////////////////////////////////////////////////////////////////
    ///////////////////////////////////////////////////////////////////////////
    
    APP_DEBUG_PRINTLN("==============================================================");
    APP_DEBUG_PRINTLN("=== RS485 sensors: TUF / Supmea / HNDA / Sondas =============");
    APP_DEBUG_PRINTLN("==============================================================");
    APP_DEBUG_PRINT("TUF polling: ");
    APP_DEBUG_PRINTLN(AppConfig::kEnableTufSensor ? "ENABLED" : "DISABLED");
    if (AppConfig::kEnableTufSensor) {
        APP_DEBUG_PRINT("  Modbus address: ");
        APP_DEBUG_PRINTLN(AppConfig::kTufModbusAddress);
    }
    APP_DEBUG_PRINT("HNDA polling: ");
    APP_DEBUG_PRINTLN(AppConfig::kEnableHndaSensor ? "ENABLED" : "DISABLED");
    if (AppConfig::kEnableHndaSensor) {
        APP_DEBUG_PRINT("  Modbus address: ");
        APP_DEBUG_PRINTLN(AppConfig::kHndaModbusAddress);
    }
    APP_DEBUG_PRINT("Supmea polling: ");
    APP_DEBUG_PRINTLN(AppConfig::kEnableSupmeaSensor ? "ENABLED" : "DISABLED");
    if (AppConfig::kEnableSupmeaSensor) {
        APP_DEBUG_PRINT("  Modbus address: ");
        APP_DEBUG_PRINTLN(AppConfig::kSupmeaSensorModbusAddress);
    }
    APP_DEBUG_PRINT("Sondas polling: ");
    APP_DEBUG_PRINTLN(AppConfig::kEnableSondasSensor ? "ENABLED" : "DISABLED");
    if (AppConfig::kEnableSondasSensor) {
        APP_DEBUG_PRINT("  Modbus address: ");
        APP_DEBUG_PRINTLN(AppConfig::kSondasModbusAddress);
    }

    if (AppConfig::kEnableTufSensor ||
        AppConfig::kEnableSupmeaSensor ||
        AppConfig::kEnableHndaSensor ||
        AppConfig::kEnableSondasSensor)
    {
        initializeRs485Bus();
    }
    initializeConfiguredFlowMeter();
    serviceHardwareWatchdog();

    if (AppConfig::kEnableHndaSensor)
    {
        initializeHndaSensor();
        serviceHardwareWatchdog();
    }

    if (AppConfig::kEnableSondasSensor)
    {
        initializeSondasSensor();
        serviceHardwareWatchdog();
    }


    state.lastReadMs = millis();
    state.lastSendMs = millis();


}
