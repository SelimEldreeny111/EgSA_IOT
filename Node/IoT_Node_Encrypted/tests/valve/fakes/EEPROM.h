#pragma once
#include <cstdint>
#define E2END 511U
void eeprom_buffer_fill();
uint8_t eeprom_buffered_read_byte(uint32_t);
void eeprom_buffered_write_byte(uint32_t, uint8_t);
void eeprom_buffer_flush();
