#include "../../src/config/RuntimeConfig.h"
#include "../../src/config/SerialConfig.h"
#include "../../src/platform/Watchdog.h"
#include <EEPROM.h>
#include <array>
#include <cassert>
#include <cstring>
#include <iostream>

HardwareSerial SerialMon;
extern const char kMqttServer[] = "broker.example.org";

namespace {
std::array<uint8_t, E2END + 1> flash{};
std::array<uint8_t, E2END + 1> buffer{};
unsigned commits = 0;
uint32_t now = 0;

bool send(const std::string& bytes)
{
    SerialMon.input.insert(SerialMon.input.end(), bytes.begin(), bytes.end());
    bool open;
    do { open = SerialConfig::service(); } while (SerialMon.available());
    return open;
}
}

void eeprom_buffer_fill() { buffer = flash; }
uint8_t eeprom_buffered_read_byte(uint32_t address) { return buffer.at(address); }
void eeprom_buffered_write_byte(uint32_t address, uint8_t value) { buffer.at(address) = value; }
void eeprom_buffer_flush() { flash = buffer; ++commits; }
uint32_t millis() { return now; }
void delay(uint32_t ms) { now += ms; }
void serviceHardwareWatchdog(WatchdogStage) {}

int main()
{
    flash.fill(0xFF);
    flash[232] = 0x31;
    assert(RuntimeConfig::load() == RuntimeConfig::LoadResult::Defaults);
    const auto original = RuntimeConfig::active();
    const std::string originalTopic = RuntimeConfig::topics().prefix;
    SerialConfig::begin(true);
    assert(SerialMon.baud == 115200 && now >= 2500);

    assert(!send("configuration\n"));
    assert(!send(std::string(80, 'x') + "config\n"));
    assert(send("config\ndefaults\n"));
    assert(!send("cancel\n") && !commits);
    assert(send("config\n2\n"));
    assert(send("\x1B"));
    now += 180000;
    assert(!SerialConfig::service() && !commits);
    assert(send("CoNfIg\r\n"));
#if APP_HAS_SENSORS
    assert(RuntimeConfig::supportsPowerMode(APP_COMPONENT_MODE_REMOTE_WAKE));
    assert(RuntimeConfig::supportsPowerMode(APP_COMPONENT_MODE_LORA_WOR) == bool(APP_HAS_LORA));
    const auto packed = RuntimeConfig::active();
    auto invalid = packed;
    invalid.sensors[0] = {1, 9};
    invalid.sensors[1] = {1, 9};
    assert(!RuntimeConfig::save(invalid) && !commits);
    assert(send("1\r\n65536\r\n"));
    assert(send("7\r\n5\r\n60\r\n"));
    assert(send("4\n120\n5\n240\n6\n2\n"));
    assert(send("8\n1\n9\n1\nsave\n"));
    assert(SerialMon.output.str().find("distinct Modbus addresses") != std::string::npos);
    assert(!commits);
    assert(send("9\n2\n12\n0\n13\n0\n"));
    assert(AppConfig::kNodeId == original.nodeId);
#else
    assert(!RuntimeConfig::supportsPowerMode(APP_COMPONENT_MODE_LORA_WOR));
    assert(send("19\n20\n20\n1\n21\n0\n22\n100\n"));
#endif
#if APP_HAS_IP_UPLINK && defined(USE_ESP8266)
    assert(send("17\r\nLab Unit 2\r\ntest-secret\r\n"));
    assert(SerialMon.output.str().find("test-secret") == std::string::npos);
#endif
#if APP_HAS_IP_UPLINK && defined(USE_SIM800)
    assert(send("23\nlab.apn\n"));
#endif
    assert(send("2\nABCDEFGHIJKLMNOPQRSTUVWX\n3\nabcdefghijklmnopqrstuvwx\n"));
    assert(RuntimeConfig::topics().prefix == originalTopic);
    try {
        send("save\r\n");
        assert(false);
    } catch (const SoftwareReset&) {}
    assert(commits == 1 && flash[232] == 0x31);
    assert(RuntimeConfig::load() == RuntimeConfig::LoadResult::Saved);
    assert(strlen(RuntimeConfig::topics().prefix) == 54);
#if APP_HAS_IP_UPLINK && defined(USE_SIM800)
    assert(!strcmp(RuntimeConfig::active().apn, "lab.apn"));
#endif
#if APP_HAS_SENSORS
    assert(AppConfig::kNodeId == 7 && !AppConfig::kEnableCommandAckReplies);
    assert(RuntimeConfig::active().sampleSeconds == 120 && RuntimeConfig::active().transmitSeconds == 240);
    assert(RuntimeConfig::active().powerMode == APP_COMPONENT_MODE_REMOTE_WAKE);
    assert(RuntimeConfig::active().retentionSeconds == 0 &&
           AppConfig::kSupmeaSensorModbusAddress == 2);
#if APP_HAS_IP_UPLINK
    assert(std::string(RuntimeConfig::topics().command).substr(54) == "/7/cmd");
#endif
#else
    assert(std::string(RuntimeConfig::topics().gatewayCommands).substr(54) == "/+/cmd");
    assert(RuntimeConfig::active().gatewayId == 20 && RuntimeConfig::active().gatewayWor == 1);
    assert(!RuntimeConfig::active().gatewayHeartbeat && RuntimeConfig::active().heartbeatSeconds == 100);
#endif
    assert(RuntimeConfig::save(RuntimeConfig::active()) && commits == 1);
    flash[264] ^= 1;
    assert(RuntimeConfig::load() == RuntimeConfig::LoadResult::Invalid);
    assert(RuntimeConfig::topics().prefix == originalTopic);
    assert(AppConfig::kNodeId == original.nodeId);
    std::cout << "PASS: console edits, validation, reset, persistence, routing and CRC fallback\n";
}
