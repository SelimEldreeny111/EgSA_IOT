/**
 * @file IoT_Node.h
 * @brief Sensor-node startup orchestration.
 */
#ifndef IOT_NODE_H
#define IOT_NODE_H

#include "AppState.h"
#include "../comm/MQTT.h"
#include "../devices/RTC.h"

/** @brief Initialize hardware, application state, sensors, and selected transport. */
void setup_Init();

#endif
