cmake_minimum_required(VERSION 3.22)
project(WIOT_STM32F401RC LANGUAGES C CXX ASM)

set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 14)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

file(GLOB_RECURSE WIOT_SOURCES
  "Core/Src/*.c"
  "Core/Src/*.cpp"
  "Core/Startup/*.s"
  "Drivers/STM32F4xx_HAL_Driver/Src/*.c"
  "Middlewares/Third_Party/nanopb/*.c"
  "Middlewares/Third_Party/AESLib/*.cpp")

set(WIOT_INCLUDE_DIRECTORIES
  Core/Inc
  Drivers/STM32F4xx_HAL_Driver/Inc
  Drivers/STM32F4xx_HAL_Driver/Inc/Legacy
  Drivers/CMSIS/Device/ST/STM32F4xx/Include
  Drivers/CMSIS/Include
  Middlewares/Third_Party/nanopb
  Middlewares/Third_Party/AESLib)

set(MCU_FLAGS
  -mcpu=cortex-m4
  -mfpu=fpv4-sp-d16
  -mfloat-abi=hard
  -mthumb)

function(add_wiot_firmware target_name app_role)
  add_executable(${target_name} ${WIOT_SOURCES})
  target_include_directories(${target_name} PRIVATE ${WIOT_INCLUDE_DIRECTORIES})
  target_compile_definitions(${target_name} PRIVATE
    USE_HAL_DRIVER
    STM32F401xC
    APP_ROLE=${app_role})
  target_compile_options(${target_name} PRIVATE
    ${MCU_FLAGS}
    -ffunction-sections
    -fdata-sections
    -fstack-usage
    -Wall
    -Wextra
    -Wpedantic
    $<$<COMPILE_LANGUAGE:CXX>:-fno-exceptions;-fno-rtti;-fno-use-cxa-atexit>
    $<$<CONFIG:Debug>:-Og;-g3>
    $<$<CONFIG:Release>:-Os>)
  target_link_options(${target_name} PRIVATE
    ${MCU_FLAGS}
    -T${CMAKE_CURRENT_SOURCE_DIR}/STM32F401RCTX_FLASH.ld
    -specs=nano.specs
    -specs=nosys.specs
    -Wl,--gc-sections
    -Wl,-Map=${target_name}.map
    -Wl,--print-memory-usage)
  set_target_properties(${target_name} PROPERTIES SUFFIX ".elf")
  add_custom_command(TARGET ${target_name} POST_BUILD
    COMMAND ${CMAKE_SIZE} $<TARGET_FILE:${target_name}>
    COMMAND ${CMAKE_OBJCOPY} -O ihex $<TARGET_FILE:${target_name}> ${target_name}.hex
    COMMAND ${CMAKE_OBJCOPY} -O binary $<TARGET_FILE:${target_name}> ${target_name}.bin)
endfunction()

add_wiot_firmware(WIOT_SensorNode 1)
add_wiot_firmware(WIOT_LoRaGateway 2)
