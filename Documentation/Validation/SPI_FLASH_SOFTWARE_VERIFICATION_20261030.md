# SPI telemetry software verification — 30 October 2026

Scope: Arduino STM32 node, LoRa gateway and Python web server. Branch
`feature/2026-10-30-spi-flash-telemetry`, based on release `4c34379`.
ESP32/CubeIDE are unchanged. No hardware was flashed and no broker/COM-port test
was performed by these checks.

## Results

- Full release validation passed, including existing valve, MQTT priority,
  network recovery, reset counter and sensor availability regressions.
- 53 real configuration acceptance/rejection cases; 65 production WOR IRQ/RTC
  cases including flash busy, retention deadline, sleep failure and transfer guards.
- 16 RTC/Supmea cases and 10 cross-component schema/routing/oracle checks.
- 124 Python server tests; 65 sensor-simulator tests; dashboard JavaScript suites.
- Actual journal tests: CRC/commit recovery, queue/full, I/O failure, duplicate
  clear, elapsed retention and 13 mutating power-cut transitions.
- Nine actual SPI driver/archive scenarios plus production 17/22/24-fragment
  LoRa reassembly tests. Capture during download remains possible while the
  frozen transfer excludes later records.
- An interleaved allocation/reclamation test fails against the old sweep and
  passes the ownership-recheck implementation, preventing new-record erasure.
- Protocol regeneration reproduced nanopb/server schemas. Maximum Telemetry is
  546 plaintext / 577 encrypted bytes; canonical samples fit 472-byte payloads.
- Doxygen HTML/XML generated with zero warnings.

## Firmware builds

STM32 Arduino core 2.12.0, BlackPill F401CC selection, ARM GCC 14.2.1, four sensor
drivers enabled. Each ELF load range is below reserved EEPROM address 0x08020000.
RAM below is ELF initialized data + BSS; it is not a measured runtime stack peak.
`node2-wor` uses the exact final AppConfig without profile overrides.

| Profile | Result | Flash load end | RAM data + BSS (bytes) |
| --- | --- | --- | ---: |
| normal-sim | PASS | 0x08018BB0 | 27,516 |
| normal-wifi | PASS | 0x08018570 | 27,516 |
| rtc-lora | PASS | 0x08018D14 | 36,020 |
| wor-lora | PASS | 0x08019908 | 36,036 |
| gateway-wor | PASS | 0x0800E6B4 | 31,960 |
| flash-disabled-wifi | PASS | 0x08015E64 | 24,056 |
| remote-wifi | PASS | 0x08018AA4 | 27,548 |
| node2-wor | PASS | 0x08019398 | 36,036 |

## Delivery and remaining acceptance

Only intended public source/docs/tests are synchronized to the final folder.
Local AppConfig.cpp, AppSecrets.h, server environment/users/databases and the
original root checkout are preserved. Binaries and generated Doxygen remain
local artifacts; private configuration is excluded from Git.

Before field use follow SPI_FLASH_TEST_PLAN.md: verify exact chip/package/pins,
3.3 V supply/decoupling, JEDEC, STIME + explicit initial CLEAR_FLASH, real power
cuts, RF history/command latency and a 24/48-hour soak. Committed data survives
resets; unchanged network startup/retry policies can still create acquisition gaps.
This is software verification, not physical qualification or an endurance claim.
