#ifndef WOR_TEST_ARDUINO_H
#define WOR_TEST_ARDUINO_H
#include <stdint.h>
#include <stddef.h>
#include <sstream>
class HardwareSerial {
public:
  std::ostringstream output;
  unsigned flushes = 0U;
  int available() { return 0; }
  template<class T> void print(const T& value) { output << value; }
  template<class T> void print(const T& value, int) { output << value; }
  template<class T> void println(const T& value) { output << value << '\n'; }
  void println() { output << '\n'; }
  void flush() { ++flushes; }
};
constexpr int HIGH=1, LOW=0, FALLING=2, RESET=0, HEX=16;
#define PC13 13U
#define RTC_CR_OSEL (3UL << 21)
#define RTC_CR_COE (1UL << 23)
#define RTC_CR_TSE (1UL << 11)
#define RTC_TAFCR_TAMP1E 1UL
constexpr uint32_t SCB_ICSR_PENDSTCLR_Msk=1U << 25;
constexpr uint32_t PWR_CR_DBP=256U, PWR_LOWPOWERREGULATOR_ON=1U, PWR_STOPENTRY_WFI=1U;
struct PWR_TypeDef { uint32_t CR=0U; };
struct RTC_TypeDef { uint32_t CR=0U, TAFCR=0U; };
struct RTC_HandleTypeDef { RTC_TypeDef* Instance=nullptr; };
struct SCB_TypeDef { uint32_t ICSR=0U; };
extern PWR_TypeDef* PWR;
extern RTC_TypeDef* RTC;
extern SCB_TypeDef* SCB;
extern uint32_t fakeExtiPending;
extern bool fakeRtcWritable;
#define __HAL_RTC_WRITEPROTECTION_DISABLE(handle) (fakeRtcWritable=true)
#define __HAL_RTC_WRITEPROTECTION_ENABLE(handle) (fakeRtcWritable=false)
enum : uint32_t { RTC_BKP_DR15=15U, RTC_BKP_DR16=16U, RTC_BKP_DR17=17U, RTC_BKP_DR18=18U, RTC_BKP_DR19=19U };
uint32_t millis();
int digitalRead(uint32_t);
void attachInterrupt(uint32_t, void (*)(), int);
void detachInterrupt(uint32_t);
inline uint32_t digitalPinToInterrupt(uint32_t pin) { return pin; }
inline uint32_t digitalPinToBitMask(uint32_t pin) { return 1U << pin; }
uint32_t __get_PRIMASK();
void __disable_irq();
void __enable_irq();
void __set_PRIMASK(uint32_t);
#define __HAL_GPIO_EXTI_GET_IT(mask) (fakeExtiPending & (mask))
#define __HAL_GPIO_EXTI_CLEAR_IT(mask) (fakeExtiPending &= ~(mask))
#define __HAL_RCC_PWR_CLK_ENABLE() ((void)0)
#define __HAL_RCC_RTC_ENABLE() ((void)0)
#define __DSB() ((void)0)
#define __ISB() ((void)0)
void HAL_SuspendTick();
void HAL_ResumeTick();
void HAL_PWR_EnterSTOPMode(uint32_t, uint32_t);
void SystemCoreClockUpdate();
void HAL_PWR_EnableBkUpAccess();
void HAL_PWR_DisableBkUpAccess();
uint32_t HAL_RTCEx_BKUPRead(RTC_HandleTypeDef*, uint32_t);
void HAL_RTCEx_BKUPWrite(RTC_HandleTypeDef*, uint32_t, uint32_t);
#endif
