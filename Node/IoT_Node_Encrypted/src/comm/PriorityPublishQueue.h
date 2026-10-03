/** @file PriorityPublishQueue.h
 * @brief Fixed-capacity FIFO command replies ahead of one periodic snapshot.
 */
#ifndef PRIORITY_PUBLISH_QUEUE_H
#define PRIORITY_PUBLISH_QUEUE_H
#include <stddef.h>
#include <stdint.h>
#include <cstring>

template<size_t PayloadCapacity, size_t ReplyCapacity>
class PriorityPublishQueue {
public:
    struct Packet { uint8_t bytes[PayloadCapacity]; size_t length = 0U; };
    bool replyFull() const { return replyCount_ == ReplyCapacity; }
    bool hasReplies() const { return replyCount_ != 0U; }
    bool hasStatus() const { return status_.length != 0U; }
    bool pending() const { return hasReplies() || hasStatus(); }
    bool pushReply(const uint8_t* bytes, size_t length) {
        if (replyFull() || !valid(bytes, length)) return false;
        Packet& packet = replies_[(replyHead_ + replyCount_) % ReplyCapacity];
        memcpy(packet.bytes, bytes, length); packet.length = length; ++replyCount_;
        return true;
    }
    bool pushStatus(const uint8_t* bytes, size_t length) {
        if (hasStatus() || !valid(bytes, length)) return false;
        memcpy(status_.bytes, bytes, length); status_.length = length;
        return true;
    }
    const Packet& front() const { return hasReplies() ? replies_[replyHead_] : status_; }
    void pop() {
        if (hasReplies()) { replyHead_ = (replyHead_ + 1U) % ReplyCapacity; --replyCount_; }
        else dropStatus();
    }
    void dropStatus() { status_.length = 0U; }
private:
    static bool valid(const uint8_t* bytes, size_t length) {
        return bytes && length && length <= PayloadCapacity;
    }
    Packet replies_[ReplyCapacity];
    Packet status_;
    size_t replyHead_ = 0U, replyCount_ = 0U;
};
#endif
