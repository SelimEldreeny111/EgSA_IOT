# STM32 SPI flash bench test

Standalone Arduino sketch for the STM32F401 and S25FL064L fitted to the WIOT node. It uses the same SPI pins and explicit four-byte read/program/erase commands as the production driver. It does not start networking, sensors, the watchdog, or the telemetry logger.

## Wiring

Disconnect power before wiring. Use 3.3 V for the flash supply and logic, a common ground, short SPI wires, and a 100 nF decoupling capacitor close to the flash supply pins. Use signal names from your fitted package/schematic; physical package pin numbers can differ.

| Flash signal | STM32 connection |
|---|---|
| VCC | 3.3 V |
| GND | GND |
| CS# | PA4 |
| SCK | PA5 |
| SO / IO1 / MISO | PA6 |
| SI / IO0 / MOSI | PA7 |

Keep WP#/IO2 and IO3/RESET#/HOLD# at their inactive levels as specified for the fitted package and board. Do not leave control inputs floating. A pull-up on CS# keeps the chip deselected while the controller resets.

Debug uses the project's USART2 connection, **115200 baud, 8 data bits, no parity, 1 stop bit**:

| USB-to-TTL adapter, 3.3 V logic | STM32 |
|---|---|
| RX | PA2 (controller TX) |
| TX | PA3 (controller RX) |
| GND | GND |

Use the adapter for debug signals; keep the board powered through its normal supply. This sketch does not use the USB virtual COM port.

## 1. Read-only communication test

1. Open `Test_SPI_Flash.ino` in Arduino IDE. Keep `TEST_ALLOW_ERASE` set to `false`.
2. Select the same STM32F401 board and upload method as the working node. The project's compile profile is `STMicroelectronics:stm32:GenF4:pnum=BLACKPILL_F401CC` with STM32 core 2.12.0.
3. Upload this standalone sketch in place of the node application. Open the debug terminal at 115200 baud, then press RESET to see startup output.
4. Expect `JEDEC ID: 016017` and `PASS: expected flash responds`. The expected chip is 64 Mbit = 8 MiB = 8,388,608 bytes. An ID match checks the SPI command/response path; it does not verify every memory byte.
5. The sketch displays the first 32 bytes at address `0x00000000` and at `0x007FF000`. Existing content may be any value; `FF` is normal for erased memory.
6. Send `r` to repeat the ID/status check or `d` to repeat both dumps. Line endings are ignored. Sending `t` in this default configuration performs no write or erase.

## 2. Optional erase, write, and read-back test

**This test erases the entire final 4 KB sector, addresses `0x007FF000` through `0x007FFFFF`. The production telemetry journal also uses this sector. It is not reserved test space. Run this only when retained telemetry can be discarded, with the production logger stopped.**

1. Change `#define TEST_ALLOW_ERASE false` to `#define TEST_ALLOW_ERASE true`, compile, and upload again.
2. Open the terminal and send `t`. The sketch checks the ID, erases that sector, verifies all 4096 bytes are `FF`, programs one 256-byte page, and compares every programmed byte.
3. Expect `PASS: erase + 256-byte program + exact read-back verified`. This proves those operations work in the tested sector; it is not a full-chip capacity test.
4. The stored pattern begins `A5 A4 A7 A6 A1 A0 A3 A2 AD AC AF AE A9 A8 AB AA`. Press RESET, then send `d`: the pattern should remain. Startup never automatically repeats the destructive test.
5. Set `TEST_ALLOW_ERASE` back to `false` after testing. Before resuming production logging, restore the node firmware and use its supported flash-clear command to initialize a disposable journal if this test modified an existing log.

Erase and program waits are bounded (2 seconds for erase/busy, 100 ms for program). Unexpected IDs, program/erase error flags, write-enable failures, busy timeouts, and mismatched bytes report `FAIL`. No chip erase or protection-register write is performed.

## Troubleshooting

| Result | Check |
|---|---|
| No terminal output | PA2 to adapter RX, PA3 to adapter TX, common GND, 115200 baud; press RESET after opening the terminal. |
| ID `FFFFFF` or `000000` | Flash supply at the chip, common GND, CS#, MISO/MOSI direction, and inactive reset/hold inputs. |
| Another stable ID | Confirm the actual chip marking. Writes are refused; do not change the expected ID without checking that chip's command set. |
| ID passes, write/erase fails | Supply stability, write-protection configuration, WP# wiring, and reported status registers. The sketch does not remove protection. |
| Intermittent ID or mismatched bytes | Shorten wires, inspect decoupling/ground, and check signals. Start at the default 1 MHz. |

After a successful 1 MHz test, change `SPI_CLOCK_HZ` to `4000000UL` and repeat to check the production clock rate. The startup banner prints the selected clock. The main application must be restored to resume node operation.

## Build verification

Both configurations compiled successfully with STM32 core 2.12.0 and the profile above: default read-only (16,596 bytes program / 1,676 bytes RAM) and `TEST_ALLOW_ERASE=true` (17,120 bytes program / 1,676 bytes RAM). No board was flashed and no physical flash operations were performed during preparation; the steps above are the hardware acceptance test.
