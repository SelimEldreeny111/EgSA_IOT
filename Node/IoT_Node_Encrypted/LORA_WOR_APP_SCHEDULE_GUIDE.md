# LoRa WOR: wake for SRATE, STRAN or a server command

Updated 2 November 2026 for the Arduino STM32 sensor node. The gateway, server protocol, ESP32 and CubeIDE ports are unchanged.

## Configuration

In the sensor node's `src/config/AppConfig.h`, use:

```cpp
#define APP_CONTROLLER_POWER_MODE APP_COMPONENT_MODE_LORA_WOR
#define APP_LORA_POWER_MODE APP_COMPONENT_MODE_WAKE_ON_RADIO
#define APP_LORA_WOR_USE_APP_SCHEDULE true
#define APP_LORA_WOR_WAKE_SOURCE APP_LORA_WOR_WAKE_SOURCE_UART_RX
#define APP_LORA_WOR_WATCHDOG_WAKE_SECONDS 15UL
```

The separately built gateway remains NORMAL with `APP_LORA_GATEWAY_WOR_TX=1`. Its Mode-1 wake probe precedes the actual command. No gateway reflash is required if that already works on the bench.

With `APP_LORA_WOR_USE_APP_SCHEDULE=true`, `APP_POWER_SLEEP_SECONDS` does **not** schedule WOR sensor reads or reports. It can remain 20 seconds in the existing deployment. The new selector defaults to true. Setting it to false restores the previous combined sample/report cycle controlled by `APP_POWER_SLEEP_SECONDS`.

This selector changes LoRa WOR only. NORMAL, schedule-driven REMOTE_WAKE, timed Standby and queued Standby retain their existing policies. A true deep-Standby profile still cannot receive an immediate server command.

## What happens

- Boot retains the existing initial fresh sample/report.
- `SRATE` controls when the next sensor acquisition is due. A completed snapshot is queued for the SPI archive; sampling alone does not force a routine report.
- `STRAN` independently controls routine Status transmission. A transmission-only wake uses the latest committed sample, or the existing explicitly marked fallback, without forcing a new read.
- The controller and LoRa radio return to Stop/Mode 2 when work is complete and the link/storage are ready. A partially completed multi-sensor cycle, active transfer, pending flash operation or explicit WAKE lease postpones sleep.
- Server radio traffic opens the existing receive window. The command is validated/executed and its requested reply is sent. The receive window delays sleep, not due sampling/reporting.
- RTC heartbeat wakes continue at up to the configured 15-second interval to service the IWDG in foreground. A heartbeat does not sample sensors or send Status. Watchdog expiry resets the controller; it is not the wake timer.

Rate changes keep the age of the previous read/send. Increasing a rate extends that task's next deadline; decreasing it below the elapsed age makes the task due on the next eligible pass. A rate change does not restart both clocks. Awake `STIME` synchronization updates calendar time without inventing elapsed sampling/transmission time.

The existing timestamp conventions are preserved: sampling counts from the previous cycle's start; transmission counts from the previous routine attempt's completion. Sensor reads, flash commits, command priority and LoRa airtime can delay execution. RTC alarms have whole-second resolution, so a quiet deadline can be rounded up by less than one second, in addition to foreground work. This is scheduling, not a hard real-time transmission guarantee.

## Why Stop needed a timing correction

STM32 Stop suspends SysTick, so `millis()` does not advance for the full sleep residence. The power manager reads coherent RTC seconds/subseconds before and after each actual Stop call. It ages `lastReadMs` and `lastSendMs` by the RTC elapsed milliseconds missing from SysTick, using unsigned arithmetic that also handles millis rollover.

It leaves HAL/Arduino global time unchanged and never marks both tasks due solely because a fixed sleep interval ended. A backward/unrepresentable RTC interval aborts that Stop cycle into active recovery. Untrusted RTC remains awake until STIME. The radio wake interrupt/clock restoration sequence is unchanged.

## Step-by-step bench test

1. Compile and flash the updated **node** from the final working folder. Keep the currently working gateway. Confirm this startup line:
   `Power: WOR follows independent SRATE/STRAN; APP_POWER_SLEEP_SECONDS ignored; IWDG RTC heartbeat=15 s; gateway must enable Mode-1 wake probe`.
2. Establish trusted RTC with `STIME`. If testing archive capture, confirm `FLASH_STATUS` reports Ready. Do not clear an existing valid archive just to test scheduling.
3. Leave `APP_POWER_SLEEP_SECONDS=20`. Send `SRATE=100` and `STRAN=300` in seconds. Verify both command acknowledgements. Allow the initial/previous work to complete, then record separate last-read and last-routine-Status times.
4. At 20, 40 and 60 seconds, expect no **new sensor read or routine Status** just because 20 seconds passed. RTC heartbeat messages/current pulses can still occur.
5. A read is due about 100 seconds after the previous read started, then again about 100 seconds later. Check that complete samples are stored without an intervening forced routine Status. A routine Status is due about 300 seconds after the previous routine attempt finished. The read/send phases need not be exactly aligned.
6. Swap the rates: `SRATE=300`, `STRAN=100`. A send-only wake must not read sensors early. Check the stored sample's acquisition timestamp rather than assuming every newly received packet is a new measurement.
7. During a quiet sleeping interval, send `FLASH_STATUS` or `GOSTM`. Confirm UART RX wake, decoded command, server reply and return to low current. This reply is requested Telemetry, not an extra routine Status. Avoid `WAKE` for this check: WAKE deliberately requests an active lease and an immediate fresh cycle under the existing command behavior.
8. Increase a rate while asleep by sending the command through the gateway; confirm it extends that task's next deadline. Reduce a rate below its already elapsed age; confirm only that task becomes due promptly.
9. Verify low idle current returns after sample-only, send-only and command-only activity. Confirm no additional WDT resets. Brief watchdog-heartbeat wakes remain expected.
10. Optional compatibility check: build with `APP_LORA_WOR_USE_APP_SCHEDULE=false`; the old combined 20-second sleep cycle should return. Re-enable true for independent SRATE/STRAN operation.

## Code locations

- `src/config/AppConfig.h`: new policy switch and true/false validation.
- `src/power/PowerManager.cpp`: `worNextWorkDelayMs()`, `accountWorStoppedTime()`, `runLoraWorStopCycle()` and the sensor/receive-window guards.
- `IoT_Node_Encrypted.ino`: existing independent read/send checks remain the application scheduler; no forced timestamp reset is introduced at an ordinary WOR deadline.
- `tests/wor_stop`: production power-manager tests for independent deadlines, command wake, storage, clock fraction, rollover and RTC changes, alongside the legacy IRQ/Stop regressions.

Host tests and successful compilation do not measure physical current or RF delivery. The steps above are the hardware acceptance test.
