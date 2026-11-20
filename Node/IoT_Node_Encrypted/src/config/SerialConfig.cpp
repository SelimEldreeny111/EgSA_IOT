/** @file SerialConfig.cpp @brief Guided local editing with a single save and software reset. */
#include "SerialConfig.h"

#if APP_ENABLE_SERIAL_CONFIG
#include "RuntimeConfig.h"
#include "../platform/Watchdog.h"
#include <string.h>

extern HardwareSerial SerialMon;

namespace SerialConfig {
namespace {
using RuntimeConfig::Settings;
constexpr uint32_t kBootWindowMs = 2500U;
constexpr uint32_t kIdleTimeoutMs = 180000U;
constexpr size_t kInputBytesPerPass = 96U;
constexpr bool kGateway = APP_ROLE == APP_ROLE_LORA_GATEWAY;
#if defined(USE_ESP8266)
constexpr bool kWifi = APP_HAS_IP_UPLINK;
constexpr bool kSim = false;
#else
constexpr bool kWifi = false;
constexpr bool kSim = APP_HAS_IP_UPLINK;
#endif

enum Field : uint8_t {
    Menu, Node, Company, Region, Sample, Transmit, Power, Sleep, Tuf, Supmea, Hnda,
    Sondas, Ack, Retention, Network, Broker, Port, WifiSsid, WifiPassword,
    Gateway, GatewayWor, Heartbeat, HeartbeatPeriod, SimApn
};

const char* const labels[] = {
    "menu", "Node ID", "Company", "Region", "Sampling interval (s)",
    "Transmission interval (s)", "Power profile", "Timed sleep interval (s)",
    "TUF", "Supmea", "HNDA", "Sondas", "Command ACK", "Flash retention (s)",
    "LoRa network ID", "MQTT broker", "MQTT port", "Wi-Fi SSID", "Wi-Fi password",
    "Gateway ID", "Wake-on-Radio transmit", "Gateway heartbeat", "Heartbeat interval (s)", "SIM APN"
};

Settings draft{};
Field pending = Menu;
char input[66]{};
char proposedSsid[33]{};
size_t length = 0;
bool overflow = false;
bool skipLineFeed = false;
bool open = false;
uint32_t lastInputMs = 0;

bool available(Field field)
{
    switch (field) {
    case Node: case Sample: case Transmit: case Power: case Tuf: case Supmea:
    case Hnda: case Sondas: case Ack: return APP_HAS_SENSORS;
    case Sleep: return RuntimeConfig::supportsPowerMode(APP_COMPONENT_MODE_POWER_DOWN);
    case Retention: return APP_HAS_SENSORS && APP_ENABLE_SPI_FLASH;
    case Network: return APP_HAS_LORA;
    case Broker: case Port: return APP_HAS_IP_UPLINK;
    case WifiSsid: case WifiPassword: return kWifi;
    case SimApn: return kSim;
    case Gateway: case GatewayWor: case Heartbeat: case HeartbeatPeriod: return kGateway;
    default: return true;
    }
}

void showValue(Field field)
{
    switch (field) {
    case Node: if (APP_HAS_SENSORS) { SerialMon.print(draft.nodeId); } break;
    case Company: SerialMon.print(draft.company); break;
    case Region: SerialMon.print(draft.region); break;
    case Sample: SerialMon.print(draft.sampleSeconds); break;
    case Transmit: SerialMon.print(draft.transmitSeconds); break;
    case Power: SerialMon.print(RuntimeConfig::powerModeName(draft.powerMode)); break;
    case Sleep: SerialMon.print(draft.sleepSeconds); break;
    case Tuf: case Supmea: case Hnda: case Sondas: {
        const auto& sensor = draft.sensors[field - Tuf];
        SerialMon.print(sensor.enabled ? "on" : "off");
        SerialMon.print(" / address ");
        SerialMon.print(sensor.address);
        break;
    }
    case Ack: SerialMon.print(draft.commandReplies ? "on" : "off"); break;
    case Retention: SerialMon.print(draft.retentionSeconds); break;
    case Network: if (APP_HAS_LORA) { SerialMon.print("0x"); SerialMon.print(draft.networkId, HEX); } break;
    case Broker: if (APP_HAS_IP_UPLINK) { SerialMon.print(draft.broker); } break;
    case Port: if (APP_HAS_IP_UPLINK) { SerialMon.print(draft.brokerPort); } break;
    case WifiSsid: if (kWifi) { SerialMon.print(draft.ssid[0] ? draft.ssid : "(firmware network)"); } break;
    case Gateway: if (kGateway) { SerialMon.print(draft.gatewayId); } break;
    case GatewayWor: if (kGateway) { SerialMon.print(draft.gatewayWor ? "on" : "off"); } break;
    case Heartbeat: if (kGateway) { SerialMon.print(draft.gatewayHeartbeat ? "on" : "off"); } break;
    case HeartbeatPeriod: if (kGateway) { SerialMon.print(draft.heartbeatSeconds); } break;
    case SimApn: if (kSim) { SerialMon.print(draft.apn[0] ? draft.apn : "(firmware APN)"); } break;
    default: break;
    }
}

void showMenu()
{
    SerialMon.println();
    SerialMon.print("WIOT configuration - ");
    SerialMon.println(APP_ROLE == APP_ROLE_LORA_GATEWAY ? "LoRa gateway" :
        (APP_HAS_LORA ? "LoRa sensor node" : "Direct MQTT sensor node"));
    for (unsigned number = Node; number <= SimApn; ++number) {
        const auto field = static_cast<Field>(number);
        if (field == WifiPassword || !available(field)) continue;
        SerialMon.print("  "); SerialMon.print(number); SerialMon.print(". ");
        SerialMon.print(labels[number]); SerialMon.print(" = ");
        showValue(field); SerialMon.println();
    }
    SerialMon.println("Enter an option number, show, defaults, save, or cancel.");
    SerialMon.print("config> ");
}

bool readNumber(const char* text, uint32_t maximum, uint32_t& result, bool hexAllowed = false)
{
    unsigned base = 10;
    if (hexAllowed && text[0] == '0' && (text[1] == 'x' || text[1] == 'X')) {
        base = 16;
        text += 2;
    }
    if (!*text) return false;
    uint32_t number = 0;
    for (; *text; ++text) {
        unsigned digit;
        if (*text >= '0' && *text <= '9') digit = *text - '0';
        else if (*text >= 'a' && *text <= 'f') digit = *text - 'a' + 10;
        else if (*text >= 'A' && *text <= 'F') digit = *text - 'A' + 10;
        else return false;
        if (digit >= base || digit > maximum || number > (maximum - digit) / base) return false;
        number = number * base + digit;
    }
    result = number;
    return true;
}

template<size_t Size> bool readText(char (&value)[Size], const char* text)
{
    if (strlen(text) >= Size) return false;
    memset(value, 0, Size);
    strcpy(value, text);
    return true;
}

bool edit(Field field, const char* value)
{
    uint32_t n = 0;
    switch (field) {
    case Node:
        if (!APP_HAS_SENSORS || !readNumber(value, 65535U, n) || !n) return false;
        draft.nodeId = n;
        return true;
    case Gateway:
        if (!kGateway || !readNumber(value, 65535U, n) || !n) return false;
        draft.gatewayId = n;
        return true;
    case Network:
        if (!APP_HAS_LORA || !readNumber(value, 65535U, n, true) || !n) return false;
        draft.networkId = n;
        return true;
    case Port:
        if (!APP_HAS_IP_UPLINK || !readNumber(value, 65535U, n) || !n) return false;
        draft.brokerPort = n;
        return true;
    case Company:
        return MqttTopicRouting::validSegment(value) && readText(draft.company, value);
    case Region:
        return MqttTopicRouting::validSegment(value) && readText(draft.region, value);
    case Broker: case SimApn: {
        if (!APP_HAS_IP_UPLINK) return false;
        constexpr char kHostChars[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789.-";
        if (strspn(value, kHostChars) != strlen(value)) return false;
        return field == Broker ? *value && readText(draft.broker, value) : readText(draft.apn, value);
    }
    case Sample: case Transmit:
        if (!readNumber(value, RuntimeConfig::kMaximumRateSeconds, n) ||
            n < AppConfig::kMinimumRateSeconds) return false;
        (field == Sample ? draft.sampleSeconds : draft.transmitSeconds) = n;
        return true;
    case Power:
        if (!readNumber(value, APP_COMPONENT_MODE_QUEUED, n) ||
            !RuntimeConfig::supportsPowerMode(n)) return false;
        draft.powerMode = n;
        return true;
    case Sleep:
        if (!readNumber(value, AppConfig::kPowerMaximumSleepSeconds, n) || n < 5U) return false;
        draft.sleepSeconds = n;
        return true;
    case Tuf: case Supmea: case Hnda: case Sondas: {
        auto& sensor = draft.sensors[field - Tuf];
        if (!strcmp(value, "off")) { sensor.enabled = 0; return true; }
        if (!readNumber(value, 247U, n) || !n) return false;
        sensor = {1U, static_cast<uint8_t>(n)};
        return true;
    }
    case Ack: case GatewayWor: case Heartbeat:
        if (!readNumber(value, 1U, n)) return false;
        if (field == Ack) draft.commandReplies = n;
        else if (field == GatewayWor) draft.gatewayWor = n;
        else draft.gatewayHeartbeat = n;
        return true;
    case Retention:
        return readNumber(value, UINT32_MAX, draft.retentionSeconds);
    case HeartbeatPeriod:
        if (!kGateway || !readNumber(value, 86400U, n) || n < 10U) return false;
        draft.heartbeatSeconds = n;
        return true;
    case WifiSsid:
        if (!kWifi || !readText(proposedSsid, value)) return false;
        if (!proposedSsid[0]) {
            memset(draft.ssid, 0, sizeof(draft.ssid));
            memset(draft.password, 0, sizeof(draft.password));
        }
        return true;
    case WifiPassword:
        if (!kWifi || !readText(draft.password, value)) return false;
        return readText(draft.ssid, proposedSsid);
    default: return false;
    }
}

void prompt(Field field)
{
    SerialMon.print(labels[field]);
    switch (field) {
    case Power:
        SerialMon.println(" choices");
        for (unsigned mode = 0; mode <= APP_COMPONENT_MODE_QUEUED; ++mode) {
            if (!RuntimeConfig::supportsPowerMode(mode)) continue;
            SerialMon.print("  "); SerialMon.print(mode); SerialMon.print(" = ");
            SerialMon.println(RuntimeConfig::powerModeName(mode));
        }
        break;
    case Tuf: case Supmea: case Hnda: case Sondas: SerialMon.println(" (1..247 enables, 'off' disables)"); break;
    case Ack: case GatewayWor: case Heartbeat: SerialMon.println(" (0 = off, 1 = on)"); break;
    case Network: SerialMon.println(" (1..65535 or 0x0001..0xFFFF)"); break;
    case WifiSsid: if (kWifi) SerialMon.println(" (blank selects firmware network)"); break;
    case WifiPassword: if (kWifi) SerialMon.println(" (blank for open network, input is hidden)"); break;
    case Retention: SerialMon.println(" (0 = manual clear only)"); break;
    case SimApn: if (kSim) SerialMon.println(" (blank selects firmware APN)"); break;
    default: SerialMon.println(); break;
    }
    SerialMon.println("Send Esc to return to the menu.");
    SerialMon.print("value> ");
}

void closeMenu()
{
    memset(&draft, 0, sizeof(draft));
    memset(proposedSsid, 0, sizeof(proposedSsid));
    pending = Menu;
    open = false;
}

bool configWord(const char* value)
{
    const char* key = "config";
    for (; *key; ++key, ++value) {
        char c = *value;
        if (c >= 'A' && c <= 'Z') c += 'a' - 'A';
        if (c != *key) return false;
    }
    return !*value;
}

void line(char* value)
{
    if (!open) {
        if (!configWord(value)) return;
        draft = RuntimeConfig::active();
        open = true;
        showMenu();
        return;
    }

    if (pending != Menu) {
        const Field field = pending;
        if (!edit(field, value)) {
            SerialMon.println("Invalid value. Try again or reset to discard.");
            prompt(field);
            return;
        }
        if (kWifi && field == WifiSsid && proposedSsid[0]) {
            pending = WifiPassword;
            prompt(pending);
            return;
        }
        pending = Menu;
        SerialMon.println("Change staged.");
        showMenu();
        return;
    }

    uint32_t number;
    if (!strcmp(value, "show") || !strcmp(value, "menu")) {
        showMenu();
    } else if (!strcmp(value, "defaults")) {
        draft = RuntimeConfig::defaults();
        SerialMon.println("Firmware defaults staged. Enter save to apply.");
        showMenu();
    } else if (!strcmp(value, "cancel")) {
        closeMenu();
        SerialMon.println("Configuration discarded.");
    } else if (!strcmp(value, "save")) {
        if (const char* error = RuntimeConfig::validate(draft)) {
            SerialMon.println(error);
        } else {
            serviceHardwareWatchdog(WatchdogStage::OperatorInput);
            if (RuntimeConfig::save(draft)) {
                SerialMon.println("Configuration saved and verified. Restarting...");
                SerialMon.flush();
                NVIC_SystemReset();
            }
            SerialMon.println("Flash verification failed. Settings were not applied.");
        }
        SerialMon.print("config> ");
    } else if (readNumber(value, SimApn, number) && number != Menu &&
               number != WifiPassword && available(static_cast<Field>(number))) {
        pending = static_cast<Field>(number);
        prompt(pending);
    } else {
        SerialMon.println("Choose an option from the menu.");
        SerialMon.print("config> ");
    }
}
}

bool service()
{
    for (size_t count = 0; count < kInputBytesPerPass && SerialMon.available() > 0; ++count) {
        const int received = SerialMon.read();
        if (received < 0) break;
        const char c = static_cast<char>(received);
        lastInputMs = millis();
        if (c == '\n' && skipLineFeed) {
            skipLineFeed = false;
            continue;
        }
        skipLineFeed = c == '\r';
        if (c == 27 && open) {
            if (kWifi) memset(proposedSsid, 0, sizeof(proposedSsid));
            pending = Menu;
            memset(input, 0, sizeof(input));
            length = 0;
            overflow = false;
            showMenu();
        } else if (c == '\r' || c == '\n') {
            if (!overflow && (length || pending == WifiSsid || pending == WifiPassword || pending == SimApn)) {
                input[length] = '\0';
                line(input);
            } else if (overflow && open) {
                SerialMon.println("Input too long. Try again.");
                if (pending != Menu) prompt(pending);
                else SerialMon.print("config> ");
            }
            memset(input, 0, sizeof(input));
            length = 0;
            overflow = false;
        } else {
            if (c == '\b' || c == 127) {
                if (length && !overflow) --length;
            } else if (length < sizeof(input) - 1 && c >= ' ') {
                input[length++] = c;
            } else {
                overflow = true;
            }
        }
    }
    if (open && millis() - lastInputMs >= kIdleTimeoutMs) {
        closeMenu();
        SerialMon.println("Configuration timed out. Changes discarded.");
    }
    return open;
}

void begin(bool offerBootWindow)
{
    SerialMon.begin(115200);
    if (!offerBootWindow) return;
    SerialMon.println("WIOT serial configuration - send config and Enter.");
    const uint32_t started = millis();
    while (service() || millis() - started < kBootWindowMs) {
        serviceHardwareWatchdog(WatchdogStage::OperatorInput);
        delay(5);
    }
}
}
#endif
