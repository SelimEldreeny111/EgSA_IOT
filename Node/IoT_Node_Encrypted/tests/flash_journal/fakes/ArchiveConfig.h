#pragma once
#include "Arduino.h"
#define APP_CONFIG_H
#define APP_ENABLE_SPI_FLASH true
#define APP_ROLE_SENSOR_NODE 1
#define APP_ROLE 1
#ifndef APP_FLASH_RETENTION_SECONDS
#define APP_FLASH_RETENTION_SECONDS 120UL
#endif
#define APP_STATE_H
#define RTC_HELPERS_H
#define SENSOR_PAYLOAD_MAPPER_H
#define PACKET_CODEC_H
#include "../../../src/generated/sensor.pb.h"
namespace AppConfig {
constexpr uint32_t kNodeId=2,kFlashMosiPin=7,kFlashMisoPin=6,kFlashSckPin=5,kFlashCsPin=4;
constexpr uint32_t kFlashSpiHz=4000000,kFlashExpectedJedec=0x016017,kFlashCapacityBytes=8388608;
constexpr uint32_t kFlashRetentionSeconds = APP_FLASH_RETENTION_SECONDS;
constexpr uint32_t kFlashHistoryAckTimeoutMs=60000,kFlashHistoryMaxAttempts=3;
}
struct AppRuntimeState {uint32_t lastTimestamp=0,samplingPeriodMs=10000,transmissionPeriodMs=60000;};
AppRuntimeState& appState();
uint32_t getEpochTime(); bool isRtcTrusted();
struct CalendarPeriodKeys {uint32_t day=20261030;};
bool getCalendarPeriodKeys(uint32_t,CalendarPeriodKeys&);
void populateSensorPayloadFields(Telemetry&,const AppRuntimeState&);
bool encodeEncryptedMessage(const pb_msgdesc_t*,const void*,uint8_t*,size_t,size_t&);
