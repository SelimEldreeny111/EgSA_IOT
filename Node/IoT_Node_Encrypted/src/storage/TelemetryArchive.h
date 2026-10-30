/** @file TelemetryArchive.h @brief Sampling, retained Status, memory commands and acknowledged history transfer. */
#ifndef WIOT_TELEMETRY_ARCHIVE_H
#define WIOT_TELEMETRY_ARCHIVE_H
#include "../config/AppConfig.h"
#include "../generated/sensor.pb.h"
#include <stddef.h>
#include <stdint.h>
namespace TelemetryArchive {
constexpr uint32_t Clear=9, Status=10, Last=11, Today=12, Cancel=13, Ack=14;
/** @brief Check the reserved storage command range, including internal persistence ACK. */
inline bool command(uint32_t id) { return id>=Clear&&id<=Ack; }
#if APP_ENABLE_SPI_FLASH && APP_ROLE == APP_ROLE_SENSOR_NODE
/** @brief Probe flash once and start cooperative recovery; does not format unknown media. */
void begin();
/** @brief Advance flash/recovery/count/read/ACK deadlines once, without sending traffic. */
void step();
/** @brief Queue one complete application snapshot with trusted acquisition time, or count a drop. */
void capture();
/** @brief Replace Status measurements/time from the newest committed record.
 * @param status Output; caller refreshes current valve/reset/power fields.
 * @return False when no safely retained, idle, valid snapshot can be read. */
bool storedStatus(Status_Message& status);
/** @brief Apply a direct storage command. ACK14 bypasses ordinary command replay tracking.
 * @param cmd Valid decoded command. @param broadcast Broadcast commands are refused.
 * @return Accepted/result; clear/transfer acceptance does not mean completion. */
bool handle(const CMD_Message& cmd,bool broadcast);
/** @brief Decorate an explicit command reply with memory/history information.
 * @param cmd Original command. @param telemetry Output control or stored sample envelope.
 * @param applied Command acceptance result. */
void reply(const CMD_Message& cmd,Telemetry& telemetry,bool applied);
/** @brief Build one ready history record/end packet; invoke only after higher-priority work.
 * @param data Encrypted-frame destination. @param capacity Buffer bytes.
 * @param length Encoded length on success. @return True when a packet is ready. */
bool packet(uint8_t* data,size_t capacity,size_t& length);
/** @brief Start application-ACK timeout after a send attempt, regardless of local transport success. */
void published(bool success);
/** @brief Prevent sleep during pending journal work or an active history transfer. */
bool blocking();
/** @brief A history job is active; keep scheduled acquisition allowed while sleep is deferred. */
bool transferring();
/** @brief Delay routine uploads until pending snapshot writes/clear/recovery finish. */
bool writePending();
/** @brief Test the trusted retention deadline for an early RTC maintenance wake. */
bool maintenanceDue(uint32_t epoch);
/** @brief Return the recovered persisted expiry, or zero before recovery. */
uint32_t expiry();
/** @brief Enter flash deep power-down if idle; missing/faulted hardware cannot block controller sleep. */
bool prepareSleep();
/** @brief Wake the flash after clocks/interrupts are restored. */
void resume();
#else
inline void begin(){}
inline void step(){}
inline void capture(){}
inline bool storedStatus(Status_Message&){return false;}
inline bool handle(const CMD_Message&,bool){return false;}
inline void reply(const CMD_Message& cmd,Telemetry& telemetry,bool){
    (void)cmd;(void)telemetry;
#if defined(APP_ENABLE_SPI_FLASH)
    if(command(cmd.cmd_id)&&cmd.cmd_id!=Ack){
        telemetry.has_flash_log=true;
        telemetry.flash_log=FlashLogInfo_init_zero; // Disabled; never open the SPI device.
    }
#endif
}
inline bool packet(uint8_t*,size_t,size_t&){return false;}
inline void published(bool){}
inline bool blocking(){return false;}
inline bool transferring(){return false;}
inline bool writePending(){return false;}
inline bool maintenanceDue(uint32_t){return false;}
inline uint32_t expiry(){return 0;}
inline bool prepareSleep(){return true;}
inline void resume(){}
#endif
}
#endif
