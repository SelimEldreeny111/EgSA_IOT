/** @file GatewayMqttReceive.h @brief Bounded MQTT stream staging before PubSubClient consumes bytes. */
#ifndef WIOT_GATEWAY_MQTT_RECEIVE_H
#define WIOT_GATEWAY_MQTT_RECEIVE_H

#include <Arduino.h>
#include <Client.h>

/** @brief Expose one complete broker packet at a time and verify command SUBACKs. */
template<size_t Capacity>
class GatewayMqttReceive {
public:
    int available(Client& socket) {
        const uint32_t now = millis();
        if (failed_) return 0;
        if (ready_ > offset_) return static_cast<int>(ready_ - offset_);
        if (ready_) received_ = ready_ = offset_ = 0;
        if ((received_ && now - rxStarted_ >= kDeadlineMs) ||
            (awaiting_ && now - subscribeStarted_ >= kDeadlineMs)) {
            failed_ = true;
            return 0;
        }

        const int count = socket.available();
        for (int i = 0; i < count && !ready_ && !failed_; ++i) {
            const int value = socket.read();
            if (value < 0 || received_ >= Capacity) {
                failed_ = true;
                break;
            }
            if (!received_) rxStarted_ = now;
            bytes_[received_++] = static_cast<uint8_t>(value);
            inspect();
        }
        return static_cast<int>(ready_);
    }

    int read(Client& socket, bool advance) {
        if (!available(socket)) return -1;
        const uint8_t value = bytes_[offset_];
        if (advance) ++offset_;
        return value;
    }

    void transmitted(const uint8_t* packet, size_t size) {
        if (size < 5 || packet[0] != 0x82) return;
        size_t offset = 1;
        while (offset < size && (packet[offset++] & 0x80U)) {}
        if (offset + 2U > size || awaiting_ == kSubscriptions) {
            failed_ = true;
            return;
        }
        if (!awaiting_) subscribeStarted_ = millis();
        mids_[awaiting_++] = word(packet + offset);
    }

    bool failed() const { return failed_; }
    bool ready() const { return !failed_ && awaiting_ == 0; }

private:
    static constexpr uint32_t kDeadlineMs = 8000;
    static constexpr unsigned kSubscriptions = 3;

    static uint16_t word(const uint8_t* bytes) {
        return static_cast<uint16_t>(bytes[0] << 8) | bytes[1];
    }

    void inspect() {
        if (received_ < 2) return;
        size_t header = 1;
        uint32_t length = 0;
        for (;;) {
            if (header == received_) return;
            if (header == 5) { failed_ = true; return; }
            const uint8_t digit = bytes_[header];
            length |= static_cast<uint32_t>(digit & 127U) << ((header - 1U) * 7U);
            ++header;
            if (!(digit & 128U)) break;
        }
        if (length > Capacity - header) { failed_ = true; return; }
        if (received_ != header + length) return;
        const uint8_t* body = bytes_ + header;
        if ((bytes_[0] & 0xF0U) == 0x30U) {
            const uint8_t qos = (bytes_[0] >> 1) & 3U;
            if (qos > 1 || length < 2 || !word(body) ||
                2U + word(body) + 2U * qos > length) {
                failed_ = true;
                return;
            }
            // Retained operator commands/receipts cannot affect a new session.
            if (bytes_[0] & 1U) { received_ = 0; return; }
        } else if (bytes_[0] == 0x90U) {
            if (length != 3 || body[2] != 1) { failed_ = true; return; }
            unsigned i = 0;
            while (i < awaiting_ && mids_[i] != word(body)) ++i;
            if (i == awaiting_) { failed_ = true; return; }
            mids_[i] = mids_[--awaiting_];
        } else if (!((bytes_[0] == 0x20 && length == 2) ||
                     (bytes_[0] == 0x40 && length == 2) ||
                     ((bytes_[0] == 0xD0 || bytes_[0] == 0xC0) && length == 0))) {
            failed_ = true;
            return;
        }
        ready_ = received_;
    }

    uint8_t bytes_[Capacity];
    uint16_t mids_[kSubscriptions] = {};
    size_t received_ = 0, ready_ = 0, offset_ = 0;
    uint32_t rxStarted_ = 0, subscribeStarted_ = 0;
    unsigned awaiting_ = 0;
    bool failed_ = false;
};
#endif
