#include "devices/FlowMeter.hpp"

#include "config/AppConfig.hpp"
#include "devices/ModbusRtuMaster.hpp"
#include "platform/Stm32Platform.hpp"

#include <cstring>

namespace
{
float wordsToFloat(uint16_t lowWord, uint16_t highWord)
{
  const uint32_t raw = static_cast<uint32_t>(highWord) << 16U | lowWord;
  float value;
  std::memcpy(&value, &raw, sizeof(value));
  return value;
}

bool readWithRetry(uint16_t address, uint16_t count, uint16_t *values)
{
  for (uint8_t attempt = 0U; attempt < 2U; ++attempt)
  {
    if (ModbusBus.readHoldingRegisters(
            AppConfig::kFlowMeterModbusAddress, address, count, values) == ModbusResult::Ok)
      return true;
    Platform::delayMs(100U);
  }
  return false;
}
}

void initFlowMeter()
{
  uint16_t error = 0U;
  SerialMon.println(readWithRetry(0x0047U, 1U, &error)
      ? "TUF-2000B Modbus sensor ready"
      : "TUF-2000B not detected");
}

FlowData readAllParameters()
{
  FlowData data{};
  uint16_t values[6]{};
  if (!readWithRetry(0x0000U, 6U, values)) return data;
  data.flowRate = wordsToFloat(values[0], values[1]);
  data.velocity = wordsToFloat(values[4], values[5]);
  data.isValid = true;
  if (readWithRetry(0x007CU, 4U, values))
  {
    data.flowRate_per_day = wordsToFloat(values[0], values[1]);
    data.flowRate_per_month = wordsToFloat(values[2], values[3]);
  }
  if (readWithRetry(0x0090U, 4U, values))
  {
    const int32_t integerPart = static_cast<int32_t>(
        static_cast<uint32_t>(values[1]) << 16U | values[0]);
    data.flowRate_per_year = static_cast<float>(integerPart) +
                            wordsToFloat(values[2], values[3]);
  }
  if (readWithRetry(0x0047U, 1U, values)) data.errorCode = values[0];
  return data;
}

void printFlowData(const FlowData &data)
{
  if (!data.isValid)
  {
    SerialMon.println("TUF-2000B read failed");
    return;
  }
  SerialMon.print("Flow rate: "); SerialMon.print(data.flowRate); SerialMon.println(" m3/h");
  SerialMon.print("Velocity: "); SerialMon.print(data.velocity); SerialMon.println(" m/s");
  SerialMon.print("Day total: "); SerialMon.print(data.flowRate_per_day); SerialMon.println(" m3");
}
