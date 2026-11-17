#pragma once
#include "Arduino.h"
#define APP_CONFIG_H
#define APP_ENABLE_DEBUG false
#define APP_DEBUG_FULL_ENABLED false
#define APP_DEBUG_LITE false
#define APP_DEBUG_RAW_FRAMES false
#define APP_ENABLE_COMMAND_ACK_REPLIES true
#ifndef APP_ENABLE_GATEWAY_HEARTBEAT
#define APP_ENABLE_GATEWAY_HEARTBEAT true
#endif
#define APP_GATEWAY_HEARTBEAT_SECONDS 60UL
#define APP_GATEWAY_ID 7
#define USE_ESP8266
#define MQTT_NODE_H
#define PACKET_CODEC_H
#define HARDWARE_WATCHDOG_H
#include "../../../src/generated/sensor.pb.h"
namespace AppConfig {
constexpr size_t kCodecBufferSize = 640;
constexpr uint16_t kNodeId = 3;
constexpr uint32_t kLoraAuxPin = 13;
constexpr bool kEnableGatewayHeartbeatLogs = false;
}
extern const char kMqttCompanyTopicPrefix[];
void serviceHardwareWatchdog();
void watchdogDelay(uint32_t);
void reportHardwareWatchdogStatus();
uint32_t hardwareWatchdogResetCount();
uint32_t powerResetCount();
void initializeMqttTransport();
bool connectNetwork();
void initializeMqttClient();
bool ensureMqttConnection();
void mqttLoop();
void asyncPublishStep();
bool mqttCommandWorkPending();
bool isAsyncPublishBusy();
uint32_t mqttConnectionGeneration();
bool publishMqttPayload(const char*, const uint8_t*, size_t);
bool encodeEncryptedMessage(const pb_msgdesc_t*, const void*, uint8_t*, size_t, size_t&);
