# WIOT Multi-Sensor RS485 Simulator Acceptance Test Plan

## 1. Purpose

This plan verifies that the PC simulator behaves as a deterministic multi-slave
Modbus RTU bus and that the STM32 WIOT node correctly reads each supported
sensor profile. Record the software commit, simulator EXE hash, node firmware
build, COM port, adapter model, and date with the test results.

## 2. Bench setup

- Windows PC running `WIOT_MultiSensor_RS485_Simulator.exe`
- Automatic-direction USB-to-RS485 adapter
- STM32 WIOT node with the intended sensor project selected
- Common signal reference where required by the adapter/node hardware
- Short twisted-pair A/B wiring for initial tests
- Serial debug console for the STM32 node

Use `9600 8N1` unless the node build deliberately specifies another common bus
format. Only one Modbus master is permitted during this procedure.

## 3. Pre-test software verification

From the simulator source directory:

```powershell
python -m py_compile multi_sensor_core.py multi_sensor_bus.py multi_sensor_simulator.py
python -m unittest discover -s tests -v
python multi_sensor_simulator.py --validate-config default_config.json
```

Pass criteria:

- All source files compile.
- Every automated test reports `ok`.
- Configuration validation reports `"valid": true`, five devices, and the
  expected per-type fleet counts.

## 4. Bus smoke test

1. Load `default_config.json`.
2. Select the adapter COM port and start the bus.
3. Start the STM32 node.
4. Confirm RX frames appear in the traffic log.
5. Confirm each recognized request produces a TX frame with the same address.
6. Confirm CRC/noise, exception, and dropped counters remain zero.

Pass criteria: valid polling continues for five minutes without simulator
failure, unintended exception, or response from the wrong slave address.

## 5. Individual profile tests

### 5.1 HNDA/Honda

1. Keep address 1 enabled and temporarily disable the other devices.
2. Set temperature to `15.1 deg C` and moisture to `35.6%`, both fixed.
3. Confirm the node reads `15.1` and `35.6`.
4. Re-enable address 2 with temperature `28.4` and moisture `71.2`.
5. Poll addresses 1 and 2 and confirm their values are not exchanged.
6. If address-write testing is required, send function 06 to register `0x0030`
   with an unused address and confirm the old address becomes silent and the
   new address responds.

Pass criteria: scaling, signed temperature, independent addresses, and address
write behavior are correct.

### 5.2 TUF

1. Enable TUF address 10 and use fixed values: flow `12.5 m3/h`, energy flow
   `3.5 GJ/h`, velocity `1.25 m/s`, today `25.5 m3`, month `340.75 m3`, year
   `2500.875 m3`, error `0`.
2. Confirm the node reads all values within Float32 display tolerance.
3. Set error to `0x8009` and confirm the high and low error bits are preserved.
4. Enable automatic totals, set flow to `1.0 m3/h`, and set time to `3600x`.
5. Confirm day, month, and year totals rise by approximately 1 m3 per real
   second.
6. Reset the totalizers and confirm all return to zero.

Pass criteria: low-word-first Float32/Int32 decoding, errors, and totalization
are correct.

### 5.3 Supmea

1. Enable Supmea address 20 and use fixed values: forward `1250.75 m3`, reverse
   `25.25 m3`, net `1225.5 m3`, flow `35.0`, velocity `1.25 m/s`, ratio
   `42.5%`, EPD `7%`, unit code `3`, EPD alarm `1`, excitation alarm `0`.
2. Confirm the node reads all ten live registers and all cumulative totals.
3. Enable automatic totals, retain unit code 3 (m3/h), set flow to `1.0`, and
   set time to `3600x`.
4. Confirm forward and net rise by approximately 1 m3 per real second.
5. Set flow to `-1.0`; confirm reverse rises while net falls.
6. Set a mass-flow unit code (6-11) and confirm volumetric totals no longer
   integrate.

Pass criteria: high-word-first Float32 decoding, unit/alarm fields, and
directional totals are correct.

### 5.4 Sondas WIOT compatibility profile

1. Enable Sondas address 30 and set fixed values: temperature `-4.2 deg C`,
   moisture `63.7%`, EC `1350`.
2. Confirm the node reads those three values with the expected x10/x10/x1
   scaling.
3. Confirm negative temperature is decoded as signed Int16.

Pass criteria: the current `SondasSensor.cpp` compatibility map is reproduced.
This test does not certify compatibility with a different commercial Sondas
model until its actual protocol manual is checked.

## 6. Multiple devices of one type

1. Select **+ Fleet**, choose HNDA, quantity 10, and explicit addresses
   `1-10`.
2. Choose random walk and create the fleet.
3. Give each sensor a distinct random seed or fixed value.
4. Poll every address and record one complete scan.
5. Repeat with TUF addresses 20-29, Supmea 40-49, and Sondas 60-69.

Pass criteria: every request is answered only by its selected address, values
remain associated with the correct virtual device, and there are no duplicate
address errors.

## 7. Dynamic value tests

For one device, test each mode independently: fixed, random range, random walk,
sine, ramp, and step. Use narrow ranges and a one-second update interval so the
expected behavior is visible. Repeat a random test after reloading the same
configuration.

Pass criteria: generated values stay within limits, integer fields remain
integer, and the same seed reproduces the same random sequence.

## 8. Error and recovery tests

Perform each fault on only one address while a second address remains healthy:

1. Mute the test device and verify node timeout/retry without blocking reads of
   the healthy device.
2. Set drop to 50% and verify intermittent recovery.
3. Set CRC corruption to 100% and verify the node rejects every response.
4. Force exceptions 01, 02, 03, and 04 and verify they are reported as errors.
5. Add response delay below the node timeout, then above it, and identify the
   threshold.
6. Clear all faults and verify normal polling resumes without restarting the
   simulator.

Pass criteria: faults are isolated to the configured address, the watchdog does
not reset during expected bounded retries, and communication recovers after the
fault is removed.

## 9. Scale and endurance test

1. Create 25 devices of each type using four non-overlapping address ranges
   (100 total virtual slaves).
2. Use mixed signal modes and deterministic seeds.
3. Run the intended polling pattern for at least eight hours.
4. Save traffic only when needed; the GUI keeps a bounded rolling log.
5. Record requests, replies, drops, exceptions, CPU use, and memory use at the
   start and end.

Pass criteria: the application remains responsive, memory does not grow
continuously, no address sends another device's data, and all unexplained
drops/exceptions remain zero.

## 10. Configuration integrity test

1. Save the 100-device fleet and close the application.
2. Reopen using the saved JSON file.
3. Confirm counts, addresses, names, values, modes, seeds, and faults match.
4. Manually create a duplicate address in a copy and confirm loading is
   rejected.
5. Change `schema_version` in a copy and confirm loading is rejected.

Pass criteria: valid configurations round-trip without loss and invalid files
fail before the bus starts.

## 11. Exit criteria

Release the simulator for project testing only when all applicable sections
pass, every deviation has an issue/reference, and the tested EXE plus JSON
configuration are archived with checksums.
