#pragma once
#include <stdint.h>
struct FakeRcc { uint32_t CSR=0U; };
extern FakeRcc* RCC;
extern bool testStandbyWake;
#define RCC_CSR_BORRSTF (1UL<<25)
#define RCC_CSR_PORRSTF (1UL<<27)
#define RCC_CSR_SFTRSTF (1UL<<28)
#define RCC_CSR_IWDGRSTF (1UL<<29)
#define RCC_CSR_WWDGRSTF (1UL<<30)
#define RCC_CSR_LPWRRSTF (1UL<<31)
#define PWR_FLAG_SB 1U
#define RESET 0U
#define __HAL_RCC_PWR_CLK_ENABLE() ((void)0)
#define __HAL_RCC_CLEAR_RESET_FLAGS() (RCC->CSR=0U)
#define __HAL_PWR_GET_FLAG(flag) (testStandbyWake ? 1U : 0U)
struct HardwareSerial {
    template<class T> void print(T) {}
    template<class T> void println(T) {}
    void println() {}
    void flush() {}
};
inline void delay(uint32_t) {}
inline void noInterrupts() {}
inline void NVIC_SystemReset() {}
inline void __WFI() {}
inline void __NOP() {}
