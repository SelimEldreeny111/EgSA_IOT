/** @file CachedTinyGsmClient.h
 * @brief Avoid repeated blocking socket-status AT commands during MQTT polling.
 */
#ifndef CACHED_TINY_GSM_CLIENT_H
#define CACHED_TINY_GSM_CLIENT_H
#include <TinyGsmClient.h>

/** @brief Socket state tracked by TinyGSM receive URCs and connection operations.
 * @note Targets TinyGSM 0.12's protected GsmClient::sock_connected member.
 * available(), read(), and write() remain the original TinyGSM operations.
 * MQTT PINGRESP timeout detects silently lost connections.
 */
class CachedTinyGsmClient : public TinyGsmClient {
public:
    explicit CachedTinyGsmClient(TinyGsm& modem) : TinyGsmClient(modem) {}
    uint8_t connected() override { return sock_connected; }
    operator bool() override { return connected() != 0U; }
};
#endif
