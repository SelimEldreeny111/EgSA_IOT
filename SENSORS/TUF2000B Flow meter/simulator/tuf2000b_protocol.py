"""Protocol core for a TUF-2000M/TUF-2000B Modbus RTU test slave.

The implemented registers are the subset used by the WIOT STM32 node.  The
addresses come from the supplied TUF-2000M register table.  That document
numbers registers from one, while Modbus requests and the firmware use
zero-based addresses.

This module has no GUI or serial-port dependency so frame handling and byte
order can be verified with automated tests.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import math
import struct
from typing import Mapping


# Zero-based Modbus holding-register addresses.  Add one to obtain the
# register number printed in the TUF-2000M manual.
REG_FLOW_RATE = 0x0000          # Manual 0001-0002, REAL4, m3/h
REG_ENERGY_FLOW_RATE = 0x0002   # Manual 0003-0004, REAL4, GJ/h
REG_VELOCITY = 0x0004           # Manual 0005-0006, REAL4, m/s
REG_ERROR_CODE = 0x0047         # Manual 0072, BIT16
REG_TODAY_TOTAL = 0x007C        # Manual 0125-0126, REAL4, m3
REG_MONTH_TOTAL = 0x007E        # Manual 0127-0128, REAL4, m3
REG_YEAR_INTEGER = 0x0090       # Manual 0145-0146, signed LONG
REG_YEAR_FRACTION = 0x0092      # Manual 0147-0148, REAL4


ERROR_BIT_NAMES = (
    "No received signal",
    "Low received signal",
    "Poor received signal",
    "Pipe empty",
    "Hardware failure",
    "Receiving-circuit gain adjusting",
    "Frequency-output overflow",
    "4-20 mA output overflow",
    "RAM checksum error",
    "Main/timer clock error",
    "Parameter checksum error",
    "ROM checksum error",
    "Temperature-circuit error",
    "Reserved",
    "Internal timer overflow",
    "Analog input over range",
)


@dataclass(frozen=True)
class Tuf2000bValues:
    """One coherent measurement set exposed by the simulated meter."""

    flow_rate_m3h: float = 12.5
    energy_flow_rate_gjh: float = 0.0
    velocity_mps: float = 1.25
    today_total_m3: float = 25.5
    month_total_m3: float = 340.75
    year_total_m3: float = 2500.875
    error_code: int = 0


@dataclass(frozen=True)
class ModbusDecision:
    """Result of examining one complete eight-byte Modbus request."""

    response: bytes | None
    description: str


def modbus_crc16(data: bytes) -> int:
    """Return the standard Modbus CRC-16 numeric value."""

    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF


def append_crc(frame_without_crc: bytes) -> bytes:
    """Append Modbus wire-order CRC bytes (low byte, then high byte)."""

    crc = modbus_crc16(frame_without_crc)
    return frame_without_crc + bytes((crc & 0xFF, (crc >> 8) & 0xFF))


def frame_has_valid_crc(frame: bytes) -> bool:
    if len(frame) < 3:
        return False
    received = frame[-2] | (frame[-1] << 8)
    return received == modbus_crc16(frame[:-2])


def bytes_to_hex(data: bytes) -> str:
    return " ".join(f"{byte:02X}" for byte in data)


def _float32_bits(value: float) -> int:
    if not math.isfinite(float(value)):
        raise ValueError("TUF floating-point values must be finite")
    try:
        packed = struct.pack(">f", float(value))
    except OverflowError as exc:
        raise ValueError("Value is outside the Float32 range") from exc
    return struct.unpack(">I", packed)[0]


def float_to_registers_low_word_first(value: float) -> tuple[int, int]:
    """Encode Float32 as the word order decoded by the STM32 TUF driver.

    Bytes inside a Modbus register remain big-endian.  The 16-bit register
    containing the low half of the IEEE-754 value is sent before the register
    containing the high half.
    """

    bits = _float32_bits(value)
    return bits & 0xFFFF, (bits >> 16) & 0xFFFF


def registers_low_word_first_to_float(low_word: int, high_word: int) -> float:
    bits = ((high_word & 0xFFFF) << 16) | (low_word & 0xFFFF)
    return struct.unpack(">f", struct.pack(">I", bits))[0]


def int32_to_registers_low_word_first(value: int) -> tuple[int, int]:
    parsed = int(value)
    if not -(2**31) <= parsed <= 2**31 - 1:
        raise ValueError("TUF LONG value is outside the signed Int32 range")
    unsigned = parsed & 0xFFFFFFFF
    return unsigned & 0xFFFF, (unsigned >> 16) & 0xFFFF


def registers_low_word_first_to_int32(low_word: int, high_word: int) -> int:
    unsigned = ((high_word & 0xFFFF) << 16) | (low_word & 0xFFFF)
    return unsigned - 0x100000000 if unsigned & 0x80000000 else unsigned


def split_year_total(value: float) -> tuple[int, float]:
    """Split a total into the LONG and REAL4 fields read by the node."""

    numeric = float(value)
    if not math.isfinite(numeric):
        raise ValueError("Year total must be finite")
    integer = math.trunc(numeric)
    int32_to_registers_low_word_first(integer)
    fraction = numeric - integer
    _float32_bits(fraction)
    return integer, fraction


def _validate_error_code(value: int) -> int:
    parsed = int(value)
    if not 0 <= parsed <= 0xFFFF:
        raise ValueError("Error code must be between 0x0000 and 0xFFFF")
    return parsed


def build_register_map(values: Tuf2000bValues) -> dict[int, int]:
    """Build the TUF registers consumed by the current STM32 firmware."""

    registers: dict[int, int] = {}

    def put_float(address: int, value: float) -> None:
        low_word, high_word = float_to_registers_low_word_first(value)
        registers[address] = low_word
        registers[address + 1] = high_word

    put_float(REG_FLOW_RATE, values.flow_rate_m3h)
    put_float(REG_ENERGY_FLOW_RATE, values.energy_flow_rate_gjh)
    put_float(REG_VELOCITY, values.velocity_mps)
    registers[REG_ERROR_CODE] = _validate_error_code(values.error_code)
    put_float(REG_TODAY_TOTAL, values.today_total_m3)
    put_float(REG_MONTH_TOTAL, values.month_total_m3)

    year_integer, year_fraction = split_year_total(values.year_total_m3)
    low_word, high_word = int32_to_registers_low_word_first(year_integer)
    registers[REG_YEAR_INTEGER] = low_word
    registers[REG_YEAR_INTEGER + 1] = high_word
    put_float(REG_YEAR_FRACTION, year_fraction)
    return registers


def advance_period_totals(
    values: Tuf2000bValues,
    elapsed_seconds: float,
    time_multiplier: float = 1.0,
) -> Tuf2000bValues:
    """Advance day, month, and year totals from the simulated flow rate."""

    elapsed = float(elapsed_seconds)
    multiplier = float(time_multiplier)
    if not math.isfinite(elapsed) or elapsed < 0.0:
        raise ValueError("Elapsed time must be a finite non-negative value")
    if not math.isfinite(multiplier) or multiplier <= 0.0:
        raise ValueError("Time multiplier must be finite and greater than zero")
    if not math.isfinite(float(values.flow_rate_m3h)):
        raise ValueError("Flow rate must be finite")

    delta_m3 = values.flow_rate_m3h * elapsed * multiplier / 3600.0
    updated = replace(
        values,
        today_total_m3=values.today_total_m3 + delta_m3,
        month_total_m3=values.month_total_m3 + delta_m3,
        year_total_m3=values.year_total_m3 + delta_m3,
    )
    # Validate that all updated values remain representable by the meter fields.
    build_register_map(updated)
    return updated


def reset_period_total(values: Tuf2000bValues, period: str) -> Tuf2000bValues:
    """Reset one simulated calendar total, or all three totals."""

    normalized = period.strip().lower()
    if normalized == "today":
        return replace(values, today_total_m3=0.0)
    if normalized == "month":
        return replace(values, month_total_m3=0.0)
    if normalized == "year":
        return replace(values, year_total_m3=0.0)
    if normalized == "all":
        return replace(
            values,
            today_total_m3=0.0,
            month_total_m3=0.0,
            year_total_m3=0.0,
        )
    raise ValueError("Period must be today, month, year, or all")


def _exception_response(slave_id: int, function: int, code: int) -> bytes:
    return append_crc(bytes((slave_id, function | 0x80, code)))


def _range_description(start_address: int, count: int) -> str:
    known = {
        (REG_FLOW_RATE, 6): "flow rate, energy flow, and velocity",
        (REG_TODAY_TOTAL, 4): "today and month totals",
        (REG_YEAR_INTEGER, 4): "year integer and fraction",
        (REG_ERROR_CODE, 1): "error code",
    }
    label = known.get((start_address, count), "holding registers")
    return f"read {label} ({start_address:#06x}, count {count})"


def handle_request(
    frame: bytes,
    slave_id: int,
    values: Tuf2000bValues,
    register_map: Mapping[int, int] | None = None,
) -> ModbusDecision:
    """Validate and answer one complete Modbus RTU request.

    The production driver uses function 0x03.  Unsupported functions receive
    a standard exception.  Bad CRCs and requests for another slave are ignored
    because an RTU slave must remain silent in those cases.
    """

    if len(frame) != 8:
        return ModbusDecision(None, f"ignored frame with length {len(frame)}")
    if not frame_has_valid_crc(frame):
        return ModbusDecision(None, "ignored frame with invalid CRC")

    configured_slave = int(slave_id)
    if not 1 <= configured_slave <= 247:
        raise ValueError("Slave ID must be between 1 and 247")

    request_slave = frame[0]
    function = frame[1]
    if request_slave == 0:
        return ModbusDecision(None, "ignored broadcast read request")
    if request_slave != configured_slave:
        return ModbusDecision(None, f"ignored request for slave {request_slave}")
    if function != 0x03:
        return ModbusDecision(
            _exception_response(request_slave, function, 0x01),
            f"illegal function 0x{function:02X}",
        )

    start_address = (frame[2] << 8) | frame[3]
    count = (frame[4] << 8) | frame[5]
    if count < 1 or count > 125:
        return ModbusDecision(
            _exception_response(request_slave, function, 0x03),
            f"illegal register count {count}",
        )

    active_map = (
        dict(register_map) if register_map is not None else build_register_map(values)
    )
    requested_addresses = range(start_address, start_address + count)
    if any(address not in active_map for address in requested_addresses):
        return ModbusDecision(
            _exception_response(request_slave, function, 0x02),
            f"illegal register range {start_address}-{start_address + count - 1}",
        )

    payload = bytearray((request_slave, function, count * 2))
    for address in requested_addresses:
        payload.extend(struct.pack(">H", active_map[address] & 0xFFFF))

    return ModbusDecision(
        append_crc(bytes(payload)),
        _range_description(start_address, count),
    )
