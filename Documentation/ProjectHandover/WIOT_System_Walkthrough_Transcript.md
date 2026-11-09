# WIOT system walkthrough transcript

Illustrated narration for the active STM32 Arduino release.

## 00:00:00 WIOT from field to dashboard

WIOT brings water and soil measurements from the field to a web dashboard. This illustrated walkthrough follows the active STM32 release, from a sensor reading to a verified operator command.

## 00:00:15 Two routes to the server

A sensor node polls its enabled instruments on a shared RS485 bus. A direct build sends its status and data through Wi-Fi or a SIM800L modem.

A LoRa build sends radio frames to the gateway. The gateway reassembles the message and publishes it to the same scoped MQTT routes.

The Python server validates company, region and node scope, stores the reading, and shows it on the dashboard.

## 00:00:47 From sample to stored record

The sampling deadline starts a polling cycle. The node also reads battery voltage. Supmea consumption uses changes in cumulative volume and trusted clock time.

A failed sensor group carries zero values and invalid quality. The other groups remain usable, and the node continues reporting.

When the external archive is enabled, the node commits completed samples to SPI flash. The retention generation lasts twenty-four elapsed hours.

The transmission deadline sends status, normally using the latest committed sample. Keep its acquisition time separate from the server's receipt time.

## 00:01:34 Trace a command to its outcome

In the dashboard, choose the company, region and node. Send a get status telemetry request and keep the request identifier.

A direct node receives the broker command. On the LoRa route, the gateway listens to scoped direct commands and regional broadcasts.

The intended node handles the request and returns its cached measurement snapshot. Radio acknowledgements cover the individual fragments.

Match the application reply on the server to the same request identifier. That reply is the evidence of node handling.

## 00:02:14 Wake for work and recover from stalls

Start with normal power mode. Confirm communications before selecting remote idle, wake on radio, or a supported standby profile.

In wake on radio mode, the normal gateway sends a wake probe. The leaf wakes on its UART receive pin and processes the addressed command.

The real-time clock tracks sampling and reporting deadlines separately. It also schedules watchdog service during long idle periods.

If foreground progress stalls, the watchdog can reset the controller. Record watchdog and power reset counters separately.

## 00:02:57 Flash the board you intend to test

Open the flashing manual and pick a profile. Check the node identity, role, transport, enabled sensors and power mode before compiling.

Verify the sketch in Arduino and export the image for the selected board.

Use ST-Link and the SWD wiring in the manual. Wait for programming and verification to complete.

Open the serial log and reset the board. Match the reported role and node identifier to your label before testing the link.

## 00:03:33 Build evidence at the bench

Start with one node. Check a status and a correlated command reply. For LoRa, add the second leaf after the first path works.

Load the four-sensor simulator fixture. Compare values, then mute devices and verify continued reports with invalid quality.

Synchronize the clock, check stored history, and test the selected sleep and recovery behavior on the board.

Capture the image, node identity, request identifiers and measured timing and current. The manual gives expected results for each test group.

## 00:04:15 Open the project handover

Use the handover index to open the system report, operator manual, editable flowcharts and source entry points. Record hardware acceptance against the deployed boards and test setup.
