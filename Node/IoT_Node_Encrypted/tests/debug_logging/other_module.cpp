#define APP_LOG_MODULE "RADIO"
#include "../../src/platform/DebugLog.h"
void completePartialLine() {
    APP_DEBUG_PRINTLN("complete");
    APP_LOG_WARN("cross_module_event");
}
