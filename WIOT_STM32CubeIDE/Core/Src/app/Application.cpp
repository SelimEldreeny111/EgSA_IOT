#include "app/Application.hpp"

#include "app/AppState.hpp"
#include "app/GatewayApp.hpp"
#include "comm/CommandHandler.hpp"
#include "comm/PacketCodec.hpp"
#include "comm/TelemetryPayload.hpp"
#include "config/AppConfig.hpp"
#include "devices/BatteryMonitor.hpp"
#include "devices/FlowMeter.hpp"
#include "devices/Rtc.hpp"
#include "devices/SoilMoistureTemperatureEcSensor.hpp"
#include "devices/SoilMoistureTemperatureSensor.hpp"
#include "generated/sensor.pb.h"
#include "platform/Stm32Platform.hpp"
#include "radio/LoraLink.hpp"

namespace
{
#if APP_ROLE == APP_ROLE_SENSOR_NODE
void pollLoraCommands()
{
  LoraFrame frame{};
  while (receiveLoraFrame(frame))
  {
    printLoraFrameSummary(frame, "LoRa CMD RX");
    const bool broadcast = frame.type == LoraPayloadType::BroadcastCommand;
    if (!broadcast && frame.type != LoraPayloadType::Command)
    {
      SerialMon.println("Sensor node ignored non-command LoRa frame");
      continue;
    }

    CMD_Message command = CMD_Message_init_zero;
    if (!decodeEncryptedCommandPayload(frame.payload, frame.payloadLength, command))
    {
      SerialMon.println("LoRa command decrypt/decode failed");
      continue;
    }

    if (command.cmd_id == CMD_GET_TELEMETRY)
    {
      if (!broadcast && command.node_id != AppConfig::kNodeId)
      {
        SerialMon.println("Telemetry request is for another node");
        continue;
      }
      uint8_t payload[AppConfig::kCodecBufferSize]{};
      size_t length = 0U;
      if (handleGetTelemetryCommand(&command, payload, length) &&
          sendLoraFrame(
              LoraPayloadType::SystemTelemetry,
              AppConfig::kNodeId,
              payload,
              length))
      {
        SerialMon.println("System telemetry response sent by LoRa");
      }
      else
      {
        SerialMon.println("System telemetry response failed");
      }
      continue;
    }
    handleCommand(command, broadcast);
  }
}

void sensorNodeSetup()
{
  (void)SerialMon.begin(115200U);
  Platform::delayMs(300U);
  SerialMon.println("\r\n=============== EgSA WIOT Sensor Node ===============");
  SerialMon.println("Native STM32F401RCT6 HAL firmware (no Arduino runtime)");

  AppRuntimeState &state = appState();
  state.nodeStatus = 0U;
  refreshEnabledSensorSummary();
  initializeBatteryMonitor();
  refreshBatteryVoltage();
  SerialMon.print("Battery voltage: "); SerialMon.print(state.batteryVoltage, 2); SerialMon.println(" V");

  initializeRtc();
  if (!isRtcTimeSet())
  {
    setRtcEpoch(AppConfig::kDefaultRtcEpoch);
    SerialMon.println("RTC initialized to 2024-01-01 00:00:00 UTC");
  }
  else
  {
    printRtcDateTime();
  }

  initializeLoraLink();
  Platform::gpioWrite(AppConfig::kRs485DirectionPin, GPIO_PIN_RESET);
  if (AppConfig::kEnableFlowMeter) initFlowMeter();
  if (AppConfig::kEnableSoilMoistureTemperatureSensor) initSoilMoistureTemperatureSensor();
  if (AppConfig::kEnableSoilMoistureTemperatureEcSensor) initSoilMoistureTemperatureEcSensor();
  state.lastReadMs = Platform::millis();
  state.lastSendMs = Platform::millis();
  SerialMon.println("Sensor-node initialization complete");
}

void sampleSensors()
{
  AppRuntimeState &state = appState();
  refreshBatteryVoltage();
  SerialMon.print("Battery ADC: "); SerialMon.print(state.batteryVoltage, 2); SerialMon.println(" V");
  if (AppConfig::kEnableFlowMeter)
  {
    const FlowData data = readAllParameters();
    updateFlowMetrics(data);
    printFlowData(data);
  }
  if (AppConfig::kEnableSoilMoistureTemperatureSensor)
  {
    const SoilMoistureTemperatureData data = readSoilMoistureTemperature();
    updateSoilMoistureTemperatureMetrics(data);
    printSoilMoistureTemperatureData(data);
  }
  if (AppConfig::kEnableSoilMoistureTemperatureEcSensor)
  {
    const SoilMoistureTemperatureEcData data = readSoilMoistureTemperatureEc();
    updateSoilMoistureTemperatureEcMetrics(data);
    printSoilMoistureTemperatureEcData(data);
  }
}

void sensorNodeLoop()
{
  AppRuntimeState &state = appState();
  serviceLoraInput();
  pollLoraCommands();
  const uint32_t now = Platform::millis();
  if (now - state.lastReadMs >= state.samplingPeriodMs)
  {
    state.lastReadMs = now;
    sampleSensors();
  }
  if (now - state.lastSendMs >= state.transmissionPeriodMs)
  {
    uint8_t payload[AppConfig::kCodecBufferSize]{};
    size_t length = 0U;
    const bool sent = buildEncryptedStatusPayload(payload, sizeof(payload), length) &&
                      sendLoraFrame(
                          LoraPayloadType::StatusTelemetry,
                          AppConfig::kNodeId,
                          payload,
                          length);
    SerialMon.println(sent ? "Encrypted status sent by LoRa" : "LoRa status send failed");
    state.lastSendMs = Platform::millis();
  }

  static uint32_t lastDiagnosticsMs = 0U;
  if (now - lastDiagnosticsMs >= AppConfig::kLoraDiagnosticsPeriodMs)
  {
    lastDiagnosticsMs = now;
    printLoraDiagnostics();
  }
}
#endif
}

namespace Application
{
void setup()
{
#if APP_ROLE == APP_ROLE_LORA_GATEWAY
  GatewayApp::setup();
#else
  sensorNodeSetup();
#endif
}

void loop()
{
#if APP_ROLE == APP_ROLE_LORA_GATEWAY
  GatewayApp::loop();
#else
  sensorNodeLoop();
#endif
}
}
