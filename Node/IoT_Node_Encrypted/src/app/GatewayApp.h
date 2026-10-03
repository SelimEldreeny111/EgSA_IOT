/**
 * @file GatewayApp.h
 * @brief LoRa-to-MQTT gateway lifecycle entry points.
 */
#ifndef GATEWAY_APP_H
#define GATEWAY_APP_H

/** @brief Initialize the gateway radio, network transport, and routing state. */
void gatewaySetup();
/** @brief Service radio ingress, MQTT forwarding, and downlink commands. */
void gatewayLoop();

#endif
