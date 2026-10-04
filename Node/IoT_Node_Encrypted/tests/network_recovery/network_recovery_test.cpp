// Compile the actual connection functions in this TU so their private counter
// and Wi-Fi helpers can be checked without exposing new production APIs.
#include "../../src/app/IoT_Node.cpp"
#include <cassert>
#include <iostream>
#include <stdexcept>

uint32_t testNow=5000;
bool tickOnMillis=false;
HardwareSerial SerialMon,SerialAT;
TinyGsm modem(SerialAT);
TestEeprom EEPROM;
const char kApn[]="test-apn", kNetworkUser[]="", kNetworkPassword[]="";
const char kWifiSsid[]="configured", kWifiPassword[]="test-password";
static int modemResets=0, controllerResets=0;
void serviceHardwareWatchdog() {} void serviceHardwareWatchdog(WatchdogStage) {}
void watchdogDelay(uint32_t ms) { delay(ms); }
void resetMqttTransportForNetworkRecovery() { ++modemResets; }
[[noreturn]] void resetModemAndControllerForNetworkFailure() { ++controllerResets; throw std::runtime_error("reset both"); }
void initializeMqttTransport() {} void initializeMqttClient() {}
void reportHardwareWatchdogStatus() {} void refreshEnabledSensorSummary() {}
void refreshBatteryVoltage() {} void initializeBatteryMonitor() {}
void initializeConfiguredFlowMeter() {} void initializeHndaSensor() {} void initializeSondasSensor() {}
void initializeRs485Bus() {} void initializeRtc() {}
bool isRtcTimeSet() { return true; } void setRtcEpoch(uint32_t) {} void printRtcDateTime() {}
AppRuntimeState& appState() { static AppRuntimeState state; return state; }

int main(int argc,char** argv) {
    assert(argc==2); const std::string scenario=argv[1];
#if defined(USE_ESP8266)
    // Do not wait for a console operator in automated tests. This does not
    // alter production provisioning or saved-credential selection behavior.
    g_wifiProvisioningPromptUsed=true;
#endif
    if(scenario=="offline" || scenario=="gprs_offline") {
        modem.registrationSuccess=scenario=="gprs_offline";
        bool reset=false;
        try { for(int rounds=0;rounds<20;rounds++) assert(!connectNetwork()); }
        catch(const std::runtime_error&) { reset=true; }
        assert(reset && modemResets==1 && controllerResets==1);
        assert(g_networkRetryPolicy.stage()==2 && g_networkRetryPolicy.failures()==10);
#if defined(USE_ESP8266)
        assert(modem.joinCalls==20);
#else
        assert(modem.registrationCalls==20);
        assert(modem.gprsCalls==(scenario=="gprs_offline"?20:0));
#endif
    } else if(scenario=="success_first_stage" || scenario=="success_second_stage") {
        const int failures=scenario=="success_first_stage"?9:19;
        for(int i=0;i<failures;i++) recordNetworkConnectionFailure();
        assert(modemResets==(failures==19?1:0) && controllerResets==0);
        modem.registrationSuccess=modem.gprsSuccess=modem.joinSuccess=true;
        assert(connectNetwork());
        assert(g_networkRetryPolicy.stage()==1 && g_networkRetryPolicy.failures()==0);
        const int previousResets=modemResets;
        for(int i=0;i<9;i++) recordNetworkConnectionFailure();
        assert(modemResets==previousResets && controllerResets==0);
        recordNetworkConnectionFailure(); assert(modemResets==previousResets+1);
#if defined(USE_ESP8266)
    } else if(scenario=="wifi_fallback") {
        assert(saveWifiCredentials("saved","saved-password"));
        assert(!connectNetwork());
        assert(modem.joinedSsids==std::vector<std::string>({"configured","configured","saved","saved"}));
        assert(g_networkRetryPolicy.failures()==4 && modemResets==0);
        // Successful compiled credentials still take precedence and do not
        // replace the separately persisted fallback.
        modem.joinSuccess=true; assert(connectNetwork());
        assert(modem.joinedSsids.back()=="configured");
        StoredWifiCredentials saved={}; assert(loadSavedWifiCredentials(saved));
        assert(std::string(saved.ssid)=="saved");
        assert(g_networkRetryPolicy.failures()==0);
    } else if(scenario=="wifi_same_fallback") {
        assert(saveWifiCredentials(kWifiSsid,kWifiPassword));
        assert(!connectNetwork()); assert(modem.joinCalls==2);
        assert(g_networkRetryPolicy.failures()==2);
#endif
    } else if(scenario=="custom_limit") {
        NetworkRetryPolicy policy(3); using Action=NetworkRetryPolicy::Action;
        assert(policy.failedAttempt()==Action::Retry);
        assert(policy.failedAttempt()==Action::Retry);
        assert(policy.failedAttempt()==Action::ResetModem);
        assert(policy.failedAttempt()==Action::Retry);
        assert(policy.failedAttempt()==Action::Retry);
        assert(policy.failedAttempt()==Action::ResetControllerAndModem);
        policy.connected(); assert(policy.stage()==1 && policy.failures()==0);
    } else assert(false);
    std::cout << "PASS actual connection recovery: " << scenario << '\n';
}
