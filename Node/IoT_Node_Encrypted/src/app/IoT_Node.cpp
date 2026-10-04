/** @file IoT_Node.cpp @brief Sensor-node startup and configuration initialization. */
/* ================== INCLUDES ================== */
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
        SerialMon.println("[NETWORK] Connected; retry recovery cleared (stage 1, 0 failures)");
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
    SerialMon.print("[NETWORK] Failed attempt, stage ");
    SerialMon.print(g_networkRetryPolicy.stage());
    SerialMon.print(": ");
    SerialMon.print(g_networkRetryPolicy.failures() + 1U);
    SerialMon.print('/');
    SerialMon.println(AppConfig::kNetworkRetriesPerStage);
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
        SerialMon.println("WiFi credential storage disabled; using configured credentials for this boot.");
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
        SerialMon.println("WiFi credential flash verification FAILED.");
        return false;
    }

    SerialMon.println("WiFi credentials saved and verified in flash.");
    return true;
}

/** @brief Try one Wi-Fi credential source with bounded retries and watchdog-safe delays. */
bool connectWifiWithCredentials(const char* source, const char* ssid, const char* password)
{
    for (int retryCount = 0; retryCount < WIFI_MAX_RETRIES; ++retryCount)
    {
        serviceHardwareWatchdog(WatchdogStage::WifiJoin);
        SerialMon.print("Connecting to ");
        SerialMon.print(source);
        SerialMon.print(" WiFi SSID: ");
        SerialMon.println(ssid);

        const bool connected = modem.networkConnect(ssid, password);
        // The modem call returned normally. Refresh here so the next bounded
        // retry receives a full watchdog window. A call that never returns is
        // deliberately not refreshed and resets the MCU.
        serviceHardwareWatchdog();
        if (connected)
        {
            SerialMon.print(source);
            SerialMon.println(" WiFi connected");
            return true;
        }

        SerialMon.println("WiFi join failed");
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
        SerialMon.print("Saved ");
        SerialMon.print(source);
        SerialMon.println(" WiFi as the flash fallback network.");
        return true;
    }

    SerialMon.print("Connected to ");
    SerialMon.print(source);
    SerialMon.println(" WiFi, but could not save it as the flash fallback.");
    return false;
}

/** @brief Read a bounded serial-console line while keeping the watchdog alive. */
bool readSerialLine(char* buffer, size_t bufferSize, uint32_t timeoutMs, bool allowEmpty)
{
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
}

/** @brief Prompt for an SSID and optional password after automatic networks fail. */
bool promptForWifiCredentials(char* ssid, size_t ssidSize, char* password, size_t passwordSize)
{
    SerialMon.println();
    SerialMon.println("Configured and saved fallback WiFi networks are not connected.");
    SerialMon.println("Enter new fallback WiFi credentials in the serial monitor.");
    SerialMon.println("Credentials are stored in flash only after a successful connection.");
    SerialMon.print("SSID (max ");
    SerialMon.print(kWifiSsidMaxLength);
    SerialMon.println(" chars):");

    if (!readSerialLine(ssid, ssidSize, kWifiSerialInputTimeoutMs, false))
    {
        SerialMon.println("No SSID entered before timeout.");
        return false;
    }

    if (strlen(ssid) > kWifiSsidMaxLength)
    {
        SerialMon.println("SSID is too long.");
        return false;
    }

    SerialMon.print("Password (max ");
    SerialMon.print(kWifiPasswordMaxLength);
    SerialMon.println(" chars, send blank line for open WiFi):");

    readSerialLine(password, passwordSize, kWifiSerialInputTimeoutMs, true);

    if (strlen(password) > kWifiPasswordMaxLength)
    {
        SerialMon.println("Password is too long.");
        return false;
    }

    return true;
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
        SerialMon.println("Connecting to GSM network.......");
        const bool networkReady = modem.waitForNetwork(10000);
        serviceHardwareWatchdog();
        if (!networkReady)
        {
            SerialMon.println("Network FAILED, retrying......");
            recordNetworkConnectionFailure();
            retryCount++;
            watchdogDelay(GPRS_RETRY_INTERVAL);
            continue;
        }

        SerialMon.println("Network connected, connecting GPRS...");
        serviceHardwareWatchdog(WatchdogStage::GprsAttach);
        const bool gprsReady =
            modem.gprsConnect(kApn, kNetworkUser, kNetworkPassword);
        serviceHardwareWatchdog();
        if (!gprsReady)
        {
            SerialMon.println("GPRS FAILED, retrying...");
            recordNetworkConnectionFailure();
            retryCount++;
            watchdogDelay(GPRS_RETRY_INTERVAL);
            continue;
        }

        SerialMon.println("GPRS Connected");
        return recordNetworkConnectionSuccess();
    }

    SerialMon.println("GPRS connection failed after retries!");
    return false; // Each failed inner attempt was already counted.

#elif defined(USE_ESP8266)
    // Connection priority is intentional:
    //   1. Credentials compiled into AppConfig.cpp.
    //   2. Independently stored fallback credentials in EEPROM/flash.
    //   3. One operator-provisioned fallback through the serial monitor.
    // A successful configured connection must not overwrite the saved
    // fallback; otherwise both choices become identical after the first boot.
    SerialMon.println("WiFi priority: configured firmware -> saved flash fallback -> operator fallback.");

    if (connectWifiWithCredentials("configured firmware", kWifiSsid, kWifiPassword))
    {
        SerialMon.println("Configured WiFi connected; saved flash fallback remains unchanged.");
        return recordNetworkConnectionSuccess();
    }

    SerialMon.println("Configured firmware WiFi is not connected.");

    StoredWifiCredentials savedCredentials = {};
    if (loadSavedWifiCredentials(savedCredentials))
    {
        SerialMon.println("Fallback WiFi credentials found in flash.");
        if (wifiCredentialsMatch(savedCredentials, kWifiSsid, kWifiPassword))
        {
            SerialMon.println("Saved fallback matches configured WiFi; duplicate attempt skipped.");
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
            SerialMon.println("Saved flash fallback WiFi failed.");
        }
    }
    else
    {
        SerialMon.println("No valid fallback WiFi credentials found in flash.");
    }

    char userSsid[kWifiSsidMaxLength + 1] = {};
    char userPassword[kWifiPasswordMaxLength + 1] = {};
    if (g_wifiProvisioningPromptUsed)
    {
        SerialMon.println("WiFi provisioning prompt already used this boot; automatic retry will continue later.");
        return false; // No new physical network attempt in this branch.
    }

    g_wifiProvisioningPromptUsed = true;
    if (!promptForWifiCredentials(userSsid, sizeof(userSsid), userPassword, sizeof(userPassword)))
    {
        SerialMon.println("WiFi credential entry cancelled or timed out.");
        return false; // Operator timeout/cancellation is not a failed modem join.
    }

    if (connectWifiWithCredentials("operator fallback", userSsid, userPassword))
    {
        saveConnectedWifiAsFallback("operator fallback", userSsid, userPassword);
        return recordNetworkConnectionSuccess();
    }

    SerialMon.println("WiFi connection failed after configured, saved fallback, and operator credentials.");
    return false; // Credential attempts already counted their individual failures.

#else
    #error "No network module defined!"
#endif
}

void setup_Init()
{
    AppRuntimeState& state = appState();

    SerialMon.begin(115200);
    watchdogDelay(1000);
    reportHardwareWatchdogStatus();
    serviceHardwareWatchdog(WatchdogStage::Setup);

    ///////////////////////////////////////////////////////////////////////////
    ///////////////////////////////////////////////////////////////////////////
    SerialMon.println("===============      Setup Initialization     ================");
    SerialMon.println("==============================================================");
    SerialMon.println("\n=========== EgSA IOT Water Monitoring project  ============="); //STM32 + GSM/WiFi + MQTT + Protobuf

    initializeValveController();
    refreshEnabledSensorSummary();
    initializeBatteryMonitor();
    refreshBatteryVoltage();
    SerialMon.print("Battery voltage: ");
    SerialMon.print(state.batteryVoltage, 2);
    SerialMon.println(" V");
    serviceHardwareWatchdog(WatchdogStage::Setup);

    initializeRtc();
    if (!isRtcTimeSet())
    {
        setRtcEpoch(AppConfig::kDefaultRtcEpoch);
        SerialMon.println("RTC initial time set to 2024-01-01 00:00:00");
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
        SerialMon.println("Network initialization failed, entering safe mode.");
    }

    initializeMqttClient();
    serviceHardwareWatchdog();
    #endif

    ///////////////////////////////////////////////////////////////////////////
    ///////////////////////////////////////////////////////////////////////////
    
    SerialMon.println("==============================================================");
    SerialMon.println("=== RS485 sensors: TUF / Supmea / HNDA / Sondas =============");
    SerialMon.println("==============================================================");
    SerialMon.print("TUF polling: ");
    SerialMon.println(AppConfig::kEnableTufSensor ? "ENABLED" : "DISABLED");
    if (AppConfig::kEnableTufSensor) {
        SerialMon.print("  Modbus address: ");
        SerialMon.println(AppConfig::kTufModbusAddress);
    }
    SerialMon.print("HNDA polling: ");
    SerialMon.println(AppConfig::kEnableHndaSensor ? "ENABLED" : "DISABLED");
    if (AppConfig::kEnableHndaSensor) {
        SerialMon.print("  Modbus address: ");
        SerialMon.println(AppConfig::kHndaModbusAddress);
    }
    SerialMon.print("Supmea polling: ");
    SerialMon.println(AppConfig::kEnableSupmeaSensor ? "ENABLED" : "DISABLED");
    if (AppConfig::kEnableSupmeaSensor) {
        SerialMon.print("  Modbus address: ");
        SerialMon.println(AppConfig::kSupmeaSensorModbusAddress);
    }
    SerialMon.print("Sondas polling: ");
    SerialMon.println(AppConfig::kEnableSondasSensor ? "ENABLED" : "DISABLED");
    if (AppConfig::kEnableSondasSensor) {
        SerialMon.print("  Modbus address: ");
        SerialMon.println(AppConfig::kSondasModbusAddress);
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
