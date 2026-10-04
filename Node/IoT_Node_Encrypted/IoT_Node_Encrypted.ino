/******************************************************************************


 * 
 * @file      IoT_Node_Encrypted.ino
 * @author    IoT Development Team
 * @version   1.13.0
 * @date      2026-09-12
 * @brief     STM32 sensor-node or LoRa-gateway sketch with RS485 acquisition.
 *
 * @details   This sketch selects a sensor-node or gateway role at build time. It:
 *            - Supports TUF, Supmea, HNDA, and Sondas RS485 sensors
 *            - Sends encrypted telemetry over the selected MQTT or LoRa route
 *            - Handles periodic sampling and transmission cycles
 *            - Provides optional watchdog-safe RTC Standby cycles for LoRa or Wi-Fi nodes
 *            - Provides debug monitoring via hardware serial
 *
 * @section HARDWARE_SETUP
 *   - Debug Interface:  PA3 (RX), PA2 (TX) - SerialMon
 *   - Cellular Modem:   PA12 (TX), PA11 (RX) - SerialAT (SIM800)
 *   - RS485 Sensors:    TUF / Supmea / HNDA / Sondas on Serial1
 *
 * @section SYSTEM_ARCHITECTURE
 *   The system operates in a main loop with two primary timed operations:
 *   1. Sensor sampling at configurable intervals (samplingPeriodMs)
 *   2. Telemetry transmission at configurable intervals (transmissionPeriodMs)
 *
 * @section CONFIGURATION
 *   Modify these parameters in application configuration (AppConfig.h):
 *   - MQTT broker address and port
 *   - Sampling and transmission periods
 *   - Topic subscriptions and publications
 *
 * @warning The application AES-CBC frame has no authentication tag. Encryption
 *          alone does not prove the origin or integrity of a received command.
 *
 ******************************************************************************/

/* ================== INCLUDES ================== */
#include "src/app/IoT_Node.h"
#include "src/app/GatewayApp.h"
#include "src/app/FlowMeterManager.h"
#include "src/app/SensorPollCycle.h"
#include "src/devices/Rs485Bus.h"
#include "src/comm/CommandHandler.h"
#include "src/comm/PacketCodec.h"
#include "src/comm/TelemetryPayload.h"
#include "src/config/AppConfig.h"
#include "src/devices/HndaSensor.h"
#include "src/devices/SondasSensor.h"
#include "src/devices/ValveController.h"
#include "src/platform/Watchdog.h"
#include "src/power/PowerManager.h"
#include "src/radio/LoraLink.h"

/* ==================================== SERIAL ===================================== */
/** @brief Debug UART (RX=PA3, TX=PA2). */
HardwareSerial SerialMon(PA3, PA2);   // Debug interface (RX, TX)

#if APP_HAS_IP_UPLINK
/** @brief IP-modem UART when Wi-Fi or SIM800 is compiled in. */
HardwareSerial SerialAT(PA12, PA11);  // ESP8266/SIM800 modem interface (RX, TX)
#else
// In LoRa-only sensor-node mode, PA12/PA11 belong exclusively to SerialLoRa.
// Keep this unused placeholder away from the LoRa pins because MQTT.cpp still
// references SerialAT at link time even though APP_HAS_IP_UPLINK is disabled.
/** @brief Unused compatibility UART in LoRa-only builds. */
HardwareSerial SerialAT(PB_11, PB_10);
#endif

/** @brief AS32/E32 LoRa module UART. */
HardwareSerial SerialLoRa(AppConfig::kLoraRxPin, AppConfig::kLoraTxPin);
bool g_loraCommandHandledThisPass = false;

#if APP_ROLE == APP_ROLE_SENSOR_NODE && APP_HAS_LORA
/**
 * @brief Process all complete LoRa command frames currently available.
 *
 * Only direct and broadcast command types are accepted. A direct telemetry
 * request must target this node. The watchdog is serviced between complete
 * frames, not inside a blocked receive or command operation.
 */
void pollLoraCommands()
{
  LoraFrame frame;
  while (receiveLoraFrame(frame))
  {
    // Reaching the next complete frame proves that the prior frame was fully
    // handled. A single blocked command/LoRa operation is intentionally not
    // serviced and will be recovered by the IWDG.
    serviceHardwareWatchdog();
    printLoraFrameSummary(frame, "LoRa CMD RX");

    const bool isBroadcastCommand = frame.type == LoraPayloadType::BroadcastCommand;
    const bool isDirectCommand = frame.type == LoraPayloadType::Command;
    if (!isBroadcastCommand && !isDirectCommand)
    {
      SerialMon.println("Sensor node ignored non-command LoRa frame");
      continue;
    }

    CMD_Message cmd = CMD_Message_init_zero;
    if (!decodeEncryptedCommandPayload(frame.payload, frame.payloadLength, cmd))
    {
      SerialMon.println("Sensor node LoRa CMD decode failed");
      continue;
    }

    g_loraCommandHandledThisPass = true;
    if (cmd.cmd_id == CMD_GET_TELEMETRY || cmd.cmd_id == CMD_REMOTE_WAKE)
    {
      if (!isBroadcastCommand && cmd.node_id != AppConfig::kNodeId)
      {
        SerialMon.println("Telemetry request not for this LoRa node");
        continue;
      }

      const bool applied = cmd.cmd_id != CMD_REMOTE_WAKE ||
          handleRemoteWakeCommand(cmd, isBroadcastCommand);
      if (!applied && cmd.request_id == 0U) continue;

      uint8_t telemetryPayload[AppConfig::kCodecBufferSize];
      size_t telemetryPayloadLength = 0;
      if (handleGetTelemetryCommand(&cmd, telemetryPayload,
                                    telemetryPayloadLength, applied) &&
          sendLoraFrame(
              LoraPayloadType::SystemTelemetry,
              AppConfig::kNodeId,
              telemetryPayload,
              telemetryPayloadLength))
      {
        SerialMon.print("Telemetry response sent by LoRa: ");
        SerialMon.print(telemetryPayloadLength);
        SerialMon.println(" bytes");
      }
      else
      {
        SerialMon.println("LoRa telemetry response failed");
      }
      continue;
    }

    const bool applied = handleCommand(cmd, isBroadcastCommand);
    if (cmd.request_id != 0U || cmd.cmd_id == CMD_OPEN_CLOSE_NODE)
    {
      uint8_t ackPayload[AppConfig::kCodecBufferSize];
      size_t ackLength = 0U;
      if (handleGetTelemetryCommand(&cmd, ackPayload, ackLength, applied))
      {
        sendLoraFrame(
            LoraPayloadType::SystemTelemetry,
            AppConfig::kNodeId,
            ackPayload,
            ackLength);
      }
    }
  }
}
#endif

/** @brief Foreground command pump invoked only in receive gaps, never an ISR. */
void serviceNodeCommandsDuringSensorWait()
{
#if APP_HAS_IP_UPLINK
  serviceMqttPriorityCommands();
#endif
#if APP_ROLE == APP_ROLE_SENSOR_NODE && APP_HAS_LORA
  pollLoraCommands();
#endif
}

/* ======================================= SETUP ==================================== */
/** @brief Initialize hardware, application state, transport and power policy.
 * @note Runs once after reset; IWDG is armed before blocking setup operations.
 */
void setup()
{
  initializeValveSafetyPins(); // STBY LOW even on reset-to-Standby early boots.
  // Periodic power mode uses a checksummed reset-to-sleep handoff. This early
  // hook must run before the independent watchdog is armed so the IWDG still
  // protects every active operation without running through long Standby time.
  powerManagerEarlyBoot();

  // Arm the independent hardware watchdog before radio or network setup so a
  // modem/library call that never returns is covered during boot as well.
  initializeHardwareWatchdog();
  serviceHardwareWatchdog(WatchdogStage::Setup);
#if APP_ROLE == APP_ROLE_LORA_GATEWAY
  gatewaySetup();
#else
  setup_Init();
#endif
  initializePowerManagerAfterSetup();
  setRs485CommandService(serviceNodeCommandsDuringSensorWait);
  serviceHardwareWatchdog(WatchdogStage::Setup);
  runHardwareWatchdogSelfTest(WatchdogSelfTestPoint::AfterSetup);
}

/* ================================= LOOP =========================================== */
/**
 * @brief Run one cooperative gateway or sensor-node iteration.
 *
 * A completed iteration is a watchdog progress checkpoint. The sensor-node
 * path polls commands, samples enabled sensors, advances the asynchronous
 * publish state machine, and services the configured power policy.
 */
void loop()
{
  // This checkpoint means the previous Arduino loop iteration completed.
  serviceHardwareWatchdog(WatchdogStage::MainLoop);
  static bool watchdogMainLoopSelfTestChecked = false;
  if (!watchdogMainLoopSelfTestChecked)
  {
    watchdogMainLoopSelfTestChecked = true;
    runHardwareWatchdogSelfTest(WatchdogSelfTestPoint::MainLoop);
  }
#if APP_ROLE == APP_ROLE_LORA_GATEWAY
  gatewayLoop();
  serviceHardwareWatchdog(WatchdogStage::MainLoop);
  return;
#else
  AppRuntimeState& state = appState();

  // Reachable-idle is CPU Sleep, never Standby. Short foreground passes still
  // service radio/MQTT keepalive and IWDG; RX interrupts or SysTick resume WFI.
#if APP_CONTROLLER_POWER_MODE == APP_COMPONENT_MODE_REMOTE_WAKE
  servicePowerManager();
  if (!powerManagerShouldRunApplication())
  {
    powerManagerIdleCpu();
    return;
  }
#endif

  // Command reception and queued replies are the first foreground work.
  // Queued publishes no longer seize the UART or disable TinyGSM reception.
  g_loraCommandHandledThisPass = false;
#if APP_ROLE == APP_ROLE_SENSOR_NODE && APP_HAS_LORA
  pollLoraCommands();
#endif
#if APP_HAS_IP_UPLINK
  beginMqttCommandPriorityPass();
  ensureMqttConnection();
  serviceMqttPriorityCommands();
  asyncPublishStep(); // correlated replies precede routine sensor/status work
#endif

  const bool allowSensorWork = powerManagerAllowsSensorWork();
  bool commandPriority = g_loraCommandHandledThisPass;
#if APP_HAS_IP_UPLINK
  commandPriority = commandPriority || mqttCommandWorkPending();
#endif
  static SensorPollCycle sensorCycle;
  if (allowSensorWork && !commandPriority && !sensorCycle.active() &&
      millis() - state.lastReadMs >= state.samplingPeriodMs)
  {
    state.lastReadMs = millis();
    refreshBatteryVoltage();
    if (AppConfig::kEnableBatteryMonitor)
    {
      SerialMon.print("Battery ADC reading: ");
      SerialMon.print(state.batteryVoltage, 2);
      SerialMon.println(" V (encoded in Status/Telemetry)");
    }
    sensorCycle.begin();
  }

  // Exactly one enabled sensor per pass; RX is serviced between every sensor
  // and in rate-limited Modbus wait gaps. Never publish a half-finished cycle.
  if (allowSensorWork && !commandPriority && sensorCycle.active())
  {
    const auto sensor = sensorCycle.next(AppConfig::kEnableTufSensor,
        AppConfig::kEnableSupmeaSensor, AppConfig::kEnableHndaSensor,
        AppConfig::kEnableSondasSensor);
    switch (sensor)
    {
      case SensorPollCycle::Sensor::Tuf:
        serviceHardwareWatchdog(WatchdogStage::FlowMeterRead);
        sampleTufFlowMeter();
        break;
      case SensorPollCycle::Sensor::Supmea:
        serviceHardwareWatchdog(WatchdogStage::FlowMeterRead);
        sampleSupmeaFlowMeter();
        break;
      case SensorPollCycle::Sensor::Hnda: {
        serviceHardwareWatchdog(WatchdogStage::HndaRead);
        const HndaSensorData data = readHndaSensor();
        updateHndaMetrics(data); printHndaSensorData(data);
        break;
      }
      case SensorPollCycle::Sensor::Sondas: {
        serviceHardwareWatchdog(WatchdogStage::SondasRead);
        const SondasSensorData data = readSondasSensor();
        updateSondasMetrics(data); printSondasSensorData(data);
        break;
      }
      case SensorPollCycle::Sensor::None: break;
    }
    sensorCycle.completed();
    (void)sensorCycle.next(AppConfig::kEnableTufSensor, AppConfig::kEnableSupmeaSensor,
        AppConfig::kEnableHndaSensor, AppConfig::kEnableSondasSensor);
    serviceHardwareWatchdog();
  }

  commandPriority = g_loraCommandHandledThisPass;
#if APP_HAS_IP_UPLINK
  commandPriority = commandPriority || mqttCommandWorkPending();
#endif
  // Only complete sensor snapshots are eligible for a routine Status send.
  if (allowSensorWork &&
      !sensorCycle.active() && !commandPriority && !isAsyncPublishBusy() &&
      (millis() - state.lastSendMs >= state.transmissionPeriodMs))
  {
#if APP_HAS_LORA
    uint8_t payload[AppConfig::kCodecBufferSize];
    size_t payloadLength = 0;
    serviceHardwareWatchdog(WatchdogStage::LoraTransmit);
    const bool telemetryDelivered =
        buildEncryptedStatusPayload(payload, sizeof(payload), payloadLength) &&
        sendLoraFrame(
            LoraPayloadType::StatusTelemetry,
            AppConfig::kNodeId,
            payload,
            payloadLength);
    if (telemetryDelivered)
    {
      SerialMon.print("Telemetry sent by LoRa: ");
      SerialMon.print(payloadLength);
      SerialMon.println(" bytes");
    }
    else
    {
      SerialMon.println("LoRa telemetry send failed");
    }
    notifyPowerManagerTelemetryResult(telemetryDelivered);
    state.lastSendMs = millis();
#else
    if (triggerAsyncPublish())
    {
      state.lastSendMs = millis();
    }
    else
    {
      // MQTT is not ready yet. Schedule the next attempt instead of printing
      // this failure on every loop iteration.
      state.lastSendMs = millis();
    }
#endif
    serviceHardwareWatchdog();
  }

#if APP_HAS_IP_UPLINK
  // Catch commands that arrived during sampling before sending routine data.
  serviceMqttPriorityCommands();
  asyncPublishStep();
  const AsyncPublishResult publishResult = takeAsyncPublishResult();
  if (publishResult != AsyncPublishResult::None)
  {
    notifyPowerManagerTelemetryResult(
        publishResult == AsyncPublishResult::Success);
  }
#endif

#if APP_HAS_LORA
  static uint32_t s_lastLoraDiagnosticsMs = 0U;
  if (millis() - s_lastLoraDiagnosticsMs >= AppConfig::kLoraDiagnosticsPeriodMs)
  {
    s_lastLoraDiagnosticsMs = millis();
    printLoraDiagnostics();
  }
#endif
  servicePowerManager();
  serviceHardwareWatchdog(WatchdogStage::MainLoop);
  powerManagerIdleCpu();
#endif
}

/* =============================================================================
 * END OF FILE - IoT_Node_Encrypted.ino
 * ============================================================================= */
