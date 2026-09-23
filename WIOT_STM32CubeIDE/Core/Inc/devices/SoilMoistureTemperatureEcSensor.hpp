#ifndef WIOT_SOIL_MOISTURE_TEMPERATURE_EC_SENSOR_HPP
#define WIOT_SOIL_MOISTURE_TEMPERATURE_EC_SENSOR_HPP

struct SoilMoistureTemperatureEcData
{
  float temperatureC;
  float moisturePercent;
  float electricalConductivity;
  bool isValid;
};

void initSoilMoistureTemperatureEcSensor();
SoilMoistureTemperatureEcData readSoilMoistureTemperatureEc();
void printSoilMoistureTemperatureEcData(const SoilMoistureTemperatureEcData &data);

#endif
