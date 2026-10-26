/** @file MqttTopicRouting.h @brief Strict routing within one company/region. */
#pragma once
#include <stdint.h>
#include <stddef.h>
#include <string.h>

namespace MqttTopicRouting {
/** @brief Restrict configured topic segments to unambiguous ASCII identifiers. */
constexpr bool validSegment(const char* value) {
    if (!value[0]) return false;
    for (size_t i = 0U; value[i]; ++i) {
        const char c = value[i];
        if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
              (c >= '0' && c <= '9') || c == '_' || c == '-')) return false;
    }
    return true;
}
/** @brief Stringification must produce the same canonical decimal ID as payload. */
constexpr bool validNodeLiteral(const char* text) {
    if (text[0] < '1' || text[0] > '9') return false;
    uint32_t value = 0U;
    for (size_t i = 0U; text[i]; ++i) {
        if (i >= 5U || text[i] < '0' || text[i] > '9') return false;
        value = value * 10U + static_cast<uint32_t>(text[i] - '0');
    }
    return value <= 65535U;
}
/** @brief Parse only prefix/node/cmd or prefix/broadcast; reject aliases. */
inline bool parseCommand(const char* topic, const char* prefix,
                         uint16_t& node, bool& broadcast) {
    node = 0U;
    broadcast = false;
    const size_t length = strlen(prefix);
    if (strncmp(topic, prefix, length) != 0 || topic[length] != '/') return false;
    const char* target = topic + length + 1U;
    if (strcmp(target, "broadcast") == 0) { broadcast = true; return true; }
    const char* slash = strchr(target, '/');
    if (!slash || strcmp(slash, "/cmd") != 0 || target[0] == '0') return false;
    const size_t digits = static_cast<size_t>(slash - target);
    if (!digits || digits > 5U) return false;
    uint32_t value = 0U;
    for (size_t i = 0U; i < digits; ++i) {
        if (target[i] < '0' || target[i] > '9') return false;
        value = value * 10U + static_cast<uint32_t>(target[i] - '0');
    }
    if (!value || value > 65535U) return false;
    node = static_cast<uint16_t>(value);
    return true;
}
}
