# Two-stage SIM800 / ESP8266 network recovery

Updated 4 October 2026. Applies only to the Arduino STM32 node and IP-equipped
LoRa gateway. ESP32, CubeIDE, server, schemas and simulators are unchanged.

## Production settings

In `src/config/AppConfig.h`, use:

```cpp
#define APP_ENABLE_HARDWARE_WATCHDOG 1
#define APP_WATCHDOG_TIMEOUT_US 30000000UL  // microseconds: nominal 30 seconds
#define APP_NETWORK_RETRIES_PER_STAGE 10U
#define APP_WATCHDOG_SELF_TEST_MODE APP_WATCHDOG_SELF_TEST_DISABLED
```

Select exactly one modem: `USE_SIM800` or `USE_ESP8266`. No new recovery-enable
switch is required. Retry limits from 1 to 100 are accepted; use 10 in production.
The previous `APP_NETWORK_FAILURES_BEFORE_RESET` macro has been replaced and
must not be used for this release. A command-line timeout override still wins
over the header default: check build flags if the boot log still shows 25000 ms.

## Behavior

| Event | Action |
| --- | --- |
| Stage 1 failures 1..9 | Continue network retries |
| Stage 1 failure 10 | Close the old MQTT transport, pulse selected modem RST, reinitialize it and start stage 2 |
| Stage 2 failures 1..9 | Continue network retries |
| Stage 2 failure 10 | Pulse selected modem RST, then request a fast controller reset through IWDG |
| Network connection succeeds in either stage | Clear failures and return to stage 1 |
| Any unserviced function exceeds the watchdog window | Global IWDG resets STM32; modem RST is pulsed during the next IP startup |

The second-stage controller reset uses the existing short IWDG reset request
(nominal 250 ms), not another 30-second wait. The selected modem is also reset
at IP startup so an independently powered, stuck modem cannot survive an MCU
restart. Normal RTC, sensor, command-priority and sleep policies remain available.
LoRa-only nodes do not initialize or reset an unused SIM/Wi-Fi modem.

One failed **SIM attempt** means registration did not succeed, or registration
succeeded but GPRS did not. It is counted once, not twice. A registered modem
with a lost GPRS link now re-enters network recovery instead of endlessly
retrying only MQTT.

One failed **Wi-Fi attempt** means one `networkConnect()` call returned false.
Configured credentials are still tried first, followed by a distinct saved
fallback and the existing one-time serial provisioning option. All credential
sources share the same counter; switching sources does not reset it. Identical
saved/configured credentials are not retried twice. The two-attempt Wi-Fi and
five-attempt SIM inner batches remain scheduling details, not reset thresholds.

MQTT broker rejection/outage alone is not a failed network attempt. A successful
network connection clears recovery even if MQTT subsequently fails. A server
publish success must not be confused with a network connection success.

## Hardware wiring

The supplied schematic maps:

| Modem | STM32 pin | Operation |
| --- | --- | --- |
| SIM800L RST | PB0 (`kSimResetPin`) | Open-drain LOW for 250 ms, then released; wait 3 seconds before initialization |
| ESP8266 RST | PB8 (`kEspResetPin`) | Active LOW for 100 ms, then released; wait 3 seconds |
| ESP8266 EN | PB7 (`kEspEnablePin`) | Kept enabled during reset |

Connect common signal ground and verify RST actually reaches the module. Do not
connect RST to a power terminal. Reset is a hardware restart, not removal of
power. SIM800L RESET uses an internal voltage-domain pull-up, so PB0 is released
as open drain rather than actively driving 3.3 V HIGH. Check your fitted board's
reset circuit; this is not a substitute for checking voltage compatibility.
See the manufacturer-authored [SIM800L hardware design, reset section](https://simcom.ee/documents/SIM800L/SIM800L%28MT6261%29_Hardware%20Design_V1.01.pdf)
and [Espressif hardware design guidance](https://documentation.espressif.com/esp8266_hardware_design_guidelines_en.html).

The modem-only reset preserves queued command replies in RAM, drops pending
routine Status, closes the old socket and binds MQTT callbacks again. After a
controller reset, RAM queues are lost as before; retry outstanding commands
from the server and check correlated application ACKs.

## Timing and precedence — important

Ten failures are not ten seconds. SIM registration waits up to 10 seconds per
attempt; retries retain their 5-second gaps. Existing sensor scheduling and
reconnect backoff also contribute. Wi-Fi's one-time operator prompt may wait
180 seconds per field with watchdog-aware delays; send a blank SSID line to
skip it during an unattended retry test.

The installed TinyGSM driver can wait longer than 30 seconds inside Wi-Fi join,
GPRS attach or socket operations. No watchdog feed was added inside those opaque
calls, and their library code was not changed. If a call fails to return before
the IWDG deadline, global reset takes priority **before** all ten retries can
complete. Thus the 10 + 10 policy is guaranteed for returned failures, not for
an unresponsive modem transaction. Both are recovery paths, with distinct logs.
Transport close/initialization during recovery is also protected by global IWDG.
Measure behavior with your installed ESP-AT/SIM firmware before deployment.

## Independent bench tests

1. **Normal regression:** keep production settings, flash the final sketch,
   confirm `Hardware watchdog: armed, timeout=30000 ms`, acquire all selected
   sensors and verify server telemetry plus command ACKs. No unexpected resets.
2. **SIM registration failure:** use a controlled unavailable-network setup,
   keeping the modem powered and UART responsive. Watch `[NETWORK] Failed
   attempt, stage 1: 1/10` through `10/10`. Confirm a PB0 LOW pulse and modem
   reboot while the STM32 does not reboot. Confirm stage 2 starts at `1/10`.
   After stage 2 `10/10`, confirm PB0 pulse, STM32 boot and deliberate-reset log.
3. **SIM GPRS failure:** with registration available, use a test-invalid APN.
   A returned GPRS failure counts once per attempt. If the driver instead waits
   past 30 seconds, expect the global GPRS-stage reset described above. Restore
   the correct APN afterwards.
4. **Wi-Fi unavailable:** select ESP8266, use an unavailable configured and
   saved AP (or incorrect test credentials), skip the serial prompt with a
   blank SSID, and verify the same 10 + 10 sequence on PB8. Confirm PB7 stays
   enabled and saved fallback selection is unchanged. A >30-second join uses
   global watchdog recovery instead of the returned-failure sequence.
5. **Recovery in stage 1:** restore network before the tenth failed attempt.
   Confirm `Connected; retry recovery cleared (stage 1, 0 failures)`. Remove
   network again: a fresh set of ten failures is needed for modem reset.
6. **Recovery in stage 2:** restore network after the first modem reset but
   before the second-stage threshold. Confirm the same clear message. The next
   outage must begin with modem-only recovery, not immediate controller reset.
7. **Broker-only outage:** keep network available but block/reject the test
   broker. No returned-network-failure threshold should accumulate merely from
   MQTT errors. Long blocking MQTT operations can still trigger global IWDG.
8. **Real hang:** use the existing main-loop watchdog self-test in a dedicated
   test image. Confirm reset around 30 seconds and the self-test stage/PASS log.
   Restore `APP_WATCHDOG_SELF_TEST_DISABLED` and reflash for production.
9. **Counter and power regression:** modem-only reset must not increase
   `wdt_reset_count`; deliberate second-stage IWDG reset increments it by one,
   as does global IWDG recovery. Verify sleep/wake and command behavior in each
   intended production profile. Software-only reset with IWDG disabled is not
   counted as an IWDG reset; keep it enabled in production.

Use a logic analyzer/oscilloscope on RST plus serial logs to distinguish modem
restart from controller restart. Record firmware/configuration, failure count,
pin pulse duration, reset cause, server recovery and ACK result. Host tests do
not verify the physical pin connection, supply quality, radio coverage or AT
firmware timing. Do not run network-unavailability tests by removing an antenna
from a transmitting module; use a safe controlled network setup.

## Automated checks

From the package root in PowerShell:

```powershell
./Node/IoT_Node_Encrypted/tests/network_recovery/run_tests.ps1
./Node/IoT_Node_Encrypted/tests/mqtt_priority/run_tests.ps1
./Node/IoT_Node_Encrypted/tests/remote_wake/test_config.ps1
./Validate-Release.ps1 -Python 'C:/Python314/python.exe'
```

Recovery tests compile the actual connection functions for both modems. MQTT
tests cover actual reset implementation, pulse timing/polarity, SIM open-drain
configuration, command-queue retention and real PubSubClient protocol behavior.
The build matrix additionally checks all eleven firmware profiles and reserved
EEPROM boundaries without flashing any hardware.
