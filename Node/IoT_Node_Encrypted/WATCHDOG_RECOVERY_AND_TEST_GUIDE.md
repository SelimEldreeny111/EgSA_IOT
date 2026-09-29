# STM32 Global Watchdog Recovery and Test Guide

## 1. Purpose

The STM32F401 independent watchdog (IWDG) protects the complete Arduino node,
not only GSM or Wi-Fi connection code. It starts before application, modem, or
LoRa initialization. If execution stops reaching verified progress
checkpoints, the IWDG resets the controller.

In the optional REMOTE_WAKE profile the IWDG remains armed during reachable
idle. CPU Sleep keeps UART/SysTick clocks enabled, and foreground loop progress
continues to service network keepalive and watchdog checkpoints. Neither WFI
nor a timer/UART ISR feeds IWDG. A blocked function still resets the controller.
This differs from RTC_PERIODIC Standby's reset-before-sleep handoff.

Network retry exhaustion remains a second policy. It deliberately requests a
fast watchdog reset after the configured number of complete failures even
when every modem function returns normally.

## 2. Timing audit

The values below are static worst-case estimates from the application and the
installed TinyGSM/PubSubClient sources. They are timeout ceilings, not typical
field measurements.

| Operation | Current theoretical duration without an application checkpoint | Decision |
| --- | ---: | --- |
| One Modbus request | 2.0 s | Normal; checkpoint follows each request/retry |
| TUF/Supmea Modbus request plus inter-request delay | about 2.1 s | Normal |
| HNDA or Sondas request | about 2.0 s | Normal |
| LoRa fragment ACK window | 12.0 s | Longest accepted healthy unserviced phase |
| LoRa physical transmit before stage splitting | up to about 23.7 s | Split into verified AUX, UART, and TX-complete stages |
| ESP8266 firmware query | 2.0 s | Normal |
| ESP8266 `networkConnect()` | up to 60 s | More than 25 s with no result is treated as a stuck modem call |
| ESP8266 `restart()` | roughly 40-45 s | More than 25 s is treated as stuck |
| MQTT connect through ESP-AT | roughly 110-115 s | More than 25 s is treated as stuck |
| SIM800 network registration attempt | 10 s | Normal |
| SIM800 `gprsConnect()` | up to roughly 492 s (8.2 min) | More than 25 s is treated as stuck |
| Operator Wi-Fi credential entry | 180 s per field | Intentional bounded wait; watchdog-aware delay keeps it alive |
| Async ESP publish FSM | 5 s prompt plus 12 s send-result limits | Non-blocking; the superloop continues to run |

The absolute longest path is therefore the SIM800 library GPRS sequence, but
it is not a suitable watchdog period. STM32duino's STM32F401 IWDG supports a
typical maximum of only about 32.76 seconds, and waiting eight minutes before
recovering an unresponsive product would defeat the watchdog's purpose.

## 3. Selected deadline

The production setting remains:

```cpp
#define APP_ENABLE_HARDWARE_WATCHDOG 1
#define APP_WATCHDOG_TIMEOUT_US 25000000UL
```

This is a **nominal 25-second deadline**. After splitting the LoRa transmit
sequence at verified progress boundaries, the longest application-owned
unserviced phase is the 12-second ACK window. The watchdog deadline is
therefore slightly more than twice that duration. Opaque third-party modem
calls receive the same 25-second limit and are considered unresponsive if they
do not return within it.

IWDG timing uses the STM32 internal low-speed oscillator. It is intentionally
independent from the CPU clock, but it is not a precision clock; measured
reset time can differ from exactly 25.000 seconds. Never design a healthy path
close to the deadline.

## 4. Runtime behavior

1. `initializeHardwareWatchdog()` captures the preceding reset cause and arms
   the IWDG before application setup.
2. Immediately before a bounded operation, firmware records its subsystem
   stage and gives it a full watchdog window.
3. The IWDG is refreshed only after a verified checkpoint, between bounded
   retries, or during an explicitly approved finite delay.
4. If the active call never returns, no later checkpoint executes and hardware
   resets the STM32 after approximately 25 seconds.
5. On the next boot, the serial log reports both the IWDG reset cause and the
   last recorded stage, for example:

   ```text
   RESET CAUSE: independent hardware watchdog timeout
   Last watchdog stage: flow-meter Modbus read
   ```

The stage record is kept in the linker-managed `.noinit` SRAM section. It does
not use RTC backup registers, so it does not conflict with Supmea consumption,
RTC trust, or power-down persistence. A magic/inverse check rejects random RAM
after a cold power-on.

## 5. Important interpretation

- A hard block in sensor, LoRa, MQTT, Wi-Fi, SIM800, RTC, codec, or any other
  code is covered as long as that path does not falsely call a progress
  checkpoint.
- A function that returns an error is not a software hang. Normal retry/error
  policy handles it; the network failure counter can still request a reset.
- A healthy but very slow TinyGSM call that exceeds 25 seconds is intentionally
  classified as an unresponsive modem transaction and reset.
- A semantic failure that keeps completing the entire main loop is not a CPU
  hang. It must be detected by its own data-validity or communication policy.
- Debugger breakpoints longer than the watchdog period reset the MCU. Disable
  the watchdog only in a dedicated debug image, never in production.

## 6. Configuration

All production and test controls are in `src/config/AppConfig.h`:

```cpp
#define APP_ENABLE_HARDWARE_WATCHDOG 1
#define APP_WATCHDOG_TIMEOUT_US 25000000UL
#define APP_NETWORK_FAILURES_BEFORE_RESET 2U
#define APP_WATCHDOG_SELF_TEST_MODE APP_WATCHDOG_SELF_TEST_DISABLED
```

Valid self-test choices are:

```cpp
APP_WATCHDOG_SELF_TEST_DISABLED
APP_WATCHDOG_SELF_TEST_AFTER_SETUP
APP_WATCHDOG_SELF_TEST_MAIN_LOOP
```

The timeout compile-time check permits 1,000,000 through 32,760,000
microseconds. Keep 25,000,000 for the approved production configuration.

## 7. Step-by-step acceptance test

### Test A - normal operation

1. Select the required sensor, transport, role, and normal/power-down profile.
2. Keep `APP_WATCHDOG_SELF_TEST_MODE` disabled.
3. Flash the node and monitor at 115200 baud.
4. Confirm `Hardware watchdog: armed, timeout=25000 ms`.
5. Run sensor acquisition and telemetry for at least one hour.
6. Pass when there is no unexplained reset and normal telemetry continues.

### Test B - setup/global coverage

1. Set the self-test mode to `APP_WATCHDOG_SELF_TEST_AFTER_SETUP`.
2. Compile and flash.
3. After setup completes, observe the deliberate block message.
4. Measure from that message to reset. Expect approximately 25 seconds, with
   normal LSI tolerance.
5. On the next boot, confirm:

   ```text
   RESET CAUSE: independent hardware watchdog timeout
   Last watchdog stage: watchdog self-test after setup
   WATCHDOG SELF-TEST PASS: reset recovered from watchdog self-test after setup
   ```

6. Return the mode to `APP_WATCHDOG_SELF_TEST_DISABLED` and reflash.

### Test C - main-loop coverage

Repeat Test B with `APP_WATCHDOG_SELF_TEST_MAIN_LOOP`. The last stage and PASS
message must say `watchdog self-test in main loop`.

### Test D - missing RS485 sensor

1. Disable the self-test.
2. Disconnect one enabled RS485 sensor and run for at least five sample cycles.
3. Confirm each Modbus request times out in about two seconds and later cycles
   continue.
4. Pass when no watchdog reset occurs. A normal sensor timeout is not a hang.

### Test E - modem non-response

1. Disable the self-test and remove the ESP/SIM UART response path or hold the
   modem in a state where the active AT call does not complete.
2. Confirm an IWDG reset occurs at approximately the configured deadline.
3. Confirm the next boot identifies the relevant modem, Wi-Fi, GPRS, MQTT, or
   socket stage.
4. Restore wiring and verify automatic recovery.

### Test F - LoRa boundaries

1. Use a LoRa sensor-node or gateway build.
2. With the peer absent, confirm the 12-second ACK timeout returns and retries
   without an unintended reset.
3. Hold AUX LOW and confirm the 10-second AUX timeout returns an error.
4. Restore AUX/peer and verify the next transmission succeeds.

### Test G - soak and power-mode regression

1. Run the selected production profile for at least 24 hours.
2. Exercise server commands, MQTT reconnects, sensor disconnect/reconnect, and
   LoRa retries as applicable.
3. For power-down builds, execute at least 20 sleep/wake cycles.
4. Pass when every reset is explained by its log, telemetry recovers, and no
   normal operation exceeds the watchdog deadline.

Record firmware commit, configuration, measured reset time, last-stage log,
and pass/fail result for every acceptance run.

### Test H - STIME and Supmea checkpoint

Follow [SUPMEA_RTC_RESET_FIX_AND_TEST_GUIDE.md](SUPMEA_RTC_RESET_FIX_AND_TEST_GUIDE.md)
to verify STIME readback, a one-commit baseline save, known consumption deltas,
and reset recovery. Additional stages distinguish RTC synchronization, Supmea
RTC calculation, backup snapshot and flash checkpoint. Old persisted stage
numbers are preserved. Keep the normal watchdog timeout; flash operations do
not contain an automatic watchdog-reload loop.
