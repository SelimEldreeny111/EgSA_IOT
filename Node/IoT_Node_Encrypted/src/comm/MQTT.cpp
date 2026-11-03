/** @file MQTT.cpp @brief IP uplink, MQTT connection, command intake, and async publish FSM. */
#define APP_LOG_MODULE "MQTT"
#include "../platform/DebugLog.h"
#include "../storage/TelemetryArchive.h"
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

/** @brief TinyGSM modem bound to the selected IP uplink UART. */
TinyGsm modem(SerialAT);
#include "CachedTinyGsmClient.h"
CachedTinyGsmClient gsmClient(modem);

#include "VerifiedBufferedClient.h"
#include "PriorityPublishQueue.h"
#include "TelemetryPayload.h"
#include "MqttTopicRouting.h"

VerifiedBufferedClient<AppConfig::kMqttPacketBufferSize> bufferedClient(gsmClient);
PubSubClient   mqtt(bufferedClient);

namespace {
uint32_t g_lastMqttActivityMs = 0;
uint32_t g_lastReconnectAttemptMs = 0;
uint8_t g_mqttConnectFailureCount = 0;
PriorityPublishQueue<AppConfig::kCodecBufferSize, 4U> g_publishQueue;
AsyncPublishResult g_asyncResult = AsyncPublishResult::None;
bool g_modemOperationActive = false;
bool g_commandHandledThisPass = false;
bool sendCheckedMqttPayload(const char* topic, const uint8_t* payload, size_t length);

/** @brief Print a timed operation only when publish-timing logging is enabled. */
void logElapsedMs(const char* label, uint32_t elapsedMs)
{
  if (!AppConfig::kEnablePublishTimingLogs) {
    return;
  }

  APP_DEBUG_PRINT(label);
  APP_DEBUG_PRINT(": ");
  APP_DEBUG_PRINT(elapsedMs);
  APP_DEBUG_PRINTLN(" ms");
}

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
  return MqttTopicRouting::parseCommand(topic, kMqttCompanyTopicPrefix,
                                        topicNodeId, isBroadcastTopic);
}
#endif
}

/** @brief Query and print the ESP-AT firmware version on ESP8266 builds. */
void printEspFirmwareVersion()
{
#if defined(USE_ESP8266) && APP_ENABLE_DEBUG
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
}

void resetMqttTransportForNetworkRecovery()
{
  APP_DEBUG_PRINTLN("[NETWORK] First retry budget exhausted: resetting active modem RST");
  g_modemOperationActive = true;
  serviceHardwareWatchdog(WatchdogStage::ModemInitialization);
  // Use the normal transport close. If its driver hangs, the global IWDG still
  // resets the MCU; startup above then also pulses the modem's hardware RST.
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
    APP_DEBUG_PRINTLN("\n=========== MQTT CALLBACK ===========");
    APP_DEBUG_PRINT("Topic: ");
    APP_DEBUG_PRINTLN(topic);
    APP_DEBUG_PRINT("Payload length: ");
    APP_DEBUG_PRINTLN(length);
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

  CMD_Message cmd = CMD_Message_init_zero;
  if (!decodeEncryptedCommandPayload(payload, length, cmd))
  {
    APP_LOG_ERROR(" CMD decode FAILED");
    return;
  }

#if APP_ROLE == APP_ROLE_LORA_GATEWAY
  if (!isBroadcastTopic && cmd.node_id != topicNodeId)
  {
    APP_DEBUG_PRINT(" Gateway rejected CMD: topic node=");
    APP_DEBUG_PRINT(topicNodeId);
    APP_DEBUG_PRINT(" payload node=");
    APP_DEBUG_PRINTLN(cmd.node_id);
    return;
  }

  const LoraPayloadType loraCommandType =
      isBroadcastTopic ? LoraPayloadType::BroadcastCommand : LoraPayloadType::Command;
  if (sendLoraWakeCommand(loraCommandType, payload, length))
  {
    APP_DEBUG_PRINT(" Gateway forwarded MQTT CMD to LoRa ");
    APP_DEBUG_PRINTLN(isBroadcastTopic ? "broadcast" : "node");
  }
  else
  {
    APP_LOG_ERROR(" Gateway failed to forward MQTT CMD over LoRa");
  }
  return;
#else
  if (!isBroadcastTopic && cmd.node_id != AppConfig::kNodeId)
  {
    APP_LOG_WARN("CMD rejected: topic/payload node mismatch");
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
    if (!isBroadcastTopic && cmd.node_id != AppConfig::kNodeId)
    {
      APP_DEBUG_PRINTLN("Telemetry/WAKE request not for this MQTT node");
      return;
    }
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
  const bool mqttConnected = mqtt.connect(kMqttClientId);
  serviceHardwareWatchdog();
  if (!mqttConnected)
  {
    bufferedClient.flush();
    ++g_mqttConnectFailureCount;
    if (AppConfig::kEnableVerboseMqttLogs) {
      APP_DEBUG_PRINT(" FAILED, mqtt state=");
      logMqttStateDetails(mqtt.state());
      APP_DEBUG_PRINTLN(" retry scheduled");
    }

#if defined(USE_ESP8266)
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
  const bool nodeSubscribed = mqtt.subscribe(kMqttGatewayCommandWildcardTopic);
  const bool nodeFlushed = bufferedClient.finishPacket();
  serviceHardwareWatchdog();
  const bool subscriptionsSent = nodeSubscribed && nodeFlushed;
#else
  const bool nodeSubscribed = mqtt.subscribe(kMqttCommandTopic);
  const bool nodeFlushed = bufferedClient.finishPacket();
  serviceHardwareWatchdog();
  const bool broadcastSubscribed = mqtt.subscribe(kMqttBroadcastTopic);
  const bool broadcastFlushed = bufferedClient.finishPacket();
  serviceHardwareWatchdog();
  const bool subscriptionsSent = nodeSubscribed && nodeFlushed &&
      broadcastSubscribed && broadcastFlushed;
#endif

  if (!subscriptionsSent)
  {
    APP_LOG_ERROR("ERROR: command SUBSCRIBE send failed; reconnecting next pass");
    mqtt.disconnect();
    serviceHardwareWatchdog();
    return false;
  }

  if (AppConfig::kEnableVerboseMqttLogs) {
    APP_DEBUG_PRINTLN("CONNECTED");
#if APP_ROLE == APP_ROLE_LORA_GATEWAY
    APP_DEBUG_PRINT("Command subscription sent: ");
    APP_DEBUG_PRINTLN(kMqttGatewayCommandWildcardTopic);
#else
    APP_DEBUG_PRINT("Command subscription sent: ");
    APP_DEBUG_PRINTLN(kMqttCommandTopic);
    APP_DEBUG_PRINT("Command subscription sent: ");
    APP_DEBUG_PRINTLN(kMqttBroadcastTopic);
#endif
  }

  return true;
}

void mqttLoop()
{
  // Callback only applies commands and queues responses. It never publishes
  // recursively while PubSubClient is decoding the inbound MQTT packet.
  if (g_modemOperationActive || mqtt.state() != 0 || g_publishQueue.replyFull()) return;
  g_modemOperationActive = true;
  serviceHardwareWatchdog(WatchdogStage::MqttService);
  mqtt.loop();
  // Flushes any PINGREQ that mqtt.loop() may have emitted, so it leaves
  // in a single AT+CIPSEND instead of sitting in the buffer until the next
  // publish/subscribe call.
  if (!bufferedClient.finishPacket())
  {
    APP_LOG_ERROR("[MQTT] Keepalive/socket send failed; closing connection");
    mqtt.disconnect();
  }
  g_modemOperationActive = false;
  serviceHardwareWatchdog();
}

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

  int signalQuality = modem.getSignalQuality();
  serviceHardwareWatchdog();
  APP_DEBUG_PRINT("Signal quality (raw CSQ): ");
  APP_DEBUG_PRINT(signalQuality);
  APP_DEBUG_PRINTLN(" (0..31; 99=unknown)");

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
  APP_LOG_INFO("tx topic=%s bytes=%lu queue_write=%u modem_write=%u elapsed_ms=%lu server_receipt=unconfirmed",
      topic, static_cast<unsigned long>(length), queued, flushed,
      static_cast<unsigned long>(millis() - started));
  if (!queued || !flushed) {
    // An ambiguous/partial MQTT packet must not be followed by another packet
    // on this TCP stream. TinyGSM owns recovery and receive-URC processing.
    mqtt.disconnect();
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
      reply ? kMqttPublishTopicTlm : kMqttPublishTopicStatus, packet.bytes, packet.length);
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
  return g_commandHandledThisPass || g_publishQueue.hasReplies();
}
