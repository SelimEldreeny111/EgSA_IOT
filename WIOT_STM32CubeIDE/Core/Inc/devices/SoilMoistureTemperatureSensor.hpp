#ifndef WIOT_SOIL_MOISTURE_TEMPERATURE_SENSOR_HPP
#define WIOT_SOIL_MOISTURE_TEMPERATURE_SENSOR_HPP

struct SoilMoistureTemperatureData
{
  float temperatureC;
  float moisturePercent;
  bool isValid;
};

void initSoilMoistureTemperatureSensor();
SoilMoistureTemperatureData readSoilMoistureTemperature();
void printSoilMoistureTemperatureData(const SoilMoistureTemperatureData &data);

#endif
