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
bool triggerAsyncPublish();    // returns true if a publish was kicked off
void asyncPublishStep();       // advance the FSM (call every loop iter)
bool isAsyncPublishBusy();     // true while the FSM owns the AT bus

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
