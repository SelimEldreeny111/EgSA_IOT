#pragma once
#include "Arduino.h"
#define APP_CONFIG_H
#define APP_HAS_LORA 1
#define APP_ROLE_SENSOR_NODE 1
#define APP_ROLE_LORA_GATEWAY 2
#define APP_ROLE 2
#define APP_LORA_GATEWAY_WOR_TX 0
#define SERIAL_RX_BUFFER_SIZE 512
#define SERIAL_TX_BUFFER_SIZE 512
#define HARDWARE_WATCHDOG_H
#define AS32_CONFIG_H
enum class WatchdogStage {LoraTransmit,LoraAckWait};
void serviceHardwareWatchdog();void serviceHardwareWatchdog(WatchdogStage);
namespace AppConfig {
constexpr size_t kCodecBufferSize=640,kLoraMaxWireFrameBytes=48,kLoraReassemblyContextCount=2,kLoraPendingFrameCount=2;
constexpr uint16_t kNodeId=2,kGatewayNodeId=0,kLoraNetworkId=0x4547;
constexpr uint32_t kLoraRxPin=12,kLoraTxPin=11,kLoraAuxPin=13,kLoraMd0Pin=1,kLoraMd1Pin=2;
constexpr bool kEnableLoraErrorHexLogs=false,kEnableLoraFrameHexLogs=false,kLoraModuleSupportsRssi=false,kEnableAs32RssiDiagnostics=false;
constexpr uint32_t kLoraAuxBusyDetectTimeoutMs=1,kLoraFinalPacketGuardMs=1,kLoraFragmentAckTimeoutMs=100;
constexpr uint32_t kLoraFragmentAssemblyTimeoutMs=60000,kLoraFragmentMaxAttempts=1,kLoraFragmentRetryBackoffMs=1;
constexpr uint32_t kLoraInterPacketGuardMs=1,kLoraPostAckGuardMs=1,kLoraRxAssemblyTimeoutMs=1000;
constexpr uint32_t kLoraTransactionPriorityMs=100,kLoraTxCompleteTimeoutMs=1000,kLoraUartWriteTimeoutMs=1000;
}
namespace AS32Config {
constexpr unsigned kUartBaudRate=9600;constexpr int kSerialMode=0;
struct RssiReadings {bool dataValid=false,environmentValid=false;int16_t dataDbm=0,environmentDbm=0;uint8_t dataRaw=0,environmentRaw=0;};
inline bool queryRssi(HardwareSerial&,uint32_t,RssiReadings&){return false;}
inline bool waitForAuxHigh(uint32_t,uint32_t){return true;}
inline void printConfigSummary(HardwareSerial&){}
inline void applyConfigurationIfEnabled(HardwareSerial&,HardwareSerial&,uint32_t,uint32_t,uint32_t){}
}
