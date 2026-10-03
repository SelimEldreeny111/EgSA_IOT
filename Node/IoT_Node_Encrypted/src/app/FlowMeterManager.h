#ifndef FLOW_METER_MANAGER_H
#define FLOW_METER_MANAGER_H

void initializeConfiguredFlowMeter();
void sampleConfiguredFlowMeter();
/** @brief Sample only TUF/Supmea so command servicing can run between meters. */
void sampleTufFlowMeter();
void sampleSupmeaFlowMeter();

#endif
