/** @file WorWakeInput.h @brief Arm GPIO EXTI on UART RX without losing its UART alternate function. */
#ifndef WOR_WAKE_INPUT_H
#define WOR_WAKE_INPUT_H
#include <Arduino.h>

namespace WorWakeInput {
/** @brief Check the RX pin is still owned by a UART alternate function before arming.
 * @param pin Arduino RX pin identifier.
 * @return True for a valid single GPIO bit in alternate-function mode.
 */
inline bool uartModeReady(uint32_t pin) {
    GPIO_TypeDef* port = digitalPinToPort(pin);
    const uint32_t bit = digitalPinToBitMask(pin);
    if (port == nullptr || bit == 0U || (bit & (bit - 1U)) != 0U) return false;
    const uint32_t shift = static_cast<uint32_t>(__builtin_ctz(bit)) * 2U;
    return ((port->MODER >> shift) & 3U) == 2U;
}

/** @brief Register falling-edge EXTI, restoring the RX pin's UART mode immediately.
 * @details Call with CPU IRQ delivery masked. STM32duino attachInterrupt changes
 * MODER to GPIO input. Restore only this pin's mode/speed bits before unmasking;
 * AFR, pull configuration and neighbouring pins retain their existing settings.
 * EXTI can monitor the digital input while the UART alternate function is active.
 * A wake probe may be partly lost during Stop/clock restoration; the gateway
 * must send the real command separately afterward.
 * @param pin UART RX pin.
 * @param callback Minimal foreground-flag ISR callback.
 * @return True when UART mode is preserved after attachment.
 */
inline bool attachUartRx(uint32_t pin, void (*callback)()) {
    if (!uartModeReady(pin)) return false;
    GPIO_TypeDef* port = digitalPinToPort(pin);
    const uint32_t shift = static_cast<uint32_t>(__builtin_ctz(digitalPinToBitMask(pin))) * 2U;
    const uint32_t mask = 3UL << shift;
    const uint32_t mode = port->MODER & mask;
    const uint32_t speed = port->OSPEEDR & mask;
    attachInterrupt(digitalPinToInterrupt(pin), callback, FALLING);
    port->MODER = (port->MODER & ~mask) | mode;
    port->OSPEEDR = (port->OSPEEDR & ~mask) | speed;
    return uartModeReady(pin);
}
}
#endif
