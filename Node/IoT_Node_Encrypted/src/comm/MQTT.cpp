/** @file MQTT.cpp @brief IP uplink, MQTT connection, command intake, and async publish FSM. */
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

  SerialMon.print(label);
  SerialMon.print(": ");
  SerialMon.print(elapsedMs);
  SerialMon.println(" ms");
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
/** @brief Validate gateway command-topic structure and extract node/broadcast routing. */
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

/** @brief Query and print the ESP-AT firmware version on ESP8266 builds. */
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
  printEspFirmwareVersion();
  serviceHardwareWatchdog(WatchdogStage::ModemInitialization);
  // Do not refresh from inside modem.init(). If the AT library becomes stuck,
  // the independent watchdog must be allowed to reset the STM32.
  modem.init();
  serviceHardwareWatchdog();
}

void resetMqttTransportForNetworkRecovery()
{
  SerialMon.println("[NETWORK] First retry budget exhausted: resetting active modem RST");
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
  SerialMon.println("[NETWORK] Modem reset finished; starting second retry budget");
}

[[noreturn]] void resetModemAndControllerForNetworkFailure()
{
  SerialMon.println("[NETWORK] Second retry budget exhausted: resetting modem RST + STM32");
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
  if (sendLoraWakeCommand(loraCommandType, payload, length))
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
  if (!isBroadcastTopic && cmd.node_id != AppConfig::kNodeId)
  {
    SerialMon.println("CMD rejected: topic/payload node mismatch");
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
      SerialMon.println("Telemetry/WAKE request not for this MQTT node");
      return;
    }
    const bool applied = cmd.cmd_id != CMD_REMOTE_WAKE ||
        handleRemoteWakeCommand(cmd, isBroadcastTopic);
    if (!applied && cmd.request_id == 0U) return;
    uint8_t telemetryPayload[AppConfig::kCodecBufferSize];
    size_t telemetryPayloadLength = 0;
    if (handleGetTelemetryCommand(&cmd, telemetryPayload,
                                  telemetryPayloadLength, applied))
    {
      if (!g_publishQueue.pushReply(telemetryPayload, telemetryPayloadLength))
        SerialMon.println("ERROR: command-reply queue full; reply was NOT sent");
      else SerialMon.println("[CMD] Telemetry reply queued with highest transmit priority");
    }
  }
  else
  {
    const bool applied = handleCommand(cmd, isBroadcastTopic);
    if (cmd.request_id != 0U)
    {
      uint8_t ackPayload[AppConfig::kCodecBufferSize];
      size_t ackLength = 0U;
      if (handleGetTelemetryCommand(&cmd, ackPayload, ackLength, applied))
      {
        if (!g_publishQueue.pushReply(ackPayload, ackLength))
          SerialMon.println("ERROR: command-reply queue full; ACK was NOT sent");
      }
    }
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
    SerialMon.println("ERROR: command SUBSCRIBE send failed; reconnecting next pass");
    mqtt.disconnect();
    serviceHardwareWatchdog();
    return false;
  }

  if (AppConfig::kEnableVerboseMqttLogs) {
    SerialMon.println("CONNECTED");
#if APP_ROLE == APP_ROLE_LORA_GATEWAY
    SerialMon.print("Command subscription sent: ");
    SerialMon.println(kMqttGatewayCommandWildcardTopic);
#else
    SerialMon.print("Command subscription sent: ");
    SerialMon.println(kMqttCommandTopic);
    SerialMon.print("Command subscription sent: ");
    SerialMon.println(kMqttBroadcastTopic);
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
    SerialMon.println("[MQTT] Keepalive/socket send failed; closing connection");
    mqtt.disconnect();
  }
  g_modemOperationActive = false;
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

namespace {
/** @brief Validate both PubSubClient's buffer write and TinyGSM's modem result. */
bool sendCheckedMqttPayload(const char* topic, const uint8_t* payload, size_t length)
{
  serviceHardwareWatchdog(WatchdogStage::MqttPublish);
  const uint32_t started = millis();
  const bool queued = mqtt.publish(topic, payload, length);
  const bool flushed = bufferedClient.finishPacket();
  serviceHardwareWatchdog();
  logElapsedMs("MQTT driver send time", millis() - started);
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
    SerialMon.println(reply ? "[MQTT] Command reply accepted by modem (server receipt not confirmed)"
                            : "[MQTT] Status accepted by modem (server receipt not confirmed)");
    if (!reply) g_asyncResult = AsyncPublishResult::Success;
  } else {
    // Keep correlated command ACKs for retry; never report a failed Status as sent.
    if (!reply) { g_publishQueue.dropStatus(); g_asyncResult = AsyncPublishResult::Failure; }
    SerialMon.println("[MQTT] Send failed; reconnect required, command replies retained");
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
