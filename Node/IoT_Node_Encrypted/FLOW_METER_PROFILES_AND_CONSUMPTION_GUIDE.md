# STM32 flow-meter profiles and consumption guide

This guide applies to the Arduino STM32F401 node in IoT_Node_Encrypted and the
matching WIOT web server. The ESP32 and STM32CubeIDE projects are not part of
this implementation.

## 1. Select the product image

There is one product-selection macro near the beginning of
src/config/AppConfig.h:

    #define APP_SENSOR_PROJECT APP_SENSOR_PROJECT_SUPMEA_SONDAS

Use exactly one of these values:

| Product macro | Flow meter | Soil sensor | Flow source |
|---|---|---|---|
| APP_SENSOR_PROJECT_TUF_HNDA | TUF | HNDA temperature/moisture | TUF native day/month/year registers |
| APP_SENSOR_PROJECT_SUPMEA_SONDAS | Supmea SUP-FMC240 | Sondas temperature/moisture/EC | STM32 RTC calculation from the Supmea forward total |

The selected family is enforced at compile time. The current source default is
APP_SENSOR_PROJECT_TUF_HNDA.

After selecting the family, the **INDIVIDUAL SENSOR SWITCHES** block in
AppConfig.h provides one `true`/`false` choice per sensor:

| Switch | Effect when true |
|---|---|
| APP_ENABLE_TUF_SENSOR | Initialize and poll TUF |
| APP_ENABLE_HNDA_SENSOR | Initialize and poll HNDA |
| APP_ENABLE_SUPMEA_SENSOR | Initialize and poll Supmea |
| APP_ENABLE_SONDAS_SENSOR | Initialize and poll Sondas |

Set either member of the selected family to `false` to test the other sensor
alone. A false sensor receives no Modbus request and is excluded from the
active-sensor count and mask. Keep the other product family's switches false;
mixed families are rejected at compile time because they use different
product/protobuf semantics.

## 2. RS485 settings

All enabled devices share Serial1 at 9600 baud, 8 data bits, no parity, and one
stop bit. PA8 controls the ISL83485 DE and active-low RE pins.

| Profile | Device | Default Modbus address | Sensor-mask bit |
|---|---|---:|---:|
| TUF + HNDA | HNDA | 1 | 0x0002 |
| TUF + HNDA | TUF | 2 | 0x0001 |
| Supmea + Sondas | Supmea | 1 | 0x0008 |
| Supmea + Sondas | Sondas | 3 | 0x0004 |

The default masks are 0x0003 for TUF + HNDA and 0x000C for Supmea + Sondas.
With one sensor disabled, the mask contains only the enabled sensor's bit.
The compiler rejects duplicate addresses and addresses outside the Modbus
unicast range 1 through 247.

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
4. Confirm the serial output says RTC synced from epoch.
5. On the next valid Supmea read, confirm RTC trusted: YES.

Until then, live and cumulative values remain available, but calendar
consumption is invalid. The first synchronized Supmea baseline is partial by
design.

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

1. Select the intended product macro and verify physical Modbus addresses.
2. Compile and flash the STM32.
3. Confirm startup names the selected meter and soil sensor.
4. Confirm both Modbus reads are valid.
5. Send STIME and verify RTC trust.
6. For Supmea, note the initial forward total and Partial baseline.
7. Increase the real or simulated forward total.
8. Confirm Today, Month, and Year rise by the same increment.
9. Confirm the server meter/source/quality and cumulative totals.
10. Reboot the STM32 and confirm the calculated totals resume.
11. Disconnect one sensor and confirm its validity changes without a
    fabricated measurement.

## 9. Build and automated tests

Default Supmea + Sondas image:

    arduino-cli compile --fqbn "STMicroelectronics:stm32:GenF4:pnum=BLACKPILL_F401CC" IoT_Node_Encrypted

TUF + HNDA image without editing AppConfig.h:

    arduino-cli compile --fqbn "STMicroelectronics:stm32:GenF4:pnum=BLACKPILL_F401CC" --build-property "build.extra_flags=-DAPP_SENSOR_PROJECT=APP_SENSOR_PROJECT_TUF_HNDA" IoT_Node_Encrypted

Server tests:

    cd "<server folder>"
    python -m unittest discover -s tests -v

Simulator tests:

    cd "<simulator folder>"
    python -m unittest discover -s tests -v

For the Supmea simulator, use slave address 1. Enable automatic totals and
choose 60x or 3600x acceleration to observe volume growth quickly. Acceleration
does not change the STM32 RTC; use a controlled RTC time for boundary testing.
Reset meter totals tests the node's counter-reset handling.

## 10. Interaction with power-down mode

After RTC Standby, the next forward-total sample supplies the complete missed
increment. Calendar accuracy requires a retained, trusted RTC. Loss of backup
power falls back to the last EEPROM checkpoint and requires a new STIME.
Quality and validity fields make uncertainty visible rather than presenting it
as exact data.
