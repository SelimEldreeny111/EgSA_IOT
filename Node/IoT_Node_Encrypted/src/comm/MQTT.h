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

void initializeMqttTransport();
bool prepareMqttTransportForPowerDown(uint32_t timeoutMs);
void restoreMqttTransportAfterPowerDownAbort();
void initializeMqttClient();
bool ensureMqttConnection();
void mqttLoop();
bool connectNetwork();
bool checkNetworkStatus();
void publishTelemetry();
bool publishMqttPayload(const char* topic, const uint8_t* payload, size_t payloadLength);
void mqttCallback(char* topic, byte* payload, unsigned int length);

// Queue a periodic Status and send through the same PubSubClient/TinyGSM path
// as command replies. Driver calls are bounded but may block until AT response.
// "Busy" means queued/outstanding work, NOT permission to skip MQTT reception.
bool triggerAsyncPublish();
void asyncPublishStep();
bool isAsyncPublishBusy();
/** @brief Start a foreground priority pass and receive one MQTT packet first. */
void beginMqttCommandPriorityPass();
/** @brief Receive commands without reconnecting or transmitting queued replies. */
void serviceMqttPriorityCommands();
/** @brief Commands received this pass or queued replies outrank sensor/status work. */
bool mqttCommandWorkPending();

enum class AsyncPublishResult : uint8_t
{
  None,
  Success,
  Failure,
};

// Returns a completed async publish result once, then clears it to None.
AsyncPublishResult takeAsyncPublishResult();

extern TinyGsm modem;

#endif
