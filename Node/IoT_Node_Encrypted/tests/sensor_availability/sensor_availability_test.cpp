// Exercise the real flow manager, application state and protobuf mapper.
#include "../../src/app/AppState.h"
#include "../../src/app/FlowMeterManager.h"
#include "../../src/app/SupmeaPeriodAccumulator.h"
#include "../../src/devices/TufSensor.h"
#include "../../src/devices/SupmeaSensor.h"
#include "../../src/comm/SensorPayloadMapper.h"
#include <cassert>
#include <iostream>

HardwareSerial SerialMon;
static TufSensorData tuf{};
static SupmeaSensorData supmea{};
static unsigned accumulatorCalls=0;
static uint64_t previousForward=0, accumulated=0;
bool isRtcTrusted() { return true; }
uint32_t getEpochTime() { return 1800000000U; }
void serviceHardwareWatchdog(WatchdogStage) {}
float readBatteryVoltage() { return 3.7f; }
uint32_t powerManagerMode() { return 1; }
uint32_t powerManagerState() { return 1; }
uint32_t powerManagerWakeRemainingSeconds() { return 0; }
void initializeTufSensor() {}
void initializeSupmeaSensor() {}
void initializeSupmeaPeriodAccumulator() {}
TufSensorData readTufSensor() { return tuf; }
SupmeaSensorData readSupmeaSensor() { return supmea; }
void printTufSensorData(const TufSensorData&) {}
void printSupmeaSensorData(const SupmeaSensorData&) {}
SupmeaPeriodResult updateSupmeaPeriodAccumulator(uint64_t forward, uint32_t, bool) {
    ++accumulatorCalls;
    if (previousForward) accumulated += forward-previousForward;
    previousForward=forward;
    return {accumulated, accumulated, accumulated, FlowPeriodQuality::Valid, true};
}
template<class M> void checkZero(const M& msg) {
    assert(msg.flow_rate==0 && msg.velocity==0);
    assert(msg.flow_rate_per_day==0 && msg.flow_rate_per_month==0 && msg.flow_rate_per_year==0);
    assert(msg.forward_total_liters==0 && msg.reverse_total_liters==0 && msg.net_total_liters==0);
    assert(!msg.flow_live_valid && !msg.flow_period_totals_valid && !msg.flow_cumulative_totals_valid);
    assert(msg.soil_temperature==0 && msg.soil_moisture==0 && !msg.soil_moisture_temp_valid);
    assert(msg.ec_temperature==0 && msg.ec_moisture==0 && msg.electrical_conductivity==0 && !msg.soil_moisture_temp_ec_valid);
    if (msg.has_secondary_flow_meter) {
        assert(msg.secondary_flow_meter.flow_rate==0 && msg.secondary_flow_meter.flow_rate_per_day==0);
        assert(msg.secondary_flow_meter.forward_total_liters==0 && !msg.secondary_flow_meter.flow_live_valid);
    }
}
int main() {
    initializeConfiguredFlowMeter();
    // Good sample followed by a complete timeout, then recovery.
    tuf={12,2,3,4,5,0,true,true,true,true,true,true};
    supmea={100,2,98,36,1,0,0,3,0,0,0,0,true,true,true};
    sampleConfiguredFlowMeter();
    updateHndaMetrics({22,55,true}); updateSondasMetrics({23,56,1500,true});
    Status_Message good=Status_Message_init_zero;
    populateSensorPayloadFields(good,appState());
    assert(good.soil_temperature==22 && good.ec_temperature==23);
    if (AppConfig::kEnableTufSensor) assert(good.flow_rate==12);
    else if (AppConfig::kEnableSupmeaSensor) assert(good.flow_rate==36);
    const unsigned callsBefore=accumulatorCalls;
    tuf={}; supmea={}; sampleConfiguredFlowMeter();
    // Even an invalid driver result containing junk cannot leak old readings.
    updateHndaMetrics({999,999,false}); updateSondasMetrics({999,999,999,false});
    assert(accumulatorCalls==callsBefore); // no artificial zero counter reset
    assert(appState().tufFlow.flowRateM3h==0 && appState().supmeaFlow.flowRateM3h==0);
    Status_Message status=Status_Message_init_zero; Telemetry telemetry=Telemetry_init_zero;
    populateSensorPayloadFields(status,appState()); populateSensorPayloadFields(telemetry,appState());
    checkZero(status); checkZero(telemetry);
    // Restore a real counter: lost communication must not discard history.
    tuf={8,1,6,7,8,0,true,true,true,true,true,true};
    supmea={101,2,99,40,2,0,0,3,0,0,0,0,true,true,true};
    sampleConfiguredFlowMeter();
    updateHndaMetrics({24,60,true}); updateSondasMetrics({25,61,1600,true});
    populateSensorPayloadFields(status,appState());
    assert(status.soil_temperature==24 && status.ec_temperature==25);
    if (AppConfig::kEnableSupmeaSensor) {
        assert(accumulated==1000);
        assert(appState().supmeaFlow.volumeTodayM3==1);
    }
    // Partial reads invalidate only the failed group, never its old numbers.
    tuf.liveValid=false; tuf.periodTotalsValid=true;
    supmea.liveValid=true; supmea.totalsValid=false;
    sampleConfiguredFlowMeter();
    populateSensorPayloadFields(status,appState());
    if (AppConfig::kEnableTufSensor) {
        assert(status.flow_rate==0 && !status.flow_live_valid);
        assert(status.flow_rate_per_day==6 && status.flow_period_totals_valid);
    } else if (AppConfig::kEnableSupmeaSensor) {
        assert(status.flow_rate==40 && status.flow_live_valid);
        assert(status.flow_rate_per_day==0 && !status.flow_period_totals_valid);
    }
    // Defense in depth: stale values with false validity must encode as zeros.
    appState().tufFlow={}; appState().supmeaFlow={};
    appState().tufFlow.flowRateM3h=999; appState().tufFlow.volumeTodayM3=999;
    appState().supmeaFlow.forwardTotalLiters=999;
    appState().hnda={999,999,false}; appState().sondas={999,999,999,false};
    populateSensorPayloadFields(status,appState()); checkZero(status);
    std::cout << "PASS sensor availability profile " << TEST_FLOW_CONFIG << '\n';
}
