# LoRa WOR UART RX wake: initial current-reduction result

| Item | Recorded result |
|---|---|
| Test date | 29 October 2026 |
| Evidence source | User-supplied serial log and measured-current report |
| Firmware under test | b60388b — UART RX wake implementation |
| Controller / platform | STM32F401, Arduino firmware |
| Role | LoRa sensor node; final-folder configuration uses node ID 2 |
| Controller power mode | APP_COMPONENT_MODE_LORA_WOR |
| LoRa power mode | APP_COMPONENT_MODE_WAKE_ON_RADIO |
| Wake source | APP_LORA_WOR_WAKE_SOURCE_UART_RX; LoRa TXD -> PA12 |
| AUX connection | Retained for radio ready/busy checks; not the wake interrupt |
| Measured low-current state | **Approximately 9 mA, reported by the user** |
| Initial result | **Current reduction confirmed by user; Stop-request path reached** |

## Observation

After flashing the UART_RX wake update, the user supplied the log below and
reported: "the current dropped to 9 m ampere". Earlier unsuccessful sleep attempts
were reported at approximately 42 mA and repeatedly exited before Stop on AUX
callbacks. The new log reaches the Stop request with UART_RX selected, RX HIGH,
no selected-input interrupt/pending flag, no buffered UART bytes, and radio
M0=0/M1=1.

```text
LoRa diag: raw=1027 buffer=0 noise=10 version=1 network=0 length=0 crc=0 overflow=0 timeout=0 frag_drop=0 frag_timeout=0 queue_drop=0 rx_frames=9 tx_frames=12 wire_rx=51 wire_tx=41 ack_rx=41 ack_tx=0 retries=0 ack_timeout=0 tx_bytes=1913 last_rx_rssi=UNSUPPORTED ambient_rssi=UNSUPPORTED rssi_note=E32-TTL-100_has_no_UART_RSSI
Power: WOR PC13 RTC pin functions before=0x0 tamper1=0
Power: WOR armed stop_calls=0 rtc_elapsed_s=0 AUX=HIGH wake_source=UART_RX wake_level=HIGH wake_irq=0 wake_edge_phase=NONE wake_pending=0 rtc_irq=0 uart_rx=0 M0=0 M1=1
Power: WOR Stop requested; alarm_epoch=1793276921
```

The armed snapshot's stop_calls=0 is expected before the first Stop attempt.
The subsequent Stop-request line records intent to call the HAL; the reported
current drop supplies the additional bench evidence. The excerpt does not
contain a post-Stop heartbeat, exact sleep duration, or decoded command reply.
The displayed alarm epoch is retained as logged; synchronization accuracy was
not independently checked for this measurement.

## Informal current comparison

| State reported during troubleshooting | Current |
|---|---:|
| Earlier unsuccessful sleep attempt / active loop | Approximately 42 mA |
| UART_RX WOR low-current state | Approximately 9 mA |
| Difference | Approximately 33 mA lower |
| Relative reduction against that earlier reading | Approximately 79% |

The comparison uses the user's approximate readings: (42 - 9) / 42 × 100.
The earlier reading is the unsuccessful-sleep baseline, not a qualified NORMAL
mode reference. These are bench assembly readings, not a claim that the STM32
silicon alone consumes 9 mA. Meter position, supply voltage at the measurement
point, exact powered-module population, observation duration and averaging method
were not supplied. No power, energy or battery-life estimate is inferred.

## Configuration retained in the final copy

```cpp
#define APP_CONTROLLER_POWER_MODE APP_COMPONENT_MODE_LORA_WOR
#define APP_LORA_POWER_MODE APP_COMPONENT_MODE_WAKE_ON_RADIO
#define APP_LORA_WOR_WAKE_SOURCE APP_LORA_WOR_WAKE_SOURCE_UART_RX
```

The final-folder settings at this release retain APP_POWER_SLEEP_SECONDS=120,
APP_LORA_WOR_WATCHDOG_WAKE_SECONDS=15, a 5000-ms command window and a nominal
30-second watchdog. These are recorded configuration values, not newly measured
timing results. The gateway must remain NORMAL with APP_LORA_GATEWAY_WOR_TX=1
for the probe-plus-command wake sequence. Its powered state during the supplied
current observation was not specified.

## Acceptance status

| Check | Status for this bench report |
|---|---|
| UART_RX source selected and Stop request reached | Observed in supplied log |
| Reduced current around 9 mA | Confirmed by user's measurement report |
| RTC heartbeat wakes and return to low current | Awaiting reported bench result |
| Periodic sampling/reporting across multiple cycles | Awaiting reported bench result |
| Server command wakes node, executes and returns matching reply | Awaiting reported bench result |
| Fragmented traffic / two-node operation / extended soak | Awaiting reported bench result |
| Reset counters unchanged during normal Stop wakes | Awaiting reported bench result |

This is an initial current-reduction success. The original electrical source of
the repeated PC13/AUX callbacks remains unconfirmed. Firmware behavior was not
changed for this documentation update.

Next: verify the RTC heartbeat and two report cycles, then one immediate GOSTM
command during sleep, followed by repeated command/reply and two-node tests.
See the [RX wake guide](../../Node/IoT_Node_Encrypted/LORA_WOR_RX_WAKE_GUIDE.md)
and [implementation verification](LORA_WOR_RX_WAKE_VERIFICATION_20261029.md).
