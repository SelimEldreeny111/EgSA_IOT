#include "MQTT.h"

#include "../config/AppConfig.h"
#include "../app/AppState.h"
#include "PacketCodec.h"
#include "CommandHandler.h"
#include "SensorPayloadMapper.h"
#include "../devices/RTC.h"
#include "../platform/Watchdog.h"
#if APP_ROLE == APP_ROLE_LORA_GATEWAY
#include "../radio/LoraLink.h"
#endif

#include <string.h>

extern HardwareSerial SerialMon;
extern HardwareSerial SerialAT;

TinyGsm modem(SerialAT);
TinyGsmClient gsmClient(modem);

/**
 * BufferedClient: coalesces successive write() calls into a single underlying
 * write() so AT-modem transports (notably ESP-AT on ESP8266) only pay the
 * AT+CIPSEND round-trip once per MQTT packet instead of three times.
 *
 * Why: PubSubClient emits each packet as 3 sequential writes (header byte,
 * remaining-length VLQ, topic+payload). On ESP-AT each underlying write maps
 * to a separate CIPSEND with a multi-second prompt/SEND-OK round-trip; on
 * SIM800 the same firmware path is fast (~70 ms) so the issue is invisible
 * there. Buffering reduces 3 round-trips to 1.
 *
 * The caller MUST invoke flush() at every MQTT packet boundary
 * (after connect / publish / subscribe / loop / disconnect).
 */
namespace {
constexpr size_t kClientWriteBufferSize = AppConfig::kMqttPacketBufferSize;
}

class BufferedClient : public Client
{
public:
  BufferedClient(Client& wrapped) : _wrapped(wrapped), _len(0) {}

  size_t write(uint8_t b) override
  {
    if (_len >= sizeof(_buf)) {
      flushBuffer();
    }
    _buf[_len++] = b;
    return 1;
  }

  size_t write(const uint8_t* buf, size_t size) override
  {
    size_t total = 0;
    while (size > 0) {
      if (_len == sizeof(_buf)) {
        flushBuffer();
      }
      const size_t space = sizeof(_buf) - _len;
      const size_t take = (size < space) ? size : space;
      memcpy(_buf + _len, buf, take);
      _len += take;
      buf += take;
      size -= take;
      total += take;
    }
    return total;
  }

  void flush() override
  {
    flushBuffer();
    _wrapped.flush();
  }

  // Auto-flush before any read so that write→read sequences inside a single
  // PubSubClient call (e.g. connect writes CONNECT then reads CONNACK) don't
  // stall waiting for bytes that are still sitting in the write buffer.
  int available() override { flushBuffer(); return _wrapped.available(); }
  int read() override { flushBuffer(); return _wrapped.read(); }
  int read(uint8_t* buf, size_t size) override { flushBuffer(); return _wrapped.read(buf, size); }
  int peek() override { flushBuffer(); return _wrapped.peek(); }
  uint8_t connected() override { return _wrapped.connected(); }
  operator bool() override { return static_cast<bool>(_wrapped); }
  int connect(IPAddress ip, uint16_t port) override { return _wrapped.connect(ip, port); }
  int connect(const char* host, uint16_t port) override { return _wrapped.connect(host, port); }
  void stop() override { flushBuffer(); _wrapped.stop(); }

private:
  void flushBuffer()
  {
    if (_len == 0) {
      return;
    }
    _wrapped.write(_buf, _len);
    _len = 0;
  }

  Client&  _wrapped;
  uint8_t  _buf[kClientWriteBufferSize];
  size_t   _len;
};

BufferedClient bufferedClient(gsmClient);
PubSubClient   mqtt(bufferedClient);

namespace {
constexpr bool kLogPayloadHex = false;
uint32_t g_lastMqttActivityMs = 0;
uint32_t g_lastReconnectAttemptMs = 0;
uint8_t g_mqttConnectFailureCount = 0;

void logElapsedMs(const char* label, uint32_t elapsedMs)
{
  if (!AppConfig::kEnablePublishTimingLogs) {
    return;
  }

  SerialMon.print(label);
  SerialMon.print(": ");
  SerialMon.print(elapsedMs);
  SerialMon.println(" ms");
}

void logMqttStateDetails(int state)
{
  if (!AppConfig::kEnableVerboseMqttLogs) {
    return;
  }

  switch (state)
  {
    case -4:
      SerialMon.println("  Connection Timeout");
      break;
    case -3:
      SerialMon.println("  Connection Lost");
      break;
    case -2:
      SerialMon.println("  Connect Failed");
      break;
    case -1:
      SerialMon.println("  Disconnected");
      break;
    case 0:
      SerialMon.println("  Connected");
      break;
    case 1:
      SerialMon.println("  Connect Bad Protocol");
      break;
    case 2:
      SerialMon.println("  Connect Bad Client ID");
      break;
    case 3:
      SerialMon.println("  Connect Unavailable");
      break;
    case 4:
      SerialMon.println("  Connect Bad Credentials");
      break;
    case 5:
      SerialMon.println("  Connect Unauthorized");
      break;
    default:
      SerialMon.println("  Unknown State");
      break;
  }
}

#if APP_ROLE == APP_ROLE_LORA_GATEWAY
bool parseGatewayNodeCommandTopic(const char* topic, uint16_t& topicNodeId, bool& isBroadcastTopic)
{
  topicNodeId = 0;
  isBroadcastTopic = false;

  const size_t prefixLength = strlen(kMqttCompanyTopicPrefix);
  if (strncmp(topic, kMqttCompanyTopicPrefix, prefixLength) != 0 || topic[prefixLength] != '/')
  {
    return false;
  }

  const char* nodePart = topic + prefixLength + 1;
  const char* slashAfterNode = strchr(nodePart, '/');
  if (slashAfterNode == nullptr)
  {
    return false;
  }

  const char* suffix = slashAfterNode + 1;
  if (strcmp(suffix, "CMD") != 0)
  {
    return false;
  }

  const size_t nodePartLength = static_cast<size_t>(slashAfterNode - nodePart);
  if (nodePartLength == strlen("BroadCast") &&
      strncmp(nodePart, "BroadCast", nodePartLength) == 0)
  {
    isBroadcastTopic = true;
    return true;
  }

  if (nodePartLength == 0 || nodePartLength > 5)
  {
    return false;
  }

  uint32_t value = 0;
  for (size_t i = 0; i < nodePartLength; ++i)
  {
    if (nodePart[i] < '0' || nodePart[i] > '9')
    {
      return false;
    }
    value = (value * 10UL) + static_cast<uint32_t>(nodePart[i] - '0');
  }

  if (value == 0 || value > 65535UL)
  {
    return false;
  }

  topicNodeId = static_cast<uint16_t>(value);
  return true;
}
#endif
}

void printEspFirmwareVersion()
{
#if defined(USE_ESP8266)
  SerialMon.println("\n--- Querying ESP-AT firmware version (AT+GMR) ---");

  // Drain any pending bytes from the modem UART.
  while (SerialAT.available()) {
    SerialAT.read();
  }

  SerialAT.print("AT+GMR\r\n");

  const uint32_t deadline = millis() + 2000UL;
  bool sawAnything = false;
  while (millis() < deadline) {
    while (SerialAT.available()) {
      const int c = SerialAT.read();
      if (c < 0) {
        break;
      }
      SerialMon.write(static_cast<uint8_t>(c));
      sawAnything = true;
    }
  }

  if (!sawAnything) {
    SerialMon.println("(no response from ESP — check baud / wiring)");
  }
  SerialMon.println("\n--- End AT+GMR ---");
#endif
}

namespace
{
#if defined(USE_ESP8266)
void driveEspEnable(bool enabled)
{
  const bool outputHigh =
      enabled == AppConfig::kEspEnableActiveHigh;
  digitalWrite(AppConfig::kEspEnablePin, outputHigh ? HIGH : LOW);
}

void driveEspReset(bool asserted)
{
  const bool outputHigh =
      asserted != AppConfig::kEspResetActiveLow;
  digitalWrite(AppConfig::kEspResetPin, outputHigh ? HIGH : LOW);
}

void resetAndWakeEsp8266()
{
  // The supplied schematic connects PB7 to ESP_EN and PB8 to ESP_RST.
  // Hold reset while enabling the module, start the UART, then release reset.
  // This also wakes ESP-AT after its indefinite AT+GSLP=0 deep sleep.
  pinMode(AppConfig::kEspEnablePin, OUTPUT);
  pinMode(AppConfig::kEspResetPin, OUTPUT);
  driveEspReset(true);
  driveEspEnable(true);
  watchdogDelay(AppConfig::kEspResetPulseMs);
  SerialAT.begin(MODEM_BAUD);
  driveEspReset(false);
  watchdogDelay(AppConfig::kEspBootDelayMs);
}
#endif
}

void initializeMqttTransport()
{
  serviceHardwareWatchdog(WatchdogStage::ModemInitialization);
#if defined(USE_ESP8266)
  resetAndWakeEsp8266();
#else
  SerialAT.begin(MODEM_BAUD);
  watchdogDelay(3000);
#endif
  printEspFirmwareVersion();
  serviceHardwareWatchdog(WatchdogStage::ModemInitialization);
  // Do not refresh from inside modem.init(). If the AT library becomes stuck,
  // the independent watchdog must be allowed to reset the STM32.
  modem.init();
  serviceHardwareWatchdog();
}

bool prepareMqttTransportForPowerDown(uint32_t timeoutMs)
{
  (void)timeoutMs;
#if defined(USE_ESP8266)
  if (isAsyncPublishBusy())
  {
    return false;
  }

  SerialMon.println("Power: closing MQTT/TCP before ESP8266 deep sleep");
  // PubSubClient::disconnect() flushes its DISCONNECT frame and calls stop()
  // on BufferedClient, which in turn closes the TinyGSM socket. Do not call
  // gsmClient.stop() again: ESP-AT can otherwise wait a second close timeout.
  serviceHardwareWatchdog(WatchdogStage::PowerTransition);
  mqtt.disconnect();
  serviceHardwareWatchdog();

  // TinyGSM maps ESP8266 poweroff() to AT+GSLP=0. ESP-AT remains asleep
  // indefinitely until the schematic's PB8 reset line is pulsed on RTC wake.
  if (!modem.poweroff())
  {
    SerialMon.println("Power: ESP8266 rejected AT+GSLP=0; sleep cancelled");
    return false;
  }

  serviceHardwareWatchdog();
  SerialAT.flush();
  SerialAT.end();
  SerialMon.println("Power: ESP8266 entered deep sleep");
  return true;
#else
  SerialMon.println(
      "Power: SIM800L shutdown is disabled because PWRKEY is not routed to the STM32");
  return false;
#endif
}

void restoreMqttTransportAfterPowerDownAbort()
{
#if defined(USE_ESP8266)
  SerialMon.println("Power: waking ESP8266 after cancelled Standby handoff");
  initializeMqttTransport();
  if (!connectNetwork())
  {
    SerialMon.println("Power: ESP8266 recovery will continue in the normal retry loop");
  }
  initializeMqttClient();
#endif
}

void initializeMqttClient()
{
  mqtt.setClient(bufferedClient);
  mqtt.setServer(kMqttServer, AppConfig::kMqttPort);
  mqtt.setCallback(mqttCallback);
  mqtt.setKeepAlive(AppConfig::kMqttKeepAliveSeconds);
  mqtt.setSocketTimeout(AppConfig::kMqttSocketTimeoutSeconds);
  mqtt.setBufferSize(AppConfig::kMqttPacketBufferSize);
}

void mqttCallback(char* topic, byte* payload, unsigned int length)
{
  g_lastMqttActivityMs = millis();

  if (AppConfig::kEnableVerboseMqttLogs) {
    SerialMon.println("\n=========== MQTT CALLBACK ===========");
    SerialMon.print("Topic: ");
    SerialMon.println(topic);
    SerialMon.print("Payload length: ");
    SerialMon.println(length);
  }

#if APP_ROLE == APP_ROLE_LORA_GATEWAY
  uint16_t topicNodeId = 0;
  bool isBroadcastTopic = false;
  const bool isNodeTopic = parseGatewayNodeCommandTopic(topic, topicNodeId, isBroadcastTopic);
#else
  const bool isNodeTopic = (strcmp(topic, kMqttCommandTopic) == 0);
  const bool isBroadcastTopic = (strcmp(topic, kMqttBroadcastTopic) == 0);
#endif

  if (AppConfig::kEnableVerboseMqttLogs) {
    SerialMon.print("Is Node Topic      : ");
    SerialMon.println(isNodeTopic);
    SerialMon.print("Is Broadcast Topic : ");
    SerialMon.println(isBroadcastTopic);
  }

  if (!isNodeTopic && !isBroadcastTopic)
  {
    SerialMon.println(" Unknown topic - ignoring");
    return;
  }

  CMD_Message cmd = CMD_Message_init_zero;
  if (!decodeEncryptedCommandPayload(payload, length, cmd))
  {
    SerialMon.println(" CMD decode FAILED");
    return;
  }

#if APP_ROLE == APP_ROLE_LORA_GATEWAY
  if (!isBroadcastTopic && cmd.node_id != topicNodeId)
  {
    SerialMon.print(" Gateway rejected CMD: topic node=");
    SerialMon.print(topicNodeId);
    SerialMon.print(" payload node=");
    SerialMon.println(cmd.node_id);
    return;
  }

  const LoraPayloadType loraCommandType =
      isBroadcastTopic ? LoraPayloadType::BroadcastCommand : LoraPayloadType::Command;
  if (sendLoraFrame(loraCommandType, AppConfig::kGatewayNodeId, payload, length))
  {
    SerialMon.print(" Gateway forwarded MQTT CMD to LoRa ");
    SerialMon.println(isBroadcastTopic ? "broadcast" : "node");
  }
  else
  {
    SerialMon.println(" Gateway failed to forward MQTT CMD over LoRa");
  }
  return;
#else
  if (cmd.cmd_id == CMD_GET_TELEMETRY)
  {
    uint8_t telemetryPayload[AppConfig::kCodecBufferSize];
    size_t telemetryPayloadLength = 0;
    if (handleGetTelemetryCommand(&cmd, telemetryPayload, telemetryPayloadLength))
    {
      mqtt.publish(kMqttPublishTopicTlm, telemetryPayload, telemetryPayloadLength);
      bufferedClient.flush();
      if (AppConfig::kEnableVerboseMqttLogs) {
        SerialMon.println(" Telemetry response published");
      }
    }
  }
  else
  {
    handleCommand(cmd, isBroadcastTopic);
  }
#endif
}

bool ensureMqttConnection()
{
  serviceHardwareWatchdog(WatchdogStage::MqttStatus);
  const bool alreadyConnected = mqtt.connected();
  serviceHardwareWatchdog();
  if (alreadyConnected)
  {
    return true;
  }

  const uint32_t now = millis();
  if (now - g_lastReconnectAttemptMs < AppConfig::kMqttReconnectIntervalMs)
  {
    return false;
  }

  g_lastReconnectAttemptMs = now;

#if defined(USE_SIM800)
  const bool networkConnected = modem.isNetworkConnected();
  serviceHardwareWatchdog();
  if (!networkConnected)
  {
    if (AppConfig::kEnableVerboseMqttLogs) {
      SerialMon.println("\n Network link is down - reconnecting transport first");
    }

    if (!connectNetwork())
    {
      SerialMon.println("Network reconnection failed");
      return false;
    }
  }
#endif

  if (AppConfig::kEnableVerboseMqttLogs) {
    SerialMon.println("\n MQTT CONNECTION LOST - Attempting Reconnection");
    SerialMon.print("MQTT State: ");
    SerialMon.println(mqtt.state());
    logMqttStateDetails(mqtt.state());
    SerialMon.print("Connecting to MQTT... ");
  }

  serviceHardwareWatchdog(WatchdogStage::MqttConnect);
  const bool mqttConnected = mqtt.connect(kMqttClientId);
  serviceHardwareWatchdog();
  if (!mqttConnected)
  {
    bufferedClient.flush();
    ++g_mqttConnectFailureCount;
    if (AppConfig::kEnableVerboseMqttLogs) {
      SerialMon.print(" FAILED, mqtt state=");
      logMqttStateDetails(mqtt.state());
      SerialMon.println(" retry scheduled");
    }

#if defined(USE_ESP8266)
    if (g_mqttConnectFailureCount >= 3)
    {
      g_mqttConnectFailureCount = 0;
      SerialMon.println("MQTT failed repeatedly - refreshing ESP8266 WiFi link");
      connectNetwork();
      serviceHardwareWatchdog();
    }
#endif

    return false;
  }
  bufferedClient.flush();

  g_lastMqttActivityMs = millis();
  g_lastReconnectAttemptMs = 0;
  g_mqttConnectFailureCount = 0;

#if APP_ROLE == APP_ROLE_LORA_GATEWAY
  mqtt.subscribe(kMqttGatewayCommandWildcardTopic);
  bufferedClient.flush();
  serviceHardwareWatchdog();
#else
  mqtt.subscribe(kMqttCommandTopic);
  bufferedClient.flush();
  serviceHardwareWatchdog();
  mqtt.subscribe(kMqttBroadcastTopic);
  bufferedClient.flush();
  serviceHardwareWatchdog();
#endif

  if (AppConfig::kEnableVerboseMqttLogs) {
    SerialMon.println("CONNECTED");
#if APP_ROLE == APP_ROLE_LORA_GATEWAY
    SerialMon.print("Subscribed to: ");
    SerialMon.println(kMqttGatewayCommandWildcardTopic);
#else
    SerialMon.print("Subscribed to: ");
    SerialMon.println(kMqttCommandTopic);
    SerialMon.print("Subscribed to: ");
    SerialMon.println(kMqttBroadcastTopic);
#endif
  }

  return true;
}

void mqttLoop()
{
  serviceHardwareWatchdog(WatchdogStage::MqttService);
  mqtt.loop();
  // Flushes any PINGREQ that mqtt.loop() may have emitted, so it leaves
  // in a single AT+CIPSEND instead of sitting in the buffer until the next
  // publish/subscribe call.
  bufferedClient.flush();
  serviceHardwareWatchdog();
}

bool checkNetworkStatus()
{
  SerialMon.println("\n--- Network Status Check ---");

  SerialMon.print("Modem Status: ");
  const bool networkConnected = modem.isNetworkConnected();
  serviceHardwareWatchdog();
  if (networkConnected)
  {
    SerialMon.println(" Network Connected");
  }
  else
  {
    SerialMon.println(" Network Disconnected");
    return false;
  }

  int signalQuality = modem.getSignalQuality();
  serviceHardwareWatchdog();
  SerialMon.print("Signal Quality: ");
  SerialMon.print(signalQuality);
  SerialMon.println(" dBm");

  return true;
}

void publishTelemetry()
{
  const uint32_t publishStartMs = millis();
  if (AppConfig::kEnableVerboseMqttLogs) {
    SerialMon.println("\n================= PUBLISH Status =================");
    SerialMon.println("\n--- Struct filling  ---");
  }

  logElapsedMs("MQTT ready time", millis() - publishStartMs);

  // Note: do NOT call mqtt.connected() here. On ESP-AT 1.x it issues
  // AT+CIPSTATUS which costs ~6 s. The connection state is already kept
  // current by mqtt.loop() in the main loop, and mqtt.publish() returns
  // false on a dead socket — that is our reconnect trigger below.

  AppRuntimeState& state = appState();
  const uint32_t rtcStartMs = millis();
  state.lastTimestamp = getEpochTime();
  refreshBatteryVoltage();
  logElapsedMs("RTC read time (getEpochTime)", millis() - rtcStartMs);

  Status_Message status = Status_Message_init_zero;
  status.node_id = AppConfig::kNodeId;
  status.timestamp = state.lastTimestamp;
  populateSensorPayloadFields(status, state);

  if (AppConfig::kEnableVerboseMqttLogs) {
    SerialMon.println("Status struct filled");
    SerialMon.println("\n--- Encode & Encrypt  ---");
  }

  uint8_t payload[AppConfig::kCodecBufferSize];
  size_t payloadLength = 0;
  const uint32_t encodeStartMs = millis();
  if (!encodeEncryptedMessage(Status_Message_fields, &status, payload, sizeof(payload), payloadLength))
  {
    SerialMon.println(" Telemetry encode FAILED");
    return;
  }
  logElapsedMs("Encode time", millis() - encodeStartMs);

  if (AppConfig::kEnableVerboseMqttLogs) {
    SerialMon.print("Encoded Data : ");
    SerialMon.print(payloadLength);
    SerialMon.println(" Bytes ");
  }

  if (kLogPayloadHex)
  {
    SerialMon.println("Encoded Payload (HEX):");
    for (size_t i = 0; i < payloadLength; i++)
    {
      if (payload[i] < 0x10) SerialMon.print("0");
      SerialMon.print(payload[i], HEX);
      SerialMon.print(" ");
    }
    SerialMon.println();
  }

  if (AppConfig::kEnableVerboseMqttLogs) {
    SerialMon.println("\n--- Publish ---");
  }

  const uint32_t publishCallStartMs = millis();
  serviceHardwareWatchdog(WatchdogStage::MqttPublish);
  const bool published = mqtt.publish(kMqttPublishTopicStatus, payload, payloadLength);
  bufferedClient.flush();
  serviceHardwareWatchdog();
  logElapsedMs("Publish call time", millis() - publishCallStartMs);
  if (!published)
  {
    SerialMon.println(" Telemetry publish FAILED");
    SerialMon.print("MQTT State after publish: ");
    SerialMon.println(mqtt.state());
    SerialMon.print("Network connected: ");
    const bool networkConnected = modem.isNetworkConnected();
    serviceHardwareWatchdog();
    SerialMon.println(networkConnected ? "YES" : "NO");
    // The publish failed: the socket is most likely dead. Trigger a reconnect
    // so the next cycle gets a fresh CONNECT (replaces the old pre-check).
    ensureMqttConnection();
    return;
  }

  g_lastMqttActivityMs = millis();
  if (AppConfig::kEnableVerboseMqttLogs) {
    SerialMon.println("Telemetry Published Successfully");
    logElapsedMs("Total publishTelemetry time", millis() - publishStartMs);
    SerialMon.println("====================================================\n");
  }
}

bool publishMqttPayload(const char* topic, const uint8_t* payload, size_t payloadLength)
{
  if (topic == nullptr || payload == nullptr || payloadLength == 0)
  {
    return false;
  }

  if (!ensureMqttConnection())
  {
    return false;
  }
  serviceHardwareWatchdog();

  serviceHardwareWatchdog(WatchdogStage::MqttPublish);
  const bool published = mqtt.publish(topic, payload, payloadLength);
  bufferedClient.flush();
  serviceHardwareWatchdog();
  if (published)
  {
    g_lastMqttActivityMs = millis();
  }
  return published;
}

/* =============================================================================
 *                    ASYNC (NON-BLOCKING) PUBLISH FSM
 * =============================================================================
 * The synchronous mqtt.publish() blocks the STM32 superloop for ~6.5 s on
 * ESP-AT 1.x because TinyGsmClient::write() waits for "SEND OK". This FSM
 * builds the same encrypted MQTT PUBLISH frame, then drives the AT bus
 * directly with AT+CIPSEND in cooperative steps so loop() returns in <1 ms
 * per iteration. Sensor sampling, RTC reads, and encryption stay responsive.
 *
 * Bus arbitration: while the FSM is non-IDLE, the caller MUST gate
 * ensureMqttConnection()/mqttLoop() on isAsyncPublishBusy() == false.
 * Inbound CMD messages (+IPD) are deferred by the ESP firmware until after
 * SEND OK; they are picked up on the next mqttLoop() call.
 *
 * Mux: assumes mux=0 (only one TinyGsmClient instance is created). If you
 * add a second client, kAsyncMux must be updated.
 * ============================================================================= */

namespace {

// ============= DEBUG SWITCH =============
// Set to true for detailed async FSM tracing (verbose).
constexpr bool kAsyncDeepDebug = false;
// ========================================

enum class PublishStage : uint8_t {
  IDLE,
  ISSUE_CIPSEND,
  WAIT_PROMPT,
  SEND_PAYLOAD,
  WAIT_SEND_OK,
};

constexpr uint8_t  kAsyncMux             = 0;
constexpr size_t   kAsyncFrameCap        = AppConfig::kMqttPacketBufferSize;
constexpr size_t   kAsyncPayloadChunk    = 64;
constexpr uint32_t kAsyncPromptTimeoutMs = 5000;
constexpr uint32_t kAsyncSendOkTimeoutMs = 12000;
constexpr uint32_t kAsyncHeartbeatMs     = 1000;   // print "still waiting" every 1s

PublishStage g_asyncStage         = PublishStage::IDLE;
AsyncPublishResult g_asyncResult  = AsyncPublishResult::None;
uint32_t     g_asyncStageStartMs  = 0;
uint32_t     g_asyncTriggerStartMs = 0;
uint32_t     g_asyncLastHeartbeat = 0;
uint8_t      g_asyncFrame[kAsyncFrameCap];
size_t       g_asyncFrameLen      = 0;
size_t       g_asyncFrameSent     = 0;
char         g_asyncLineBuf[80];
size_t       g_asyncLineLen       = 0;
char         g_asyncPromptBuf[64];     // captures bytes received before '>'
size_t       g_asyncPromptLen     = 0;
uint32_t     g_asyncStepCallCount = 0;  // how many step() calls per publish

void setStage(PublishStage next)
{
  g_asyncStage         = next;
  g_asyncStageStartMs  = millis();
  g_asyncLastHeartbeat = millis();
}

void heartbeat(const char* what)
{
  // Silenced for cleaner logs. Enable if debugging async stalls.
  (void)what;
}

void dumpHex(const char* label, const uint8_t* buf, size_t len)
{
  if (!kAsyncDeepDebug) return;
  SerialMon.print("[async] ");
  SerialMon.print(label);
  SerialMon.print(" (");
  SerialMon.print(len);
  SerialMon.print(" B):");
  for (size_t i = 0; i < len; ++i) {
    if ((i & 0x0F) == 0) SerialMon.println();
    if (buf[i] < 0x10) SerialMon.print('0');
    SerialMon.print(buf[i], HEX);
    SerialMon.print(' ');
  }
  SerialMon.println();
}

void logRxByte(int c)
{
  if (!kAsyncDeepDebug) return;
  // Print printable as char, otherwise as <HH>
  if (c >= 0x20 && c < 0x7F) {
    SerialMon.write(static_cast<uint8_t>(c));
  } else if (c == '\r') {
    SerialMon.print("\\r");
  } else if (c == '\n') {
    SerialMon.print("\\n");
  } else {
    SerialMon.print('<');
    if (c < 0x10) SerialMon.print('0');
    SerialMon.print(c, HEX);
    SerialMon.print('>');
  }
}

// Build a complete MQTT PUBLISH frame (QoS 0, no retain, no dup) into `out`.
// Returns total length, or 0 on error.
size_t buildEncryptedPublishFrame(const char* topic, uint8_t* out, size_t outCap)
{
  if (kAsyncDeepDebug) {
    SerialMon.print("[async] buildFrame: topic='");
    SerialMon.print(topic);
    SerialMon.print("' (len=");
    SerialMon.print(strlen(topic));
    SerialMon.print("), outCap=");
    SerialMon.println(outCap);
  }

  AppRuntimeState& state = appState();
  const uint32_t rtcStart = millis();
  state.lastTimestamp = getEpochTime();
  refreshBatteryVoltage();
  if (kAsyncDeepDebug) {
    SerialMon.print("[async] buildFrame: getEpochTime=");
    SerialMon.print(state.lastTimestamp);
    SerialMon.print(" (");
    SerialMon.print(millis() - rtcStart);
    SerialMon.println(" ms)");
  }

  Status_Message status = Status_Message_init_zero;
  status.node_id            = AppConfig::kNodeId;
  status.timestamp          = state.lastTimestamp;
  populateSensorPayloadFields(status, state);

  SerialMon.println("--- Encode & Encrypt  ---");
  uint8_t payload[AppConfig::kCodecBufferSize];
  size_t  payloadLen = 0;
  const uint32_t encStart = millis();
  if (!encodeEncryptedMessage(Status_Message_fields, &status, payload, sizeof(payload), payloadLen)) {
    SerialMon.println("[async] buildFrame: encodeEncryptedMessage FAILED");
    return 0;
  }
  SerialMon.print("Encode time: ");
  SerialMon.print(millis() - encStart);
  SerialMon.println(" ms");
  SerialMon.print("Encoded Data : ");
  SerialMon.print(payloadLen);
  SerialMon.println(" Bytes ");
  if (kAsyncDeepDebug) {
    dumpHex("encrypted payload", payload, payloadLen);
  }

  const size_t topicLen        = strlen(topic);
  const size_t variableHdrLen  = 2 + topicLen;
  const size_t remainingLen    = variableHdrLen + payloadLen;

  // VLQ-encode remainingLen (1..4 bytes).
  uint8_t vlq[4];
  size_t  vlqLen = 0;
  size_t  r = remainingLen;
  do {
    uint8_t b = static_cast<uint8_t>(r & 0x7F);
    r >>= 7;
    if (r > 0) b |= 0x80;
    vlq[vlqLen++] = b;
  } while (r > 0 && vlqLen < 4);

  const size_t totalLen = 1 + vlqLen + variableHdrLen + payloadLen;
  if (totalLen > outCap) {
    SerialMon.print("[async] buildFrame: OVERFLOW totalLen=");
    SerialMon.print(totalLen);
    SerialMon.print(" > cap=");
    SerialMon.println(outCap);
    return 0;
  }

  SerialMon.println();
  SerialMon.println("--- Publish ---");

  size_t off = 0;
  out[off++] = 0x30;                                              // PUBLISH | QoS0 | retain=0 | dup=0
  memcpy(out + off, vlq, vlqLen); off += vlqLen;                  // remaining length
  out[off++] = static_cast<uint8_t>((topicLen >> 8) & 0xFF);      // topic len MSB
  out[off++] = static_cast<uint8_t>(topicLen & 0xFF);             // topic len LSB
  memcpy(out + off, topic, topicLen); off += topicLen;            // topic
  memcpy(out + off, payload, payloadLen); off += payloadLen;      // payload

  if (kAsyncDeepDebug) {
    SerialMon.print("[async] buildFrame: totalLen=");
    SerialMon.print(off);
    SerialMon.print(" B  (header=1, vlq=");
    SerialMon.print(vlqLen);
    SerialMon.print(", topicLenField=2, topic=");
    SerialMon.print(topicLen);
    SerialMon.print(", payload=");
    SerialMon.print(payloadLen);
    SerialMon.println(")");
    dumpHex("full MQTT PUBLISH frame", out, off);
  }
  return off;
}
}  // namespace

bool isAsyncPublishBusy()
{
  return g_asyncStage != PublishStage::IDLE;
}

AsyncPublishResult takeAsyncPublishResult()
{
  const AsyncPublishResult result = g_asyncResult;
  g_asyncResult = AsyncPublishResult::None;
  return result;
}

bool triggerAsyncPublish()
{
  if (g_asyncStage != PublishStage::IDLE) {
    return false;
  }
  const int mqttState = mqtt.state();
  if (mqttState != 0) {
    return false;
  }

  SerialMon.println("\n================= PUBLISH Status =================");
  SerialMon.println();
  SerialMon.println("--- Struct filling  ---");
  g_asyncFrameLen = buildEncryptedPublishFrame(
      kMqttPublishTopicStatus, g_asyncFrame, sizeof(g_asyncFrame));
  SerialMon.print("Status struct filled\n\n");
  if (g_asyncFrameLen == 0) {
    SerialMon.println("[PUB] Frame build FAILED");
    return false;
  }

  g_asyncFrameSent      = 0;
  g_asyncLineLen        = 0;
  g_asyncPromptLen      = 0;
  g_asyncStepCallCount  = 0;
  g_asyncTriggerStartMs = millis();
  g_asyncResult         = AsyncPublishResult::None;
  setStage(PublishStage::ISSUE_CIPSEND);
  return true;
}

void asyncPublishStep()
{
  if (g_asyncStage != PublishStage::IDLE) {
    g_asyncStepCallCount++;
  }

  switch (g_asyncStage) {

  case PublishStage::IDLE:
    return;

  case PublishStage::ISSUE_CIPSEND: {
    if (kAsyncDeepDebug) {
      SerialMon.print("[async] TX> AT+CIPSEND=");
      SerialMon.print(static_cast<unsigned>(kAsyncMux));
      SerialMon.print(",");
      SerialMon.println(static_cast<unsigned>(g_asyncFrameLen));
    }
    SerialAT.print("AT+CIPSEND=");
    SerialAT.print(static_cast<unsigned>(kAsyncMux));
    SerialAT.print(",");
    SerialAT.print(static_cast<unsigned>(g_asyncFrameLen));
    SerialAT.print("\r\n");
    g_asyncLineLen   = 0;
    g_asyncPromptLen = 0;
    setStage(PublishStage::WAIT_PROMPT);
    return;
  }

  case PublishStage::WAIT_PROMPT: {
    bool sawByte = false;
    while (SerialAT.available()) {
      const int c = SerialAT.read();
      sawByte = true;
      // Capture for forensics
      if (g_asyncPromptLen + 1 < sizeof(g_asyncPromptBuf)) {
        g_asyncPromptBuf[g_asyncPromptLen++] = static_cast<char>(c);
      }
      if (kAsyncDeepDebug) {
        SerialMon.print("[async] RX< ");
        logRxByte(c);
        SerialMon.println();
      }
      if (c == '>') {
        if (kAsyncDeepDebug) {
          g_asyncPromptBuf[g_asyncPromptLen] = '\0';
          SerialMon.print("[async] '>' prompt detected after ");
          SerialMon.print(millis() - g_asyncStageStartMs);
          SerialMon.print(" ms; preamble bytes=");
          SerialMon.println(g_asyncPromptLen);
        }
        g_asyncFrameSent = 0;
        setStage(PublishStage::SEND_PAYLOAD);
        return;
      }
    }
    if (!sawByte) {
      heartbeat("waiting for '>' prompt");
    }
    if (millis() - g_asyncStageStartMs > kAsyncPromptTimeoutMs) {
      g_asyncPromptBuf[g_asyncPromptLen] = '\0';
      SerialMon.println("[async] CIPSEND prompt TIMEOUT");
      SerialMon.print("[async] preamble received before timeout (");
      SerialMon.print(g_asyncPromptLen);
      SerialMon.println(" B):");
      SerialMon.println(g_asyncPromptBuf);
      g_asyncResult = AsyncPublishResult::Failure;
      setStage(PublishStage::IDLE);
    }
    return;
  }

  case PublishStage::SEND_PAYLOAD: {
    const size_t remain = g_asyncFrameLen - g_asyncFrameSent;
    const size_t take   = (remain < kAsyncPayloadChunk) ? remain : kAsyncPayloadChunk;
    const size_t wrote  = SerialAT.write(g_asyncFrame + g_asyncFrameSent, take);
    g_asyncFrameSent += wrote;
    if (kAsyncDeepDebug) {
      SerialMon.print("[async] TX payload chunk: wrote ");
      SerialMon.print(wrote);
      SerialMon.print("/");
      SerialMon.print(take);
      SerialMon.print(" B  total ");
      SerialMon.print(g_asyncFrameSent);
      SerialMon.print("/");
      SerialMon.print(g_asyncFrameLen);
      SerialMon.println(" B");
    }
    if (wrote == 0) {
      // Should never happen on STM32 HardwareSerial — TX FIFO blocks if needed.
      SerialMon.println("[async] WARN: SerialAT.write returned 0 — UART backed up?");
    }
    if (g_asyncFrameSent >= g_asyncFrameLen) {
      g_asyncLineLen = 0;
      setStage(PublishStage::WAIT_SEND_OK);
    }
    return;
  }

  case PublishStage::WAIT_SEND_OK: {
    bool sawByte = false;
    while (SerialAT.available()) {
      const int c = SerialAT.read();
      sawByte = true;
      if (kAsyncDeepDebug) {
        SerialMon.print("[async] RX< ");
        logRxByte(c);
        SerialMon.println();
      }
      if (c == '\r') continue;

      if (c == '\n') {
        g_asyncLineBuf[g_asyncLineLen] = '\0';
        if (g_asyncLineLen > 0) {
          if (kAsyncDeepDebug) {
            SerialMon.print("[async] line: \"");
            SerialMon.print(g_asyncLineBuf);
            SerialMon.println("\"");
          }
          if (strstr(g_asyncLineBuf, "SEND OK")) {
            const uint32_t totalMs = millis() - g_asyncTriggerStartMs;
            SerialMon.print("Publish call time: ");
            SerialMon.print(totalMs);
            SerialMon.println(" ms");
            SerialMon.println("\nTelemetry Published Successfully");
            SerialMon.println("====================================================\n");
            g_lastMqttActivityMs = millis();
            g_asyncResult = AsyncPublishResult::Success;
            setStage(PublishStage::IDLE);
            return;
          }
          if (strstr(g_asyncLineBuf, "SEND FAIL") ||
              strstr(g_asyncLineBuf, "ERROR")    ||
              strstr(g_asyncLineBuf, "link is not valid")) {
            SerialMon.print("[async] publish FAILED line: \"");
            SerialMon.print(g_asyncLineBuf);
            SerialMon.println("\"");
            g_asyncResult = AsyncPublishResult::Failure;
            setStage(PublishStage::IDLE);
            return;
          }
          // Other lines (echoes, "Recv N bytes", "busy p...", "+IPD,...")
          // are ignored. +IPD interleaved with SEND OK is rare; if it
          // happens, those bytes are lost — accept this for QoS 0.
        }
        g_asyncLineLen = 0;
      } 
      else if (g_asyncLineLen + 1 < sizeof(g_asyncLineBuf)) 
      {
        g_asyncLineBuf[g_asyncLineLen++] = static_cast<char>(c);
      }
      // If line buffer fills up without a newline, we silently reset it on
      // next \n; this is fine because we only match short literals.
    }
    if (!sawByte) {
      heartbeat("waiting for SEND OK");
    }
    if (millis() - g_asyncStageStartMs > kAsyncSendOkTimeoutMs) {
      SerialMon.println("[async] SEND OK TIMEOUT");
      g_asyncLineBuf[g_asyncLineLen] = '\0';
      SerialMon.print("[async] last partial line: \"");
      SerialMon.print(g_asyncLineBuf);
      SerialMon.println("\"");
      g_asyncResult = AsyncPublishResult::Failure;
      setStage(PublishStage::IDLE);
    }
    return;
  }
  }
}
