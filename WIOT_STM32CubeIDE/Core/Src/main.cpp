#include "main.h"

#include "app/Application.hpp"
#include "config/AppConfig.hpp"
#include "platform/Stm32Platform.hpp"

ADC_HandleTypeDef hadc1;
RTC_HandleTypeDef hrtc;
UART_HandleTypeDef huart1;
UART_HandleTypeDef huart2;
UART_HandleTypeDef huart6;

static void SystemClock_Config();
static void MX_GPIO_Init();
static void MX_ADC1_Init();
static void MX_RTC_Init();
static void MX_USART1_UART_Init();
static void MX_USART2_UART_Init();
static void MX_USART6_UART_Init();

int main(void)
{
  HAL_Init();
  SystemClock_Config();

  CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;
  DWT->CYCCNT = 0U;
  DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk;

  MX_GPIO_Init();
  MX_ADC1_Init();
  MX_RTC_Init();
  MX_USART1_UART_Init();
  MX_USART2_UART_Init();
  MX_USART6_UART_Init();
  Platform::initializePortsForRole();

  Application::setup();
  while (true)
  {
    Application::loop();
  }
}

static void SystemClock_Config()
{
  RCC_OscInitTypeDef oscillator{};
  RCC_ClkInitTypeDef clock{};

  __HAL_RCC_PWR_CLK_ENABLE();
  __HAL_PWR_VOLTAGESCALING_CONFIG(PWR_REGULATOR_VOLTAGE_SCALE2);

  oscillator.OscillatorType = RCC_OSCILLATORTYPE_HSI | RCC_OSCILLATORTYPE_LSI;
  oscillator.HSIState = RCC_HSI_ON;
  oscillator.HSICalibrationValue = RCC_HSICALIBRATION_DEFAULT;
  oscillator.LSIState = RCC_LSI_ON;
  oscillator.PLL.PLLState = RCC_PLL_ON;
  oscillator.PLL.PLLSource = RCC_PLLSOURCE_HSI;
  oscillator.PLL.PLLM = 8U;
  oscillator.PLL.PLLN = 84U;
  oscillator.PLL.PLLP = RCC_PLLP_DIV2;
  oscillator.PLL.PLLQ = 4U;
  if (HAL_RCC_OscConfig(&oscillator) != HAL_OK) Error_Handler();

  clock.ClockType = RCC_CLOCKTYPE_HCLK | RCC_CLOCKTYPE_SYSCLK |
                    RCC_CLOCKTYPE_PCLK1 | RCC_CLOCKTYPE_PCLK2;
  clock.SYSCLKSource = RCC_SYSCLKSOURCE_PLLCLK;
  clock.AHBCLKDivider = RCC_SYSCLK_DIV1;
  clock.APB1CLKDivider = RCC_HCLK_DIV2;
  clock.APB2CLKDivider = RCC_HCLK_DIV1;
  if (HAL_RCC_ClockConfig(&clock, FLASH_LATENCY_2) != HAL_OK) Error_Handler();

  HAL_SYSTICK_Config(HAL_RCC_GetHCLKFreq() / 1000U);
  HAL_SYSTICK_CLKSourceConfig(SYSTICK_CLKSOURCE_HCLK);
  HAL_NVIC_SetPriority(SysTick_IRQn, TICK_INT_PRIORITY, 0U);
}

static void MX_GPIO_Init()
{
  __HAL_RCC_GPIOA_CLK_ENABLE();
  __HAL_RCC_GPIOB_CLK_ENABLE();
  __HAL_RCC_GPIOC_CLK_ENABLE();

  HAL_GPIO_WritePin(GPIOA, RS485_DE_Pin, GPIO_PIN_RESET);
  HAL_GPIO_WritePin(GPIOB, LORA_MD0_Pin | LORA_MD1_Pin, GPIO_PIN_RESET);

  GPIO_InitTypeDef gpio{};
  gpio.Pin = RS485_DE_Pin;
  gpio.Mode = GPIO_MODE_OUTPUT_PP;
  gpio.Pull = GPIO_NOPULL;
  gpio.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(GPIOA, &gpio);

  gpio.Pin = LORA_MD0_Pin | LORA_MD1_Pin;
  HAL_GPIO_Init(GPIOB, &gpio);

  gpio.Pin = LORA_AUX_Pin;
  gpio.Mode = GPIO_MODE_INPUT;
  gpio.Pull = GPIO_NOPULL;
  HAL_GPIO_Init(GPIOC, &gpio);
}

static void MX_ADC1_Init()
{
  hadc1.Instance = ADC1;
  hadc1.Init.ClockPrescaler = ADC_CLOCK_SYNC_PCLK_DIV4;
  hadc1.Init.Resolution = ADC_RESOLUTION_12B;
  hadc1.Init.ScanConvMode = DISABLE;
  hadc1.Init.ContinuousConvMode = DISABLE;
  hadc1.Init.DiscontinuousConvMode = DISABLE;
  hadc1.Init.ExternalTrigConvEdge = ADC_EXTERNALTRIGCONVEDGE_NONE;
  hadc1.Init.ExternalTrigConv = ADC_SOFTWARE_START;
  hadc1.Init.DataAlign = ADC_DATAALIGN_RIGHT;
  hadc1.Init.NbrOfConversion = 1U;
  hadc1.Init.DMAContinuousRequests = DISABLE;
  hadc1.Init.EOCSelection = ADC_EOC_SINGLE_CONV;
  if (HAL_ADC_Init(&hadc1) != HAL_OK) Error_Handler();

  ADC_ChannelConfTypeDef channel{};
  channel.Channel = ADC_CHANNEL_0;
  channel.Rank = 1U;
  channel.SamplingTime = ADC_SAMPLETIME_480CYCLES;
  if (HAL_ADC_ConfigChannel(&hadc1, &channel) != HAL_OK) Error_Handler();
}

static void MX_RTC_Init()
{
  RCC_PeriphCLKInitTypeDef peripheralClock{};
  peripheralClock.PeriphClockSelection = RCC_PERIPHCLK_RTC;
  peripheralClock.RTCClockSelection = RCC_RTCCLKSOURCE_LSI;
  if (HAL_RCCEx_PeriphCLKConfig(&peripheralClock) != HAL_OK) Error_Handler();
  __HAL_RCC_RTC_ENABLE();

  hrtc.Instance = RTC;
  hrtc.Init.HourFormat = RTC_HOURFORMAT_24;
  hrtc.Init.AsynchPrediv = 127U;
  hrtc.Init.SynchPrediv = 249U;
  hrtc.Init.OutPut = RTC_OUTPUT_DISABLE;
  hrtc.Init.OutPutPolarity = RTC_OUTPUT_POLARITY_HIGH;
  hrtc.Init.OutPutType = RTC_OUTPUT_TYPE_OPENDRAIN;
  if (HAL_RTC_Init(&hrtc) != HAL_OK) Error_Handler();
}

static void initializeUart(UART_HandleTypeDef &uart, USART_TypeDef *instance, uint32_t baud)
{
  uart.Instance = instance;
  uart.Init.BaudRate = baud;
  uart.Init.WordLength = UART_WORDLENGTH_8B;
  uart.Init.StopBits = UART_STOPBITS_1;
  uart.Init.Parity = UART_PARITY_NONE;
  uart.Init.Mode = UART_MODE_TX_RX;
  uart.Init.HwFlowCtl = UART_HWCONTROL_NONE;
  uart.Init.OverSampling = UART_OVERSAMPLING_16;
  if (HAL_UART_Init(&uart) != HAL_OK) Error_Handler();
}

static void MX_USART1_UART_Init() { initializeUart(huart1, USART1, 9600U); }
static void MX_USART2_UART_Init() { initializeUart(huart2, USART2, 115200U); }
static void MX_USART6_UART_Init()
{
#if APP_ROLE == APP_ROLE_LORA_GATEWAY
  initializeUart(huart6, USART6, 115200U);
#else
  initializeUart(huart6, USART6, 9600U);
#endif
}

extern "C" void Error_Handler(void)
{
  __disable_irq();
  while (true)
  {
  }
}
