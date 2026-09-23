#include "devices/SoilMoistureTemperatureSensor.hpp"

#include "config/AppConfig.hpp"
#include "devices/ModbusRtuMaster.hpp"
#include "platform/Stm32Platform.hpp"

void initSoilMoistureTemperatureSensor()
{
  uint16_t values[2]{};
  const ModbusResult result = ModbusBus.readHoldingRegisters(
      AppConfig::kSoilMoistureTemperatureModbusAddress,
      AppConfig::kSoilMoistureTemperatureTemperatureRegister,
      2U,
      values);
  SerialMon.println(result == ModbusResult::Ok
      ? "Soil temperature/moisture sensor ready"
      : "Soil temperature/moisture sensor not detected");
}

SoilMoistureTemperatureData readSoilMoistureTemperature()
{
  SoilMoistureTemperatureData data{};
  uint16_t values[2]{};
  if (ModbusBus.readHoldingRegisters(
          AppConfig::kSoilMoistureTemperatureModbusAddress,
          AppConfig::kSoilMoistureTemperatureTemperatureRegister,
          2U,
          values) != ModbusResult::Ok)
  {
    SerialMon.println("Soil temperature/moisture read failed");
    return data;
  }
  data.temperatureC = static_cast<float>(static_cast<int16_t>(values[0])) /
                      AppConfig::kSoilMoistureTemperatureScale;
  data.moisturePercent = static_cast<float>(values[1]) /
                         AppConfig::kSoilMoistureTemperatureScale;
  data.isValid = true;
  return data;
}

void printSoilMoistureTemperatureData(const SoilMoistureTemperatureData &data)
{
  if (!data.isValid) return;
  SerialMon.print("Soil temperature: "); SerialMon.print(data.temperatureC); SerialMon.println(" C");
  SerialMon.print("Soil moisture: "); SerialMon.print(data.moisturePercent); SerialMon.println(" %");
}
