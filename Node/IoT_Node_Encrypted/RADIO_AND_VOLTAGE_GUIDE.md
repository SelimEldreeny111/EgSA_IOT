# Radio diagnostics and battery telemetry

This guide describes the current Arduino STM32 implementation. It replaces
older README references to documentation files that were not present in the
repository. Confirm the actual purchased radio's manual before selecting a
different module protocol; E32/AS32 versions are not interchangeable merely
because they use TTL UART.

## LoRa configuration and routing

Select sensor-node/gateway role and MQTT-direct/LoRa uplink in AppConfig.h.
Radio settings are in `src/radio/AS32_Config.h`. Both ends must have compatible
frequency/channel, air rate, addressing, parity, UART baud and wake timing.
`AS32_AUTO_APPLY_CONFIG` defaults to zero: changing a setting does not write it
to a previously configured module unless auto-apply is explicitly enabled or
the module is configured separately. Confirm the printed settings and actual
read-back/communication on the bench.

| Active build | STM32 RX / TX | Important separation |
| --- | --- | --- |
| Direct IP sensor node | PA11 / PA12 | LoRa path is not active |
| LoRa sensor node | PA12 / PA11 | Direct IP path is not active |
| IP side of gateway | PA11 / PA12 | Sensors are disabled on gateway |
| LoRa side of gateway | PA10 / PA9 | Uses the UART otherwise used by RS485 sensors |
| Debug monitor | PA3 / PA2 | Separate from sensor/modem UARTs |

Connect each STM32 RX to module TX and STM32 TX to module RX. LoRa control pins
are MD0 PB2, MD1 PB1 and AUX PC13. Do not leave competing modules driving the
same UART nets. PC13 cannot simultaneously serve AUX and the default valve
output; the firmware rejects that output command in the conflicting LoRa build.

Large encrypted messages are fragmented into bounded LoRa wire frames. A
gateway reassembles and forwards their unchanged encrypted payloads to MQTT.
Use frame hex logs at both ends to distinguish physical reception, reassembly,
link ACK, broker forwarding and server validation. A radio link ACK is not an
application command ACK or proof of server receipt.

Test normal node/gateway communication first, then fragmentation/all-four-sensor
payloads, then disconnected radio/ACK timeouts. Follow NEW_POWER_MODES_USER_GUIDE.md
for WOR wake probes and AUX/RTC Stop behavior; do not apply normal-mode-only
assumptions to a sleeping node.

## Why RSSI must not be a fabricated constant

`APP_LORA_MODULE_SUPPORTS_AS32_V3_RSSI` defaults to zero. The installed E32
profile deliberately disables UART RSSI queries and prints `UNSUPPORTED`;
it does not convert an arbitrary byte into a believable fixed dBm measurement.
Leave this setting zero for the present unsupported-radio profile.

The optional AS32 V3 path has a different diagnostic command family. Enable
it only after confirming that the exact fitted firmware supports those commands.
It accepts exactly one magnitude byte in the supported format and separately
tracks data/environment validity. RSSI is a serial diagnostic in this project,
not a newly added Status/Telemetry protobuf field. Changing this flag cannot
add a hardware measurement facility the module does not possess.

## Battery-voltage data path

BatteryMonitor.cpp discards the initial ADC sample, averages 16 12-bit samples,
and applies the configured divider and calibration:

```text
battery_voltage = average_count / 4095 * reference_volts
                * (high_ohms + low_ohms) / low_ohms * calibration_factor
```

Current defaults are PA0, 3.3 V reference, measured 21.6 kOhm upper and 9.8 kOhm
lower resistors, and calibration factor 1.0. The code comments describe a
100 nF ADC-node capacitor. Never apply battery voltage directly to the ADC pin;
check the actual board divider, reference, grounding and ADC limits before use.
Override APP_BATTERY_* values when the production board differs.

The runtime voltage is mapped centrally into Status tag 19 and Telemetry tag 5.
The same field mapping is used for direct MQTT, LoRa and command replies;
the web server stores and displays it. Disabled battery monitoring returns
zero, which should not be interpreted as a calibrated low-battery measurement.

Bench test: compare serial voltage with a meter at several safe supply levels,
then verify the same value in server RX/storage/dashboard for MQTT and LoRa.
Test a command Telemetry reply as well as a periodic Status. If the ADC log
changes but the server does not, check the current schemas, topic/node match,
server RX errors and browser refresh before changing calibration.
