/** @file GatewayDelivery.h @brief Delivery proof types shared by the radio and MQTT schedulers. */
#ifndef WIOT_GATEWAY_DELIVERY_H
#define WIOT_GATEWAY_DELIVERY_H
#include <stddef.h>
#include <stdint.h>
#include "../generated/sensor.pb.h"

enum GatewayDeliveryPhase : uint32_t {
    GatewayQueued = 1, GatewayDispatched, GatewayDecodeFailed, GatewayQueueFull,
    GatewayRadioFailed, ServerPersisted, GatewayQueueExpired, GatewaySuperseded, GatewayReplyQueued
};

/** @brief Diagnostic correlation of exact wire bytes, independent of decryption. */
inline uint64_t frameFingerprint(const uint8_t* data, size_t length) {
    uint64_t fingerprint = UINT64_C(14695981039346656037);
    for (size_t i = 0; i < length; ++i) {
        fingerprint ^= data[i];
        fingerprint *= UINT64_C(1099511628211);
    }
    return fingerprint;
}

struct GatewayCommand {
    Gateway_Delivery proof;
    uint32_t receivedMs, commandId;
    bool broadcast, superseded;
    uint8_t payload[49];
};

const GatewayCommand* gatewayPendingCommand();
void completeGatewayCommand(GatewayDeliveryPhase phase);
bool takeGatewayReceipt(Gateway_Delivery& proof);
void reportGatewayReply(const Gateway_Delivery& commandProof);
void serviceGatewayDeliveryEvents();
#endif
