# SIM800 MQTT recovery and command-priority guide

## What was wrong

The supplied test log contains 30 `SEND OK TIMEOUT` messages, repeated MQTT
reconnections, and no successful publish or received-command messages.

The previous publisher wrote AT commands directly to the modem UART. It waited
for `SEND OK`, but the installed TinyGSM SIM800 driver enables `AT+CIPQSEND=1`
and expects `DATA ACCEPT:` with an accepted-byte count. The old publisher also
bypassed PubSubClient's outgoing-activity tracking and discarded incoming
modem receive notifications while publishing. These are confirmed software
defects, not evidence that the server successfully received the uploads.
Blocking all four sensor reads in one pass further delayed command reception.

The log alone cannot establish cellular signal quality, power-supply stability,
broker availability, or correct server tenant/key selection. Check these on
the bench if communication remains unreliable after reflashing.

## New behavior

1. TinyGSM alone handles MQTT transport AT transactions and receive notifications.
   Both SIM800 and ESP8266 use their own installed driver implementations.
2. PubSubClient builds publishes and maintains MQTT keepalive. Buffered writes
   are checked against the driver's actual accepted-byte count. A zero or short
   write closes the socket instead of reporting success or continuing a damaged
   MQTT byte stream.
3. Incoming commands are serviced before routine sensor work and periodic
   Status uploads. ACK/Telemetry replies have a four-entry FIFO queue and always
   precede pending periodic Status. A received command invalidates an older
   queued Status snapshot containing pre-command control settings.
4. Only one enabled sensor is read per foreground pass. Modbus wait gaps also
   service command reception, rate-limited to a 100 ms minimum between service
   calls. Routine Status waits until the sensor cycle is complete.
5. Replies are queued, not published recursively inside the MQTT callback.
   Failed replies remain in RAM for reconnection retry; new command reception
   pauses while the reply queue is full. Direct commands for another node ID
   are rejected before application or ACK generation.
6. Modbus response timing excludes time spent servicing commands. The hardware
   watchdog stays active: command-service idle hooks neither feed IWDG nor
   overwrite the parent sensor's diagnostic stage. A stuck callback/read still
   resets the controller. Existing reset-counter persistence is unchanged.

No protobuf fields, sensor addresses, AES framing, RTC consumption calculations,
power profiles, or server protocol were changed. ESP32 and CubeIDE ports were
not updated. Legacy async function names remain for application compatibility;
they now represent a queue, not a raw-AT state machine.

## Important limits

- This is cooperative priority, not hard real-time preemption. An in-progress
  AT command, sensor decode, LoRa transaction, or network reconnect cannot be
  interrupted. The 100 ms service interval is not a guaranteed command latency.
- TinyGSM 0.12 is the validated interface. Its socket flag is accessed legally
  from a derived client to avoid repeated blocking socket-status queries;
  receive/read/write operations still use TinyGSM. MQTT PINGRESP timeout detects
  silently lost sockets. Re-run tests if upgrading this library.
- `accepted by modem (server receipt not confirmed)` means local transport
  acceptance, not broker/server delivery. These publishes use MQTT QoS 0. Confirm
  receipt in server RX logs and confirm commands using their correlated ACKs.
- Retry storage is RAM-only. A reset loses queued replies. Ambiguous network
  failure can cause duplicate replies; this is not an exactly-once protocol.
- No network means no live remote command delivery. Deep-sleep/RTC and queued
  wake profiles keep their existing reachability rules. Use NORMAL for the first
  test, then verify each desired power profile separately.

## Configuration before testing

Use the sketch in your same `WIOT_Final_PowerModes_20261001` folder. Its private
`src/config/AppConfig.cpp`, `AppSecrets.h`, sensor enables/addresses and server
configuration must remain local; never upload them to GitHub.

Check the following values without publishing credentials:

| Setting | Required agreement |
| --- | --- |
| Broker and port | Node and server must use the same broker/port |
| MQTT client ID | Unique for every simultaneously connected device |
| Node ID | `APP_NODE_ID`, payload ID, topic node and server selection must match |
| Company | Explicit Status, Telemetry, direct CMD and broadcast topics must agree |
| AES key | Same node/gateway/server key and framing version |
| Gateway company prefix | Must match the deployment tenant when using a gateway |

Your final copy currently uses direct topics for **Company_2, node 1**. The
separate company-prefix setting was **Company_1** when inspected. Direct-node
topics remain unchanged; check the prefix before a gateway test. Do not change
tenant IDs casually or bypass server topic/payload validation.

## Step-by-step hardware acceptance

1. **Baseline:** select NORMAL controller/modem power policies, SIM800 uplink,
   production WDT settings and unique sensor addresses. Start the server for
   Company_2/node 1, then compile and flash this updated Arduino sketch. Keep
   serial and server logs. Do not use the unrelated original sketch folder.
2. **Subscription:** check that both command subscription sends succeed. This
   local log is not proof of broker SUBACK; verify it by the next command test.
   No old `[async] SEND OK TIMEOUT` message should remain.
3. **Uplink:** run the simulator at fixed distinctive values. Verify Status
   messages arrive on the server and values match. Run for at least five minutes
   or more than two configured keepalive windows, whichever is longer. Record
   any reconnects/resets and their diagnostic stages.
4. **Commands:** use the server's GOSTM/get-telemetry control, then VALVE/open-close,
   STRAN/transmission-period, SRATE/sampling-period and STIME/RTC synchronization
   controls one at a time.
   Use valid values and a request ID; confirm each applied setting and matching
   ACK before continuing. Restore the original settings afterwards. An upload
   log alone is not a command ACK.
5. **Priority during sampling:** send a command while each sensor is being
   polled, then while periodic Status is due. Confirm a correlated reply comes
   before the next routine upload. Measure actual send-to-ACK latency; do not
   assume a 100 ms latency guarantee.
6. **Offline sensors:** disconnect/disable simulator responses for all four
   addresses while keeping enables true. Send commands during timeouts. They
   must still be serviced; subsequent complete Status cycles must show zero and
   invalid flags for unavailable groups. Restore replies and check recovery.
7. **Network recovery:** briefly remove the cellular network connection in a
   controlled bench test. The node must not claim server delivery. Restore it,
   verify reconnect/subscription and send a fresh command. Check the server's
   existing command-expiry/queued-wake behavior separately.
8. **Watchdog:** run the documented WDT self-test in a dedicated test image.
   Confirm reset cause, retained stage and incremented `wdt_reset_count`, then
   restore production self-test settings. An ordinary sensor timeout is not a
   watchdog hang.
9. **Other profiles:** repeat uplink/command tests with ESP8266 and LoRa/gateway,
   then follow `NEW_POWER_MODES_USER_GUIDE.md` for REMOTE_WAKE, RTC_PERIODIC,
   queued wake and LoRa WOR. A sleeping offline modem cannot receive an instant
   server command merely because command priority is enabled.

If Step 3 or 4 fails, provide matching node and server log timestamps. Distinguish
no raw RX, decrypt/schema rejection, wrong node/company, expired command,
driver-send failure and watchdog reset; they require different diagnoses.

## Automated regression checks

From the node directory in PowerShell:

```powershell
./tests/mqtt_priority/run_tests.ps1
./tests/watchdog_counter/run_tests.ps1
./tests/sensor_availability/run_tests.ps1
./tests/rtc_supmea/run_tests.ps1
./tests/remote_wake/run_tests.ps1
./tests/remote_wake/test_config.ps1
./tests/remote_wake/run_build_matrix.ps1 -ArduinoCli 'C:/Program Files/Arduino PLC IDE Tools/arduino-cli.exe'
```

Host tests require g++ on PATH. The MQTT suite additionally requires the real
PubSubClient sources; pass `-PubSubClientSource` if not in the script's default
Arduino library location. The ARM matrix compiles all four sensor drivers in
11 normal/power/gateway profiles and checks that flash load sections stay below
the reserved EEPROM sector. It compiles without flashing hardware.

New regression tests cover full/zero/partial driver writes, command-before-Status,
receive while publish is queued, ACK retry, reply-queue backpressure, foreign-node
rejection, subscription failure and empty idle polls. Tests using the actual
vendored ModbusMaster verify delayed-command response timing, offline timeout
and CRC rejection. The real PubSubClient test checks MQTT wire framing,
command parsing/ACK priority and 120 seconds of simulated keepalive operation.
These use simulated hardware; physical SIM800 delivery remains a bench test.
