/**
 * @file ValveController.h
 * @brief Bounded bipolar pulses for the Uflow latching valve / TB6612FNG.
 * @warning Reported state is the last completed command, NOT position feedback.
 */
#ifndef VALVE_CONTROLLER_H
#define VALVE_CONTROLLER_H
#include <stdint.h>

/** @brief Wire-compatible node_status values; 0/1 retain their original meaning. */
enum class ValveState : uint8_t { Closed = 0, Open = 1, Unknown = 2, Fault = 3 };

/** @brief Hold STBY and both direction inputs low before any boot/sleep work.
 * @note Does not touch pins in LoRa/gateway/disabled builds or write flash.
 */
void initializeValveSafetyPins();
/** @brief Restore the checksummed last command without actuating the coil.
 * @note Missing/interrupted/corrupt records restore Unknown, not Closed.
 */
void initializeValveController();
/** @brief Apply a commissioned open/close pulse and update node_status.
 * @param open True=ON/open; false=OFF/closed.
 * @return True after a complete timer-terminated pulse or an idempotent command.
 * @details Rejects unconfigured hardware and rapid opposite-direction commands.
 * A TIM10 interrupt disables the bridge even if the foreground stalls. The
 * foreground also checks the configured deadline (1 ms yield granularity);
 * it never feeds IWDG or re-enters MQTT. EEPROM commits are separately bounded
 * by the global watchdog. An independent hardware pulse limiter is required
 * for protection if interrupts/CPU fail while the coil is energized.
 */
bool commandValve(bool open);
#endif
