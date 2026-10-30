/** @file NorFlash.h @brief Bounded asynchronous NOR interface used by the telemetry journal. */
#ifndef WIOT_NOR_FLASH_H
#define WIOT_NOR_FLASH_H
#include <stdint.h>
#include <stddef.h>
namespace WiotStorage {
/** @brief Completion state; no API waits for a program/erase busy interval. */
enum class Poll : uint8_t { Ready, Busy, Failed };
/** @brief Exclusive flash device; program calls must fit within one 256-byte page. */
class NorFlash {
public:
    /** @brief Destroy the device abstraction without implicitly erasing data. */
    virtual ~NorFlash() = default;
    /** @brief Identify/wake the device. @return False for missing/unsupported/busy hardware. */
    virtual bool begin() = 0;
    /** @brief Synchronous bounded SPI read; never waits for WIP to clear.
     * @param address Byte offset. @param data Destination. @param size Byte count.
     * @return True only when every byte was transferred. */
    virtual bool read(uint32_t address, uint8_t* data, size_t size) = 0;
    /** @brief Start one page program; caller retains no dependency on the data buffer after return.
     * @param address Byte offset. @param data Source bytes. @param size Count within one page.
     * @return Acceptance only; poll() must subsequently confirm completion. */
    virtual bool program(uint32_t address, const uint8_t* data, size_t size) = 0;
    /** @brief Start one 4 KiB erase. @param sectorAddress Aligned byte offset.
     * @return Acceptance only; poll() must confirm completion. */
    virtual bool erase(uint32_t sectorAddress) = 0;
    /** @brief Check WIP/errors/deadline once. @return Ready, Busy or terminal Failed. */
    virtual Poll poll() = 0;
    /** @brief Return cached manufacturer/type/capacity ID, without a transaction. */
    virtual uint32_t jedec() const = 0;
    /** @brief Enter device deep power-down only if no operation is pending. */
    virtual bool sleep() = 0;
    /** @brief Leave deep power-down and satisfy the device wake timing. */
    virtual bool wake() = 0;
};
}
#endif
