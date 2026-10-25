/** @file ResetCause.h @brief Pure STM32F401 RCC reset-flag classification. */
#ifndef WIOT_RESET_CAUSE_H
#define WIOT_RESET_CAUSE_H
#include <stdint.h>
namespace ResetCause {
// RCC_CSR bit positions from STM32F401 CMSIS. PINRSTF can accompany power-on.
constexpr uint32_t Brownout = 1UL << 25, Pin = 1UL << 26, PowerOn = 1UL << 27;
constexpr uint32_t Software = 1UL << 28, Iwdg = 1UL << 29;
constexpr uint32_t Wwdg = 1UL << 30, LowPower = 1UL << 31;
/** @brief Exclude Standby and more specific warm-reset causes from power resets. */
constexpr bool isPowerReset(uint32_t flags, bool standbyWake) {
    return !standbyWake && (flags & (PowerOn | Brownout)) != 0U &&
        (flags & (Software | Iwdg | Wwdg | LowPower)) == 0U;
}
}
#endif
