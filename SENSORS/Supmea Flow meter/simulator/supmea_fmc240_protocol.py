"""Protocol core for a Supmea SUP-FMC240 Modbus RTU test slave.

The register addresses and byte order follow Chapter 9 of the supplied
SUP-FMC240 user manual. This module deliberately has no GUI or serial-port
dependency so its frame handling can be unit tested.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import math
import struct
from typing import Mapping


FLOW_UNIT_NAMES = (
    "L/h",
    "L/min",
    "L/s",
    "m3/h",
    "m3/min",
    "m3/s",
    "kg/h",
    "kg/min",
    "kg/s",
    "t/h",
    "t/min",
    "t/s",
)

# Multipliers from each volumetric unit to cubic metres per hour. Unit codes
# 6..11 are mass-flow units and cannot update a volume total without density.
VOLUMETRIC_TO_M3_PER_HOUR = {
    0: 0.001,
    1: 0.060,
    2: 3.600,
    3: 1.000,
    4: 60.000,
    5: 3600.000,
}

REG_FORWARD_TOTAL = 90
REG_REVERSE_TOTAL = 92
REG_NET_TOTAL = 94
REG_TOTALIZER_RESET = 96
REG_FLOW_RATE = 98
REG_VELOCITY = 100
REG_FLOW_RATIO = 102
REG_EPD_VALUE = 104
REG_FLOW_RATE_UNIT = 105
REG_EPD_ALARM = 106
REG_EXCITATION_ALARM = 107


@dataclass(frozen=True)
class Fmc240Values:
    """One coherent set of values exposed through the simulated meter."""

    forward_total_m3: float = 1250.75
    reverse_total_m3: float = 25.25
    net_total_m3: float = 1225.50
    flow_rate: float = 35.0
    velocity_mps: float = 1.25
    flow_ratio_percent: float = 42.5
    epd_percent: int = 0
    flow_rate_unit: int = 3
    epd_alarm: int = 0
    excitation_alarm: int = 0


@dataclass(frozen=True)
class ModbusDecision:
    """Result of examining one complete eight-byte Modbus request."""

    response: bytes | None
    description: str


def flow_rate_to_m3_per_hour(flow_rate: float, unit_code: int) -> float:
    """Normalize one FMC240 volumetric flow value to m3/h."""

    if not math.isfinite(float(flow_rate)):
        raise ValueError("Flow rate must be finite")
    if int(unit_code) not in VOLUMETRIC_TO_M3_PER_HOUR:
        raise ValueError(
            "Automatic volume totals require a volumetric unit (codes 0..5)"
        )
    return float(flow_rate) * VOLUMETRIC_TO_M3_PER_HOUR[int(unit_code)]


def advance_totalizers(
    values: Fmc240Values,
    elapsed_seconds: float,
    time_multiplier: float = 1.0,
) -> Fmc240Values:
    """Advance forward/reverse/net totals using the configured flow rate.

    This calculation exists only in the PC simulator. The STM32 production
    firmware derives period consumption from the meter's cumulative forward
    counter and never integrates instantaneous flow.
    """

    elapsed = float(elapsed_seconds)
    multiplier = float(time_multiplier)
    if not math.isfinite(elapsed) or elapsed < 0.0:
        raise ValueError("Elapsed time must be a finite non-negative value")
    if not math.isfinite(multiplier) or multiplier <= 0.0:
        raise ValueError("Time multiplier must be finite and greater than zero")

    delta_m3 = (
        flow_rate_to_m3_per_hour(values.flow_rate, values.flow_rate_unit)
        * elapsed
        * multiplier
        / 3600.0
    )
    forward = values.forward_total_m3 + max(delta_m3, 0.0)
    reverse = values.reverse_total_m3 + max(-delta_m3, 0.0)
    return replace(
        values,
        forward_total_m3=forward,
        reverse_total_m3=reverse,
        net_total_m3=values.net_total_m3 + delta_m3,
    )


def reset_totalizers(values: Fmc240Values) -> Fmc240Values:
    """Return the same live measurement with all three meter totals reset."""

    return replace(
        values,
        forward_total_m3=0.0,
        reverse_total_m3=0.0,
        net_total_m3=0.0,
    )


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


def float_to_registers(value: float) -> tuple[int, int]:
    """Encode IEEE-754 Float32 as FMC240 high-word-first registers."""

    if not math.isfinite(value):
        raise ValueError("FMC240 floating-point values must be finite")
    try:
        packed = struct.pack(">f", float(value))
    except OverflowError as exc:
        raise ValueError("Value is outside the Float32 range") from exc
    return struct.unpack(">HH", packed)


def registers_to_float(high_word: int, low_word: int) -> float:
    packed = struct.pack(">HH", high_word & 0xFFFF, low_word & 0xFFFF)
    return struct.unpack(">f", packed)[0]


def _validate_u16(name: str, value: int) -> int:
    parsed = int(value)
    if not 0 <= parsed <= 0xFFFF:
        raise ValueError(f"{name} must be between 0 and 65535")
    return parsed


def build_register_map(values: Fmc240Values) -> dict[int, int]:
    """Build the documented FMC240 live/frequently-used register map."""

    if not 0 <= int(values.flow_rate_unit) < len(FLOW_UNIT_NAMES):
        raise ValueError("Flow-rate unit code must be between 0 and 11")

    registers: dict[int, int] = {}

    def put_float(address: int, value: float) -> None:
        high_word, low_word = float_to_registers(value)
        registers[address] = high_word
        registers[address + 1] = low_word

    put_float(REG_FORWARD_TOTAL, values.forward_total_m3)
    put_float(REG_REVERSE_TOTAL, values.reverse_total_m3)
    put_float(REG_NET_TOTAL, values.net_total_m3)
    registers[REG_TOTALIZER_RESET] = 0
    registers[REG_TOTALIZER_RESET + 1] = 0
    put_float(REG_FLOW_RATE, values.flow_rate)
    put_float(REG_VELOCITY, values.velocity_mps)
    put_float(REG_FLOW_RATIO, values.flow_ratio_percent)
    registers[REG_EPD_VALUE] = _validate_u16("EPD value", values.epd_percent)
    registers[REG_FLOW_RATE_UNIT] = int(values.flow_rate_unit)
    registers[REG_EPD_ALARM] = _validate_u16("EPD alarm", values.epd_alarm)
    registers[REG_EXCITATION_ALARM] = _validate_u16(
        "Excitation-current alarm", values.excitation_alarm
    )
    return registers


def _exception_response(slave_id: int, function: int, code: int) -> bytes:
    return append_crc(bytes((slave_id, function | 0x80, code)))


def handle_request(
    frame: bytes,
    slave_id: int,
    values: Fmc240Values,
    register_map: Mapping[int, int] | None = None,
) -> ModbusDecision:
    """Validate and answer one eight-byte Modbus RTU request.

    The Arduino driver uses function 0x03. Unsupported functions receive the
    standard illegal-function exception, while invalid CRCs and frames for a
    different slave are ignored as required on a shared RTU bus.
    """

    if len(frame) != 8:
        return ModbusDecision(None, f"ignored frame with length {len(frame)}")
    if not frame_has_valid_crc(frame):
        return ModbusDecision(None, "ignored frame with invalid CRC")

    request_slave = frame[0]
    function = frame[1]
    if request_slave != int(slave_id):
        return ModbusDecision(None, f"ignored request for slave {request_slave}")
    if request_slave == 0:
        return ModbusDecision(None, "ignored broadcast read request")
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

    active_map = dict(register_map) if register_map is not None else build_register_map(values)
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
        f"read holding registers {start_address}-{start_address + count - 1}",
    )
