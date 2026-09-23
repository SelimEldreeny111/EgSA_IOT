FLOW SCHEMA V2
==============

For deployment, database, dashboard, API, and test instructions, read
FLOW_METER_SERVER_GUIDE.md.

Status_Message is the periodic message the node publishes normally.
Telemetry is the response to GOSTM; it contains the same sensor readings plus config/status info like sampling rate, transmission rate, and active sensor count.
The old fields are:
node_id
sensor_id
timestamp
flow_rate
velocity
flow_rate_per_day
flow_rate_per_month
flow_rate_per_year
node_status
These now form a common flow block for either TUF or Supmea and the node
valve/on-off status. flow_rate is m3/h; day/month/year fields are consumption
volumes in m3.
The new soil moisture + temperature sensor fields are:
float soil_temperature;
float soil_moisture;
uint32_t soil_moisture_temp_valid;
Meaning:
soil_temperature: temperature from the soil moisture/temperature sensor, in Celsius.
soil_moisture: soil moisture percentage.
soil_moisture_temp_valid: tells the server whether this reading is real/valid.
So:
soil_moisture_temp_valid = 1
means the Modbus read succeeded and soil_temperature / soil_moisture should be displayed.
soil_moisture_temp_valid = 0
means the sensor was disabled, missing, or the Modbus read failed, so the server should ignore/show - for those values.
The new moisture + temperature + EC sensor fields are:
float ec_temperature;
float ec_moisture;
float electrical_conductivity;
uint32_t soil_moisture_temp_ec_valid;
Meaning:
ec_temperature: temperature from the EC-capable soil sensor.
ec_moisture: moisture from that sensor.
electrical_conductivity: EC reading.
soil_moisture_temp_ec_valid: same idea as above, but for the EC sensor.
So:
soil_moisture_temp_ec_valid = 1
means the EC sensor read succeeded.
soil_moisture_temp_ec_valid = 0
means ignore those EC sensor values.
sensor_mask is a compact bit field that tells the server which sensors are configured/enabled on this node.
Current bits are:
0x0001 = TUF flow meter enabled
0x0002 = soil moisture + temperature sensor enabled
0x0004 = soil moisture + temperature + EC sensor enabled
0x0008 = Supmea flow meter enabled
Examples:
sensor_mask = 1   // only flow meter
sensor_mask = 2   // only soil temp/moisture
sensor_mask = 3   // flow meter + soil temp/moisture
sensor_mask = 4   // only EC soil sensor
sensor_mask = 5   // flow meter + EC sensor
sensor_mask = 6   // both soil sensors, no flow meter
sensor_mask = 7   // all three sensors
The approved product masks are 0x0003 for TUF + HNDA and 0x000C for Supmea +
Sondas. active_sensor_count is the number of enabled devices and is normally 2.
Important difference:
sensor_mask / active_sensor_count say what the node is configured to use.
*_valid says whether the latest Modbus read actually succeeded.
So a sensor can be enabled in sensor_mask, but its valid flag can still be 0 if the sensor is disconnected or failed to answer.

Flow schema v2 appends meter type, period source, separate live/period/
cumulative validity, RTC trust, cumulative forward/reverse/net litres, period
quality, and alarms. Existing HNDA and Sondas fields and all old tag numbers
remain unchanged.
