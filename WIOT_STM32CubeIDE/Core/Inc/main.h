#ifndef WIOT_MAIN_H
#define WIOT_MAIN_H

#ifdef __cplusplus
extern "C" {
#endif

#include "stm32f4xx_hal.h"

extern ADC_HandleTypeDef hadc1;
extern RTC_HandleTypeDef hrtc;
extern UART_HandleTypeDef huart1;
extern UART_HandleTypeDef huart2;
extern UART_HandleTypeDef huart6;

void Error_Handler(void);

#define RS485_DE_Pin          GPIO_PIN_8
#define RS485_DE_GPIO_Port    GPIOA
#define LORA_MD1_Pin          GPIO_PIN_1
#define LORA_MD1_GPIO_Port    GPIOB
#define LORA_MD0_Pin          GPIO_PIN_2
#define LORA_MD0_GPIO_Port    GPIOB
#define LORA_AUX_Pin          GPIO_PIN_13
#define LORA_AUX_GPIO_Port    GPIOC
#define BATTERY_ADC_Pin       GPIO_PIN_0
#define BATTERY_ADC_GPIO_Port GPIOA

#ifdef __cplusplus
}
#endif

#endif
