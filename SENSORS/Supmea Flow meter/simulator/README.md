# Supmea SUP-FMC240 RS485 test simulator

25 October: the GUI includes independent Today/Month/Year consumption for RTC
comparison. These values are display-only and are not returned on Modbus.
Starting the bus creates a reference session; **Reset comparison only** zeros
that session without changing meter totals. Match the node's calendar and x1
time. See RESET_COUNTERS_AND_SUPMEA_REFERENCE_GUIDE.md in the Arduino node folder.

This tool behaves as a SUP-FMC240 Modbus RTU slave for commissioning the
production Arduino/STM32 Supmea + Sondas profile. It can hold fixed values or
advance its cumulative forward/reverse/net totals from the configured flow
rate.

## What the test covers

For a standalone Windows application, run `./build_exe.ps1` in this directory.
It checks the protocol tests and creates `dist/SUPMEA_FMC240_Simulator.exe`.
Pass `-Python 'C:/Python314/python.exe'` to select an interpreter, or
`-SkipDependencyInstall` when pyserial/PyInstaller are already installed.

The simulator implements function `0x03` for the FMC240 register block used by
the node:

| Modbus address | Registers | Value | Encoding |
|---:|---:|---|---|
| 90 | 2 | Forward total | IEEE-754 Float32, high word first |
| 92 | 2 | Reverse total | IEEE-754 Float32, high word first |
| 94 | 2 | Net total | IEEE-754 Float32, high word first |
| 98 | 2 | Flow rate | IEEE-754 Float32, high word first |
| 100 | 2 | Velocity | IEEE-754 Float32, high word first |
| 102 | 2 | Flow ratio | IEEE-754 Float32, high word first |
| 104-107 | 4 | EPD, unit, and alarm words | Unsigned 16-bit words |

The map and byte order come from Chapter 9 of the supplied FMC240 user manual.
The GUI also returns standard Modbus exceptions for unsupported functions,
invalid register ranges, and invalid register counts.

## Wiring for the simulator

Use one USB-to-RS485 adapter between the PC and the node's existing RS485
transceiver. Do not connect a PC USB-UART TTL adapter directly to the RS485 A/B
pair.

| Node side | USB-RS485 simulator side |
|---|---|
| Transceiver A / `+` | Adapter A / `+` |
| Transceiver B / `-` | Adapter B / `-` |
| RS485 reference GND | Adapter GND, when provided |

The STM32-side transceiver remains wired as in the project: USART1 TX `PA9` to
DI, USART1 RX `PA10` from RO, and `PA8` to the tied DE and active-low RE pins.
Use 120-ohm termination only at the two physical ends of a long bus. If the
link stays silent despite matching settings, power down first and check whether
the adapter vendor labels A/B in the opposite convention.

For a real FMC240, connect its `TXR+` terminal to A/+ and `TXR-` to B/-. Power
the meter from a supply permitted by its exact ordered variant; do not power it
from the STM32 board.

## Run the GUI

### Standalone Windows executable

Open `dist/Supmea_FMC240_Simulator.exe`. The packaged application includes
Python, Tkinter, the FMC240 protocol implementation, and pyserial, so no Python
installation is required on the test PC.

### Run from Python source

From this directory:

```powershell
python -m pip install -r requirements.txt
python supmea_fmc240_simulator.py
```

Select the USB-RS485 COM port, keep 9600, N, and slave ID 1, then press
**Start**. Change any measurement and press **Apply values**. The request and
response bytes appear in the traffic log.

The node defaults to the same test settings:

- Modbus RTU: 9600 baud, 8 data bits, no parity, 1 stop bit
- FMC240 slave address: 1
- Sampling interval: the normal node sampling interval (currently 10 seconds)

The real meter's communication menu must also be set to address 1 and 9600 8N1,
or APP_SUPMEA_SENSOR_MODBUS_ADDRESS must be changed to match it. The supplied
manual allows configurable address, baud, and parity; the full bus must use one
common baud/parity configuration.

Expected node output includes:

```text
=========== SUP-FMC240 READINGS =============
Forward total : 1250.750 m3
Flow rate     : 35.000 m3/h
Velocity      : 1.250 m/s
Overall result: VALID
```

## Consumption and fault controls

**Simulate timeout** receives requests but suppresses replies, which is useful
for checking retry, stale-data, and watchdog behavior.

**Advance cumulative totals from flow rate** makes the simulator behave like a
running meter. It converts volumetric unit codes 0 through 5 to m3/h and
updates forward total for positive flow or reverse total for negative flow.
The STM32 still calculates consumption from the cumulative forward counter; it
does not integrate the flow-rate field.

**Time acceleration** provides 1x, 60x, and 3600x operation. At 3600x, one real
second adds the volume that one hour of meter flow would produce. This speeds
volume and persistence tests only; it does not change the STM32 RTC. Test a
calendar rollover by synchronizing a test node close to the intended boundary.

**Reset meter totals** sets forward, reverse, and net to zero. On the next
sample the STM32 should report period quality Counter reset, establish a new
baseline, and avoid adding a false negative volume.

Mass-flow units cannot drive automatic volume totals because density is not
known; the GUI stops the automatic totalizer and logs a clear error. Fixed
mass-flow register testing remains possible with automatic totals disabled.

The standalone executable is rebuilt from the source in this folder. The
STM32CubeIDE and ESP32 projects are not changed by this simulator.

## Protocol self-test

```powershell
python -m unittest discover -s tests -v
```
