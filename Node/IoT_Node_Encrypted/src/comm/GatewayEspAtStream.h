/** @file GatewayEspAtStream.h @brief Incremental ESP-AT socket receive on the gateway UART. */
#ifndef WIOT_GATEWAY_ESP_AT_STREAM_H
#define WIOT_GATEWAY_ESP_AT_STREAM_H

#include <Arduino.h>
#include <cstring>

/**
 * @brief Separate ESP-AT text from binary +IPD records as bytes arrive.
 *
 * TinyGSM still owns AT requests and their responses. MQTT reads only the binary
 * FIFO. The radio loop can pump the UART without launching an AT transaction or
 * waiting for an advertised but incomplete record. Uses CIPMUX=1, socket 0,
 * and the modem's active receive format +IPD,0,<length>:<bytes>.
 */
class GatewayEspAtStream : public Stream {
    template<size_t Capacity>
    struct Fifo {
        uint8_t bytes[Capacity];
        size_t head = 0, count = 0;
        bool put(uint8_t byte) {
            if (count == Capacity) return false;
            bytes[(head + count) % Capacity] = byte;
            ++count;
            return true;
        }
        int front() const { return count ? bytes[head] : -1; }
        int take() {
            const int value = front();
            if (count) { head = (head + 1U) % Capacity; --count; }
            return value;
        }
        void clear() { head = count = 0; }
    };

    class SocketInput : public Stream {
    public:
        explicit SocketInput(GatewayEspAtStream& owner) : owner_(owner) {}
        int available() override { owner_.pump(); return owner_.network_.count; }
        int read() override { return owner_.network_.take(); }
        int peek() override { return owner_.network_.front(); }
        size_t write(uint8_t) override { return 0; }
        void flush() override {}
    private:
        GatewayEspAtStream& owner_;
    };

public:
    explicit GatewayEspAtStream(Stream& uart) : uart_(uart), socket_(*this) {}
    Stream& socketInput() { return socket_; }
    const char* fault() const { return fault_; }
    /** @brief Drain a bounded UART slice without AT commands or MQTT callbacks. */
    void serviceUart() { pump(); }
    int readStagedAtByte() { return text_.take(); }
    bool takeWifiDisconnect() {
        const bool lost = wifiDisconnected_;
        wifiDisconnected_ = false;
        return lost;
    }

    /** @brief Announced and observed payload bytes for the current +IPD record. */
    struct IpdProgress {
        uint32_t announced;
        uint32_t received;
    };
    IpdProgress ipdProgress() const {
        return state_ == State::Payload ? IpdProgress{length_, length_ - remaining_}
                                        : IpdProgress{0, 0};
    }
    void resetInput() {
        text_.clear();
        atLineLength_ = 0;
        wifiDisconnected_ = false;
        resetSocket();
    }
    void resetSocket() {
        network_.clear();
        matched_ = digits_ = length_ = remaining_ = 0;
        state_ = State::Text;
        fault_ = nullptr;
    }
    int available() override { pump(); return text_.count; }
    int read() override {
        if (!text_.count) pump();
        return text_.take();
    }
    int peek() override {
        if (!text_.count) pump();
        return text_.front();
    }
    size_t write(uint8_t byte) override { return uart_.write(byte); }
    size_t write(const uint8_t* bytes, size_t size) override { return uart_.write(bytes, size); }
    void flush() override { uart_.flush(); }

private:
    enum class State : uint8_t { Text, Mux, Separator, Length, Payload };
    void emitText(uint8_t byte) {
        // Notice link changes without removing URCs from TinyGSM's input.
        if (byte == '\n') {
            if (atLineLength_ < sizeof(atLine_)) {
                atLine_[atLineLength_] = '\0';
                if (!strcmp(atLine_, "WIFI DISCONNECT")) wifiDisconnected_ = true;
                if (!strcmp(atLine_, "WIFI GOT IP")) wifiDisconnected_ = false;
            }
            atLineLength_ = 0;
        } else if (byte != '\r' && atLineLength_ < sizeof(atLine_)) {
            atLine_[atLineLength_++] = static_cast<char>(byte);
        }
        // A full AT text FIFO would leave TinyGSM with an ambiguous response.
        if (!text_.put(byte)) fault_ = "esp_at_text_overflow";
    }
    void pump() {
        if (fault_) return;
        const uint32_t now = millis();
        if ((state_ != State::Text || matched_) && now - lastByteMs_ >= 1000U && uart_.available() <= 0)
            fault_ = "esp_ipd_timeout";
        // A bounded slice preserves foreground LoRa service, even on a busy UART.
        for (size_t i = 0; i < 256U && !fault_ && uart_.available() > 0; ++i) {
            const int value = uart_.read();
            if (value < 0) { fault_ = "esp_uart_short_read"; break; }
            consume(static_cast<uint8_t>(value));
            lastByteMs_ = now;
        }
    }
    void consume(uint8_t byte) {
        switch (state_) {
        case State::Text: {
            static const char prefix[] = "+IPD,";
            if (byte == prefix[matched_]) {
                if (++matched_ == sizeof(prefix) - 1U) {
                    matched_ = 0;
                    state_ = State::Mux;
                }
                return;
            }
            for (size_t i = 0; i < matched_; ++i) emitText(prefix[i]);
            matched_ = 0;
            if (byte == '+') matched_ = 1;
            else emitText(byte);
            break;
        }
        case State::Mux:
            if (byte != '0') { fault_ = "esp_ipd_socket"; break; }
            state_ = State::Separator;
            break;
        case State::Separator:
            if (byte != ',') { fault_ = "esp_ipd_header"; break; }
            length_ = digits_ = 0;
            state_ = State::Length;
            break;
        case State::Length:
            if (byte == ':' && digits_ && length_) {
                remaining_ = length_;
                state_ = State::Payload;
            } else if (byte >= '0' && byte <= '9' && digits_ < 5U) {
                ++digits_;
                length_ = 10U * length_ + (byte - '0');
                if (length_ > 65535U) fault_ = "esp_ipd_length";
            } else fault_ = "esp_ipd_header";
            break;
        case State::Payload:
            --remaining_;
            if (!network_.put(byte)) { fault_ = "esp_socket_rx_overflow"; break; }
            if (!remaining_) state_ = State::Text;
            break;
        }
    }

    Stream& uart_;
    SocketInput socket_;
    Fifo<512> text_{};
    Fifo<2048> network_{};
    State state_ = State::Text;
    uint32_t lastByteMs_ = 0;
    uint32_t length_ = 0, remaining_ = 0;
    size_t matched_ = 0, digits_ = 0;
    const char* fault_ = nullptr;
    char atLine_[24] = {};
    size_t atLineLength_ = 0;
    bool wifiDisconnected_ = false;
};
#endif
