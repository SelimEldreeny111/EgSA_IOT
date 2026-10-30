/** @file S25Fl064l.h @brief Single-I/O 3.3-V S25FL064L driver with bounded asynchronous completion. */
#ifndef WIOT_S25FL064L_H
#define WIOT_S25FL064L_H
#include "NorFlash.h"
#include <SPI.h>
namespace WiotStorage {
/** @brief Dedicated SPI1 flash. Unknown JEDEC IDs and protected-write errors fail closed. */
class S25Fl064l final : public NorFlash {
public:
    /** @brief Bind dedicated SPI pins, rate and the required 24-bit JEDEC identity. */
    S25Fl064l(uint32_t mosi,uint32_t miso,uint32_t sck,uint32_t cs,uint32_t hz,uint32_t expected);
    /** @copydoc NorFlash::begin */
    bool begin() override;
    /** @copydoc NorFlash::read */
    bool read(uint32_t address,uint8_t* data,size_t size) override;
    /** @copydoc NorFlash::program */
    bool program(uint32_t address,const uint8_t* data,size_t size) override;
    /** @copydoc NorFlash::erase */
    bool erase(uint32_t sectorAddress) override;
    /** @copydoc NorFlash::poll */
    Poll poll() override;
    /** @copydoc NorFlash::jedec */
    uint32_t jedec() const override {return id_;}
    /** @copydoc NorFlash::sleep */
    bool sleep() override;
    /** @copydoc NorFlash::wake */
    bool wake() override;
private:
    SPIClass spi_;
    SPISettings settings_;
    uint32_t cs_, expected_,id_=0,started_=0,timeout_=0;
    bool available_=false,asleep_=false,pending_=false,failed_=false;
    void select(); ///< Begin SPI transaction and assert CS#.
    void release(); ///< Deassert CS# and release the bus.
    void command(uint8_t opcode); ///< Send a standalone instruction.
    uint8_t status(uint8_t opcode); ///< Read one status-register byte.
    void address(uint8_t opcode,uint32_t value); ///< Send instruction plus explicit 32-bit big-endian SPI address.
    bool writeEnabled(); ///< Wake, reject WIP, issue WREN and confirm WEL.
};
}
#endif
