# WIOT Multi-Sensor RS485 Lab

This desktop simulator emulates a complete Modbus RTU sensor fleet on one
USB-to-RS485 adapter. It supports any mixture of the four WIOT sensor profiles,
including multiple devices of the same type at different slave addresses.

The starter configuration demonstrates this directly:

| Address | Virtual device | Initial behavior |
| ---: | --- | --- |
| 1 | HNDA/Honda soil sensor 1 | Temperature and moisture random walk |
| 2 | HNDA/Honda soil sensor 2 | Independent fixed values |
| 10 | TUF-2000B/M flow meter | Sine-wave live values and integrated totals |
| 20 | Supmea SUP-FMC240 flow meter | Random-walk values and integrated totals |
| 30 | Sondas soil sensor | Ramping temperature, moisture, and EC |

Every address is dispatched independently. A request for address 1 receives
only the address-1 HNDA data; a request for address 2 receives the independently
configured address-2 data. Up to 247 unique unicast addresses can be defined.

## Main capabilities

- Add one sensor, clone a sensor, or create a fleet in one operation.
- Create multiple sensors of the same type with sequential or explicit
  addresses, for example `1,2,7,10-15`.
- Enable, disable, mute, edit, clone, or remove each virtual sensor while
  retaining one shared serial bus.
- Configure every measurement separately as fixed, random range, random walk,
  sine wave, triangle/ramp, or two-level step.
- Configure per-device update interval, deterministic random seed, and
  simulated-time multiplier.
- Automatically integrate TUF period totals and Supmea cumulative totals from
  their flow-rate values.
- Inject realistic faults per address: silence/drop, response latency, invalid
  CRC, and Modbus exceptions 01-04.
- Inspect live values, request/response statistics, raw hexadecimal traffic,
  and a built-in register reference.
- Save and load complete fleet configurations as human-readable JSON.

## Supported Modbus profiles

The simulator implements the register subset read by the current WIOT STM32
node. Modbus bytes inside a 16-bit register are big-endian.

| Profile | Function/registers | Encoding |
| --- | --- | --- |
| HNDA/Honda | `03: 0x0000..0x0001` | Temperature signed x10; moisture unsigned x10 |
| HNDA/Honda address | `06: 0x0030` | New slave address 1..247; request is echoed |
| TUF live | `03: 0x0000..0x0005` | Three Float32 values, low 16-bit word first |
| TUF error | `03: 0x0047` | UInt16 error bitmap |
| TUF totals | `03: 0x007C..0x007F`, `0x0090..0x0093` | Day/month Float32; year Int32 + Float32 fraction, low word first |
| Supmea totals | `03: 0x005A..0x005F` | Forward/reverse/net Float32, high word first |
| Supmea live | `03: 0x0062..0x006B` | Flow/velocity/ratio Float32 plus EPD, unit, and alarms |
| Sondas | `03: 0x0000..0x0002` | Temperature x10, moisture x10, EC x1 |

The supplied Sondas document describes an SDI-12 product and does not provide a
Modbus register table. The Sondas entry above is therefore explicitly a **WIOT
compatibility profile** matching `SondasSensor.cpp`; it must be updated if the
final purchased Sondas model supplies a different Modbus manual.

Unsupported functions and register ranges return standard Modbus exceptions.
Broadcast address 0 is ignored because the implemented reads require replies.

## Windows application

The current development workspace includes a tested build at:

```text
dist\WIOT_MultiSensor_RS485_Simulator.exe
```

Generated `dist` files are intentionally excluded from Git. After a fresh
clone, run `build_exe.ps1` once to create the EXE. It needs no Python
installation on the target test PC. Keep `default_config.json` beside it to use
the editable starter fleet. The application also contains an internal fallback
copy, so it still starts if the external file is removed.

## Run from Python

From this directory:

```powershell
python -m pip install -r requirements.txt
python multi_sensor_simulator.py
```

To start with a particular fleet file:

```powershell
python multi_sensor_simulator.py --config .\my_fleet.json
```

To validate a file without opening the GUI:

```powershell
python multi_sensor_simulator.py --validate-config .\default_config.json
```

## Physical RS485 connection

Use a USB-to-RS485 adapter with automatic transmit-direction control.

1. Remove power before changing the wiring.
2. Connect the adapter `A`, `D+`, or `+` terminal to the node RS485 positive
   line.
3. Connect adapter `B`, `D-`, or `-` to the node RS485 negative line.
4. Connect signal ground when both interfaces expose it, particularly on a
   non-isolated bench setup. Do not connect protective earth as a substitute
   for signal ground.
5. Start with a short cable. On a long bus, use 120-ohm termination only at the
   two physical ends and provide biasing at one location.
6. If valid traffic never appears and the vendor's A/B naming is reversed,
   power down and swap A and B.

Do not connect a TTL UART directly to RS485 A/B. The node, adapter, and any real
sensor must share the same baud rate, parity, and stop-bit format.

## Create and run a fleet

1. Select the USB-RS485 COM port. The default is `9600`, `8N1`, with a 20 ms
   response delay.
2. Select **+ Fleet**.
3. Select HNDA, TUF, SUPMEA, or SONDAS.
4. Enter a quantity and a starting address, or enter explicit addresses such
   as `1,2,6,9-12`. Addresses already used by any type are rejected.
5. Select the initial signal behavior and create the fleet.
6. Double-click each row to set its exact values, ranges, update rate,
   totalizer behavior, or fault profile.
7. Select **Start bus**, then reset or start the STM32 node.
8. Use **Bus traffic** to confirm each RX request and TX response. The type and
   slave address are shown for every routed reply.
9. Save the verified setup with **Save config** so the same test is repeatable.

The serial configuration is common to the entire physical bus. Individual
devices can have different addresses and data behavior, but not different baud
rates on that same open port.

## Signal generation

| Mode | Behavior |
| --- | --- |
| Fixed | Holds the configured value until edited |
| Random range | Picks a new value anywhere between minimum and maximum |
| Random walk | Moves up or down by at most the configured step |
| Sine wave | Uses the value as center, step as amplitude, and period in seconds |
| Ramp / triangle | Moves by one step per update and reverses at the limits |
| Two-level step | Alternates between minimum and maximum at the period |

Each virtual device has its own random generator and seed. The same
configuration therefore produces repeatable random sequences. Integer alarm,
error, unit-code, and EC fields are rounded to integer register values.

### Flow totalizers

For TUF, automatic totalization adds:

```text
flow_m3_per_hour * simulated_elapsed_seconds / 3600
```

to the day, month, and year totals. For Supmea, volumetric unit codes 0-5 are
converted to m3/h before forward, reverse, and net totals are updated. Mass-flow
codes 6-11 cannot be integrated into cubic metres and leave these totals
unchanged. Use the time multiplier, for example `3600x`, to make one real
second represent one simulated hour.

## Fault and recovery tests

Edit one device to apply faults without affecting the others:

- **Extra delay** verifies node timeout margins.
- **Drop percentage** simulates intermittent or fully silent devices.
- **CRC error percentage** verifies corrupt-frame rejection.
- **Forced exception** verifies Modbus exception handling.
- **Mute** provides an immediate 100% no-response test while preserving the
  device configuration.
- **Disable** removes that address from the active bus.

Use a value of 100% for deterministic drop or CRC tests. Return all fault
settings to zero before normal acceptance testing.

## Important multi-node rule

Multiple simulated **slaves** can safely share one RS485 bus. Multiple WIOT
controller nodes acting as independent Modbus **masters** must not transmit on
the same two-wire bus unless their polling is explicitly coordinated; otherwise
their requests can collide. For two controller boards, either test one master
at a time, use separate adapters/buses, or implement a defined multi-master
arbitration scheme.

## Configuration file

`default_config.json` is the working example and includes two HNDA devices.
The GUI writes all device fields, signal profiles, fault settings, and shared
bus settings. The file includes a schema version and fleet counts, both checked
when loading. Manual edits with duplicate or out-of-range addresses are
rejected before the serial port is opened.

## Build and automated verification

Run:

```powershell
powershell -ExecutionPolicy Bypass -File .\build_exe.ps1
```

The build performs syntax checks, 20+ protocol/transport tests, configuration
validation, and PyInstaller packaging. Output is written to:

```text
dist\WIOT_MultiSensor_RS485_Simulator.exe
```

For the complete hardware and scale procedure, follow `TEST_PLAN.md`.
