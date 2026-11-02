# LoRa WOR independent application schedule - 2 November 2026

## Problem and change

The previous LoRa WOR implementation used `APP_POWER_SLEEP_SECONDS` to wake and force both sensor sampling and routine transmission. Thus a deployed 20-second sleep interval overrode SRATE/STRAN work even when the application periods were 100 seconds or longer.

`APP_LORA_WOR_USE_APP_SCHEDULE` now defaults to true. The power manager selects the earliest independent application deadline, flash-maintenance deadline or IWDG heartbeat. A sample-only deadline does not force transmission; a transmit-only deadline does not force sampling. The receive window postpones Stop without blocking due work. Partial multi-sensor cycles, storage/transfer activity, radio transactions and WAKE leases still defer Stop. The false selector retains the old combined sleep/report policy.

Because SysTick stops in STM32 Stop, elapsed RTC seconds/subseconds age the application's read/send timestamps by the portion missing from `millis()`. Global HAL/Arduino time is not changed. Awake RTC synchronization does not reset the independent interval ages. Backward/unrepresentable RTC elapsed intervals abort the Stop cycle to active recovery; an untrusted RTC stays awake for commissioning.

The gateway wake-probe sequence, UART RX wake arming, AES/protobuf messages, server, ESP32 and CubeIDE ports are unchanged. No server update or gateway reflash is required when command wake already works.

## Actual verification

- **65 existing production WOR scenarios** passed across AUX and UART_RX sources: pre-arm/armed/Stop/heartbeat races, UART mode preservation, pending flags, unexpected wake, radio restoration, storage guards and legacy behavior.
- **34 schedule-driven production WOR scenarios** passed across both sources. Tests cover SRATE 100 s / STRAN 300 s and the reverse; sample-only and send-only wakes; increasing/decreasing rates; unfinished sensor cycles; due work during a receive window; failed-report retry timing; millis rollover; forward/backward awake RTC changes; fractional RTC residence; active ticks without double-counting; command wake; storage maintenance/busy; backward RTC during Stop; and untrusted time.
- Production REMOTE_WAKE legacy and schedule-driven integration regressions passed with command/reset-counter validation, duplicate handling, leases, UART, rate bounds and rollover.
- **56 real AppConfig preprocessor policy cases** passed. The new true/false selector is accepted, invalid values rejected, and the default is explicitly checked as true.
- Real Arduino STM32 builds passed with installed STM32 core 2.12.0, `STMicroelectronics:stm32:GenF4:pnum=BLACKPILL_F401CC`:

| Build | Flash bytes | Static RAM bytes |
| --- | ---: | ---: |
| Repository node defaults, four sensors, schedule-driven WOR | 108780 | 34644 |
| Final-folder deployment configuration, schedule-driven WOR | 105996 | 34636 |
| LoRa gateway, controller/radio NORMAL, WOR_TX=1 | 58532 | 30420 |
| Four-sensor node, legacy WOR selector false | 102788 | 34500 |

The final-folder build preserved the user's 20-second sleep setting and existing sensor selections. Only the new scheduling switch and its validation were inserted into its AppConfig.h. The updated power-manager copies match the repository source. Deployment credentials/private source files were not modified or included in Git.

Original deployment `AppConfig.h`, `PowerManager.cpp` and `PowerManager.h` were backed up under `backups/WOR_AppSchedule_20261102/` in the final working folder before modification.

## Hardware acceptance still required

No controller was flashed or physical RF/current measurement performed by this verification. Follow [the current configuration and step-by-step bench guide](../../Node/IoT_Node_Encrypted/LORA_WOR_APP_SCHEDULE_GUIDE.md). In particular, leave the old sleep value at 20, set SRATE=100 and STRAN=300, distinguish heartbeat/command replies from new sensor reads and routine Status, and verify low-current return plus command wake after each type of work.

The initial boot sample/report and explicit WAKE-command fresh cycle remain intentional exceptions. Second-granular RTC alarms, sensor/flash work and non-preemptible radio traffic affect observed timing. This release does not claim exact physical deadlines or RF delivery without a bench test.
