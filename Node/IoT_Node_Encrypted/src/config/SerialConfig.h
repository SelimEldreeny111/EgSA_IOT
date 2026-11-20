/** @file SerialConfig.h @brief Local commissioning console on the debug UART. */
#pragma once

#include "AppConfig.h"

namespace SerialConfig {
#if APP_ENABLE_SERIAL_CONFIG
void begin(bool offerBootWindow, bool invalidSavedConfig = false);
bool service();
#else
inline void begin(bool, bool = false) {}
inline bool service() { return false; }
#endif
}
