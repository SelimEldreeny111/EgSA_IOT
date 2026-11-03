# STM32 node and gateway diagnostic logging

Release: 3 November 2026. Applies to the Arduino STM32 firmware in this folder,
for both sensor-node and LoRa-gateway roles.

## Choose testing or launch

The first configuration block in `src/config/AppConfig.h` contains:

```cpp
#ifndef APP_ENABLE_DEBUG
#define APP_ENABLE_DEBUG true
#endif
#ifndef APP_DEBUG_RAW_FRAMES
#define APP_DEBUG_RAW_FRAMES false
#endif
```

| Build | APP_ENABLE_DEBUG | APP_DEBUG_RAW_FRAMES | Result |
|---|---|---|---|
| Normal testing | `true` | `false` | Detailed events and readings; packet hex dumps omitted |
| Radio/packet investigation | `true` | `true` | Events plus encrypted payload and radio wire hex dumps |
| Launch | `false` | `false` | Diagnostic UART is not started; no diagnostic output or formatting |
| Master disabled, raw selected | `false` | `true` | Still silent; the master switch takes priority |

Change the macro, compile and flash each affected STM32. A macro is a build-time
setting; changing it in the editor does not change already flashed firmware.
Both macros accept only `true`/`false` (or `1`/`0`). Defaults retain testing logs.

The debug port remains **PA2 TX / PA3 RX, 115200 baud, 8N1**. These are debug
pins, separate from the LoRa, modem and RS485 protocol UARTs.

Disabling debug removes diagnostic calls **and their argument evaluation**.
For example, a string is not formatted and a diagnostic-only buffer is not
walked merely to discard its output. Owned output calls are audited by tests.
The application still services the watchdog, polls sensors, stores samples,
accepts commands, transmits telemetry and enters its configured power mode.
Faults and reset counters continue to be represented in normal telemetry.

The serial Wi-Fi credential prompt is available only with debugging enabled.
A silent launch uses configured Wi-Fi credentials first, then the saved flash
fallback, followed by the existing network recovery policy. It does not wait
for input on an invisible serial console. The optional ESP firmware-version
query (`AT+GMR`) is also skipped in a silent build. Actual AT communication,
LoRa configuration writes when enabled, and Modbus requests remain active.

`APP_ENABLE_COMMAND_ACK_REPLIES` is independent. Setting debug false does not
disable command acknowledgements or flash-history replies.

## Read the output

Each nonempty diagnostic line has this prefix:

```text
[tick_ms=1234][INFO][CMD] received request=42 command=FLASH_STATUS(10) target=2 local=2 scope=direct data=0
```

`tick_ms` is Arduino active milliseconds since boot. STM32 Stop pauses that
clock; use the explicit RTC `epoch` fields and power `rtc_elapsed_s` fields to
measure wall time across Stop. It is not a UTC timestamp. It wraps with Arduino
`millis()`. No RTC transaction is needed just to prefix a line.

`INFO` describes normal activity, `WARN` identifies rejected requests or retry
conditions, and `ERROR` identifies failed operations. Optional raw byte rows use
`TRACE`. Related events carry identities such as node, request, message or
sample sequence rather than relying on screen position.

| Module | Information |
|---|---|
| BOOT, WDT | Role, topic scope, watchdog policy, reset cause and cumulative counters |
| APP | Sample start/completion, rates, enabled sensors and LoRa Status result |
| RS485, TUF, SUPMEA, HNDA, SONDAS | Addresses, transactions, decoded readings and validity/errors |
| SENSORS, VOLUME, RTC | Calendar totals, source/quality, persistence and time synchronization |
| BATTERY, VALVE | Voltage and output actions; valve messages describe software actuation |
| CMD | Request ID, command name/ID, target, scope, argument, duplicate handling and result |
| CODEC, TLM | Encoding errors, current/stored source, timestamp, sensor mask, frame size and counters |
| LORA | Named payload type, source/message, fragmentation, ACKs, retries, CRC and link counters |
| GATEWAY, MQTT | Routing topics, local send outcome, command priority and connection recovery |
| FLASH | Chip/status, append queueing, commits, retention/clear transitions and history progress |
| POWER | Selected policies, Stop preparation, wake source, RTC heartbeat, exit reason and deferrals |

The four-sensor acquisition and numeric reading logs retain their familiar
field names and units, now with a consistent module/timestamp prefix.

An example command/reply sequence is:

```text
[tick_ms=1234][CMD...] received ... request=42 ...
[tick_ms=1235][FLASH...] status request=42 ... records=24 ...
[tick_ms=1236][CMD...] result request=42 command=FLASH_STATUS outcome=accepted
[tick_ms=1237][CMD...] reply_ready request=42 ... bytes=177 ...
[tick_ms=1240][LORA...] tx_begin ... type=DATA ... fragments=7 ...
[tick_ms=1250][LORA...] tx_fragment ... part=1/7 ... attempt=1/4
...
[tick_ms=5000][LORA...] tx_complete ... stage=transport_acknowledged server_receipt=unconfirmed
```

The shortened prefixes above are illustrative. Actual output uses the complete
`[tick_ms=...][LEVEL][MODULE]` prefix on every line. Frame sizes, counts and times
depend on the real message; this example is not an expected byte-level trace.

### Distinguish acceptance from completion

- `sample_append ... queued_not_yet_committed` means a RAM queue accepted the
  sample. `journal_update ... committed_records=...` reports durable progress.
- Flash state codes are `0=Disabled`, `1=Missing`, `2=Unformatted`,
  `3=Recovering`, `4=Ready`, `5=Full`, `6=Fault`.
- `clear_request ... accepted_async` acknowledges the clear request. Subsequent
  generation/record events and `clear_sweep_complete` describe its progress.
- A fragmented LoRa `transport_acknowledged` event confirms the peer transport's
  fragment ACKs. An unfragmented `radio_write_accepted` event confirms the local
  radio write. Neither proves that the web server stored the measurement.
- MQTT `modem_write` describes local transmission acceptance, not server receipt.
- Flash history advances only after a matching server `FLASH_HISTORY_ACK`
  (command 14). `history_server_ack` / `history_complete` show that confirmation.
- A valve ACK confirms software pulse execution; physical valve position still
  requires observation or an independent position sensor.
- `sleep_deferred reason=RTC_UNTRUSTED action=send_STIME` appears once while the
  schedule-driven LoRa WOR policy waits for valid time, instead of flooding the
  console. A valid STIME permits the normal scheduler to proceed.

No AES key or Wi-Fi password is added to diagnostics. Raw packet logs contain
wire/encrypted frames; keep raw dumping off during routine timing measurements.

## Step-by-step bench check

1. Build with debug true and raw frames false. Open the debug terminal before
   resetting the STM32. Confirm role/node/topic scope, reset counters, sensor
   addresses, power policy and watchdog configuration.
2. Let one sample finish. Check each enabled sensor's validity and decoded
   values. Confirm `sample_complete`, then flash append/commit if available,
   then `status_ready` with its sample sequence and source.
3. Send a read-only GOSTM or FLASH_STATUS from the server. Match its request ID
   across command reception, result, reply creation and transport output.
   Confirm receipt on the server separately. Use FLASH_LAST/FLASH_TODAY to
   inspect stored measurements and server history acknowledgements.
4. For LoRa WOR, synchronize the RTC, set independent SRATE/STRAN deadlines
   with enough quiet time, and confirm Stop entry, command wake and scheduled
   work. The gateway must retain `APP_LORA_GATEWAY_WOR_TX=1` for WOR downlinks.
5. If needed, temporarily enable raw frames, rebuild and inspect CRC/header
   errors or packet boundaries. Turn raw frames off after the investigation.
6. Build with debug false and flash the same role/configuration. Confirm the
   debug terminal remains blank through reset, sampling, commands and wake.
   Confirm the server still receives Status, command replies, flash status and
   history. Compare actual current/timing on hardware; software builds alone
   do not establish a measured current saving.
7. Re-enable debug true and rebuild when further troubleshooting is required.

Do not erase flash, clear counters or actuate a valve merely to check logging.
The read-only commands above are sufficient for basic verification.

## Implementation and software checks

`src/platform/DebugLog.h` is a header-only, fixed-memory foreground logger.
Do not call it from an interrupt or the fault handler. Structured events use
a 256-byte stack formatting buffer and mark oversized text with `[truncated]`.
Legacy numeric reading output uses Arduino's existing numeric formatting.
There is no dynamically allocated log queue or logging task.

Host checks in `tests/debug_logging/run_tests.py` exercise all four switch
combinations, argument suppression, zero UART access when disabled, line framing
across modules, truncation, unsigned 64-bit argument formatting, absence of a
debug string from the silent executable, output-call coverage, and identical
LoRa fragment-ACK wire bytes with debugging on/off.

Other regression suites cover command priority, RTC consumption, power modes,
network retry/reset, sensors, valve control, flash journal/history and counters.
The release validation note records the compiler/build results for this change.
