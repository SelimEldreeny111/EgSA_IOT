# Final tested WIOT release — 29 October 2026

GitHub branch: `feature/2026-10-29-final-tested-release`

This branch contains the accumulated node firmware, server, sensor simulators,
guides, tests and documentation, including LoRa UART RX wake and the user-reported
9 mA bench result. Its active STM32 AppConfig.h matches the final working folder's
tested node-2 configuration. The implementation under the bench test was b60388b;
the following documentation update was b3eb122. This snapshot does not alter the
firmware algorithms or the locally tested settings.

## Active node configuration

| Setting | Value |
|---|---|
| Role / uplink | Sensor node / LoRa to gateway |
| Company / region / node | Company_1 / Region_1 / 2 |
| Controller mode | APP_COMPONENT_MODE_LORA_WOR |
| LoRa mode | APP_COMPONENT_MODE_WAKE_ON_RADIO |
| Wake source | APP_LORA_WOR_WAKE_SOURCE_UART_RX, PA12 |
| Combined sampling/report sleep interval | 120 seconds |
| RTC watchdog maintenance interval | 15 seconds |
| Command receive window | 5000 ms |
| Hardware watchdog | Nominal 30 seconds |
| Sensors enabled | TUF, HNDA, SUPMEA and Sondas |

The general-default configuration remains available on the preceding feature
branches. This branch deliberately starts with the tested LoRa-node profile.
For a gateway build, choose gateway role, NORMAL controller/radio policies and
APP_LORA_GATEWAY_WOR_TX=1 as described in the RX wake guide. Modem selection is
retained as ESP8266, but this node profile's active uplink is LoRa.

The user's existing valve commissioning values are preserved in AppConfig.h.
In this LoRa profile valve output is inhibited because the default valve enable
pin and LoRa AUX share PC13. Selecting another transport changes that pin-conflict
condition; configure the valve settings for the actual target board.

Private AppConfig.cpp/AppSecrets.h, server credentials/environment, live databases
and generated build outputs remain local. The repository includes configuration
examples and setup instructions. Generated Doxygen HTML is available in the final
working folder; the sources and generation script are versioned.

## Evidence and usage

Publication checks: 234 tracked node/server/simulator source and guide files
match the final working folder, and all 47 configuration policy cases pass.
The exact node-2 configuration compiles for BLACKPILL_F401CC: 91972 sketch bytes,
26492 global RAM bytes, flash load end 0x08016950 (below the reserved EEPROM
sector at 0x08020000). This is a compile check; the 9 mA measurement is the user's
separately recorded hardware result.

- [RX wake configuration, wiring and tests](Node/IoT_Node_Encrypted/LORA_WOR_RX_WAKE_GUIDE.md)
- [9 mA bench result](Documentation/Validation/LORA_WOR_9MA_BENCH_RESULT_20261029.md)
- [Firmware validation](Documentation/Validation/LORA_WOR_RX_WAKE_VERIFICATION_20261029.md)
- [Release setup](RELEASE_GUIDE.md)

The 9 mA observation confirms the initial current reduction. Multi-cycle RTC
reporting and server-command wake/reply acceptance remain separately recorded
tests. Flashing and physical hardware tests are performed by the user.
