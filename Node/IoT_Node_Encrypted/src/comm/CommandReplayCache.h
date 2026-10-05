/** @file CommandReplayCache.h
 * @brief Bounded, RAM-only duplicate suppression for correlated ordinary commands.
 * @details Not authentication or persistent anti-replay. Eight recent intents survive
 * ordinary Sleep/STOP, not reboot/Standby. Request zero retains legacy behavior.
 * WAKE retains PowerManager's separate expiry-aware duplicate policy.
 */
#pragma once
#include <stdint.h>

/** @brief Remembers accepted/rejected results without repeating side effects. */
class CommandReplayCache {
public:
  /** @brief Lookup result; conflicting reuse of an ID is rejected. */
  enum Match { Missing, Duplicate, Conflict };
  /** @brief Find ID and compare its complete command/target tuple. */
  Match lookup(uint32_t request, uint32_t node, uint32_t command, uint64_t data,
               bool broadcast, bool& result) const {
    if (!request) return Missing;
    for (const Entry& entry : entries_) {
      if (entry.request != request) continue;
      if (entry.node != node || entry.command != command || entry.data != data ||
          entry.broadcast != broadcast) return Conflict;
      result = entry.result;
      return Duplicate;
    }
    return Missing;
  }
  /** @brief FIFO eviction after eight distinct nonzero requests; zero is ignored. */
  void remember(uint32_t request, uint32_t node, uint32_t command, uint64_t data,
                bool broadcast, bool result) {
    if (!request) return;
    entries_[next_] = {request, node, command, data, broadcast, result};
    next_ = static_cast<uint8_t>((next_ + 1U) % 8U);
  }
private:
  /** @brief A full command tuple and its original application result. */
  struct Entry {
    uint32_t request;
    uint32_t node;
    uint32_t command;
    uint64_t data;
    bool broadcast;
    bool result;
  };
  Entry entries_[8] = {};
  uint8_t next_ = 0;
};
