#ifndef REMOTE_TEST_ARDUINO_H
#define REMOTE_TEST_ARDUINO_H
#include <stdint.h>
#include <stddef.h>
#include <sstream>
class HardwareSerial {
public:
  std::ostringstream output;
  int queued = 0;
  int available() { return queued; }
  template<class T> void print(const T& value) { output << value; }
  template<class T> void print(const T& value, int) { output << value; }
  template<class T> void println(const T& value) { output << value << '\n'; }
  void println() { output << '\n'; }
};
constexpr int HIGH = 1, LOW = 0, HEX = 16;
void digitalWrite(uint32_t, uint8_t);
uint32_t millis();
struct PWR_TypeDef { uint32_t CR = 0U; };
struct RTC_TypeDef {};
struct RTC_HandleTypeDef { RTC_TypeDef* Instance = nullptr; };
struct SCB_TypeDef { uint32_t SCR = 0U; };
extern PWR_TypeDef* PWR;
extern RTC_TypeDef* RTC;
extern SCB_TypeDef* SCB;
constexpr uint32_t PWR_CR_DBP = 256U, SCB_SCR_SLEEPDEEP_Msk = 4U;
enum : uint32_t { RTC_BKP_DR15=15U, RTC_BKP_DR16=16U, RTC_BKP_DR17=17U, RTC_BKP_DR18=18U, RTC_BKP_DR19=19U };
#define __HAL_RCC_PWR_CLK_ENABLE() ((void)0)
#define __HAL_RCC_RTC_ENABLE() ((void)0)
#define __DSB() ((void)0)
void __WFI();
void HAL_PWR_EnableBkUpAccess();
void HAL_PWR_DisableBkUpAccess();
uint32_t HAL_RTCEx_BKUPRead(RTC_HandleTypeDef*, uint32_t);
void HAL_RTCEx_BKUPWrite(RTC_HandleTypeDef*, uint32_t, uint32_t);
#endif
