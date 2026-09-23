#include "devices/SoilMoistureTemperatureEcSensor.hpp"

#include "config/AppConfig.hpp"
#include "devices/ModbusRtuMaster.hpp"
#include "platform/Stm32Platform.hpp"

void initSoilMoistureTemperatureEcSensor()
{
  uint16_t values[3]{};
  const ModbusResult result = ModbusBus.readHoldingRegisters(
      AppConfig::kSoilMoistureTemperatureEcModbusAddress,
      AppConfig::kSoilMoistureTemperatureEcTemperatureRegister,
      3U,
      values);
  SerialMon.println(result == ModbusResult::Ok ? "Soil EC sensor ready" : "Soil EC sensor not detected");
}

SoilMoistureTemperatureEcData readSoilMoistureTemperatureEc()
{
  SoilMoistureTemperatureEcData data{};
  uint16_t values[3]{};
  if (ModbusBus.readHoldingRegisters(
          AppConfig::kSoilMoistureTemperatureEcModbusAddress,
          AppConfig::kSoilMoistureTemperatureEcTemperatureRegister,
          3U,
          values) != ModbusResult::Ok)
    return data;
  data.temperatureC = static_cast<float>(static_cast<int16_t>(values[0])) /
                      AppConfig::kSoilMoistureTemperatureEcTemperatureScale;
  data.moisturePercent = static_cast<float>(values[1]) /
                         AppConfig::kSoilMoistureTemperatureEcMoistureScale;
  data.electricalConductivity = static_cast<float>(values[2]) /
                                AppConfig::kSoilMoistureTemperatureEcScale;
  data.isValid = true;
  return data;
}

void printSoilMoistureTemperatureEcData(const SoilMoistureTemperatureEcData &data)
{
  if (!data.isValid) return;
  SerialMon.print("EC temperature: "); SerialMon.print(data.temperatureC); SerialMon.println(" C");
  SerialMon.print("EC moisture: "); SerialMon.print(data.moisturePercent); SerialMon.println(" %");
  SerialMon.print("Conductivity: "); SerialMon.println(data.electricalConductivity);
}
