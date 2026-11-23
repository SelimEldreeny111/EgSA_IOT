/** @file ReplyDiagnostics.h @brief Correlated debug output for command and history replies. */
#ifndef WIOT_REPLY_DIAGNOSTICS_H
#define WIOT_REPLY_DIAGNOSTICS_H

#include "../generated/sensor.pb.h"

/** @brief Print the reply fields and, when enabled, the exact encrypted payload.
 * @param direction TX for the node or RX for the gateway.
 * @param reply Telemetry as encoded by the node or decoded by the gateway.
 * @param payload The encrypted application envelope at this end of the link.
 * @param length Size of the encrypted envelope.
 */
void logReplyData(const char* direction, const Telemetry& reply, const uint8_t* payload, size_t length);

#endif
