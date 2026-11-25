/** @file MQTT.cpp @brief IP uplink, MQTT connection, command intake, and async publish FSM. */
#define APP_LOG_MODULE "MQTT"
#include "../platform/DebugLog.h"
#include "../storage/TelemetryArchive.h"
#include "MQTT.h"

#include "../config/AppConfig.h"
#include "../config/RuntimeConfig.h"
#include "../app/AppState.h"
#include "PacketCodec.h"
#include "CommandHandler.h"
#include "SensorPayloadMapper.h"
#include "../devices/RTC.h"
#include "../platform/Watchdog.h"
#if APP_ROLE == APP_ROLE_LORA_GATEWAY
#include "GatewayDelivery.h"
#endif

#include <string.h>

extern HardwareSerial SerialMon;
extern HardwareSerial SerialAT;

/** @brief TinyGSM modem bound to the selected IP uplink UART. */
#if APP_ROLE == APP_ROLE_LORA_GATEWAY && defined(USE_ESP8266)
#include "GatewayWifiLink.h"
GatewayEspAtStream gatewayEspInput(SerialAT);
GatewayWifiLink gatewayWifi(SerialAT, gatewayEspInput);
TinyGsm modem(gatewayEspInput);
#else
TinyGsm modem(SerialAT);
#endif
#if APP_GATEWAY_MQTT_TLS
#include "../config/AppSecrets.h"
#include "GatewayMqttTlsClient.h"
#ifndef WIOT_MQTT_CREDENTIAL_HOST
#define WIOT_MQTT_CREDENTIAL_HOST ""
#endif
#ifndef WIOT_MQTT_USERNAME
#define WIOT_MQTT_USERNAME ""
#endif
#ifndef WIOT_MQTT_PASSWORD
#define WIOT_MQTT_PASSWORD ""
#endif
GatewayMqttTlsClient gsmClient(modem);
#else
#include "CachedTinyGsmClient.h"
CachedTinyGsmClient gsmClient(modem);
#endif

#include "VerifiedBufferedClient.h"
#include "PriorityPublishQueue.h"
#include "TelemetryPayload.h"
#include "MqttTopicRouting.h"

VerifiedBufferedClient<AppConfig::kMqttPacketBufferSize, APP_ROLE == APP_ROLE_LORA_GATEWAY> bufferedClient(gsmClient);
PubSubClient   mqtt(bufferedClient);

namespace {
uint32_t g_lastMqttActivityMs = 0;
uint32_t g_lastReconnectAttemptMs = 0;
uint8_t g_mqttConnectFailureCount = 0;
uint32_t g_connectionGeneration = 0;
PriorityPublishQueue<AppConfig::kCodecBufferSize, 4U> g_publishQueue;
AsyncPublishResult g_asyncResult = AsyncPublishResult::None;
bool g_modemOperationActive = false;
bool g_commandHandledThisPass = false;
bool sendCheckedMqttPayload(const char* topic, const uint8_t* payload, size_t length);
#if APP_ROLE == APP_ROLE_LORA_GATEWAY
template<class T, size_t Count>
struct Fifo {
  T entries[Count];
  size_t head = 0, count = 0;
  T* front() { return count ? &entries[head] : nullptr; }
  T* reserve() { return count < Count ? &entries[(head + count) % Count] : nullptr; }
  void push() { ++count; }
  void pop() { head = (head + 1) % Count; --count; }
};
Fifo<GatewayCommand, 8> g_gatewayCommands{};
Fifo<Gateway_Delivery, 16> g_gatewayEvents{};
Fifo<Gateway_Delivery, 12> g_gatewayReceipts{};
struct SeenCommand { uint64_t fingerprint; uint32_t receivedMs; };
SeenCommand g_seenCommands[16] = {};
unsigned g_seenNext = 0;
bool g_gatewayReady = false;
bool g_gatewayRecoveryPending = false;

void scheduleGatewayMqttRecovery(const char* fault)
{
  if (g_gatewayRecoveryPending) return;
#if defined(USE_ESP8266)
  const auto ipd = gatewayEspInput.ipdProgress();
  APP_LOG_ERROR("mqtt_receive_fault reason=%s packet_type=%u staged_bytes=%lu "
      "ipd_announced_bytes=%lu ipd_received_bytes=%lu action=modem_recovery",
      fault, bufferedClient.rxPacketType(), static_cast<unsigned long>(bufferedClient.rxStagedBytes()),
      static_cast<unsigned long>(ipd.announced), static_cast<unsigned long>(ipd.received));
  (void)ipd;
#else
  APP_LOG_ERROR("mqtt_receive_fault reason=%s packet_type=%u staged_bytes=%lu action=modem_recovery",
      fault, bufferedClient.rxPacketType(), static_cast<unsigned long>(bufferedClient.rxStagedBytes()));
#endif
  (void)fault;
  // Mark the transport stopped first. PubSubClient may try DISCONNECT, flush
  // and stop(), but those operations can no longer touch the faulty socket.
  bufferedClient.stop();
  mqtt.disconnect();
  g_gatewayReady = false;
  g_gatewayRecoveryPending = true;
  g_lastReconnectAttemptMs = millis();
}

const char* gatewayInputFault()
{
#if defined(USE_ESP8266)
  if (const char* fault = gatewayEspInput.fault()) return fault;
#endif
  if (const char* fault = bufferedClient.receiveFault()) return fault;
  if (bufferedClient.transportStopped()) return "mqtt_socket_stopped";
  return nullptr;
}

void confirmGatewaySubscriptionState()
{
  if (!g_gatewayReady && mqtt.state() == 0 && bufferedClient.subscriptionsReady()) {
    g_gatewayReady = true;
    ++g_connectionGeneration;
    APP_LOG_EVENT("mqtt_subscriptions_ready qos=1");
  }
}
void queueGatewayEvent(Gateway_Delivery proof, GatewayDeliveryPhase phase)
{
  Gateway_Delivery* entry = g_gatewayEvents.reserve();
  if (!entry) {
    APP_LOG_EVENT_WARN("gateway_event_queue_full request=%lu phase=%u",
        static_cast<unsigned long>(proof.request_id), static_cast<unsigned>(phase));
    return;
  }
  proof.phase = phase;
  *entry = proof;
  g_gatewayEvents.push();
}

bool parseServerReceiptTopic(const char* topic, uint16_t& node)
{
  const char* prefix = WIOT_ACTIVE_TOPIC(kMqttCompanyTopicPrefix, prefix);
  const size_t length = strlen(prefix);
  if (strncmp(topic, prefix, length) || topic[length] != '/') return false;
  const char* number = topic + length + 1U;
  if (*number < '1' || *number > '9') return false;
  char* end = nullptr;
  const unsigned long id = strtoul(number, &end, 10);
  if (id > UINT16_MAX || strcmp(end, "/receipt")) return false;
  node = static_cast<uint16_t>(id);
  return true;
}
#endif


/** @brief Print a timed operation only when publish-timing logging is enabled. */
#if APP_DEBUG_FULL_ENABLED
void logElapsedMs(const char* label, uint32_t elapsedMs)
{
  (void)label; (void)elapsedMs;
  if (!AppConfig::kEnablePublishTimingLogs) {
    return;
  }

  APP_DEBUG_PRINT(label);
  APP_DEBUG_PRINT(": ");
  APP_DEBUG_PRINT(elapsedMs);
  APP_DEBUG_PRINTLN(" ms");
}
#endif

/** @brief Decode PubSubClient status codes for verbose diagnostics. */
void logMqttStateDetails(int state)
{
  if (!AppConfig::kEnableVerboseMqttLogs) {
    return;
  }

  switch (state)
  {
    case -4:
      APP_DEBUG_PRINTLN("  Connection Timeout");
      break;
    case -3:
      APP_DEBUG_PRINTLN("  Connection Lost");
      break;
    case -2:
      APP_DEBUG_PRINTLN("  Connect Failed");
      break;
    case -1:
      APP_DEBUG_PRINTLN("  Disconnected");
      break;
    case 0:
      APP_DEBUG_PRINTLN("  Connected");
      break;
    case 1:
      APP_DEBUG_PRINTLN("  Connect Bad Protocol");
      break;
    case 2:
      APP_DEBUG_PRINTLN("  Connect Bad Client ID");
      break;
    case 3:
      APP_DEBUG_PRINTLN("  Connect Unavailable");
      break;
    case 4:
      APP_DEBUG_PRINTLN("  Connect Bad Credentials");
      break;
    case 5:
      APP_DEBUG_PRINTLN("  Connect Unauthorized");
      break;
    default:
      APP_DEBUG_PRINTLN("  Unknown State");
      break;
  }
}

#if APP_ROLE == APP_ROLE_LORA_GATEWAY
/** @brief Validate gateway command-topic structure and extract node/broadcast routing. */
bool parseGatewayNodeCommandTopic(const char* topic, uint16_t& topicNodeId, bool& isBroadcastTopic)
{
  return MqttTopicRouting::parseCommand(topic, WIOT_ACTIVE_TOPIC(kMqttCompanyTopicPrefix, prefix),
                                        topicNodeId, isBroadcastTopic);
}
#endif
}

/** @brief Query and print the ESP-AT firmware version on ESP8266 builds. */
void printEspFirmwareVersion()
{
#if defined(USE_ESP8266) && APP_DEBUG_FULL_ENABLED
  APP_DEBUG_PRINTLN("\n--- Querying ESP-AT firmware version (AT+GMR) ---");

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
      APP_DEBUG_WRITE(static_cast<uint8_t>(c));
      sawAnything = true;
    }
  }

  if (!sawAnything) {
    APP_DEBUG_PRINTLN("(no response from ESP — check baud / wiring)");
  }
  APP_DEBUG_PRINTLN("\n--- End AT+GMR ---");
#endif
}

namespace
{
#if defined(USE_ESP8266)
/** @brief Set the schematic's ESP enable signal with configured polarity. */
void driveEspEnable(bool enabled)
{
  const bool outputHigh =
      enabled == AppConfig::kEspEnableActiveHigh;
  digitalWrite(AppConfig::kEspEnablePin, outputHigh ? HIGH : LOW);
}

/** @brief Set the schematic's ESP reset signal with configured polarity. */
void driveEspReset(bool asserted)
{
  const bool outputHigh =
      asserted != AppConfig::kEspResetActiveLow;
  digitalWrite(AppConfig::kEspResetPin, outputHigh ? HIGH : LOW);
}

/** @brief Re-enable and hardware-reset ESP8266 before UART use. */
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
#elif defined(USE_SIM800)
/** @brief Pulse SIM800L RESET without driving its internal pull-up above its voltage. */
void resetSim800Hardware()
{
  digitalWrite(AppConfig::kSimResetPin, HIGH); // Open drain HIGH means released.
  pinMode(AppConfig::kSimResetPin, OUTPUT_OPEN_DRAIN);
  digitalWrite(AppConfig::kSimResetPin, LOW);
  watchdogDelay(AppConfig::kSimResetPulseMs);
  digitalWrite(AppConfig::kSimResetPin, HIGH);
}
#endif
}

void initializeMqttTransport()
{
  serviceHardwareWatchdog(WatchdogStage::ModemInitialization);
#if APP_ROLE == APP_ROLE_LORA_GATEWAY && defined(USE_ESP8266)
  gatewayWifi.begin();
#else
#if defined(USE_ESP8266)
  resetAndWakeEsp8266();
#else
  // Reset the independently powered SIM800 on every MCU boot as well. A stuck
  // modem must not survive a watchdog/controller reset and poison the next boot.
  resetSim800Hardware();
  SerialAT.begin(MODEM_BAUD);
  watchdogDelay(AppConfig::kSimBootDelayMs);
#endif
  APP_DEBUG_ONLY(printEspFirmwareVersion());
  serviceHardwareWatchdog(WatchdogStage::ModemInitialization);
  // Do not refresh from inside modem.init(). If the AT library becomes stuck,
  // the independent watchdog must be allowed to reset the STM32.
  modem.init();
  serviceHardwareWatchdog();
#endif
}

void resetMqttTransportForNetworkRecovery()
{
  APP_DEBUG_PRINTLN("[NETWORK] First retry budget exhausted: resetting active modem RST");
  g_modemOperationActive = true;
  serviceHardwareWatchdog(WatchdogStage::ModemInitialization);
#if APP_ROLE == APP_ROLE_LORA_GATEWAY
  bufferedClient.stop(); // Retire locally before resetting the modem.
#endif
  mqtt.disconnect();
  serviceHardwareWatchdog();
  if (g_publishQueue.hasStatus()) {
    g_publishQueue.dropStatus();
    g_asyncResult = AsyncPublishResult::Failure;
  }
  // Correlated command replies remain in RAM for retry after reconnection.
  initializeMqttTransport();
  initializeMqttClient();
  g_lastReconnectAttemptMs = 0U;
  g_mqttConnectFailureCount = 0U;
  g_modemOperationActive = false;
  APP_DEBUG_PRINTLN("[NETWORK] Modem reset finished; starting second retry budget");
}

[[noreturn]] void resetModemAndControllerForNetworkFailure()
{
  APP_DEBUG_PRINTLN("[NETWORK] Second retry budget exhausted: resetting modem RST + STM32");
  serviceHardwareWatchdog(WatchdogStage::ModemInitialization);
  // No close/AT transaction here: guarantee the physical reset pulse before
  // requesting MCU reset even if the UART/driver is unhealthy.
#if defined(USE_ESP8266)
  resetAndWakeEsp8266();
#else
  resetSim800Hardware();
#endif
  forceHardwareWatchdogReset("Second GSM/WiFi retry budget exhausted; modem RST pulsed");
}

bool prepareMqttTransportForPowerDown(uint32_t timeoutMs)
{
  (void)timeoutMs;
#if defined(USE_ESP8266)
  if (isAsyncPublishBusy())
  {
    return false;
  }

  APP_DEBUG_PRINTLN("Power: closing MQTT/TCP before ESP8266 deep sleep");
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
    APP_LOG_WARN("Power: ESP8266 rejected AT+GSLP=0; sleep cancelled");
    return false;
  }

  serviceHardwareWatchdog();
  SerialAT.flush();
  SerialAT.end();
  APP_DEBUG_PRINTLN("Power: ESP8266 entered deep sleep");
  return true;
#else
  APP_DEBUG_PRINTLN(
      "Power: SIM800L shutdown is disabled because PWRKEY is not routed to the STM32");
  return false;
#endif
}

void restoreMqttTransportAfterPowerDownAbort()
{
#if defined(USE_ESP8266)
  APP_DEBUG_PRINTLN("Power: waking ESP8266 after cancelled Standby handoff");
  initializeMqttTransport();
  if (!connectNetwork())
  {
    APP_DEBUG_PRINTLN("Power: ESP8266 recovery will continue in the normal retry loop");
  }
  initializeMqttClient();
#endif
}

void initializeMqttClient()
{
#if APP_GATEWAY_MQTT_TLS
  APP_LOG_EVENT("Gateway MQTT transport=TLS port=%u", static_cast<unsigned>(AppConfig::kMqttPort));
#elif APP_ROLE == APP_ROLE_LORA_GATEWAY
  APP_LOG_EVENT("Gateway MQTT transport=plain TCP port=%u", static_cast<unsigned>(AppConfig::kMqttPort));
#endif
#if APP_ROLE == APP_ROLE_LORA_GATEWAY && defined(USE_ESP8266)
  bufferedClient.setReceiveStream(gatewayEspInput.socketInput());
#endif
  mqtt.setClient(bufferedClient);
  mqtt.setServer(WIOT_ACTIVE_VALUE(kMqttServer, broker), AppConfig::kMqttPort);
  mqtt.setCallback(mqttCallback);
  mqtt.setKeepAlive(AppConfig::kMqttKeepAliveSeconds);
  mqtt.setSocketTimeout(AppConfig::kMqttSocketTimeoutSeconds);
  mqtt.setBufferSize(AppConfig::kMqttPacketBufferSize);
}

void mqttCallback(char* topic, byte* payload, unsigned int length)
{
  g_lastMqttActivityMs = millis();

  if (AppConfig::kEnableVerboseMqttLogs) {
    APP_DEBUG_PRINTLN("\n=========== MQTT CALLBACK ===========");
    APP_DEBUG_PRINT("Topic: ");
    APP_DEBUG_PRINTLN(topic);
    APP_DEBUG_PRINT("Payload length: ");
    APP_DEBUG_PRINTLN(length);
  }

#if APP_ROLE == APP_ROLE_LORA_GATEWAY
  uint16_t topicNodeId = 0;
  if (parseServerReceiptTopic(topic, topicNodeId)) {
    Gateway_Delivery proof = Gateway_Delivery_init_zero;
    auto* entry = g_gatewayReceipts.reserve();
    if (entry && decodeEncryptedGatewayDelivery(payload, length, proof) &&
        proof.phase == ServerPersisted && proof.node_id == topicNodeId) {
      *entry = proof;
      g_gatewayReceipts.push();
    }
    return;
  }
  bool isBroadcastTopic = false;
  const bool isNodeTopic = parseGatewayNodeCommandTopic(topic, topicNodeId, isBroadcastTopic);
#else
  const bool isNodeTopic = (strcmp(topic, WIOT_ACTIVE_TOPIC(kMqttCommandTopic, command)) == 0);
  const bool isBroadcastTopic = (strcmp(topic, WIOT_ACTIVE_TOPIC(kMqttBroadcastTopic, broadcast)) == 0);
#endif

  if (AppConfig::kEnableVerboseMqttLogs) {
    APP_DEBUG_PRINT("Is Node Topic      : ");
    APP_DEBUG_PRINTLN(isNodeTopic);
    APP_DEBUG_PRINT("Is Broadcast Topic : ");
    APP_DEBUG_PRINTLN(isBroadcastTopic);
  }

  if (!isNodeTopic && !isBroadcastTopic)
  {
    APP_DEBUG_PRINTLN(" Unknown topic - ignoring");
    return;
  }

#if APP_ROLE == APP_ROLE_LORA_GATEWAY
  Gateway_Delivery proof = Gateway_Delivery_init_zero;
  proof.node_id = topicNodeId;
  proof.fingerprint = frameFingerprint(payload, length);
  proof.wire_bytes = length;
#if APP_ENABLE_DEBUG
  APP_LOG_EVENT("command_wire_rx topic=%s bytes=%u fingerprint=%s",
      topic, length, WiotDebug::Decimal64(proof.fingerprint).text);
#endif
#endif
  CMD_Message cmd = CMD_Message_init_zero;
  if (!decodeEncryptedCommandPayload(payload, length, cmd))
  {
    APP_LOG_ERROR("command_decode_failed transport=MQTT bytes=%u", length);
#if APP_ROLE == APP_ROLE_LORA_GATEWAY
    queueGatewayEvent(proof, GatewayDecodeFailed);
#endif
    return;
  }
  APP_LOG_COMMAND_RX("MQTT", cmd, isBroadcastTopic);

#if APP_ROLE == APP_ROLE_LORA_GATEWAY
  proof.request_id = cmd.request_id;
  if (!isBroadcastTopic && cmd.node_id != topicNodeId)
  {
    APP_LOG_EVENT_WARN("command_rejected request=%lu reason=topic_payload_mismatch",
        static_cast<unsigned long>(cmd.request_id));
    queueGatewayEvent(proof, GatewayDecodeFailed);
    return;
  }
  const uint32_t now = millis();
  for (const auto& seen : g_seenCommands) {
    if (seen.fingerprint == proof.fingerprint && now - seen.receivedMs < 120000U) return;
  }
  // Match the server's desired-value supersession policy before either value can
  // leave the queue. A command already on the radio remains an uncertain outcome.
  if (cmd.cmd_id == CMD_OPEN_CLOSE_NODE || cmd.cmd_id == CMD_SET_SAMPLING_PERIOD ||
      cmd.cmd_id == CMD_SET_TRANSMISSION_PERIOD || cmd.cmd_id == CMD_SYNC_RTC)
  {
    for (size_t i = 0; i < g_gatewayCommands.count; ++i) {
      auto& older = g_gatewayCommands.entries[(g_gatewayCommands.head + i) % 8U];
      if (older.commandId == cmd.cmd_id && older.proof.node_id == topicNodeId &&
          older.broadcast == isBroadcastTopic) older.superseded = true;
    }
  }
  GatewayCommand* entry = g_gatewayCommands.reserve();
  if (!entry || length > sizeof(entry->payload)) {
    APP_LOG_ERROR("command_queue_full request=%lu", static_cast<unsigned long>(cmd.request_id));
    queueGatewayEvent(proof, GatewayQueueFull);
    return;
  }
  entry->proof = proof;
  entry->broadcast = isBroadcastTopic;
  entry->receivedMs = now;
  entry->commandId = cmd.cmd_id;
  entry->superseded = false;
  memcpy(entry->payload, payload, length);
  g_gatewayCommands.push();
  g_seenCommands[g_seenNext] = {proof.fingerprint, now};
  g_seenNext = (g_seenNext + 1U) % (sizeof(g_seenCommands) / sizeof(g_seenCommands[0]));
  queueGatewayEvent(proof, GatewayQueued);
  APP_LOG_EVENT("command_queued request=%lu target=%u", static_cast<unsigned long>(cmd.request_id),
      static_cast<unsigned>(topicNodeId));
  return;
#else
  if (!isBroadcastTopic && cmd.node_id != AppConfig::kNodeId)
  {
    APP_LOG_EVENT_WARN("command_rejected request=%lu reason=not_for_this_node local=%u",
        static_cast<unsigned long>(cmd.request_id), static_cast<unsigned>(AppConfig::kNodeId));
    return;
  }
  if (cmd.cmd_id == CMD_HISTORY_ACK) {
    TelemetryArchive::handle(cmd,isBroadcastTopic);
    return;
  }
  g_commandHandledThisPass = true;
  if (g_publishQueue.hasStatus())
  {
    g_publishQueue.dropStatus();
    g_asyncResult = AsyncPublishResult::Failure;
  }
  if (cmd.cmd_id == CMD_GET_TELEMETRY || cmd.cmd_id == CMD_REMOTE_WAKE)
  {
    const bool applied = cmd.cmd_id != CMD_REMOTE_WAKE ||
        handleRemoteWakeCommand(cmd, isBroadcastTopic);
    if (!shouldSendCommandTelemetryReply(cmd.cmd_id, AppConfig::kEnableCommandAckReplies))
    {
      APP_DEBUG_PRINTLN("[CMD] Automatic ACK reply disabled by configuration");
      return;
    }
    if (!applied && cmd.request_id == 0U) return;
    uint8_t telemetryPayload[AppConfig::kCodecBufferSize];
    size_t telemetryPayloadLength = 0;
    if (handleGetTelemetryCommand(&cmd, telemetryPayload,
                                  telemetryPayloadLength, applied))
    {
      if (!g_publishQueue.pushReply(telemetryPayload, telemetryPayloadLength))
        APP_LOG_ERROR("ERROR: command-reply queue full; reply was NOT sent");
      else APP_DEBUG_PRINTLN("[CMD] Telemetry reply queued with highest transmit priority");
    }
  }
  else
  {
    const bool applied = handleCommand(cmd, isBroadcastTopic);
    if (shouldSendCommandTelemetryReply(cmd.cmd_id, AppConfig::kEnableCommandAckReplies) &&
        (cmd.request_id != 0U || cmd.cmd_id == CMD_OPEN_CLOSE_NODE))
    {
      uint8_t ackPayload[AppConfig::kCodecBufferSize];
      size_t ackLength = 0U;
      if (handleGetTelemetryCommand(&cmd, ackPayload, ackLength, applied))
      {
        if (!g_publishQueue.pushReply(ackPayload, ackLength))
          APP_LOG_ERROR("ERROR: command-reply queue full; ACK was NOT sent");
      }
    }
    else if (!AppConfig::kEnableCommandAckReplies)
      APP_DEBUG_PRINTLN("[CMD] Automatic ACK reply disabled by configuration");
  }
#endif
}

bool ensureMqttConnection()
{
  if (g_modemOperationActive) return false;
#if APP_ROLE == APP_ROLE_LORA_GATEWAY
  if (g_gatewayRecoveryPending) {
    if (millis() - g_lastReconnectAttemptMs < AppConfig::kMqttReconnectIntervalMs)
      return false;
    g_gatewayRecoveryPending = false;
    APP_LOG_EVENT("mqtt_recovery modem_reset_begin");
    initializeMqttTransport();
    g_lastReconnectAttemptMs = millis();
    return false; // Reconnect and subscribe on a subsequent quiet pass.
  }
#if defined(USE_ESP8266)
  const bool wasOnline = gatewayWifi.connected();
  if (!gatewayWifi.poll()) {
    if (wasOnline) {
      bufferedClient.stop();
      mqtt.disconnect();
      g_gatewayReady = false;
    }
    return false; // A booting, searching or offline ESP never starts TCP/MQTT.
  }
  if (!wasOnline) g_lastReconnectAttemptMs = millis() - AppConfig::kMqttReconnectIntervalMs;
#endif
#endif
  serviceHardwareWatchdog(WatchdogStage::MqttStatus);
  const bool alreadyConnected = mqtt.connected();
  serviceHardwareWatchdog();
  if (alreadyConnected)
  {
#if APP_ROLE == APP_ROLE_LORA_GATEWAY
    return g_gatewayReady;
#else
    return true;
#endif
  }
#if APP_ROLE == APP_ROLE_LORA_GATEWAY
  g_gatewayReady = false;
#endif

  const uint32_t now = millis();
  if (now - g_lastReconnectAttemptMs < AppConfig::kMqttReconnectIntervalMs)
  {
    return false;
  }

  g_lastReconnectAttemptMs = now;

#if defined(USE_SIM800)
  const bool networkConnected = modem.isNetworkConnected();
  serviceHardwareWatchdog();
  const bool dataConnected = networkConnected && modem.isGprsConnected();
  serviceHardwareWatchdog();
  if (!dataConnected)
  {
    if (AppConfig::kEnableVerboseMqttLogs) {
      APP_DEBUG_PRINTLN("\n Network link is down - reconnecting transport first");
    }

    if (!connectNetwork())
    {
      APP_LOG_ERROR("Network reconnection failed");
      return false;
    }
  }
#endif

  if (AppConfig::kEnableVerboseMqttLogs) {
    APP_DEBUG_PRINTLN("\n MQTT CONNECTION LOST - Attempting Reconnection");
    APP_DEBUG_PRINT("MQTT State: ");
    APP_DEBUG_PRINTLN(mqtt.state());
    logMqttStateDetails(mqtt.state());
    APP_DEBUG_PRINT("Connecting to MQTT... ");
  }

  serviceHardwareWatchdog(WatchdogStage::MqttConnect);
#if APP_ROLE == APP_ROLE_LORA_GATEWAY
  // Distinct from sensor-node clients even when AppConfig.cpp uses the same ID.
  char gatewayClientId[128];
  const int clientIdLength = snprintf(gatewayClientId, sizeof(gatewayClientId),
      "%s-gateway-%u", WIOT_ACTIVE_TOPIC(kMqttClientId, clientId), static_cast<unsigned>(WIOT_ACTIVE_VALUE(APP_GATEWAY_ID, gatewayId)));
  if (clientIdLength <= 0 || static_cast<size_t>(clientIdLength) >= sizeof(gatewayClientId))
  {
    APP_LOG_ERROR("Gateway MQTT client ID is too long");
    return false;
  }
#if defined(USE_ESP8266)
  gatewayEspInput.resetSocket();
#endif
#if APP_GATEWAY_MQTT_TLS
  const char* const username = WIOT_MQTT_USERNAME;
  const char* const password = WIOT_MQTT_PASSWORD;
  if (!*username && *password)
  {
    APP_LOG_ERROR("Gateway MQTT requires a username when a password is configured");
    return false;
  }
  if (*username && strcmp(WIOT_ACTIVE_VALUE(kMqttServer, broker), WIOT_MQTT_CREDENTIAL_HOST) != 0)
  {
    APP_LOG_ERROR("Gateway MQTT broker does not match the configured credential host");
    return false;
  }
  const bool mqttConnected = *username ? mqtt.connect(gatewayClientId, username, password)
                                        : mqtt.connect(gatewayClientId);
#else
  const bool mqttConnected = mqtt.connect(gatewayClientId);
#endif
#else
  const bool mqttConnected = mqtt.connect(WIOT_ACTIVE_TOPIC(kMqttClientId, clientId));
#endif
  serviceHardwareWatchdog();
  if (!mqttConnected)
  {
#if APP_ROLE == APP_ROLE_LORA_GATEWAY
#if defined(USE_ESP8266)
    if (const char* fault = gatewayEspInput.fault()) {
      scheduleGatewayMqttRecovery(fault);
      return false;
    }
#endif
    if (const char* fault = bufferedClient.receiveFault()) {
      scheduleGatewayMqttRecovery(fault);
      return false;
    }
#endif
    bufferedClient.flush();
#if APP_GATEWAY_MQTT_TLS
    APP_LOG_EVENT_WARN("Gateway MQTT/TLS connection failed, mqtt_state=%d", mqtt.state());
#endif
    ++g_mqttConnectFailureCount;
    if (AppConfig::kEnableVerboseMqttLogs) {
      APP_DEBUG_PRINT(" FAILED, mqtt state=");
      logMqttStateDetails(mqtt.state());
      APP_DEBUG_PRINTLN(" retry scheduled");
    }

#if defined(USE_ESP8266) && APP_ROLE != APP_ROLE_LORA_GATEWAY
    if (g_mqttConnectFailureCount >= 3)
    {
      g_mqttConnectFailureCount = 0;
      APP_LOG_ERROR("MQTT failed repeatedly - refreshing ESP8266 WiFi link");
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
  const char* const commandTopic = WIOT_ACTIVE_TOPIC(kMqttGatewayCommandWildcardTopic, gatewayCommands);
#else
  const char* const commandTopic = WIOT_ACTIVE_TOPIC(kMqttCommandTopic, command);
#endif
#if APP_ROLE == APP_ROLE_LORA_GATEWAY
  char receiptTopic[160];
  const int written = snprintf(receiptTopic, sizeof(receiptTopic), "%s/+/receipt",
      WIOT_ACTIVE_TOPIC(kMqttCompanyTopicPrefix, prefix));
  const bool valid = written > 0 && static_cast<size_t>(written) < sizeof(receiptTopic);
  const bool subscriptionsSent = valid && mqtt.subscribe(commandTopic, 1) &&
      bufferedClient.finishPacket() &&
      mqtt.subscribe(WIOT_ACTIVE_TOPIC(kMqttBroadcastTopic, broadcast), 1) &&
      bufferedClient.finishPacket() &&
      mqtt.subscribe(receiptTopic, 1) && bufferedClient.finishPacket();
#else
  const bool nodeSubscribed = mqtt.subscribe(commandTopic);
  const bool nodeFlushed = bufferedClient.finishPacket();
  serviceHardwareWatchdog();
  const bool broadcastSubscribed = mqtt.subscribe(WIOT_ACTIVE_TOPIC(kMqttBroadcastTopic, broadcast));
  const bool broadcastFlushed = bufferedClient.finishPacket();
  serviceHardwareWatchdog();
  const bool subscriptionsSent = nodeSubscribed && nodeFlushed && broadcastSubscribed && broadcastFlushed;
#endif
  if (!subscriptionsSent)
  {
    APP_LOG_ERROR("ERROR: command SUBSCRIBE send failed; reconnecting next pass");
#if APP_ROLE == APP_ROLE_LORA_GATEWAY
    scheduleGatewayMqttRecovery("mqtt_subscribe_write");
#else
    mqtt.disconnect();
#endif
    serviceHardwareWatchdog();
    return false;
  }

  if (AppConfig::kEnableVerboseMqttLogs) {
    APP_DEBUG_PRINTLN("CONNECTED");
    APP_DEBUG_PRINT("Command subscription sent: ");
    APP_DEBUG_PRINTLN(commandTopic);
    APP_DEBUG_PRINT("Command subscription sent: ");
    APP_DEBUG_PRINTLN(WIOT_ACTIVE_TOPIC(kMqttBroadcastTopic, broadcast));
  }

#if APP_ROLE == APP_ROLE_LORA_GATEWAY
  return false; // mqttLoop marks ready after all three matching SUBACKs.
#else
  ++g_connectionGeneration;
  return true;
#endif
}

uint32_t mqttConnectionGeneration()
{
  return g_connectionGeneration;
}

void mqttLoop()
{
  if (g_modemOperationActive || mqtt.state() != 0 || g_publishQueue.replyFull()) return;
  g_modemOperationActive = true;
  serviceHardwareWatchdog(WatchdogStage::MqttService);
  mqtt.loop();
#if APP_ROLE == APP_ROLE_LORA_GATEWAY
  if (const char* fault = gatewayInputFault()) {
    scheduleGatewayMqttRecovery(fault);
  } else if (!bufferedClient.finishPacket()) {
    scheduleGatewayMqttRecovery("mqtt_control_write");
  } else {
    confirmGatewaySubscriptionState();
  }
#else
  if (!bufferedClient.finishPacket()) {
    APP_LOG_ERROR("[MQTT] Keepalive/socket send failed; closing connection");
    mqtt.disconnect();
  }
#endif
  g_modemOperationActive = false;
  serviceHardwareWatchdog();
}

#if APP_ROLE == APP_ROLE_LORA_GATEWAY
#if defined(USE_ESP8266)
void serviceGatewayModemRxDuringRadio()
{
  if (!g_modemOperationActive && !g_gatewayRecoveryPending)
  {
    gatewayEspInput.serviceUart();
  }
}

bool gatewayWifiConnected()
{
  return gatewayWifi.connected();
}
#endif

void serviceGatewayMqttIntake()
{
  if (g_modemOperationActive || g_gatewayRecoveryPending || mqtt.state() != 0) return;
  // Receive only during a reserved radio window. MQTT ACK/control writes
  // remain buffered until a quiet foreground pass can run the modem.
  bufferedClient.setReceiveOnly(true);
  g_modemOperationActive = true;
  const bool staged = bufferedClient.stageReceiveOnlyPacket();
  if (const char* fault = gatewayInputFault()) {
    scheduleGatewayMqttRecovery(fault);
  } else if (staged) {
    mqtt.loop();
    if (const char* fault = gatewayInputFault()) scheduleGatewayMqttRecovery(fault);
    else confirmGatewaySubscriptionState();
  }
  g_modemOperationActive = false;
  bufferedClient.setReceiveOnly(false);
}
#endif

bool checkNetworkStatus()
{
  APP_DEBUG_PRINTLN("\n--- Network Status Check ---");

  APP_DEBUG_PRINT("Modem Status: ");
  const bool networkConnected = modem.isNetworkConnected();
  serviceHardwareWatchdog();
  if (networkConnected)
  {
    APP_DEBUG_PRINTLN(" Network Connected");
  }
  else
  {
    APP_DEBUG_PRINTLN(" Network Disconnected");
    return false;
  }

#if APP_DEBUG_FULL_ENABLED
  const int signalQuality = modem.getSignalQuality();
  serviceHardwareWatchdog();
  APP_DEBUG_PRINT("Signal quality (raw CSQ): ");
  APP_DEBUG_PRINT(signalQuality);
  APP_DEBUG_PRINTLN(" (0..31; 99=unknown)");
#endif

  return true;
}

namespace {
/** @brief Validate both PubSubClient's buffer write and TinyGSM's modem result. */
bool sendCheckedMqttPayload(const char* topic, const uint8_t* payload, size_t length)
{
  serviceHardwareWatchdog(WatchdogStage::MqttPublish);
  const uint32_t started = millis();
  const bool queued = mqtt.publish(topic, payload, length);
  const bool flushed = bufferedClient.finishPacket();
  serviceHardwareWatchdog();
  APP_DEBUG_ONLY(logElapsedMs("MQTT driver send time", millis() - started));
  (void)started;
  APP_LOG_EVENT("tx topic=%s bytes=%lu queue_write=%u modem_write=%u elapsed_ms=%lu server_receipt=unconfirmed",
      topic, static_cast<unsigned long>(length), queued, flushed,
      static_cast<unsigned long>(millis() - started));
  if (!queued || !flushed) {
    // An ambiguous/partial MQTT packet must not be followed by another packet
    // on this TCP stream. TinyGSM owns recovery and receive-URC processing.
#if APP_ROLE == APP_ROLE_LORA_GATEWAY
    scheduleGatewayMqttRecovery("mqtt_publish_write");
#else
    mqtt.disconnect();
#endif
    serviceHardwareWatchdog();
    return false;
  }
  g_lastMqttActivityMs = millis();
  return true;
}
}

void publishTelemetry()
{
  if (triggerAsyncPublish()) asyncPublishStep();
}

bool publishMqttPayload(const char* topic, const uint8_t* payload, size_t payloadLength)
{
  if (!topic || !payload || !payloadLength || g_modemOperationActive) return false;
  if (!ensureMqttConnection()) return false;
  serviceMqttPriorityCommands();
  if (g_publishQueue.hasReplies()) {
    asyncPublishStep();
    if (g_publishQueue.hasReplies()) return false;
  }
  g_modemOperationActive = true;
  const bool accepted = sendCheckedMqttPayload(topic, payload, payloadLength);
  g_modemOperationActive = false;
  return accepted;
}

/** @brief Legacy async API now queues packets through PubSubClient/TinyGSM.
 * SIM800 CIPQSEND=1 returns DATA ACCEPT, not SEND OK. Only TinyGSM owns the
 * modem UART, including receive URCs; PubSubClient maintains MQTT keepalive.
 * Calls remain cooperative between bounded driver operations, not interruptible
 * within an AT transaction. Command replies always precede periodic Status.
 */
bool isAsyncPublishBusy()
{
  return g_modemOperationActive || g_publishQueue.pending();
}

AsyncPublishResult takeAsyncPublishResult()
{
  const AsyncPublishResult result = g_asyncResult;
  g_asyncResult = AsyncPublishResult::None;
  return result;
}

bool triggerAsyncPublish()
{
  if (g_publishQueue.pending() || g_commandHandledThisPass || mqtt.state() != 0)
    return false;
  uint8_t payload[AppConfig::kCodecBufferSize];
  size_t length = 0U;
  if (!buildEncryptedStatusPayload(payload, sizeof(payload), length)) return false;
  g_asyncResult = AsyncPublishResult::None;
  return g_publishQueue.pushStatus(payload, length);
}

void asyncPublishStep()
{
  if (g_modemOperationActive || mqtt.state() != 0 || !g_publishQueue.pending()) return;
  // A command can invalidate a previously queued periodic control-state snapshot.
  if (g_commandHandledThisPass && !g_publishQueue.hasReplies()) return;
  const bool reply = g_publishQueue.hasReplies();
  const auto& packet = g_publishQueue.front();
  g_modemOperationActive = true;
  const bool accepted = sendCheckedMqttPayload(
      reply ? WIOT_ACTIVE_TOPIC(kMqttPublishTopicTlm, telemetry) : WIOT_ACTIVE_TOPIC(kMqttPublishTopicStatus, status), packet.bytes, packet.length);
  g_modemOperationActive = false;
  if (accepted) {
    g_publishQueue.pop();
    APP_DEBUG_PRINTLN(reply ? "[MQTT] Command reply accepted by modem (server receipt not confirmed)"
                            : "[MQTT] Status accepted by modem (server receipt not confirmed)");
    if (!reply) g_asyncResult = AsyncPublishResult::Success;
  } else {
    // Keep correlated command ACKs for retry; never report a failed Status as sent.
    if (!reply) { g_publishQueue.dropStatus(); g_asyncResult = AsyncPublishResult::Failure; }
    APP_LOG_ERROR("[MQTT] Send failed; reconnect required, command replies retained");
  }
}

void beginMqttCommandPriorityPass()
{
  g_commandHandledThisPass = false;
  mqttLoop();
}

void serviceMqttPriorityCommands()
{
  if (g_modemOperationActive || mqtt.state() != 0 || g_publishQueue.replyFull()) return;
  // TinyGSM processes +CIPRXGET/+IPD here without reconnecting. In sensor wait
  // gaps, only enter the MQTT parser if bytes exist. Full keepalive maintenance
  // is performed at the beginning of every foreground application pass.
  if (gsmClient.available() > 0) mqttLoop();
}

bool mqttCommandWorkPending()
{
#if APP_ROLE == APP_ROLE_LORA_GATEWAY
  return g_gatewayCommands.front() != nullptr;
#else
  return g_commandHandledThisPass || g_publishQueue.hasReplies();
#endif
}

#if APP_ROLE == APP_ROLE_LORA_GATEWAY
const GatewayCommand* gatewayPendingCommand() { return g_gatewayCommands.front(); }

void completeGatewayCommand(GatewayDeliveryPhase phase)
{
  if (auto* entry = g_gatewayCommands.front()) {
    queueGatewayEvent(entry->proof, phase);
    APP_LOG_EVENT("command_dispatch request=%lu target=%lu phase=%u",
        static_cast<unsigned long>(entry->proof.request_id), static_cast<unsigned long>(entry->proof.node_id),
        static_cast<unsigned>(phase));
    g_gatewayCommands.pop();
  }
}

bool takeGatewayReceipt(Gateway_Delivery& proof)
{
  auto* entry = g_gatewayReceipts.front();
  if (!entry) return false;
  proof = *entry;
  g_gatewayReceipts.pop();
  return true;
}

void reportGatewayReply(const Gateway_Delivery& proof) { queueGatewayEvent(proof, GatewayReplyQueued); }

void serviceGatewayDeliveryEvents()
{
  auto* entry = g_gatewayEvents.front();
  if (!entry || !g_gatewayReady) return;
  char topic[160];
  const int written = snprintf(topic, sizeof(topic), "%s/gateway/%u/event",
      WIOT_ACTIVE_TOPIC(kMqttCompanyTopicPrefix, prefix),
      static_cast<unsigned>(WIOT_ACTIVE_VALUE(APP_GATEWAY_ID, gatewayId)));
  uint8_t packet[65];
  size_t length = 0;
  if (written > 0 && static_cast<size_t>(written) < sizeof(topic) &&
      encodeEncryptedMessage(Gateway_Delivery_fields, entry, packet, sizeof(packet), length) &&
      publishMqttPayload(topic, packet, length)) g_gatewayEvents.pop();
}
#endif
