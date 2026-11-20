# WIOT water operations

The **Water Operations** tab monitors each configured water line using the node's
existing Status reports. It works through Wi-Fi, SIM800L and LoRa gateway paths
that publish the current regional MQTT topics. This release runs in the web
server and uses the installed sensors, gateway and firmware. It is alert-only.

## Configure a monitored line

1. Restart the WIOT server using the standard `python server_web.py` entry point.
   Keep the existing server data directory and MQTT configuration. The server
   adds two columns to each tenant's message database and creates
   `water_operations.db` beside its main database.
2. Sign in as an administrator and select the **Company** and **Region** at the
   top of the dashboard. Open **Water Operations** and expand **Configure a
   monitored line**.
3. Enter the node ID, a site or line name, and the TUF or Supmea meter to monitor.
   A Status report can carry the selected meter in either meter slot. Enter the
   gateway ID for a LoRa line when that gateway already sends its heartbeat.
4. Set **Report interval** to match the node's normal Status transmission
   interval in seconds. The sample gap defaults to twice the report interval.
   Set the maximum gap and confirmation holds to suit the site's reporting
   cadence. Set the site time zone using an IANA name such as `Africa/Cairo`.
5. Enter only the flow and battery thresholds you want to use. The flow limits
   are in m³/h. The battery limit is in volts. Quiet hours can cross midnight.
   Save the profile and wait for a new Status report.

Use **Edit** to update a line. Clearing **Monitoring enabled** pauses it and
retains its incident history. Changing settings starts a new observation
period. Open incidents from the previous settings are marked
**Monitoring changed**. Include `water_operations.db` in the server backup to
retain profiles, incident history and acknowledgements.

## Interpret the dashboard

| Condition | Behavior |
| --- | --- |
| Unexpected flow during quiet hours | Forward flow at or above the configured threshold, sustained over fresh samples during the selected local hours. An open incident can recover when low flow is confirmed within a quiet window. |
| High flow | Forward flow at or above the configured threshold, sustained over fresh samples. |
| Reverse flow | Negative flow whose magnitude reaches the configured threshold and lasts for the alert hold. |
| Stale or unverified sample, untrusted clock | Repeated evidence opens a data quality incident. Flow rules wait for a fresh, trusted sample. A packet marked as live fallback cannot establish sample freshness. Use the existing node time synchronization command when needed. |
| Unavailable meter or soil sensor | Two consecutive, timely reports indicate a missing valid measurement for the selected meter or an enabled HNDA/Sondas sensor. |
| Low battery | Two consecutive, timely readings below the configured threshold. A zero reading is displayed as unavailable. Recovery uses a 0.1 V margin above the threshold. |
| Watchdog or power resets | A rising count opens or updates an incident. The first count establishes the baseline. A cleared counter establishes a new baseline. |
| Node reporting overdue or offline | Two report intervals without a new report marks the line overdue. Three intervals opens an offline incident. MQTT disconnects and unavailable assigned gateways pause node offline detection. A reconnect starts a new observation window. |

Flow alerts require at least two distinct measurements and the configured alert
hold. Recovery requires confirmed flow at or below 85% of the threshold for
the recovery hold. Duplicate measurements, missing samples and invalid data
cannot confirm a flow incident or close an active one. Evidence shows the
first and most recent flow readings, observed duration and the available
meter-totalizer change in litres. The volume is marked partial if a gap or
counter decrease prevents a complete calculation.

An acknowledgement records the operator and time. An incident remains open
until the rule detects recovery or its monitoring settings change. CSV export
covers the selected company and region. Export timestamps use UTC epoch seconds.

## Bench acceptance

Use a test node with the existing RS485 simulator. Confirm its clock and confirm
that its Status reports carry fresh, valid samples.

| Step | Input and expected result |
| --- | --- |
| Confirm a high-flow alert | Set the node Status interval to 10 s for this bench run. Configure a 10 m³/h high-flow limit, 20 s alert hold and 10 s recovery hold. Set simulator flow to 15 m³/h. The first three distinct reports spanning 20 s create one incident. |
| Confirm recovery | Set flow to 8 m³/h and leave it there for two fresh reports spanning 10 s. The incident changes to **Resolved**. |
| Check missing data | While high flow is open, disconnect the selected meter. The existing high-flow incident stays open and the meter condition appears after successive invalid reports. Reconnect the meter and restore valid, low flow to confirm recovery. |
| Check communications | With an online gateway, stop reports from its test node for three intervals. Expect **Offline**. Turn off the gateway and allow its heartbeat to age out. New node offline alarms are suppressed while the gateway is unavailable. Resume normal traffic and check that the node returns **Online**. |
| Verify the audit | Acknowledge the incident, reload the dashboard and export the region CSV. Confirm the acknowledgement survives a server restart. Switch to a different region and verify that both the table and export follow the selection. |

Run the automated checks from the project root with
`powershell -NoProfile -ExecutionPolicy Bypass -File Validate-Release.ps1 -UseFactoryConfigurationFixture`.
