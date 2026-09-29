#ifndef TEST_ARDUINO_H
#define TEST_ARDUINO_H

#include <cstdint>
#include <cstddef>
#include <cstdarg>
#include <cstdio>
#include <sstream>
#include <string>

class HardwareSerial
{
public:
    std::ostringstream output;
    template<typename T> void print(const T& value) { output << value; }
    template<typename T> void println(const T& value) { output << value << '\n'; }
    void println() { output << '\n'; }
    void printf(const char* format, ...)
    {
        char buffer[160];
        va_list args;
        va_start(args, format);
        std::vsnprintf(buffer, sizeof(buffer), format, args);
        va_end(args);
        output << buffer;
    }
};

struct PWR_TypeDef { uint32_t CR = 0U; };
struct RTC_TypeDef { uint32_t CR = 0U; };
struct RTC_HandleTypeDef { RTC_TypeDef* Instance = nullptr; };
extern PWR_TypeDef* PWR;
extern RTC_TypeDef* RTC;
constexpr uint32_t PWR_CR_DBP = 1U << 8U;
constexpr uint32_t RTC_CR_ALRAE = 1U << 8U;
constexpr uint32_t RTC_FLAG_ALRAF = 1U;
enum : uint32_t
{
    RTC_BKP_DR0 = 0U, RTC_BKP_DR13 = 13U, RTC_BKP_DR14 = 14U,
    RTC_BKP_DR15 = 15U, RTC_BKP_DR16 = 16U, RTC_BKP_DR19 = 19U
};
#define __HAL_RCC_PWR_CLK_ENABLE() ((void)0)
#define __HAL_RCC_RTC_ENABLE() ((void)0)
#define __HAL_RTC_ALARM_CLEAR_FLAG(handle, flag) ((void)(handle), (void)(flag))
#define __HAL_RTC_ALARM_EXTI_CLEAR_FLAG() ((void)0)
void HAL_PWR_EnableBkUpAccess();
void HAL_PWR_DisableBkUpAccess();
uint32_t HAL_RTCEx_BKUPRead(RTC_HandleTypeDef*, uint32_t index);
void HAL_RTCEx_BKUPWrite(RTC_HandleTypeDef*, uint32_t index, uint32_t value);
uint32_t millis();

#endif
