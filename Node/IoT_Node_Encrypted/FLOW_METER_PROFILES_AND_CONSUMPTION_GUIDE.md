# STM32 four-sensor RS485 and consumption guide

This guide applies to the Arduino STM32F401 node in IoT_Node_Encrypted and the
matching WIOT web server. The ESP32 and STM32CubeIDE projects are not part of
this implementation.

## 1. Select each sensor independently

There is no longer a product-family selector. The four switches in
`src/config/AppConfig.h` can be set in any combination, including all four:

| Switch | Effect when true |
|---|---|
| APP_ENABLE_TUF_SENSOR | Initialize and poll TUF |
| APP_ENABLE_HNDA_SENSOR | Initialize and poll HNDA |
| APP_ENABLE_SUPMEA_SENSOR | Initialize and poll Supmea |
| APP_ENABLE_SONDAS_SENSOR | Initialize and poll Sondas |

The safe source default remains TUF `true` and the other three `false`. A
disabled sensor receives no Modbus request and is excluded from the active
count and mask. For a four-sensor test, set all four to `true`.

## 2. RS485 settings

All enabled devices share Serial1 at 9600 baud, 8 data bits, no parity, and one
stop bit. PA8 controls the ISL83485 DE and active-low RE pins.

| Device | Address macro | Source default | Sensor-mask bit |
|---|---|---:|---:|
| TUF | `APP_TUF_SENSOR_MODBUS_ADDRESS` | 1 | 0x0001 |
| HNDA | `APP_HNDA_SENSOR_MODBUS_ADDRESS` | 3 | 0x0002 |
| Supmea | `APP_SUPMEA_SENSOR_MODBUS_ADDRESS` | 2 | 0x0008 |
| Sondas | `APP_SONDAS_SENSOR_MODBUS_ADDRESS` | 4 | 0x0004 |

These defaults do **not** reconfigure physical meters. Match each address
macro to the slave address programmed in that meter. If your commissioned
Supmea is address 1, set its macro to 1; disable TUF or move TUF to another
address before enabling both. The compiler rejects duplicate addresses among
enabled sensors and addresses outside the Modbus unicast range 1 through 247.
With all four enabled, the mask is `0x000F` and count is 4.

If a physical device has a different address, override the matching
APP_*_SENSOR_MODBUS_ADDRESS macro. Every device on the same A/B bus must have a
unique address. Connect A to A, B to B, and use a reference ground when the
converter or meter provides one. Terminate only the two physical ends of a
long RS485 bus.

## 3. Meaning of transmitted values

| Field | Meaning | Unit |
|---|---|---|
| flow_rate | Instantaneous volumetric flow | m3/h |
| velocity | Fluid velocity | m/s |
| flow_rate_per_day | Consumption in the current local day | m3 |
| flow_rate_per_month | Consumption in the current local month | m3 |
| flow_rate_per_year | Consumption in the current local year | m3 |

When both flow meters are enabled, the original flow fields contain TUF and
the optional `secondary_flow_meter` protobuf record contains Supmea. A
Supmea-only build keeps Supmea in the original fields for compatibility.
HNDA and Sondas always use their own existing fields. The server stores each
meter separately in `meter_samples` and `consumption_periods`; the live node
view shows the additional meter in a second card. Older servers ignore the
new optional record, so update the server before expecting both readings.

The old protobuf field names contain flow_rate_per_*, but these three fields
are volumes, not rates. Their field numbers were preserved for compatibility.

For TUF, the node reads the meter's native day/month/year values. For Supmea,
the node reads forward, reverse, and net cumulative totals plus live values.
It normalizes volumetric unit codes 0 through 5 to m3/h. Mass-flow codes 6
through 11 are rejected because converting mass to volume requires density.

HNDA data remains in soil_temperature, soil_moisture, and
soil_moisture_temp_valid. Sondas data remains in ec_temperature, ec_moisture,
electrical_conductivity, and soil_moisture_temp_ec_valid. An enabled sensor can
still report an invalid latest read. Use the validity field; zero is a
legitimate value and must not be treated as failure.

## 4. Supmea day, month, and year calculation

The STM32 does not integrate instantaneous flow. It calculates each increment
from the meter's cumulative forward total:

    new consumption = current forward total - previous forward total

This remains reliable across normal MCU resets and missed samples because the
meter owns the primary cumulative counter.

The first trusted sample establishes a baseline and adds no historical water.
Its quality is Partial. Calendar boundaries come from the trusted RTC. If a
sample interval crosses a boundary, the increment is allocated proportionally
across that interval and marked Estimated.

Exceptional behavior:

- Backward movement up to APP_SUPMEA_COUNTER_NOISE_LITERS is ignored.
- A larger backward movement is treated as a meter counter reset. A new
  baseline is taken and quality becomes Counter reset.
- An impossible jump is rejected when APP_SUPMEA_MAX_EXPECTED_FLOW_M3H is
  configured. Set it to the installed maximum flow; zero disables this check.
- An untrusted or backward-moving RTC prevents the node from claiming valid
  calendar totals.

State is checksummed in RTC backup registers DR0 through DR13 after each
accepted sample. DR14 is the RTC-trust marker. The power manager uses DR15
through DR19, so the regions do not overlap. A durable EEPROM checkpoint starts
at offset 128 and is written at a baseline, boundary, reset/anomaly, or the
configured interval. This limits flash wear while surviving loss of backup
power.

To intentionally clear only the Supmea period state, build and flash once with:

    #define APP_RESET_SUPMEA_PERIOD_STATE 1

Wait for the Supmea period state RESET log, then return the macro to 0 and flash
again. Do not leave it enabled.

## 5. RTC and local calendar

RTC and transmitted timestamps remain UTC. The default period calendar is
APP_CALENDAR_TIMEZONE_AFRICA_CAIRO, including the current Egypt daylight-saving
rule. UTC and a fixed offset are also available in AppConfig.h.
The embedded rule matches the IANA Africa/Cairo definition used from 2023
onward. Because an MCU has no automatic timezone database update, review it
before deployment if Egyptian time law changes:
https://data.iana.org/time-zones/tzdb/tz-link.html

A placeholder date is deliberately not trusted. After a new board, backup
battery loss, or RTC reset:

1. Start the node and server.
2. Connect the server to MQTT.
3. Send STIME to the node.
4. Confirm the serial output says `RTC synced from epoch (verified)` and prints
   the actual current UTC date/time, not the 2024 placeholder.
5. On the next valid Supmea read, confirm RTC trusted: YES.

Until then, live and cumulative values remain available, but calendar
consumption is invalid. The first synchronized Supmea baseline is partial by
design.

For the STIME/Supmea watchdog-reset correction and its step-by-step acceptance
tests, see [SUPMEA_RTC_RESET_FIX_AND_TEST_GUIDE.md](SUPMEA_RTC_RESET_FIX_AND_TEST_GUIDE.md).
The snapshot is committed once through buffered EEPROM emulation; this does
not change the protobuf fields. The current global watchdog deadline is 30 seconds.

## 6. Protobuf compatibility and sensor data

All original field numbers remain unchanged. Flow schema v2 was appended:

| Value | Status tags | Telemetry tags |
|---|---:|---:|
| Meter type through RTC validity | 20-25 | 24-29 |
| Forward/reverse/net total litres | 26-28 | 30-32 |
| Period quality and alarm flags | 29-30 | 33-34 |

Meter type is 1 for TUF and 2 for Supmea. Period source is 1 for meter-native
and 2 for node-RTC-calculated. Quality values are Invalid, Valid, Partial,
Estimated, Counter reset, Anomaly, and Time uncertain.

HNDA and Sondas were not omitted: their original Status tags 10-16 and
Telemetry tags 16-22 remain intact. A central mapper fills Status, GOSTM
Telemetry, direct MQTT, and LoRa payloads so every transport carries the same
configured sensor data.

## 7. Server behavior

At startup, each company database is migrated without deleting old rows.
Legacy TUF rows are recognized only from the established TUF mask bit and are
marked as legacy; the server does not invent RTC trust or Supmea totals.

The server stores:

- every received payload in messages;
- one duplicate-safe flow record in meter_samples;
- current day/month/year snapshots in consumption_periods.

The dashboard shows meter, source, quality, RTC trust, cumulative
forward/reverse/net totals, and separate HNDA and Sondas cards. Period data is
available from:

    GET /api/consumption
    GET /api/consumption?node_id=1&period=day
    GET /api/consumption?node_id=1&sensor_id=1&period=month

The API returns volume_liters and volume_m3.

## 8. Commissioning sequence

1. Power down the RS485 bus, program each physical meter to a different
   address, and set the matching four macros. The source defaults are 1, 2,
   3, 4 for TUF, Supmea, HNDA, Sondas respectively. The bus is 9600 8N1.
2. Test one switch at a time (`true` for one sensor, `false` for the other
   three). Compile, flash, and confirm the named meter and address appear at
   startup. Confirm a valid read; `sensor_mask` must equal that meter's bit.
3. Enable all four, compile and flash again. Confirm four named polls,
   `active_sensor_count=4`, and `sensor_mask=0x000F`.
4. Update the server before testing dual-flow telemetry. Confirm its primary
   TUF card and second Supmea card show separate values; verify HNDA and
   Sondas values/validity independently.
5. Send STIME and verify RTC trust. For Supmea, note the initial forward total
   and Partial baseline. Increase the real or simulated total and confirm
   Today, Month, and Year rise by the same increment.
6. Query `/api/consumption?node_id=1&period=day` and confirm separate TUF
   (`flow_meter_type=1`) and Supmea (`flow_meter_type=2`) rows. Reboot the STM32
   and confirm the calculated Supmea totals resume.
7. Disconnect one meter at a time and confirm only that meter's validity
   changes. A stale numeric value must not be presented as a valid read.

The multi-sensor RS485 simulator in `SENSORS/Multi Sensor RS485 Simulator`
can emulate all four slave addresses on one serial bus for this sequence.
Use its configured addresses and values to compare each decoded reading.

## 9. Build and automated tests

This Git worktree does not contain the ignored, site-specific
`src/config/AppConfig.cpp` and `src/config/AppSecrets.h`. Supply your local
production versions (or copy the `.example` files and fill in valid values)
before compiling or flashing. Never commit the real credentials or AES key.

Default TUF-only image:

    arduino-cli compile --fqbn "STMicroelectronics:stm32:GenF4:pnum=BLACKPILL_F401CC" IoT_Node_Encrypted

All-four image without editing AppConfig.h:

    arduino-cli compile --fqbn "STMicroelectronics:stm32:GenF4:pnum=CoreBoard_F401RC" --build-property "compiler.cpp.extra_flags=-DAPP_ENABLE_TUF_SENSOR=true -DAPP_ENABLE_HNDA_SENSOR=true -DAPP_ENABLE_SUPMEA_SENSOR=true -DAPP_ENABLE_SONDAS_SENSOR=true" IoT_Node_Encrypted

Server tests:

    cd "<server folder>"
    python -m unittest discover -s tests -v

Simulator tests:

    cd "<simulator folder>"
    python -m unittest discover -s tests -v

For the Supmea simulator, use the configured Supmea address. Enable automatic totals and
choose 60x or 3600x acceleration to observe volume growth quickly. Acceleration
does not change the STM32 RTC; use a controlled RTC time for boundary testing.
Reset meter totals tests the node's counter-reset handling.

## 10. Interaction with power-down mode

After RTC Standby, the next forward-total sample supplies the complete missed
increment. Calendar accuracy requires a retained, trusted RTC. Loss of backup
power falls back to the last EEPROM checkpoint and requires a new STIME.
Quality and validity fields make uncertainty visible rather than presenting it
as exact data.
