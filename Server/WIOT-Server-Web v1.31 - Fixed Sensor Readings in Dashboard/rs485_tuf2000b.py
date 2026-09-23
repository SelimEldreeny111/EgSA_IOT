"""
rs485_tuf2000b.py
-----------------
Annotated RS-485 / Modbus helper for the IoT Node Simulator.

Purpose of this file:
- Own the complete RS-485 sensor side of the project.
- Open/close the Modbus RTU connection.
- Read the flow value from the TUF-2000B register map.
- Capture the REAL serial-layer TX/RX bytes seen by pyserial.

Why this file matters:
- It is the bridge between the high-level Modbus call in pymodbus and the
  low-level raw bytes that physically go to/from the COM port through pyserial.
- If you want to change slave id, COM settings, register address, raw logging,
  or float decoding, this is the first file to inspect.

Data flow in this file:
    read_once()
        -> _read_2regs()
            -> pymodbus.read_holding_registers(...)
            -> pyserial write/read through _SerialSpy
        -> _regs_to_f32()
        -> Tuf2000bReading
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Dict
import time
import struct


# Custom project-level error used when pymodbus / pyserial are not installed.
class Rs485DependencyError(RuntimeError):
    pass


@dataclass
class Tuf2000bConfig:
    """
    Static configuration for one RS-485 / Modbus RTU connection.

    This class is intentionally simple: it only stores settings and does not
    open the port by itself.
    """

    port: str = "COM3"
    baudrate: int = 9600
    parity: str = "N"
    stopbits: int = 1
    bytesize: int = 8
    timeout_s: float = 1.0
    unit_id: int = 1
    address_base: int = 0
    reg_flow: int = 0


@dataclass
class Tuf2000bReading:
    """
    One decoded sensor reading bundle plus the matching raw serial request/response.

    measurements:
    - instant_flow: instantaneous flow rate (m3/h)
    - velocity: fluid velocity (m/s)
    - flow_today: total flow for today (m3)
    - flow_month: total flow for this month (m3)
    - flow_year: total flow for this year (m3)

    request_hex / response_hex keep one entry per Modbus transaction because this
    task reads three RTU request frames.
    """

    timestamp: float
    instant_flow: Optional[float] = None
    velocity: Optional[float] = None
    flow_today: Optional[float] = None
    flow_month: Optional[float] = None
    flow_year: Optional[float] = None
    request_hex: Dict[str, str] | None = None
    response_hex: Dict[str, str] | None = None


# Import pymodbus lazily so the GUI file can still load even if the dependency
# is missing on the current PC.
def _import_client():
    try:
        from pymodbus.client import ModbusSerialClient  # type: ignore
        return ModbusSerialClient
    except Exception as e:
        raise Rs485DependencyError(
            "Missing RS-485 dependencies. Install with: pip install pymodbus pyserial"
        ) from e


# Format raw bytes for human-readable logging in the GUI.
def _hex(data: bytes) -> str:
    return " ".join(f"{b:02X}" for b in data)


# Convert two 16-bit Modbus registers into one big-endian Float32.
#
# Important detail:
# - This project currently assumes NO word swap.
# - Register 0 is the high word, register 1 is the low word.
# - If the real device uses a different word order, this is one of the first
#   places that would need to change.
def _regs_to_f32(r0: int, r1: int) -> float:
    raw = struct.pack(">HH", (r0 & 0xFFFF), (r1 & 0xFFFF))
    return struct.unpack(">f", raw)[0]


def _combine_year_parts(integer_part: float, decimal_part: float) -> float:
    """
    Combine the special Flow-Year format used by the LabVIEW simulator.

    The 0145-0148 response does NOT carry one plain Float32 value.
    Instead it carries:
    - registers 0145-0146 -> integer part   (example: 1200)
    - registers 0147-0148 -> decimal field  (example: 900.0)

    The GUI labels in the simulator show these as separate integer / decimal
    inputs, so the intended human-readable value is 1200.900 rather than
    1200 + 900 = 2100 or a raw binary reinterpretation.

    We therefore scale the decimal field as thousandths.
    """
    integer_part = float(integer_part)
    decimal_part = abs(float(decimal_part))

    # Normal simulator use sends values such as 900 -> 0.900.
    # If a future sender already provides a fractional decimal (0.9),
    # keep it directly instead of scaling again.
    if decimal_part >= 1.0:
        decimal_part = decimal_part / 1000.0

    return integer_part + decimal_part


class _SerialSpy:
    """
    Thin wrapper around the pyserial object created internally by pymodbus.

    Why this class exists:
    - pymodbus builds the Modbus RTU frame and performs the transaction.
    - pyserial is the layer that actually writes/reads bytes on the COM port.
    - To show REAL TX/RX bytes in the GUI, we intercept pyserial.write() and
      pyserial.read() here.
    """

    def __init__(self, ser):
        self._ser = ser
        self.last_tx = b""
        self.last_rx = b""

    # Store the exact bytes being transmitted before forwarding them to the real port.
    def write(self, data):
        self.last_tx = bytes(data)
        return self._ser.write(data)

    # Append all received chunks so the full raw Modbus response can be logged.
    def read(self, size=1):
        data = self._ser.read(size)
        if data:
            self.last_rx += data
        return data

    # Clear previous transaction bytes before starting the next Modbus request.
    def reset_buffers(self):
        self.last_tx = b""
        self.last_rx = b""

    # Delegate any attribute not explicitly overridden to the original serial object.
    # This keeps pymodbus working as if it was using the real pyserial instance.
    def __getattr__(self, name):
        return getattr(self._ser, name)


class Tuf2000bRtuClient:
    """
    Project-level RS-485 client used by the GUI.

    Main responsibilities:
    - connect / close the Modbus RTU transport
    - perform one flow read transaction
    - retain the latest raw TX/RX bytes for the GUI log panels
    """

    def __init__(self, cfg: Tuf2000bConfig):
        # Configuration object passed from the GUI.
        self.cfg = cfg

        # Underlying pymodbus client object, created at connect time.
        self._client = None
        self._connected = False

        # Last error / last decoded reading are useful for debugging and display.
        self.last_error: Optional[str] = None
        self.last_reading: Optional[Tuf2000bReading] = None

        # These fields expose the exact last serial transaction in both bytes and hex text.
        self.last_request_bytes: bytes = b""
        self.last_response_bytes: bytes = b""
        self.last_request_hex: str = ""
        self.last_response_hex: str = ""

        # Spy object attached after a successful normal connect so we can capture
        # real serial TX/RX bytes without interfering with COM-port opening.
        self._spy = None

    @property
    def is_connected(self) -> bool:
        """Small convenience property used by the GUI to enable/disable buttons."""
        return self._connected

    def connect(self) -> None:
        """
        Open the Modbus RTU connection.

        Stable approach:
        - Let pymodbus open the COM port normally first.
        - After connect succeeds, wrap the already-created serial object with _SerialSpy.
        - This keeps connect stable while preserving real TX/RX raw logging.
        """
        ModbusSerialClient = _import_client()

        # This is where the high-level Modbus RTU client is created.
        self._client = ModbusSerialClient(
            method="rtu",
            port=self.cfg.port,
            baudrate=int(self.cfg.baudrate),
            parity=str(self.cfg.parity).upper(),
            stopbits=int(self.cfg.stopbits),
            bytesize=int(self.cfg.bytesize),
            timeout=float(self.cfg.timeout_s),
        )

        # Actual port open / transport setup happens here.
        if not self._client.connect():
            self._connected = False
            raise ConnectionError(f"Failed to connect to {self.cfg.port}")

        self._connected = True
        self.last_error = None

        # Attach spy AFTER a successful normal connect.
        self._attach_serial_spy()

    def _attach_serial_spy(self) -> None:
        """
        Wrap the real pyserial instance already opened by pymodbus.

        We avoid monkey-patching pyserial constructors because that can break
        COM-port opening on some systems / versions.
        """
        if self._client is None:
            return

        candidate_attrs = [
            "socket",
            "serial",
            "_serial",
            "transport",
        ]

        ser = None

        for attr in candidate_attrs:
            obj = getattr(self._client, attr, None)
            if obj is not None and hasattr(obj, "write") and hasattr(obj, "read"):
                ser = obj
                break

        # Some pymodbus versions keep the serial object one level deeper.
        if ser is None:
            transport = getattr(self._client, "transport", None)
            if transport is not None:
                nested_attrs = ["serial", "_serial", "socket"]
                for attr in nested_attrs:
                    obj = getattr(transport, attr, None)
                    if obj is not None and hasattr(obj, "write") and hasattr(obj, "read"):
                        ser = obj
                        break

        if ser is None:
            # No crash here; connection is already valid.
            # Raw logs simply won't be available on this version/layout.
            self._spy = None
            return

        # Prevent double-wrapping.
        if isinstance(ser, _SerialSpy):
            self._spy = ser
            return

        spy = _SerialSpy(ser)
        self._spy = spy

        replaced = False

        for attr in candidate_attrs:
            if getattr(self._client, attr, None) is ser:
                setattr(self._client, attr, spy)
                replaced = True
                break

        if not replaced:
            transport = getattr(self._client, "transport", None)
            if transport is not None:
                for attr in ["serial", "_serial", "socket"]:
                    if getattr(transport, attr, None) is ser:
                        setattr(transport, attr, spy)
                        replaced = True
                        break

        if not replaced:
            self._spy = None

    def close(self) -> None:
        """Close the underlying Modbus client and reset connection-only runtime state."""
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
        self._client = None
        self._connected = False
        self._spy = None

    def _read_regs(self, reg: int, count: int):
        """
        Low-level Modbus helper.

        What it returns:
        - raw register integers exactly as returned by the Modbus device

        What it does internally:
        1) reset previous spy buffers
        2) send a Modbus RTU read_holding_registers request for the requested count
        3) validate the response
        4) copy the exact serial TX/RX bytes into last_request_* / last_response_*

        This is a low-level helper. It does NOT convert the data to engineering
        units yet; it only reads the registers.
        """
        if not self._client or not self._connected:
            raise ConnectionError("RS-485 client not connected")

        # In this project, address_base is intentionally fixed and we read from
        # the explicit register passed in. The comment keeps this design choice visible.
        addr = reg  # fixed address=0 mode in this project

        # Start each transaction with empty spy buffers so the logged bytes belong
        # only to the current request/response pair.
        if self._spy is not None:
            self._spy.reset_buffers()

        # Sensitive integration point:
        # - pymodbus builds the Modbus RTU frame
        # - pyserial actually writes/reads the raw bytes
        # - slave=... is the modern pymodbus parameter used in this project
        rr = self._client.read_holding_registers(address=addr, count=int(count), slave=int(self.cfg.unit_id))

        if rr is None:
            raise TimeoutError("No response from Modbus device")
        if hasattr(rr, "isError") and rr.isError():
            raise IOError(f"Modbus error reading addr={addr}: {rr}")

        regs = getattr(rr, "registers", None)
        if not regs or len(regs) < int(count):
            raise ValueError(f"Invalid register response: {regs}")

        # Copy the exact serial-layer bytes captured by _SerialSpy.
        self.last_request_bytes = bytes(self._spy.last_tx) if self._spy is not None else b""
        self.last_response_bytes = bytes(self._spy.last_rx) if self._spy is not None else b""
        self.last_request_hex = _hex(self.last_request_bytes)
        self.last_response_hex = _hex(self.last_response_bytes)

        return [int(v) for v in regs[: int(count)]]

    def read_once(self) -> Tuf2000bReading:
        """
        High-level read helper used by the GUI.

        This task groups the requested values into three Modbus RTU request frames:
        1) manual 0001-0006  -> Modbus address 0000-0005 -> Instant Flow + Velocity
        2) manual 0125-0128  -> Modbus address 0124-0127 -> Flow Today + Flow Month
        3) manual 0145-0148  -> Modbus address 0144-0147 -> Flow Year (integer part + decimal fraction)
        """
        ts = time.time()
        try:
            req_hex: Dict[str, str] = {}
            resp_hex: Dict[str, str] = {}

            # Manual register 0001 starts at Modbus address 0000 (zero-based).
            regs_1_6 = self._read_regs(0, 6)
            req_hex["frame_0001_0006"] = self.last_request_hex
            resp_hex["frame_0001_0006"] = self.last_response_hex
            instant_flow = _regs_to_f32(regs_1_6[0], regs_1_6[1])
            velocity = _regs_to_f32(regs_1_6[4], regs_1_6[5])

            # Manual register 0125 starts at Modbus address 0124 (zero-based).
            regs_125_128 = self._read_regs(124, 4)
            req_hex["frame_0125_0128"] = self.last_request_hex
            resp_hex["frame_0125_0128"] = self.last_response_hex
            flow_today = _regs_to_f32(regs_125_128[0], regs_125_128[1])
            flow_month = _regs_to_f32(regs_125_128[2], regs_125_128[3])

            # Manual register 0145 starts at Modbus address 0144 (zero-based).
            regs_145_148 = self._read_regs(144, 4)
            req_hex["frame_0145_0148"] = self.last_request_hex
            resp_hex["frame_0145_0148"] = self.last_response_hex
            flow_year_integer = _regs_to_u32_low_byte_first(regs_145_148[0], regs_145_148[1])
            flow_year_fraction = _regs_to_f32(regs_145_148[2], regs_145_148[3])
            flow_year = _combine_year_parts(flow_year_integer, flow_year_fraction)

            r = Tuf2000bReading(
                timestamp=ts,
                instant_flow=instant_flow,
                velocity=velocity,
                flow_today=flow_today,
                flow_month=flow_month,
                flow_year=flow_year,
                request_hex=req_hex,
                response_hex=resp_hex,
            )
            self.last_reading = r
            self.last_error = None
            return r
        except Exception as e:
            self.last_error = str(e)
            raise

    def read_measurements(self) -> dict:
        """
        GUI-friendly wrapper.

        Returns all requested values plus one request/response hex string per RTU frame.
        """
        r = self.read_once()
        return {
            "instant_flow": r.instant_flow,
            "velocity": r.velocity,
            "flow_today": r.flow_today,
            "flow_month": r.flow_month,
            "flow_year": r.flow_year,
            "request_hex": r.request_hex or {},
            "response_hex": r.response_hex or {},
        }


# Convert two 16-bit registers to an unsigned LONG using the TUF low-byte-first note.
def _regs_to_u32_low_byte_first(r0: int, r1: int) -> int:
    """
    Convert two 16-bit Modbus registers into one unsigned 32-bit integer.

    Despite the legacy function name, the LabVIEW simulator sends the integer
    part of flow-per-year in normal Modbus register order:
      reg0 = high word, reg1 = low word

    Example response bytes:
      00 00 04 B0 -> 1200

    The previous implementation packed as little-endian words and produced
    0x04B00000 (= 78643200), which is why flow-per-year was exploding in the
    StatusMessage.
    """
    raw = struct.pack(">HH", (r0 & 0xFFFF), (r1 & 0xFFFF))
    return struct.unpack(">I", raw)[0]
