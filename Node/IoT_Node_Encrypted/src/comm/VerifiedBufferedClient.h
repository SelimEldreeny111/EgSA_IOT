/** @file VerifiedBufferedClient.h
 * @brief Coalesce MQTT packet writes and verify the underlying TinyGSM send.
 * Buffer acceptance is not modem acceptance: callers must finishPacket().
 */
#ifndef VERIFIED_BUFFERED_CLIENT_H
#define VERIFIED_BUFFERED_CLIENT_H
#include <Arduino.h>
#include <Client.h>
#include <cstring>
#include "GatewayMqttReceive.h"

template<size_t Capacity, bool GuardReceive = false>
class VerifiedBufferedClient : public Client {
public:
    explicit VerifiedBufferedClient(Client& wrapped) : wrapped_(wrapped) {}
    size_t write(uint8_t byte) override { return write(&byte, 1U); }
    size_t write(const uint8_t* bytes, size_t size) override {
        size_t accepted = 0U;
        while (size && !failed_ && !stopped_) {
            if (length_ == Capacity && (receiveOnly_ || !flushBuffer())) break;
            const size_t space = Capacity - length_;
            const size_t take = size < space ? size : space;
            memcpy(buffer_ + length_, bytes, take);
            length_ += take; bytes += take; size -= take; accepted += take;
        }
        return accepted;
    }
    /** @return True only if every buffered byte was accepted by the driver. */
    bool finishPacket() {
        const bool sent = flushBuffer();
        if (!receiveOnly_ && !stopped_) wrapped_.flush();
        return sent;
    }
    void flush() override { (void)finishPacket(); }
    bool writeFailed() const { return failed_; }
    void setReceiveStream(Stream& input) { input_ = &input; }
    void setReceiveOnly(bool enabled) { receiveOnly_ = enabled; }
    const char* receiveFault() const { return GuardReceive ? receive_.fault() : nullptr; }
    bool transportStopped() const { return stopped_; }
    size_t rxStagedBytes() const { return receive_.receivedBytes(); }
    unsigned rxPacketType() const { return receive_.packetType(); }
    bool stageReceiveOnlyPacket() {
        return input_ ? receive_.available(*input_) > 0 : receive_.stagedBytes() > 0;
    }
    bool subscriptionsReady() const { return !GuardReceive || receive_.ready(); }
    int available() override {
        if (!flushBuffer()) return 0;
        if (!GuardReceive) return wrapped_.available();
        if (receiveOnly_ && !input_) return receive_.stagedBytes();
        return receive_.available(receiveStream());
    }
    int read() override {
        if (!flushBuffer()) return -1;
        if (!GuardReceive) return wrapped_.read();
        if (receiveOnly_ && !input_ && !receive_.stagedBytes()) return -1;
        return receive_.read(receiveStream(), true);
    }
    int read(uint8_t* bytes, size_t size) override {
        if (!flushBuffer()) return -1;
        if (!GuardReceive) return wrapped_.read(bytes, size);
        size_t count = 0;
        const size_t ready = static_cast<size_t>(available());
        while (count < size && count < ready) bytes[count++] = receive_.read(receiveStream(), true);
        return count ? static_cast<int>(count) : -1;
    }
    int peek() override {
        if (!flushBuffer()) return -1;
        if (!GuardReceive) return wrapped_.peek();
        if (receiveOnly_ && !input_ && !receive_.stagedBytes()) return -1;
        return receive_.read(receiveStream(), false);
    }
    uint8_t connected() override { return failed_ || stopped_ ? 0U : wrapped_.connected(); }
    operator bool() override { return !failed_ && !stopped_ && static_cast<bool>(wrapped_); }
    int connect(IPAddress ip, uint16_t port) override {
        reset(); return wrapped_.connect(ip, port);
    }
    int connect(const char* host, uint16_t port) override {
        reset(); return wrapped_.connect(host, port);
    }
    void stop() override {
        // Never retransmit the tail of a partially sent MQTT packet.
        length_ = 0U;
        // A gateway stop can be called by PubSubClient from its receive loop.
        // Dispose of that stream without spending an AT timeout on it.
        if (GuardReceive) stopped_ = true;
        else wrapped_.stop();
    }
private:
    Stream& receiveStream() { return input_ ? *input_ : static_cast<Stream&>(wrapped_); }
    bool flushBuffer() {
        if (failed_ || stopped_) return false;
        if (receiveOnly_ || !length_) return true;
        const size_t expected = length_;
        length_ = 0U;
        failed_ = wrapped_.write(buffer_, expected) != expected;
        if (GuardReceive && !failed_) receive_.transmitted(buffer_, expected);
        return !failed_;
    }
    void reset() { length_ = 0U; failed_ = stopped_ = false; if (GuardReceive) receive_ = {}; }
    Client& wrapped_;
    uint8_t buffer_[Capacity];
    size_t length_ = 0U;
    bool failed_ = false;
    bool stopped_ = false, receiveOnly_ = false;
    Stream* input_ = nullptr;
    GatewayMqttReceive<GuardReceive ? Capacity : 1> receive_{};
};
#endif
