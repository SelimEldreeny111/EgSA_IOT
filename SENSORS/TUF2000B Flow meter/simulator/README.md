# TUF-2000B / TUF-2000M Modbus Simulator

This Windows simulator emulates the Modbus RTU data used by the WIOT STM32
node. It was implemented from the register table in `../TUF-2000M.pdf` and
checked against the requests and decoding in
`../../../Node/IoT_Node_Encrypted/src/devices/TufSensor.cpp`.

The GUI lets a tester change the meter values, set any documented TUF error
bit, advance the calendar totals automatically, simulate a silent meter, and
change the Modbus slave address without restarting the program.

## Supported register blocks

The TUF manual uses one-based register numbers. The Modbus frame and STM32 code
use the zero-based address shown below.

| Data returned to the node | Manual register | Modbus address | Format |
|---|---:|---:|---|
| Flow rate | 0001-0002 | `0x0000` | REAL4, m3/h |
| Energy flow rate | 0003-0004 | `0x0002` | REAL4, GJ/h |
| Velocity | 0005-0006 | `0x0004` | REAL4, m/s |
| Error code | 0072 | `0x0047` | 16-bit bitmap |
| Flow today | 0125-0126 | `0x007C` | REAL4, m3 |
| Flow this month | 0127-0128 | `0x007E` | REAL4, m3 |
| Flow this year, integer | 0145-0146 | `0x0090` | signed LONG |
| Flow this year, fraction | 0147-0148 | `0x0092` | REAL4 |

The simulator intentionally sends the low 16-bit word before the high 16-bit
word. This is the order reconstructed by `responseU32LowWordFirst()` in the
current STM32 driver. Bytes within each 16-bit Modbus register remain in normal
big-endian order.

Only Modbus function `0x03` and the register subset above are emulated. This is
the exact subset needed to test the current node. Unsupported functions and
registers return standard Modbus exceptions.

## Run the simulator

### Ready-built EXE

Run:

```text
dist\TUF2000B_Simulator.exe
```

No Python installation is needed for the EXE.

### Python source

From this directory:

```powershell
python -m pip install -r requirements.txt
python tuf2000b_simulator.py
```

### Rebuild the EXE

```powershell
powershell -ExecutionPolicy Bypass -File .\build_exe.ps1
```

The build script installs the listed dependencies, runs all protocol tests,
and creates `dist\TUF2000B_Simulator.exe`.

## Configure the STM32 test image

In `Node/IoT_Node_Encrypted/src/config/AppConfig.h`, use the TUF/HNDA project
and enable TUF. Disable HNDA when the purpose of the image is an isolated TUF
test:

```cpp
#define APP_SENSOR_PROJECT APP_SENSOR_PROJECT_TUF_HNDA
#define APP_ENABLE_TUF_SENSOR true
#define APP_ENABLE_HNDA_SENSOR false
#define APP_TUF_SENSOR_MODBUS_ADDRESS 2
```

The current node baud rate is `9600`. The simulator starts with these matching
defaults:

- Port: selected PC COM port
- Baud: 9600
- Data format: 8 data bits, no parity, 1 stop bit
- Slave ID: 2

The address is not fixed. Enter any value from 1 to 247 and select **Apply**.
If the simulator is already running, the new address becomes active
immediately. For a successful node test, set
`APP_TUF_SENSOR_MODBUS_ADDRESS` to the same value and rebuild the node. Using a
different value deliberately tests the node's no-response behavior.

## RS485 connection

Use a USB-to-RS485 adapter that supports automatic transmit direction.

1. Disconnect power while making the wiring.
2. Connect node RS485 `+` / `A` / `D+` to adapter `A` / `D+`.
3. Connect node RS485 `-` / `B` / `D-` to adapter `B` / `D-`.
4. Connect signal ground when both interfaces expose it, especially for a
   bench setup without galvanic isolation.
5. Keep the cable short for the first test. Use a 120-ohm termination only at
   each physical end of a longer bus; do not add several parallel terminators.
6. Power the node, choose the adapter COM port, and select **Start**.

Do not connect a TTL UART directly to the RS485 A/B pair. If there is no
traffic and the wiring labels are ambiguous, power down and swap A and B.

## Step-by-step functional test

### 1. Communication and decoding

1. Set flow rate to `12.5`, velocity to `1.25`, today to `25.5`, month to
   `340.75`, and year to `2500.875`.
2. Clear all error bits and select **Apply values**.
3. Start the simulator, then reset the STM32 node.
4. Confirm the GUI shows the following requests. CRC bytes are included:

```text
02 03 00 47 00 01 34 2C
02 03 00 00 00 06 C5 FB
02 03 00 7C 00 04 85 E2
02 03 00 90 00 04 44 17
```

5. Confirm the node prints flow `12.5 m3/h`, velocity `1.25 m/s`, today
   `25.5 m3`, month `340.75 m3`, year `2500.875 m3`, and error code `0x0000`.

The initialization error-code request can appear before the first live-data
request. The normal driver also inserts at least 100 ms between transactions.

### 2. Change values while running

1. Enter new values and select **Apply values**.
2. Leave the serial connection running.
3. Confirm the next node polling cycle reports the new values.

### 3. Change the Modbus address

1. Enter a different slave ID and select the address **Apply** button.
2. The simulator immediately ignores requests to the old address.
3. Restore address `2`, or rebuild the STM32 with the same new address.
4. Confirm communication resumes.

This test proves that replies are coming from the selected slave rather than
from stale serial data.

### 4. Timeout and retry

1. Enable **Simulate timeout**.
2. Confirm requests appear as RX frames but no TX response is sent.
3. Confirm the STM32 retries a transient read once and reports the failed TUF
   read without remaining permanently blocked.
4. Clear **Simulate timeout** and confirm the next poll recovers.

### 5. Error-code bitmap

1. Select **Bit 3: Pipe empty** and **Apply values**.
2. Confirm the STM32 reads `0x0008`.
3. Select Bit 0 as well and apply again; confirm it reads `0x0009`.
4. Select **Clear all errors**, apply, and confirm `0x0000`.

The GUI provides all 16 documented bits, including high bit 15, so byte-order
problems can be detected by testing `0x8000`.

### 6. Calendar-total behavior

1. Enable automatic totals and set time speed to `3600x`.
2. Set flow rate to `1.0 m3/h` and apply the values.
3. Every real second represents one simulated hour, so all three totals should
   increase by about `1 m3` per second.
4. Test the independent Today, Month, and Year reset buttons.
5. Test a negative flow rate and confirm the totals decrease.

Automatic total integration is a PC-simulator aid. The STM32 reads the actual
TUF day/month registers directly and reads the yearly LONG plus REAL4 fraction;
it does not perform this integration for the TUF sensor.

## Automated verification

Run:

```powershell
python -m unittest discover -s tests -v
```

The tests verify the exact STM32 request CRCs, exact default response, word
order, positive and negative yearly totals, all error bits, configurable slave
addresses, exception responses, invalid CRC behavior, total advancement, and
independent period resets.

## Important limitations

- This is a test slave, not a complete firmware clone of every TUF register.
- Function `0x06`, meter setup menus, historical day/month queues, analog
  outputs, and energy configuration are not emulated.
- The simulator address change is temporary and resets to `2` when the program
  is reopened.
- REAL4 values have Float32 precision, matching the meter and node protocol.
