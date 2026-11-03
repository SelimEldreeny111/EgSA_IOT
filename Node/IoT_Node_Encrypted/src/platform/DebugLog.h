/**
 * @file DebugLog.h
 * @brief Compile-time diagnostics for foreground code; never use in an ISR.
 *
 * APP_ENABLE_DEBUG=false removes calls AND their arguments. Protocol UARTs,
 * telemetry, command acknowledgements and watchdog servicing are independent.
 * The timestamp is Arduino active milliseconds (it pauses in STM32 Stop).
 * Structured events use a bounded stack buffer; no heap allocation is used.
 */
#ifndef WIOT_DEBUG_LOG_H
#define WIOT_DEBUG_LOG_H

#include "../config/AppConfig.h"
// Isolated host harnesses may replace AppConfig.h with a minimal fake.
#ifndef APP_ENABLE_DEBUG
#define APP_ENABLE_DEBUG true
#endif
#ifndef APP_DEBUG_RAW_FRAMES
#define APP_DEBUG_RAW_FRAMES false
#endif
#ifndef APP_LOG_MODULE
#define APP_LOG_MODULE "APP"
#endif

#if APP_ENABLE_DEBUG
#include <Arduino.h>
#include <stdarg.h>
#include <stdio.h>
extern HardwareSerial SerialMon;

namespace WiotDebug {
/** @brief Shared, foreground-only line framing state across translation units. */
struct LineState { bool start = true; };
inline LineState& lineState() { static LineState state; return state; }

/** @brief Start a nonempty line with active ticks, severity and module. */
inline void prefix(const char* module, const char* level = "INFO") {
    if (!lineState().start) return;
    SerialMon.print("[tick_ms="); SerialMon.print(static_cast<unsigned long>(millis()));
    SerialMon.print("]["); SerialMon.print(level); SerialMon.print("][");
    SerialMon.print(module); SerialMon.print("] ");
    lineState().start = false;
}
/** @brief Emit text without allowing embedded newlines to lose their prefix. */
inline void print(const char* module, char value) {
    if (value == '\r') return;
    if (value == '\n') {
        if (!lineState().start) SerialMon.println();
        lineState().start = true;
        return;
    }
    prefix(module); SerialMon.print(value);
}
inline void print(const char* module, const char* value) {
    if (!value) value = "(null)";
    while (*value) print(module, *value++);
}
inline void print(const char* module, char* value) { print(module, static_cast<const char*>(value)); }
template<size_t N> inline void print(const char* module, const char (&value)[N]) {
    print(module, static_cast<const char*>(value));
}
template<class T> inline void print(const char* module, const T& value) {
    prefix(module); SerialMon.print(value);
}
template<class T> inline void print(const char* module, const T& value, int format) {
    prefix(module); SerialMon.print(value, format);
}
inline void println(const char* module) {
    (void)module;
    if (!lineState().start) SerialMon.println();
    lineState().start = true;
}
template<class T> inline void println(const char* module, const T& value) {
    print(module, value); println(module);
}
template<class T> inline void println(const char* module, const T& value, int format) {
    print(module, value, format); println(module);
}
/** @brief Allow the zero-argument println macro in standard C++14. */
struct NewLine {
    const char* module;
    template<class... Args> void operator()(const Args&... args) const { println(module, args...); }
};
/** @brief Write one complete structured event, marking oversized messages. */
inline void event(const char* module, const char* level, const char* format, ...)
    __attribute__((format(printf, 3, 4)));
inline void event(const char* module, const char* level, const char* format, ...) {
    char buffer[256];
    va_list args; va_start(args, format);
    const int count = vsnprintf(buffer, sizeof(buffer), format, args);
    va_end(args);
    println(module); prefix(module, level);
    if (count < 0) print(module, "format_error");
    else {
        print(module, buffer);
        if (static_cast<size_t>(count) >= sizeof(buffer)) print(module, " [truncated]");
    }
    println(module);
}
/** @brief Name protocol commands without pulling protobuf into the logger. */
inline const char* commandName(uint32_t id) {
    switch (id) {
    case 1: return "SRATE"; case 2: return "STRAN"; case 3: return "STIME";
    case 4: return "GOSTM"; case 5: return "VALVE"; case 6: return "WAKE";
    case 7: return "CLEAR_POWER_RESETS"; case 8: return "CLEAR_WDT_RESETS";
    case 9: return "CLEAR_FLASH"; case 10: return "FLASH_STATUS";
    case 11: return "FLASH_LAST"; case 12: return "FLASH_TODAY";
    case 13: return "FLASH_CANCEL"; case 14: return "FLASH_HISTORY_ACK";
    default: return "UNKNOWN";
    }
}
/** @brief Decimal uint64 formatting without newlib-nano %llu support. */
struct Decimal64 {
    char text[21];
    explicit Decimal64(uint64_t value) {
        char reverse[20]; unsigned n = 0;
        do { reverse[n++] = static_cast<char>('0' + value % 10U); value /= 10U; } while (value);
        unsigned i = 0; while (n) text[i++] = reverse[--n];
        text[i] = '\0';
    }
};
/** @brief Describe logical and transport LoRa frame types. */
inline const char* frameName(uint32_t type) {
    switch (type) {
    case 1: return "STATUS"; case 2: return "CMD"; case 3: return "ACK";
    case 4: return "BROADCAST_CMD"; case 5: return "DATA"; case 6: return "WAKE_PROBE";
    case 240: return "FRAGMENT"; case 241: return "FRAGMENT_ACK";
    default: return "UNKNOWN";
    }
}
/** @brief Optional bounded hexadecimal rows; master switch always wins. */
inline void hex(const char* module, const char* label, const uint8_t* data, size_t length) {
    event(module, "TRACE", "%s bytes=%lu", label, static_cast<unsigned long>(length));
    for (size_t offset = 0; offset < length; offset += 16) {
        char row[80];
        int n = snprintf(row, sizeof(row), "%04lX:", static_cast<unsigned long>(offset));
        for (size_t i = offset; i < length && i < offset + 16; ++i)
            n += snprintf(row + n, sizeof(row) - static_cast<size_t>(n), " %02X", data[i]);
        event(module, "TRACE", "%s", row);
    }
}
} // namespace WiotDebug

#define APP_DEBUG_PRINT(...) ::WiotDebug::print(APP_LOG_MODULE, __VA_ARGS__)
#define APP_DEBUG_PRINTLN(...) ::WiotDebug::NewLine{APP_LOG_MODULE}(__VA_ARGS__)
#define APP_DEBUG_PRINTF(...) ::WiotDebug::event(APP_LOG_MODULE, "INFO", __VA_ARGS__)
#define APP_DEBUG_WRITE(value) ::WiotDebug::print(APP_LOG_MODULE, static_cast<char>(value))
#define APP_DEBUG_BEGIN(...) SerialMon.begin(__VA_ARGS__)
#define APP_DEBUG_FLUSH() SerialMon.flush()
#define APP_DEBUG_ONLY(...) do { __VA_ARGS__; } while (0)
#define APP_LOG_INFO(...) ::WiotDebug::event(APP_LOG_MODULE, "INFO", __VA_ARGS__)
#define APP_LOG_WARN(...) ::WiotDebug::event(APP_LOG_MODULE, "WARN", __VA_ARGS__)
#define APP_LOG_ERROR(...) ::WiotDebug::event(APP_LOG_MODULE, "ERROR", __VA_ARGS__)
#else
#define APP_DEBUG_PRINT(...) do {} while (0)
#define APP_DEBUG_PRINTLN(...) do {} while (0)
#define APP_DEBUG_PRINTF(...) do {} while (0)
#define APP_DEBUG_WRITE(...) do {} while (0)
#define APP_DEBUG_BEGIN(...) do {} while (0)
#define APP_DEBUG_FLUSH() do {} while (0)
#define APP_DEBUG_ONLY(...) do {} while (0)
#define APP_LOG_INFO(...) do {} while (0)
#define APP_LOG_WARN(...) do {} while (0)
#define APP_LOG_ERROR(...) do {} while (0)
#endif

#if APP_ENABLE_DEBUG && APP_DEBUG_RAW_FRAMES
#define APP_DEBUG_HEX(...) ::WiotDebug::hex(APP_LOG_MODULE, __VA_ARGS__)
#else
#define APP_DEBUG_HEX(...) do {} while (0)
#endif
#endif
