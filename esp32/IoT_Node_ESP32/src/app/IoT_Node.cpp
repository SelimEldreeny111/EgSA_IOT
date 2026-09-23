/* ================== INCLUDES ================== */
#include "../config/AppConfig.h"
#include "IoT_Node.h"
#include "../devices/BatteryMonitor.h"
#include "../devices/HndaSensor.h"
#include "../devices/SondasSensor.h"
#include "../devices/SupmeaSensor.h"
#include "../devices/TufSensor.h"
#include "../platform/SerialPorts.h"
#include "../platform/Watchdog.h"
#include "../radio/LoraLink.h"

#include <EEPROM.h>
#include <string.h>

/* =================================== SERIAL ======================================= */
extern HardwareSerial& SerialMon;    // Debug
extern HardwareSerial& SerialAT;     // SIM800 or Wi-Fi
extern HardwareSerial& SerialRs485;  // Shared RS485 sensor bus

#define WIFI_RETRY_INTERVAL 5000
#define WIFI_MAX_RETRIES    2

#define GPRS_RETRY_INTERVAL 5000
#define GPRS_MAX_RETRIES    5

namespace
{
uint8_t g_consecutiveNetworkFailures = 0U;

bool recordNetworkConnectionSuccess()
{
    g_consecutiveNetworkFailures = 0U;
    serviceHardwareWatchdog();
    return true;
}

bool recordNetworkConnectionFailure()
{
    if (g_consecutiveNetworkFailures < UINT8_MAX)
    {
        ++g_consecutiveNetworkFailures;
    }

    SerialMon.print("Complete network connection failures: ");
    SerialMon.print(g_consecutiveNetworkFailures);
    SerialMon.print('/');
    SerialMon.println(AppConfig::kNetworkFailuresBeforeReset);

    if (AppConfig::kNetworkFailuresBeforeReset > 0U &&
        g_consecutiveNetworkFailures >= AppConfig::kNetworkFailuresBeforeReset)
    {
        forceHardwareWatchdogReset(
            "GSM/WiFi recovery failed repeatedly");
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

struct StoredWifiCredentials
{
    uint32_t magic;
    uint8_t version;
    char ssid[kWifiSsidMaxLength + 1];
    char password[kWifiPasswordMaxLength + 1];
    uint32_t checksum;
};

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

void beginCredentialStore()
{
#if defined(ESP8266) || defined(ESP32)
    EEPROM.begin(sizeof(StoredWifiCredentials));
#endif
}

void commitCredentialStore()
{
#if defined(ESP8266) || defined(ESP32)
    EEPROM.commit();
#endif
}

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

bool wifiCredentialsMatch(const StoredWifiCredentials& credentials, const char* ssid, const char* password)
{
    return strcmp(credentials.ssid, ssid) == 0 && strcmp(credentials.password, password) == 0;
}

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

bool connectWifiWithCredentials(const char* source, const char* ssid, const char* password)
{
    for (int retryCount = 0; retryCount < WIFI_MAX_RETRIES; ++retryCount)
    {
        serviceHardwareWatchdog();
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

        SerialMon.println("WiFi failed, retrying...");
        modem.restart();
        serviceHardwareWatchdog();
        watchdogDelay(WIFI_RETRY_INTERVAL);
    }

    return false;
}

bool rememberConnectedWifi(const char* source, const char* ssid, const char* password)
{
    if (saveWifiCredentials(ssid, password))
    {
        SerialMon.print("Remembered ");
        SerialMon.print(source);
        SerialMon.println(" WiFi as the last successful network.");
        return true;
    }

    SerialMon.print("Connected to ");
    SerialMon.print(source);
    SerialMon.println(" WiFi, but could not save it as the last network.");
    return false;
}

bool readSerialLine(char* buffer, size_t bufferSize, uint32_t timeoutMs, bool allowEmpty)
{
    if (buffer == nullptr || bufferSize == 0)
    {
        return false;
    }

    size_t index = 0;
    const uint32_t startMs = millis();
    buffer[0] = '\0';

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

bool promptForWifiCredentials(char* ssid, size_t ssidSize, char* password, size_t passwordSize)
{
    SerialMon.println();
    SerialMon.println("Default WiFi is not connected.");
    SerialMon.println("Enter fallback WiFi credentials in the serial monitor.");
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
        serviceHardwareWatchdog();
        SerialMon.println("Connecting to GSM network.......");
        const bool networkReady = modem.waitForNetwork(10000);
        serviceHardwareWatchdog();
        if (!networkReady)
        {
            SerialMon.println("Network FAILED, retrying......");
            retryCount++;
            watchdogDelay(GPRS_RETRY_INTERVAL);
            continue;
        }

        SerialMon.println("Network connected, connecting GPRS...");
        const bool gprsReady =
            modem.gprsConnect(kApn, kNetworkUser, kNetworkPassword);
        serviceHardwareWatchdog();
        if (!gprsReady)
        {
            SerialMon.println("GPRS FAILED, retrying...");
            retryCount++;
            watchdogDelay(GPRS_RETRY_INTERVAL);
            continue;
        }

        SerialMon.println("GPRS Connected");
        return recordNetworkConnectionSuccess();
    }

    SerialMon.println("GPRS connection failed after retries!");
    return recordNetworkConnectionFailure();

#elif defined(USE_ESP8266)
    StoredWifiCredentials savedCredentials = {};
    if (loadSavedWifiCredentials(savedCredentials))
    {
        SerialMon.println("Last successful WiFi credentials found in flash.");
        if (connectWifiWithCredentials("last saved", savedCredentials.ssid, savedCredentials.password))
        {
            rememberConnectedWifi("last saved", savedCredentials.ssid, savedCredentials.password);
            return recordNetworkConnectionSuccess();
        }

        SerialMon.println("Last saved WiFi credentials failed.");
    }
    else
    {
        SerialMon.println("No last successful WiFi credentials found in flash.");
    }

    if (connectWifiWithCredentials("default", kWifiSsid, kWifiPassword))
    {
        rememberConnectedWifi("default", kWifiSsid, kWifiPassword);
        return recordNetworkConnectionSuccess();
    }

    SerialMon.println("Default WiFi is not connected.");

    char userSsid[kWifiSsidMaxLength + 1] = {};
    char userPassword[kWifiPasswordMaxLength + 1] = {};
    if (g_wifiProvisioningPromptUsed)
    {
        SerialMon.println("WiFi provisioning prompt already used this boot; automatic retry will continue later.");
        return recordNetworkConnectionFailure();
    }

    g_wifiProvisioningPromptUsed = true;
    if (!promptForWifiCredentials(userSsid, sizeof(userSsid), userPassword, sizeof(userPassword)))
    {
        SerialMon.println("WiFi credential entry cancelled or timed out.");
        return recordNetworkConnectionFailure();
    }

    if (connectWifiWithCredentials("operator fallback", userSsid, userPassword))
    {
        rememberConnectedWifi("operator fallback", userSsid, userPassword);
        return recordNetworkConnectionSuccess();
    }

    SerialMon.println("WiFi connection failed after default, saved, and operator credentials.");
    return recordNetworkConnectionFailure();

#else
    #error "No network module defined!"
#endif
}

void setup_Init()
{
    AppRuntimeState& state = appState();

    beginDebugSerial(115200);
    watchdogDelay(1000);
    reportHardwareWatchdogStatus();
    serviceHardwareWatchdog();

    ///////////////////////////////////////////////////////////////////////////
    ///////////////////////////////////////////////////////////////////////////
    SerialMon.println("===============      Setup Initialization     ================");
    SerialMon.println("==============================================================");
    SerialMon.println("\n=========== EgSA IOT Water Monitoring project  ============="); // ESP32 + GSM/WiFi + MQTT + Protobuf

    state.nodeStatus = 0;
    if (AppConfig::kEnableOpenCloseNodeOutput)
    {
        pinMode(AppConfig::kOpenCloseNodeGpio, OUTPUT);
        digitalWrite(
            AppConfig::kOpenCloseNodeGpio,
            AppConfig::kOpenCloseNodeActiveLow ? HIGH : LOW);
    }
    else
    {
        SerialMon.println("OPEN_CLOSE output disabled: configured GPIO conflicts with AS32 AUX.");
    }
    refreshEnabledSensorSummary();
    initializeBatteryMonitor();
    refreshBatteryVoltage();
    SerialMon.print("Battery voltage: ");
    SerialMon.print(state.batteryVoltage, 2);
    SerialMon.println(" V");
    serviceHardwareWatchdog();

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
    serviceHardwareWatchdog();

    ///////////////////////////////////////////////////////////////////////////
    ///////////////////////////////////////////////////////////////////////////
    #if APP_HAS_LORA
    initializeLoraLink();
    serviceHardwareWatchdog();
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

    beginRs485Serial(AppConfig::kRs485BaudRate, SERIAL_8N1);
    delay(50);
    pinMode(AppConfig::kRs485TxEnablePin, OUTPUT);
    digitalWrite(AppConfig::kRs485TxEnablePin, LOW);
    serviceHardwareWatchdog();

    if (AppConfig::kEnableTufSensor)
    {
        initializeTufSensor();
        serviceHardwareWatchdog();
    }

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

    if (AppConfig::kEnableSupmeaSensorTest)
    {
        initializeSupmeaSensor();
        serviceHardwareWatchdog();
    }
    
    state.lastReadMs = millis();
    state.lastSendMs = millis();


}
