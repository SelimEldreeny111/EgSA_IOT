// Compile the REAL configuration with symbolic GPIO IDs, no production secrets.
#define PB0 16
#define PB1 17
#define PB2 18
#define PB7 23
#define PB8 24
#define PB9 25
#define PB15 31
#define PC13 45
#define PA0 0
#define PA8 8
#define PA9 9
#define PA10 10
#define PA11 11
#define PA12 12
#include "../../src/config/AppConfig.h"
static_assert(AppConfig::kValveAin1Pin == PB9 && AppConfig::kValveAin2Pin == PB15,
    "Agreed polarity pins must remain PB9/PB15");
static_assert(AppConfig::kOpenCloseNodeGpio == PC13 && !AppConfig::kOpenCloseNodeActiveLow,
    "Original valve pin must be active-high TB6612 STBY");
static_assert(AppConfig::kEnableOpenCloseNodeOutput ==
    bool(APP_HAS_SENSORS && APP_ENABLE_LATCHING_VALVE && !APP_HAS_LORA),
    "No valve GPIO access on disabled/gateway/PC13 AUX builds");
static_assert(AppConfig::kValveEepromAddress == 212U, "Preserve EEPROM layout");
#ifndef TEST_COMMISSIONED
static_assert(AppConfig::kValveOpenPulseMs == 0 && AppConfig::kValveClosePulseMs == 0 &&
    !AppConfig::kValvePolarityConfirmed, "Factory defaults must inhibit actuation");
#endif
