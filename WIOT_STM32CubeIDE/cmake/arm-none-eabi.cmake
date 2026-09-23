set(CMAKE_SYSTEM_NAME Generic)
set(CMAKE_SYSTEM_PROCESSOR arm)
set(CMAKE_TRY_COMPILE_TARGET_TYPE STATIC_LIBRARY)

set(STM32_GNU_BIN "C:/ST/STM32CubeIDE_1.18.1/STM32CubeIDE/plugins/com.st.stm32cube.ide.mcu.externaltools.gnu-tools-for-stm32.14.3.rel1.win32_1.0.100.202602081740/tools/bin")
set(CMAKE_C_COMPILER "${STM32_GNU_BIN}/arm-none-eabi-gcc.exe")
set(CMAKE_CXX_COMPILER "${STM32_GNU_BIN}/arm-none-eabi-g++.exe")
set(CMAKE_ASM_COMPILER "${STM32_GNU_BIN}/arm-none-eabi-gcc.exe")
set(CMAKE_OBJCOPY "${STM32_GNU_BIN}/arm-none-eabi-objcopy.exe")
set(CMAKE_SIZE "${STM32_GNU_BIN}/arm-none-eabi-size.exe")

# Bare-metal targets cannot execute CMake's host ABI probes. The compiler is
# the same GNU Arm Embedded toolchain bundled with STM32CubeIDE and is verified
# by the real firmware link below.
set(CMAKE_C_COMPILER_FORCED TRUE)
set(CMAKE_CXX_COMPILER_FORCED TRUE)
set(CMAKE_C_COMPILER_WORKS TRUE)
set(CMAKE_CXX_COMPILER_WORKS TRUE)
