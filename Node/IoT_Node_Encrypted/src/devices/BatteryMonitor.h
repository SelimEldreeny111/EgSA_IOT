/**
 * @file BatteryMonitor.h
 * @brief ADC sampling and resistor-divider conversion for node supply voltage.
 */
#ifndef BATTERY_MONITOR_H
#define BATTERY_MONITOR_H

/** @brief Configure the battery ADC input and discard its first conversion. */
void initializeBatteryMonitor();
/** @brief Average ADC samples and apply divider/calibration factors. @return Battery or supply voltage in volts; zero when monitoring is disabled. */
float readBatteryVoltage();

#endif
