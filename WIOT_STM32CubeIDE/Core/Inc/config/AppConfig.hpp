#ifndef WIOT_APP_CONFIG_HPP
#define WIOT_APP_CONFIG_HPP

#include "platform/Stm32Platform.hpp"

#include <cstddef>
#include <cstdint>

#define APP_ROLE_SENSOR_NODE 1
#define APP_ROLE_LORA_GATEWAY 2
#ifndef APP_ROLE
#define APP_ROLE APP_ROLE_SENSOR_NODE
#endif

#if APP_ROLE == APP_ROLE_SENSOR_NODE
#define APP_HAS_SENSORS 1
#define APP_HAS_LORA 1
#define APP_HAS_IP_UPLINK 0
#elif APP_ROLE == APP_ROLE_LORA_GATEWAY
#define APP_HAS_SENSORS 0
#define APP_HAS_LORA 1
#define APP_HAS_IP_UPLINK 1
#else
#error "APP_ROLE must be APP_ROLE_SENSOR_NODE or APP_ROLE_LORA_GATEWAY"
#endif

namespace AppConfig
{
constexpr uint16_t kNodeId = 3U;
constexpr uint16_t kGatewayNodeId = 0U;
constexpr uint16_t kSensorId = 1U;
constexpr uint16_t kLoraNetworkId = 0x4547U;

extern const Platform::GpioPin kLoraMd0Pin;
extern const Platform::GpioPin kLoraMd1Pin;
extern const Platform::GpioPin kLoraAuxPin;
extern const Platform::GpioPin kRs485DirectionPin;

constexpr bool kEnableFlowMeter = false;
constexpr bool kEnableSoilMoistureTemperatureSensor = true;
constexpr bool kEnableSoilMoistureTemperatureEcSensor = false;
constexpr bool kEnableBatteryMonitor = APP_HAS_SENSORS != 0;
constexpr bool kEnableOpenCloseNodeOutput = false;
constexpr bool kOpenCloseNodeActiveLow = true;

constexpr uint16_t kSensorMaskFlowMeter = 0x0001U;
constexpr uint16_t kSensorMaskSoilMoistureTemperature = 0x0002U;
constexpr uint16_t kSensorMaskSoilMoistureTemperatureEc = 0x0004U;
constexpr uint8_t kFlowMeterModbusAddress = 0x02U;
constexpr uint8_t kSoilMoistureTemperatureModbusAddress = 0x01U;
constexpr uint16_t kSoilMoistureTemperatureTemperatureRegister = 0x0000U;
constexpr uint16_t kSoilMoistureTemperatureMoistureRegister = 0x0001U;
constexpr float kSoilMoistureTemperatureScale = 10.0F;
constexpr uint8_t kSoilMoistureTemperatureEcModbusAddress = 0x03U;
constexpr uint16_t kSoilMoistureTemperatureEcTemperatureRegister = 0x0000U;
constexpr uint16_t kSoilMoistureTemperatureEcMoistureRegister = 0x0001U;
constexpr uint16_t kSoilMoistureTemperatureEcRegister = 0x0002U;
constexpr float kSoilMoistureTemperatureEcTemperatureScale = 10.0F;
constexpr float kSoilMoistureTemperatureEcMoistureScale = 10.0F;
constexpr float kSoilMoistureTemperatureEcScale = 1.0F;

constexpr uint8_t kBatterySampleCount = 16U;
constexpr uint16_t kBatteryAdcMaximumCount = 4095U;
constexpr float kBatteryDividerHighOhms = 21600.0F;
constexpr float kBatteryDividerLowOhms = 9800.0F;
constexpr float kBatteryAdcReferenceVolts = 3.3F;
constexpr float kBatteryCalibrationFactor = 1.0F;

constexpr size_t kAesBlockSize = 16U;
constexpr size_t kIvLength = 16U;
constexpr size_t kCodecBufferSize = 256U;
constexpr uint8_t kProtocolVersion = 1U;
constexpr uint32_t kDefaultSamplingPeriodMs = 10000UL;
constexpr uint32_t kDefaultTransmissionPeriodMs = 15000UL;
constexpr uint32_t kDefaultRtcEpoch = 1704067200UL;
constexpr uint32_t kMinimumRateSeconds = 10UL;

constexpr uint16_t kMqttPort = 1883U;
constexpr uint16_t kMqttKeepAliveSeconds = 45U;
constexpr uint32_t kMqttReconnectIntervalMs = 3000UL;
constexpr bool kEnableGatewayHeartbeatLogs = true;

constexpr bool kLoraModuleSupportsRssi = false;
constexpr bool kEnableAs32RssiDiagnostics = false;
constexpr uint32_t kLoraDiagnosticsPeriodMs = 5000UL;
constexpr bool kEnableLoraFrameHexLogs = true;
constexpr bool kEnableLoraErrorHexLogs = true;
constexpr size_t kLoraMaxWireFrameBytes = 48U;
constexpr uint32_t kLoraAuxBusyDetectTimeoutMs = 200UL;
constexpr uint32_t kLoraInterPacketGuardMs = 500UL;
constexpr uint32_t kLoraFinalPacketGuardMs = 200UL;
constexpr uint32_t kLoraFragmentAckTimeoutMs = 12000UL;
constexpr uint8_t kLoraFragmentMaxAttempts = 3U;
constexpr uint32_t kLoraFragmentRetryBackoffMs = 250UL;
constexpr uint32_t kLoraPostAckGuardMs = 500UL;
constexpr uint32_t kLoraRxAssemblyTimeoutMs = 4000UL;
constexpr uint32_t kLoraTransactionPriorityMs = 15000UL;
constexpr uint32_t kLoraFragmentAssemblyTimeoutMs = 60000UL;
constexpr size_t kLoraReassemblyContextCount = 8U;
constexpr size_t kLoraPendingFrameCount = 4U;
constexpr uint32_t kLoraUartWriteTimeoutMs = 3000UL;
constexpr uint32_t kLoraTxCompleteTimeoutMs = 10000UL;
}

extern const char kWifiSsid[];
extern const char kWifiPassword[];
extern const char kMqttServer[];
extern const char kMqttClientId[];
extern const char kMqttCompanyTopicPrefix[];
extern const char kMqttPublishTopicStatus[];
extern const char kMqttPublishTopicTlm[];
extern const char kMqttCommandTopic[];
extern const char kMqttBroadcastTopic[];
extern const char kMqttGatewayCommandWildcardTopic[];

#endif
