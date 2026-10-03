#pragma once
#include "Arduino.h"
#define APP_CONFIG_H
#define USE_SIM800
#define MODEM_BAUD 9600
#define APP_ROLE_SENSOR_NODE 1
#define APP_ROLE_LORA_GATEWAY 2
#define APP_ROLE 1
#define APP_HAS_IP_UPLINK 1
#define HARDWARE_WATCHDOG_H
enum class WatchdogStage { ModemInitialization, MqttStatus, MqttConnect, MqttService, MqttPublish, PowerTransition };
void serviceHardwareWatchdog();
void serviceHardwareWatchdog(WatchdogStage);
void watchdogDelay(uint32_t);
#define RTC_HELPERS_H
uint32_t getEpochTime();
#define APP_STATE_H
struct AppRuntimeState {};
#define SENSOR_PAYLOAD_MAPPER_H
#define PACKET_CODEC_H
#include "../../../src/generated/sensor.pb.h"
bool decodeEncryptedCommandPayload(const uint8_t*,size_t,CMD_Message&);
namespace AppConfig {
constexpr size_t kMqttPacketBufferSize=640, kCodecBufferSize=416;
constexpr uint16_t kMqttPort=1883, kMqttKeepAliveSeconds=45, kMqttSocketTimeoutSeconds=8;
constexpr uint32_t kMqttReconnectIntervalMs=3000;
constexpr bool kEnablePublishTimingLogs=false, kEnableVerboseMqttLogs=false;
constexpr uint16_t kNodeId=1;
}
extern const char kMqttServer[],kMqttClientId[],kMqttCommandTopic[],kMqttBroadcastTopic[];
extern const char kMqttPublishTopicStatus[],kMqttPublishTopicTlm[];
