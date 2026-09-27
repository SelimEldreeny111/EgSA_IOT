/**
 * @file FlowMeterManager.h
 * @brief Product-profile selection and normalization of flow-meter samples.
 */
#ifndef FLOW_METER_MANAGER_H
#define FLOW_METER_MANAGER_H

/** @brief Initialize the enabled TUF or Supmea driver and its period state. */
void initializeConfiguredFlowMeter();
/** @brief Poll the configured meter and publish normalized metrics to app state. */
void sampleConfiguredFlowMeter();

#endif
