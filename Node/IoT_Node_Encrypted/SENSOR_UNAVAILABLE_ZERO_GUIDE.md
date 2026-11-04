# Zero readings on failed sensor communication

After a completed sensor polling attempt, a missing/invalid reply replaces
that sensor's outgoing readings with zero and sets the corresponding validity
flags to false. No old numeric readings are carried into a failed poll.

This applies to TUF, Supmea, HNDA and Sondas; to both primary and secondary
flow-meter blocks; and to Status and Telemetry over MQTT or LoRa. Unaffected
sensors continue reporting their own valid readings. For partial flow-meter
reads, each validity group is independent: live flow/velocity, period totals,
and cumulative totals. A failed group sends zeros while successful groups
can still report their newly read values.

Zero with validity **false** means unavailable. Zero with validity **true**
means a real measured zero. Protobuf field numbers do not change. Proto3 may
omit zero-valued fields from the wire; the server decodes them as zero.

Supmea's RTC accumulator and saved baselines are not reset or advanced by a
missing counter reply. Recovery continues from the last real counter sample.
The displayed/transmitted failed sample is zero, but historical daily/monthly/
yearly consumption records are not erased or replaced with invented readings.

The server's Live Status cards show zeros for a received invalid sensor sample
and retain the error/quality indication. Invalid placeholders are not plotted
as real zero-flow chart points. No received message/offline remains a separate
state. Existing command acknowledgments still identify cached sensor data.

Sampling and transmission remain separate schedules: a report between polling
attempts uses the latest completed poll. Values are not cleared just because
another report was sent. Changing this would incorrectly mark good slow-polled
sensors unavailable on every faster transmission.

If a Modbus timeout makes the sampling deadline overdue, the finished cycle
can leave a sample queued for flash. An overdue Status now gets its turn after
that write clears, before the node starts another poll. If flash cannot provide
a retained record, Status uses the live fallback.

## Bench test

1. Flash the updated node and restart the updated server. Hard-refresh the
   browser so it loads the new JavaScript. Keep your current sensor addresses.
2. Run all four simulator devices with distinct nonzero values. Confirm both
   flow-meter blocks, soil values and EC reach the server correctly.
3. Disable replies for TUF only (or disconnect it). Wait for the next completed
   polling attempt and Status. TUF readings must be zero and validity false;
   Supmea/HNDA/Sondas must remain valid. Repeat for every sensor individually.
4. Keep the sensor enables set and disable all simulator replies. Use a
   10-second sampling period and a ready SPI log to exercise the overrun path
   with Supmea and Sondas. Wait for a completed poll and `status_tx` or the MQTT
   send result, then confirm Status arrives with zero readings and false
   validity. The configured sensor mask still identifies the enabled devices.
   To test a node with no polls configured, disable all four enables and verify
   a zero sensor mask, zero validity flags and continued Status delivery.
5. Re-enable each device. Fresh readings must return without rebooting. For
   Supmea, increase its cumulative counter during the outage and confirm the
   accumulated consumption resumes without an artificial reset-to-zero.
6. Inject a CRC error or Modbus exception and repeat. Test a partial TUF period
   read failure and a Supmea totals-only failure; only failed validity groups
   must be zero. Finally test a genuine measured zero: validity must stay true.

## Automated checks

From the node sketch directory:

```powershell
./tests/sensor_availability/run_tests.ps1
./tests/rtc_supmea/run_tests.ps1
./tests/remote_wake/run_tests.ps1
```

The new host suite exercises the real flow manager, application state and
protobuf mapper in dual-flow, TUF-only, Supmea-only and no-flow configurations.
It tests good readings, total failures, partial failures, recovery, cached
invalid values and protection of the Supmea accumulator baseline.

From the server directory:

```powershell
python -m unittest discover -s tests -v
node tests/test_sensor_display.js
node tests/test_wake_control.js
node --check static/js/app.js
```
