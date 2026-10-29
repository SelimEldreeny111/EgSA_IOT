# WIOT additional power modes — STM32 Arduino node

These are **opt-in** modes. Existing NORMAL, RTC_PERIODIC and REMOTE_WAKE
remain available and retain their previous numeric settings. Nothing here
changes the ESP32 or STM32CubeIDE projects.

## Select a profile in `src/config/AppConfig.h`

| Profile | Controller | Active transport | Server command delivery |
|---|---|---|---|
| NORMAL (existing) | `APP_COMPONENT_MODE_NORMAL` (0) | NORMAL (0) | Immediate |
| RTC_PERIODIC (existing) | `APP_COMPONENT_MODE_POWER_DOWN` (1) | LoRa/Wi-Fi POWER_DOWN (1) | Only during the existing short awake window |
| REMOTE_WAKE (existing) | `APP_COMPONENT_MODE_REMOTE_WAKE` (2) | NORMAL (0) | Immediate WAKE with CPU Sleep |
| LORA_WOR_STOP (new) | `APP_COMPONENT_MODE_LORA_WOR` (3) | LoRa WAKE_ON_RADIO (2) | Gateway Mode-1 probe then command; STM32 Stop exits on UART RX by default |
| RTC_QUEUED (new) | `APP_COMPONENT_MODE_QUEUED` (4) | LoRa/Wi-Fi POWER_DOWN (1) | Server mailbox dispatches at next Status |

Only compile a **sensor node** with the two new controller profiles. The
gateway stays controller NORMAL. The node's active transport must match its
controller profile; invalid combinations fail at compile time.

Both new modes require a trusted RTC: send **STIME** from the server while
the node is awake before commissioning sleep. A valid-looking default date
alone is not sufficient. Without trusted time, the node stays awake and logs
the reason. RTC trust must survive the chosen board's backup-power conditions.

### LoRa RTC-or-radio wake

For the LoRa **sensor node**, select LoRa uplink and:

```cpp
#define APP_CONTROLLER_POWER_MODE APP_COMPONENT_MODE_LORA_WOR
#define APP_LORA_POWER_MODE APP_COMPONENT_MODE_WAKE_ON_RADIO
```

Set `APP_UPLINK=APP_UPLINK_LORA_TO_GATEWAY` (the value is 2). Build the
**gateway firmware separately**, keeping its controller and LoRa policies
NORMAL, with:

```cpp
#define APP_LORA_GATEWAY_WOR_TX 1
```

Both E32 radios must have the same channel, UART settings and wake interval.
The gateway's wake-preamble setting must be at least the node's receive
monitor interval. The gateway sends a Mode-1 wake probe, waits for the node
to restore its clock/UART and change from Mode 2 to Mode 0, and then sends
the encrypted command. The node's E32 is in Mode 2 between events and cannot
transmit until returned to Mode 0. The default wake source is LoRa TXD -> STM32
UART RX (PA12 on a sensor node), monitored by GPIO EXTI while UART alternate
function is preserved. AUX on PC13 remains connected for ready/busy checks;
it does not generate wake interrupts in this configuration. M0=PB2 and M1=PB1
are radio mode outputs. See [RX wake configuration and tests](LORA_WOR_RX_WAKE_GUIDE.md).
Set APP_LORA_WOR_WAKE_SOURCE=APP_LORA_WOR_WAKE_SOURCE_AUX to retain the older
AUX wake implementation.

After a successful report, the node listens for
`APP_LORA_WOR_COMMAND_WINDOW_MS` (default 5 s), then enters STM32 Stop.
Either the selected wake input or RTC exits Stop. The RTC also wakes the MCU every
`APP_LORA_WOR_WATCHDOG_WAKE_SECONDS` (default 8 s) to feed the existing IWDG;
the normal watchdog timeout is now about 30 s. This heartbeat is not used
to hide a hung active application. On the report deadline the node samples
and publishes again. On a receive edge it listens for and handles the command. WAKE can
hold the node active for the requested lease.

**Bench qualification is mandatory.** The first probe packet may be lost
while the STM32 restores its clock and UART; that is intentional, but the
subsequent command must be captured. Verify this with the real E32 modules,
chosen UART/air rates, worst-case temperature, command fragments, and
collisions. Verify the selected wake input and that UART reception remains
functional after each Stop wake. If radio restoration fails, firmware resumes active operation
and logs an error rather than claiming it is asleep/reachable.

### RTC-scheduled command mailbox

For a LoRa sensor node:

```cpp
#define APP_CONTROLLER_POWER_MODE APP_COMPONENT_MODE_QUEUED
#define APP_LORA_POWER_MODE APP_COMPONENT_MODE_POWER_DOWN
```

For a Wi-Fi sensor node, use the same controller setting and set
`APP_WIFI_POWER_MODE` to `APP_COMPONENT_MODE_POWER_DOWN`; select the ESP8266
IP uplink. The SIM800L is **not supported in this profile on this PCB**:
PWRKEY is not MCU-controlled, so powering the modem down cannot be followed
by a guaranteed restart. The compiler rejects that selection. ESP8266/LoRa
deep sleep does **not** receive commands while sleeping.

The node samples and publishes Status, then keeps its command path open for
`APP_QUEUED_COMMAND_WINDOW_MS` (default 20 s). It enters the existing
watchdog-safe RTC/Standby handoff afterward. Standby resets the STM32 at its
next RTC wake. A queued WAKE command received in this window keeps the node
active for its requested duration; it does not wake an already sleeping node
early.

In the web server Command panel choose **Queue until next Status** and a
per-node target. Set an expiry in 60..604800 seconds (default 86400). The
server stores the request in its `pending_commands.db` and does not use MQTT
retained messages. On a valid matching node Status, it dispatches **one**
due command, then waits for the node's encrypted Telemetry ACK. A rejected
command is recorded as `rejected`; an ACK lost in transit permits retry of
value-setting commands on a later Status. **WAKE is dispatched at most once**
to avoid renewing its lease after a Standby reset. If its ACK is lost, it
remains `dispatched` until expiry; inspect the node before deliberately sending
a new WAKE request. Further pending commands wait for later Status reports. The
server must be running and broker-connected when the Status arrives.

The response includes `request_id` and `expires_at`. Inspect it with:

```
GET /api/queued_command/<request_id>?company=<company>&node_id=<node_id>
```

States are `pending`, `dispatched`, `acknowledged`, `rejected`, `expired`.
`dispatched` means execution is unconfirmed; `expired` does not prove a
previously dispatched command was never executed. MQTT publication alone is
not delivery confirmation. This is not an exactly-once delivery protocol.
Only an authorized administrator for that company can inspect it. The
server/firmware protobuf adds Telemetry fields 41–43 for a command ID,
request ID and success flag; old protobuf tags remain unchanged. A command
ACK uses cached sensor values and is not inserted as a new flow/consumption
sample. Existing SRATE/STRAN/RTC/VALVE commands set values rather than
incrementing counters; STIME uses the current server time at each dispatch.
WAKE is the non-retryable exception. Do not extend queued delivery to other
non-idempotent commands without durable
node-side deduplication.

## Step-by-step commissioning

1. Update and restart the server first, then keep all profiles NORMAL and
   confirm existing sensor, LoRa, Wi-Fi and server
   operation. Back up the server's runtime databases and use local secrets;
   never flash the repository's example key/configuration.
2. Build the desired node/gateway profiles independently and send STIME while
   awake. Confirm `power_mode`
   Status values: 1 NORMAL, 2 RTC_PERIODIC, 3 REMOTE_WAKE, 4 RTC_QUEUED,
   5 LORA_WOR_STOP. Run the Python server tests and the firmware build matrix.
3. Test RTC_QUEUED first with `APP_POWER_SLEEP_SECONDS=30`. Queue one benign
   `GOSTM` or `SRATE` command while asleep. Confirm no immediate execution,
   one dispatch after Status, a matching node ACK, and no retransmission
   after ACK. Repeat with broker temporarily disconnected; the row must stay
   pending until a later Status. Test expiry and a rejected command.
4. For LORA_WOR_STOP, use a powered gateway and one E32 node. Measure current
   at node battery input in active, Mode-2/Stop and wake states. Send at least
   20 commands while the node is in Stop. Confirm AUX wake, gateway probe,
   command execution/ACK, and subsequent RTC Status. Repeat with RF loss and
   interrupted UART traffic. Check no false watchdog resets across several
   report intervals.
5. Test with all four configured RS485 sensors, RTC flow accumulation, battery
   voltage, and the final production sampling/report interval. Only then
   enable the selected mode on deployed hardware.

## Important limits

- LoRa hybrid wake requires the gateway to remain available; an unpowered
  gateway cannot forward server commands.
- Stop retains STM32 RAM; Standby does not. No GPIO on this board can wake
  the existing Standby profile through LoRa AUX. PA0 is already battery ADC.
- SIM800L DTR/RI are not wired to the STM32 in the supplied schematic. This
  release does not claim SIM800L MQTT-command hardware wake.
- RTC_QUEUED inherits Standby's reset semantics: SRATE/STRAN and GPIO output
  state are RAM settings and return to their configured defaults after reset.
  An execution ACK is not a promise of persistent settings or a valve held
  through sleep. LoRa builds also reject VALVE when its GPIO conflicts with AUX.
- The queued command window starts after the node sends Status, not after the
  server receives it. Measure gateway/broker latency and increase the window
  if needed. The node cannot know that the entire server mailbox is empty.
- A physically fitted but unselected modem or RS485 transceiver may still draw
  current. Measure the **whole board**; these modes are not a guarantee of a
  particular milliampere value.

## Automated checks

From the node sketch directory, in PowerShell:

```powershell
./tests/remote_wake/run_tests.ps1
./tests/rtc_supmea/run_tests.ps1
./tests/remote_wake/run_build_matrix.ps1 -ArduinoCli 'arduino-cli'
```

From the Python web server directory:

```powershell
python -m unittest discover -s tests -v
node --check static/js/app.js
node tests/test_wake_control.js
```

The build matrix covers 11 normal, existing sleep, new sleep and gateway
profiles with all four sensor drivers enabled. It also checks that firmware
does not overlap the flash EEPROM sector. Host checks cover 28 configuration
guards, 16 RTC/Supmea regression scenarios, 41 Python server tests including
mailbox dispatch/ACK/expiry,
and existing remote-wake UI behavior. These checks do not substitute for the
real Stop/AUX/current measurements above. Local `AppConfig.cpp` and
`AppSecrets.h` remain private; use your own values when building for hardware.
