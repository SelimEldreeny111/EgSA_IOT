/* code was modified by george spanos <spaniakos@gmail.com>
 * 16/12/14
 */

#ifndef __AES_CONFIG_H__
#define __AES_CONFIG_H__

#include <stdint.h>
#include <stdlib.h>
#include <string.h>

/* Native Cortex-M build: constant lookup tables already live in flash. */
#define PROGMEM
#define pgm_read_byte(p) (*(p))
typedef unsigned char byte;
#define printf_P printf
#define PSTR(x) (x)

#define N_ROW                   4
#define N_COL                   4
#define N_BLOCK   (N_ROW * N_COL)
#define N_MAX_ROUNDS           14
#define KEY_SCHEDULE_BYTES ((N_MAX_ROUNDS + 1) * N_BLOCK)
#define AES_OPERATION_SUCCESS (0)
#define AES_OPERATION_FAILURE (-1)

#endif
