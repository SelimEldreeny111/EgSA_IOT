#pragma once
#include <stdint.h>
#define E2END 511U
void eeprom_buffer_fill();
uint8_t eeprom_buffered_read_byte(uint32_t address);
void eeprom_buffered_write_byte(uint32_t address, uint8_t value);
void eeprom_buffer_flush();
