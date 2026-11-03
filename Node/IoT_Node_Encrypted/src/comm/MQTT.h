/**
 * @file MQTT.h
 * @brief SIM800L/ESP8266 network and MQTT publish/receive interface.
 *
 * TinyGSM owns AT operations for both modems. A cooperative priority queue
 * orders command replies before periodic Status; individual driver calls block.
 */
#ifndef MQTT_NODE_H
#define MQTT_NODE_H

//#define TINY_GSM_DEBUG SerialMon
#define TINY_GSM_USE_GPRS true

#include <Arduino.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

#include "../config/AppConfig.h"
// The application master switch also suppresses optional TinyGSM tracing.
#if !APP_ENABLE_DEBUG
#undef TINY_GSM_DEBUG
#undef DUMP_AT_COMMANDS
#endif
#include <PubSubClient.h>
#include <TinyGsmClient.h>

#include "../generated/sensor.pb.h"

/** @brief Configure the selected modem interface, pins, and serial port. */
void initializeMqttTransport();
/** @brief Close/reset/reinitialize the active modem after the first failed-network budget; preserve queued command replies. */
void resetMqttTransportForNetworkRecovery();
/** @brief Pulse active modem RST and request fast IWDG recovery after the second budget. Never returns. */
[[noreturn]] void resetModemAndControllerForNetworkFailure();
/** @brief Quiesce the active modem before controller standby. @param timeoutMs Maximum time allowed for shutdown. @return True when transport is safe to sleep. */
bool prepareMqttTransportForPowerDown(uint32_t timeoutMs);
/** @brief Restore modem operation when a planned standby entry is cancelled. */
void restoreMqttTransportAfterPowerDownAbort();
/** @brief Bind MQTT callbacks and configure the broker client. */
void initializeMqttClient();
/** @brief Connect or reconnect the broker within the configured retry policy. @return True when MQTT is connected. */
bool ensureMqttConnection();
/** @brief Service MQTT keepalive and inbound packets on the active transport. */
void mqttLoop();
/** @brief Establish the selected Wi-Fi or cellular network link. @return True when the underlying network is usable. */
bool connectNetwork();
/** @brief Query the selected modem's current network status. @return True when network connectivity is available. */
bool checkNetworkStatus();
/** @brief Encode and publish the latest status snapshot over MQTT. */
void publishTelemetry();
/** @brief Publish a pre-encoded frame to a specific topic. @param topic Destination MQTT topic. @param payload Encrypted payload bytes. @param payloadLength Number of bytes to publish. @return True only after a full local driver write; server receipt is not confirmed. */
bool publishMqttPayload(const char* topic, const uint8_t* payload, size_t payloadLength);
/** @brief Process a received MQTT command frame. @param topic Subscribed topic carrying the frame. @param payload MQTT payload bytes. @param length Payload length in bytes. */
void mqttCallback(char* topic, byte* payload, unsigned int length);

// Queue a periodic Status and send through the same PubSubClient/TinyGSM path
// as command replies. Driver calls are bounded but may block until AT response.
// "Busy" means queued/outstanding work, NOT permission to skip MQTT reception.
/** @brief Queue a periodic Status snapshot. @return False when pending, disconnected or command-priority work blocks it. */
bool triggerAsyncPublish();
/** @brief Attempt one queued send, command FIFO first, through TinyGSM. */
void asyncPublishStep();
/** @brief Check queued work or active modem call; this must not gate reception. */
bool isAsyncPublishBusy();
/** @brief Start a foreground priority pass and receive one MQTT packet first. */
void beginMqttCommandPriorityPass();
/** @brief Receive commands without reconnecting or transmitting queued replies. */
void serviceMqttPriorityCommands();
/** @brief Commands received this pass or queued replies outrank sensor/status work. */
bool mqttCommandWorkPending();

/** @brief Final outcome of the most recent asynchronous publish attempt. */
enum class AsyncPublishResult : uint8_t
{
  None,
  Success,
  Failure,
};

/** @brief Consume the last completed async result. @return Success, Failure, or None; a completed result is cleared after this call. */
AsyncPublishResult takeAsyncPublishResult();

extern TinyGsm modem;

#endif
