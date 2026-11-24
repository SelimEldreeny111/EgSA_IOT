# Coordinated LoRa traffic qualification

The tests exercise the production gateway scheduler and LoRa fragment logic
with a simulated clock, radio and MQTT path. No board was flashed and no live
radio traffic was generated for these tests.

## Traffic scenarios

Each gateway run models ten minutes of traffic followed by a short drain
period. Nodes start with synchronized reporting deadlines and a 60-second
report interval. The test queues 60 direct commands in pairs, including during
active Status reception. It injects a 12-second MQTT outage and drops the
first MQTT persistence receipt for every fifth command. It also forces silent
grants and keeps one receive transaction active beyond the gateway's initial
five-second window. The simulated gateway must never start a second exchange
during an in-flight transmission.

| Simulated nodes | Logical command replies received | Status frames received / forwarded | Commands queued during Status | Longest simulated gap between grants |
|---|---:|---:|---:|---:|
| 2 | 60 / 60 | 21 / 21 | 20 | 33.6 s |
| 8 | 60 / 60 | 82 / 82 | 28 | 50.0 s |
| 32 | 60 / 60 | 260 / 214 | 48 | 79.9 s |

In each run the gateway retried 12 replies and recovered two replies received
during the outage. The 32-node model demonstrates that the roster limit alone
cannot justify a 60-second reporting target. The Status totals are transport
observations across the simulation and its drain period. Grant gaps depend on
the synthetic frame times and are not RF capacity measurements.

## Transport and regressions

- Interleaved fragments with the same message ID on two nodes remained
  separated by source ID. A saturated application queue withheld the final
  fragment ACK. Resending after capacity freed admitted exactly one copy,
  and a further resend recovered a lost ACK without another queued copy.
- The coordinated WOR build was exercised with UART RX wake, overdue reports waiting for a grant, and pending flash writes that prevent Stop.
- The release suite covers Wi-Fi/SIM MQTT receive, subscription readiness,
  reply recovery, WOR/RTC scheduling, flash history, and server persistence.
- The ordinary and coordinated STM32 node and gateway firmware builds were
  checked in the preceding delivery release. This qualification adds tests
  and evidence without changing the production firmware.

## Repeat

From the project root, run:

    powershell -NoProfile -ExecutionPolicy Bypass -File Validate-Release.ps1 -UseFactoryConfigurationFixture

Then run the integrated bench sequence in WIOT_MQTT_LORA_DELIVERY.md. Record
both node UARTs and the gateway UART, check actual WOR wake and sleep
behavior, and confirm the server records each requested reply. RF airtime,
interference, power consumption and modem behavior remain bench checks.
