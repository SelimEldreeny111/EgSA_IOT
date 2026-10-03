/**
 * @file FlowMeterManager.h
 * @brief Independent TUF/Supmea acquisition and flow-meter normalization.
 */
#ifndef FLOW_METER_MANAGER_H
#define FLOW_METER_MANAGER_H

/** @brief Initialize each enabled flow-meter driver and Supmea period state. */
void initializeConfiguredFlowMeter();
/** @brief Poll both enabled flow meters and update their separate runtime metrics. */
void sampleConfiguredFlowMeter();
/** @brief Sample TUF alone so the foreground can service commands between meters. */
void sampleTufFlowMeter();
/** @brief Sample Supmea alone and advance RTC consumption for a valid acquisition. */
void sampleSupmeaFlowMeter();

#endif
