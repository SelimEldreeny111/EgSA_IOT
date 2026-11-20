# WIOT serial configuration

Use the STM32 debug UART at **115200 baud, 8 data bits, no parity, 1 stop bit**.
Connect the 3.3 V USB-to-UART adapter TX to **PA3**, RX to **PA2**, and GND to GND.
Select CR, LF, or CRLF as the terminal line ending. Turn off the terminal's
local echo before entering a Wi-Fi password.

## Set up a unit

1. Send `config` followed by Enter while the unit is awake. For a sleeping node or
   a unit that cannot connect, press RESET and send `config` when the boot
   prompt appears. The boot window is 2.5 seconds and precedes network setup.
2. Enter an option number, then the requested value. The menu shows what is
   staged and prompts for another option. Use Esc to leave a value prompt.
3. Enter `save` to validate, write and verify the configuration, then restart.
   Use `cancel` to discard edits. `defaults` stages the compiled defaults and
   still requires `save`. The console discards staged edits after three minutes
   of inactivity. Normal traffic pauses while the menu is open.

For example, on a LoRa sensor node, select **4** and enter `120` for sampling,
select **5** and enter `300` for transmission, then select **6** and choose
`3` for LoRa WOR. Enter `save`. On its gateway, select **20**, enter `1`,
and save to enable the Mode 1 wake probe.

## Settings by firmware profile

| Profile | Menu settings |
|---|---|
| All | Company and region |
| Sensor node | Node ID, startup sampling and transmission intervals, power profile, fitted sensors and their Modbus addresses, command ACK policy, and retention when SPI flash is enabled |
| Node or gateway with LoRa | WIOT LoRa network ID |
| Node or gateway with an IP modem | MQTT broker and port, Wi-Fi credentials or SIM APN as appropriate |
| Gateway | Gateway ID, WOR transmit, heartbeat enable and interval |

For sensor edits, enter the Modbus address to enable the sensor, or enter
`off`. Enabled sensors on the same RS485 bus must have distinct addresses.
MQTT topics, payload node identity and LoRa addressing use the stored node ID
after the restart. Server SRATE and STRAN commands still change the running
schedule; a restart reloads the startup intervals set in this menu. Changing
the node ID makes the archive for the old ID unavailable
under the new ID. The menu does not clear the archive.

Power options depend on the compiled hardware profile. LoRa sensor nodes can
select NORMAL, RTC_PERIODIC, REMOTE_WAKE, LORA_WOR or RTC_QUEUED. Direct Wi-Fi
nodes have the same choices except LORA_WOR. Direct SIM nodes support NORMAL
and REMOTE_WAKE. Gateways stay NORMAL and may enable the transmit wake probe.
RTC standby profiles require their existing board wiring. A LoRa WOR node
needs a trusted RTC and a gateway with WOR transmit enabled.

The role, radio and modem drivers, physical pin assignments, RF channel and
FEC, valve commissioning, watchdog limits, and diagnostic verbosity are
set in the build or on the hardware. Use the same RF settings at both ends.
`APP_ENABLE_SERIAL_CONFIG=false` disables the console and saved overrides.
Diagnostic output may be disabled independently with `APP_ENABLE_DEBUG=false`.

## Persistence

Saved settings override the compiled defaults at startup and survive power
cycling. A Wi-Fi profile tries a serial-configured network first, followed by
its compiled network and existing Wi-Fi fallback. The console never prints
the saved password. Keep physical access to the UART controlled. Wi-Fi
credentials reside in local STM32 flash.

The settings record is versioned and checksummed. Blank or invalid settings
load the compiled defaults. A full internal flash erase clears settings.
Use stable power while saving. The STM32 EEPROM emulation uses a shared
erase sector, so interrupted writes can affect records in that sector.

Changing the Supmea address starts a new consumption baseline for that meter.
Existing recordings remain available through the archive for the current
node ID while they are within the configured retention period.
