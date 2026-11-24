#pragma once
#include "Arduino.h"
#define APP_CONFIG_H
#define APP_ROLE_LORA_GATEWAY 2
#define APP_ROLE APP_ROLE_LORA_GATEWAY
#ifndef APP_LORA_COORDINATED
#define APP_LORA_COORDINATED 0
#endif
#ifndef APP_LORA_COORDINATED_NODES
#define APP_LORA_COORDINATED_NODES 1, 2, 3
#endif
#define APP_LORA_GRANT_POLL_MS 30000UL
#ifndef APP_ENABLE_DEBUG
#define APP_ENABLE_DEBUG false
#endif
#ifndef APP_DEBUG_LITE
#define APP_DEBUG_LITE true
#endif
#ifndef APP_DEBUG_RAW_FRAMES
#define APP_DEBUG_RAW_FRAMES false
#endif
#define APP_DEBUG_FULL_ENABLED (APP_ENABLE_DEBUG && !APP_DEBUG_LITE)
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
constexpr bool kEnableCommandAckReplies = APP_ENABLE_COMMAND_ACK_REPLIES;
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
bool decodeEncryptedTelemetryPayload(const uint8_t*, size_t, Telemetry&);
