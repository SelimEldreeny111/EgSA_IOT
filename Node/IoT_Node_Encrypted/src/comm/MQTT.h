/**
 * @file MQTT.h
 * @brief SIM800L/ESP8266 network and MQTT publish/receive interface.
 *
 * The transport exposes both synchronous PubSubClient publishing and a
 * cooperative asynchronous publish state machine for the ESP-AT path.
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
#include <PubSubClient.h>
#include <TinyGsmClient.h>

#include "../generated/sensor.pb.h"

/** @brief Configure the selected modem interface, pins, and serial port. */
void initializeMqttTransport();
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
/** @brief Publish a pre-encoded frame to a specific topic. @param topic Destination MQTT topic. @param payload Encrypted payload bytes. @param payloadLength Number of bytes to publish. @return True if the broker client accepted the publish. */
bool publishMqttPayload(const char* topic, const uint8_t* payload, size_t payloadLength);
/** @brief Process a received MQTT command frame. @param topic Subscribed topic carrying the frame. @param payload MQTT payload bytes. @param length Payload length in bytes. */
void mqttCallback(char* topic, byte* payload, unsigned int length);

// --- Async (non-blocking) publish FSM ---
// Driven cooperatively from the main loop. While the FSM is busy, the AT bus
// is owned by the FSM and PubSubClient must NOT be invoked.
//
// Usage:
//   if (!isAsyncPublishBusy()) {
//     ensureMqttConnection();
//     mqttLoop();
//     if (timeToPublish) triggerAsyncPublish();
//   }
//   asyncPublishStep();        // advance one tiny step every loop iteration
/** @brief Begin one non-blocking status publish. @return True if the FSM accepted the request. */
bool triggerAsyncPublish();
/** @brief Advance the publish FSM once; call on every main-loop iteration. */
void asyncPublishStep();
/** @brief Test whether the async FSM currently owns the AT serial bus. @return True while PubSubClient calls must be avoided. */
bool isAsyncPublishBusy();

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
