"""Core models and Modbus RTU protocol for the WIOT multi-sensor simulator.

The module is intentionally independent from Tk and pyserial.  It provides a
thread-safe registry containing any number of TUF, Supmea, HNDA, and Sondas
devices, deterministic signal generation, JSON configuration, register-map
encoding, Modbus request dispatch, and fault injection.

Register-map sources:

* HNDA/Honde RD-SMT-P-O: supplied product manual, holding registers 0x0000
  and 0x0001, signed/unsigned values scaled by 10.
* TUF-2000B/M: supplied TUF register table and the existing WIOT decoder.
* Supmea SUP-FMC240: supplied manual chapter 9.4.1, high-word-first Float32.
* Sondas: WIOT compatibility map used by the production node.  The supplied
  Nutricontrol brochure describes SDI-12 hardware and has no Modbus map.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import Enum
import json
import math
from pathlib import Path
import random
import struct
import threading
import time
import uuid
from supmea_reference import SupmeaReference
from typing import Any, Iterable, Mapping, Sequence


CONFIG_VERSION = 1
MODBUS_READ_HOLDING_REGISTERS = 0x03
MODBUS_WRITE_SINGLE_REGISTER = 0x06


class SensorType(str, Enum):
    HNDA = "HNDA"
    TUF = "TUF"
    SUPMEA = "SUPMEA"
    SONDAS = "SONDAS"

    @property
    def display_name(self) -> str:
        return {
            SensorType.HNDA: "HNDA soil moisture + temperature",
            SensorType.TUF: "TUF-2000B/M ultrasonic flow meter",
            SensorType.SUPMEA: "Supmea SUP-FMC240 magnetic flow meter",
            SensorType.SONDAS: "Sondas soil moisture + temperature + EC",
        }[self]


class SignalMode(str, Enum):
    FIXED = "fixed"
    RANDOM = "random"
    RANDOM_WALK = "random_walk"
    SINE = "sine"
    RAMP = "ramp"
    STEP = "step"

    @property
    def display_name(self) -> str:
        return {
            SignalMode.FIXED: "Fixed",
            SignalMode.RANDOM: "Random range",
            SignalMode.RANDOM_WALK: "Random walk",
            SignalMode.SINE: "Sine wave",
            SignalMode.RAMP: "Ramp / triangle",
            SignalMode.STEP: "Two-level step",
        }[self]


@dataclass(frozen=True)
class SignalDefinition:
    key: str
    label: str
    unit: str
    default: float
    minimum: float
    maximum: float
    step: float
    period_s: float = 20.0
    integer: bool = False
    totalizer: bool = False
    discrete: bool = False


SIGNAL_DEFINITIONS: dict[SensorType, tuple[SignalDefinition, ...]] = {
    SensorType.HNDA: (
        SignalDefinition(
            "temperature_c", "Soil temperature", "deg C", 23.5, -30.0, 70.0, 0.2
        ),
        SignalDefinition(
            "moisture_percent", "Soil moisture", "% VWC", 35.6, 0.0, 100.0, 0.5
        ),
    ),
    SensorType.TUF: (
        SignalDefinition(
            "flow_rate_m3h", "Flow rate", "m3/h", 12.5, -100.0, 100.0, 1.0
        ),
        SignalDefinition(
            "energy_flow_rate_gjh", "Energy flow", "GJ/h", 0.0, -100.0, 100.0, 0.5
        ),
        SignalDefinition(
            "velocity_mps", "Velocity", "m/s", 1.25, -20.0, 20.0, 0.1
        ),
        SignalDefinition(
            "today_total_m3",
            "Today total",
            "m3",
            25.5,
            -2_000_000_000.0,
            2_000_000_000.0,
            1.0,
            totalizer=True,
        ),
        SignalDefinition(
            "month_total_m3",
            "Month total",
            "m3",
            340.75,
            -2_000_000_000.0,
            2_000_000_000.0,
            10.0,
            totalizer=True,
        ),
        SignalDefinition(
            "year_total_m3",
            "Year total",
            "m3",
            2500.875,
            -2_000_000_000.0,
            2_000_000_000.0,
            100.0,
            totalizer=True,
        ),
        SignalDefinition(
            "error_code", "Error bit mask", "0x0000", 0, 0, 65535, 1,
            integer=True, discrete=True
        ),
    ),
    SensorType.SUPMEA: (
        SignalDefinition(
            "forward_total_m3", "Forward total", "m3", 1250.75, 0.0, 1.0e9, 10.0,
            totalizer=True
        ),
        SignalDefinition(
            "reverse_total_m3", "Reverse total", "m3", 25.25, 0.0, 1.0e9, 1.0,
            totalizer=True
        ),
        SignalDefinition(
            "net_total_m3", "Net total", "m3", 1225.5, -1.0e9, 1.0e9, 10.0,
            totalizer=True
        ),
        SignalDefinition(
            "flow_rate", "Flow rate", "selected unit", 35.0, -1000.0, 1000.0, 2.0
        ),
        SignalDefinition(
            "velocity_mps", "Velocity", "m/s", 1.25, -20.0, 20.0, 0.1
        ),
        SignalDefinition(
            "flow_ratio_percent", "Flow ratio", "%", 42.5, -200.0, 200.0, 1.0
        ),
        SignalDefinition(
            "epd_percent", "EPD value", "%", 0, 0, 100, 1,
            integer=True
        ),
        SignalDefinition(
            "flow_rate_unit", "Flow-rate unit code", "0..11", 3, 0, 11, 1,
            integer=True, discrete=True
        ),
        SignalDefinition(
            "epd_alarm", "EPD alarm", "0/1", 0, 0, 1, 1,
            integer=True, discrete=True
        ),
        SignalDefinition(
            "excitation_alarm", "Excitation alarm", "0/1", 0, 0, 1, 1,
            integer=True, discrete=True
        ),
    ),
    SensorType.SONDAS: (
        SignalDefinition(
            "temperature_c", "Soil temperature", "deg C", 24.0, -30.0, 70.0, 0.2
        ),
        SignalDefinition(
            "moisture_percent", "Soil moisture", "% VWC", 42.0, 0.0, 100.0, 0.5
        ),
        SignalDefinition(
            "electrical_conductivity",
            "Electrical conductivity",
            "WIOT raw x1",
            850,
            0,
            65535,
            25,
            integer=True,
        ),
    ),
}


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

VOLUMETRIC_TO_M3_PER_HOUR = {
    0: 0.001,
    1: 0.060,
    2: 3.600,
    3: 1.000,
    4: 60.000,
    5: 3600.000,
}


REGISTER_REFERENCE: dict[SensorType, tuple[str, ...]] = {
    SensorType.HNDA: (
        "0x0000: soil temperature, signed Int16 x10",
        "0x0001: soil moisture, UInt16 x10",
        "0x0030: device address (function 0x06 supported)",
    ),
    SensorType.TUF: (
        "0x0000..0x0005: flow, energy flow, velocity (Float32 low-word first)",
        "0x0047: error bit mask",
        "0x007C..0x007F: today and month totals",
        "0x0090..0x0093: year integer + fractional total",
    ),
    SensorType.SUPMEA: (
        "0x005A..0x005F: forward, reverse, and net totals",
        "0x0062..0x0067: flow, velocity, and flow ratio (Float32 high-word first)",
        "0x0068..0x006B: EPD, unit code, EPD alarm, excitation alarm",
    ),
    SensorType.SONDAS: (
        "0x0000: temperature, signed Int16 x10",
        "0x0001: moisture, UInt16 x10",
        "0x0002: electrical conductivity, UInt16 x1",
        "WIOT compatibility profile; supplied Sondas brochure is SDI-12, not Modbus",
    ),
}


def utc_timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def modbus_crc16(data: bytes) -> int:
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
    crc = modbus_crc16(frame_without_crc)
    return frame_without_crc + bytes((crc & 0xFF, (crc >> 8) & 0xFF))


def frame_has_valid_crc(frame: bytes) -> bool:
    if len(frame) < 3:
        return False
    received = frame[-2] | (frame[-1] << 8)
    return received == modbus_crc16(frame[:-2])


def bytes_to_hex(data: bytes) -> str:
    return " ".join(f"{byte:02X}" for byte in data)


def _finite_float(name: str, value: Any) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"{name} must be finite")
    return parsed


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


@dataclass
class SignalProfile:
    mode: SignalMode
    value: float
    minimum: float
    maximum: float
    step: float
    period_s: float

    def validate(self, definition: SignalDefinition) -> None:
        if not isinstance(self.mode, SignalMode):
            self.mode = SignalMode(str(self.mode))
        self.value = _finite_float(f"{definition.label} value", self.value)
        self.minimum = _finite_float(f"{definition.label} minimum", self.minimum)
        self.maximum = _finite_float(f"{definition.label} maximum", self.maximum)
        self.step = abs(_finite_float(f"{definition.label} step", self.step))
        self.period_s = _finite_float(f"{definition.label} period", self.period_s)
        if self.minimum > self.maximum:
            raise ValueError(f"{definition.label}: minimum cannot exceed maximum")
        if not self.minimum <= self.value <= self.maximum:
            raise ValueError(
                f"{definition.label}: initial value must be inside its range"
            )
        if self.period_s <= 0:
            raise ValueError(f"{definition.label}: period must be greater than zero")
        if definition.integer:
            self.value = float(round(self.value))
            self.minimum = float(math.ceil(self.minimum))
            self.maximum = float(math.floor(self.maximum))
            self.step = float(max(1, round(self.step)))

    @classmethod
    def from_definition(
        cls,
        definition: SignalDefinition,
        mode: SignalMode = SignalMode.FIXED,
    ) -> "SignalProfile":
        return cls(
            mode=mode,
            value=float(definition.default),
            minimum=float(definition.minimum),
            maximum=float(definition.maximum),
            step=float(definition.step),
            period_s=float(definition.period_s),
        )

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, Any],
        definition: SignalDefinition,
    ) -> "SignalProfile":
        profile = cls(
            mode=SignalMode(str(data.get("mode", SignalMode.FIXED.value))),
            value=float(data.get("value", definition.default)),
            minimum=float(data.get("minimum", definition.minimum)),
            maximum=float(data.get("maximum", definition.maximum)),
            step=float(data.get("step", definition.step)),
            period_s=float(data.get("period_s", definition.period_s)),
        )
        profile.validate(definition)
        return profile

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "value": self.value,
            "minimum": self.minimum,
            "maximum": self.maximum,
            "step": self.step,
            "period_s": self.period_s,
        }


@dataclass
class FaultProfile:
    extra_delay_ms: int = 0
    drop_percent: float = 0.0
    crc_error_percent: float = 0.0
    forced_exception: int = 0

    def validate(self) -> None:
        self.extra_delay_ms = int(self.extra_delay_ms)
        self.drop_percent = _finite_float("Drop percentage", self.drop_percent)
        self.crc_error_percent = _finite_float(
            "CRC-error percentage", self.crc_error_percent
        )
        self.forced_exception = int(self.forced_exception)
        if not 0 <= self.extra_delay_ms <= 60_000:
            raise ValueError("Extra response delay must be between 0 and 60000 ms")
        if not 0.0 <= self.drop_percent <= 100.0:
            raise ValueError("Drop percentage must be between 0 and 100")
        if not 0.0 <= self.crc_error_percent <= 100.0:
            raise ValueError("CRC-error percentage must be between 0 and 100")
        if self.forced_exception not in (0, 1, 2, 3, 4):
            raise ValueError("Forced exception must be 0, 1, 2, 3, or 4")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "FaultProfile":
        raw = data or {}
        profile = cls(
            extra_delay_ms=int(raw.get("extra_delay_ms", 0)),
            drop_percent=float(raw.get("drop_percent", 0.0)),
            crc_error_percent=float(raw.get("crc_error_percent", 0.0)),
            forced_exception=int(raw.get("forced_exception", 0)),
        )
        profile.validate()
        return profile

    def to_dict(self) -> dict[str, Any]:
        return {
            "extra_delay_ms": self.extra_delay_ms,
            "drop_percent": self.drop_percent,
            "crc_error_percent": self.crc_error_percent,
            "forced_exception": self.forced_exception,
        }


@dataclass
class DeviceStatistics:
    requests: int = 0
    responses: int = 0
    exceptions: int = 0
    dropped: int = 0
    last_seen: str = "-"
    last_request: str = "-"

    def to_dict(self) -> dict[str, Any]:
        return {
            "requests": self.requests,
            "responses": self.responses,
            "exceptions": self.exceptions,
            "dropped": self.dropped,
            "last_seen": self.last_seen,
            "last_request": self.last_request,
        }


@dataclass
class SensorDevice:
    sensor_type: SensorType
    address: int
    name: str
    enabled: bool = True
    muted: bool = False
    update_interval_s: float = 1.0
    auto_totalizers: bool = False
    time_multiplier: float = 1.0
    random_seed: int = 1
    reference_timezone: str = "Africa/Cairo"
    signals: dict[str, SignalProfile] = field(default_factory=dict)
    faults: FaultProfile = field(default_factory=FaultProfile)
    device_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    statistics: DeviceStatistics = field(default_factory=DeviceStatistics, init=False)
    runtime_values: dict[str, float] = field(default_factory=dict, init=False)
    _directions: dict[str, int] = field(default_factory=dict, init=False, repr=False)
    _last_update: float = field(default_factory=time.monotonic, init=False, repr=False)
    _sim_elapsed: float = field(default=0.0, init=False, repr=False)
    _rng: random.Random = field(init=False, repr=False)
    reference: SupmeaReference | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.sensor_type, SensorType):
            self.sensor_type = SensorType(str(self.sensor_type).upper())
        self.address = int(self.address)
        self.name = str(self.name).strip()
        self.enabled = bool(self.enabled)
        self.muted = bool(self.muted)
        self.update_interval_s = _finite_float(
            "Update interval", self.update_interval_s
        )
        self.time_multiplier = _finite_float("Time multiplier", self.time_multiplier)
        self.random_seed = int(self.random_seed)
        self.faults.validate()
        if not 1 <= self.address <= 247:
            raise ValueError("Modbus address must be between 1 and 247")
        if not self.name:
            raise ValueError("Device name cannot be empty")
        if self.update_interval_s < 0.05:
            raise ValueError("Update interval must be at least 0.05 seconds")
        if self.time_multiplier <= 0:
            raise ValueError("Time multiplier must be greater than zero")

        definitions = signal_definition_map(self.sensor_type)
        normalized: dict[str, SignalProfile] = {}
        for key, definition in definitions.items():
            profile = self.signals.get(key)
            if profile is None:
                profile = SignalProfile.from_definition(definition)
            profile.validate(definition)
            normalized[key] = profile
        unknown = set(self.signals) - set(definitions)
        if unknown:
            raise ValueError(
                f"Unknown {self.sensor_type.value} signal(s): {', '.join(sorted(unknown))}"
            )
        self.signals = normalized
        self._rng = random.Random(self.random_seed)
        self.reset_runtime()

    def reset_runtime(self) -> None:
        self.runtime_values = {
            key: float(profile.value) for key, profile in self.signals.items()
        }
        self._directions = {key: 1 for key in self.signals}
        self._last_update = time.monotonic()
        self._sim_elapsed = 0.0
        self.reference = (SupmeaReference(self.reference_timezone)
                          if self.sensor_type is SensorType.SUPMEA else None)

    def advance(self, now: float | None = None) -> bool:
        current_time = time.monotonic() if now is None else float(now)
        elapsed_real = max(0.0, current_time - self._last_update)
        if elapsed_real < self.update_interval_s:
            return False

        elapsed_sim = elapsed_real * self.time_multiplier
        self._sim_elapsed += elapsed_sim
        definitions = signal_definition_map(self.sensor_type)

        for key, profile in self.signals.items():
            definition = definitions[key]
            if self.auto_totalizers and definition.totalizer:
                continue
            current = self.runtime_values[key]
            evolved = self._evolve_signal(key, profile, current)
            if definition.integer:
                evolved = float(round(evolved))
            self.runtime_values[key] = _clamp(
                evolved, profile.minimum, profile.maximum
            )

        if self.auto_totalizers:
            self._advance_totalizers(elapsed_sim)

        if self.reference is not None:
            factor = VOLUMETRIC_TO_M3_PER_HOUR.get(int(round(self.runtime_values["flow_rate_unit"])))
            normalized = (self.runtime_values["flow_rate"] * factor
                          if self.auto_totalizers and factor is not None else None)
            self.reference.advance(elapsed_sim, normalized)

        self._last_update = current_time
        return True

    def _evolve_signal(
        self,
        key: str,
        profile: SignalProfile,
        current: float,
    ) -> float:
        mode = profile.mode
        if mode is SignalMode.FIXED:
            return profile.value
        if mode is SignalMode.RANDOM:
            return self._rng.uniform(profile.minimum, profile.maximum)
        if mode is SignalMode.RANDOM_WALK:
            return current + self._rng.uniform(-profile.step, profile.step)
        if mode is SignalMode.SINE:
            return profile.value + profile.step * math.sin(
                (2.0 * math.pi * self._sim_elapsed) / profile.period_s
            )
        if mode is SignalMode.STEP:
            phase = int(self._sim_elapsed / profile.period_s) % 2
            return profile.minimum if phase == 0 else profile.maximum
        if mode is SignalMode.RAMP:
            direction = self._directions.get(key, 1)
            candidate = current + profile.step * direction
            if candidate >= profile.maximum:
                candidate = profile.maximum
                self._directions[key] = -1
            elif candidate <= profile.minimum:
                candidate = profile.minimum
                self._directions[key] = 1
            return candidate
        raise ValueError(f"Unsupported signal mode: {mode}")

    def _advance_totalizers(self, elapsed_sim: float) -> None:
        if self.sensor_type is SensorType.TUF:
            delta = self.runtime_values["flow_rate_m3h"] * elapsed_sim / 3600.0
            for key in ("today_total_m3", "month_total_m3", "year_total_m3"):
                profile = self.signals[key]
                self.runtime_values[key] = _clamp(
                    self.runtime_values[key] + delta,
                    profile.minimum,
                    profile.maximum,
                )
            return

        if self.sensor_type is SensorType.SUPMEA:
            unit_code = int(round(self.runtime_values["flow_rate_unit"]))
            multiplier = VOLUMETRIC_TO_M3_PER_HOUR.get(unit_code)
            if multiplier is None:
                return
            delta = (
                self.runtime_values["flow_rate"]
                * multiplier
                * elapsed_sim
                / 3600.0
            )
            if delta >= 0:
                self.runtime_values["forward_total_m3"] += delta
            else:
                self.runtime_values["reverse_total_m3"] += -delta
            self.runtime_values["net_total_m3"] += delta
            for key in ("forward_total_m3", "reverse_total_m3", "net_total_m3"):
                profile = self.signals[key]
                self.runtime_values[key] = _clamp(
                    self.runtime_values[key], profile.minimum, profile.maximum
                )

    def reset_totalizers(self) -> bool:
        keys: tuple[str, ...]
        if self.sensor_type is SensorType.TUF:
            keys = ("today_total_m3", "month_total_m3", "year_total_m3")
        elif self.sensor_type is SensorType.SUPMEA:
            keys = ("forward_total_m3", "reverse_total_m3", "net_total_m3")
        else:
            return False
        for key in keys:
            self.runtime_values[key] = 0.0
            self.signals[key].value = 0.0
        return True

    def build_register_map(self) -> dict[int, int]:
        return build_register_map(self.sensor_type, self.runtime_values)

    def to_config_dict(self) -> dict[str, Any]:
        return {
            "id": self.device_id,
            "name": self.name,
            "type": self.sensor_type.value,
            "address": self.address,
            "enabled": self.enabled,
            "muted": self.muted,
            "update_interval_s": self.update_interval_s,
            "auto_totalizers": self.auto_totalizers,
            "time_multiplier": self.time_multiplier,
            "random_seed": self.random_seed,
            "reference_timezone": self.reference_timezone,
            "faults": self.faults.to_dict(),
            "signals": {key: value.to_dict() for key, value in self.signals.items()},
        }

    def to_runtime_dict(self) -> dict[str, Any]:
        result = self.to_config_dict()
        result["values"] = dict(self.runtime_values)
        result["statistics"] = self.statistics.to_dict()
        if self.reference is not None:
            result["supmea_reference"] = self.reference.snapshot()
        return result

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SensorDevice":
        sensor_type = SensorType(str(data["type"]).upper())
        definitions = signal_definition_map(sensor_type)
        raw_signals = data.get("signals", {})
        if not isinstance(raw_signals, Mapping):
            raise ValueError("Device signals must be a JSON object")
        signals = {
            key: SignalProfile.from_dict(
                raw_signals.get(key, {}), definition
            )
            for key, definition in definitions.items()
        }
        return cls(
            sensor_type=sensor_type,
            address=int(data["address"]),
            name=str(data.get("name") or f"{sensor_type.value}-{int(data['address']):03d}"),
            enabled=bool(data.get("enabled", True)),
            muted=bool(data.get("muted", False)),
            update_interval_s=float(data.get("update_interval_s", 1.0)),
            auto_totalizers=bool(
                data.get(
                    "auto_totalizers",
                    sensor_type in (SensorType.TUF, SensorType.SUPMEA),
                )
            ),
            time_multiplier=float(data.get("time_multiplier", 1.0)),
            random_seed=int(data.get("random_seed", int(data["address"]))),
            reference_timezone=str(data.get("reference_timezone", "Africa/Cairo")),
            signals=signals,
            faults=FaultProfile.from_dict(data.get("faults")),
            device_id=str(data.get("id") or uuid.uuid4().hex),
        )


@dataclass
class BusSettings:
    port: str = "COM3"
    baudrate: int = 9600
    parity: str = "N"
    stopbits: int = 1
    response_delay_ms: int = 20

    def validate(self) -> None:
        self.port = str(self.port).strip()
        self.baudrate = int(self.baudrate)
        self.parity = str(self.parity).upper().strip()
        self.stopbits = int(self.stopbits)
        self.response_delay_ms = int(self.response_delay_ms)
        if not self.port:
            raise ValueError("Serial port cannot be empty")
        if self.baudrate not in (
            300,
            600,
            1200,
            2400,
            4800,
            9600,
            19200,
            38400,
            57600,
            115200,
        ):
            raise ValueError("Unsupported baud rate")
        if self.parity not in ("N", "E", "O"):
            raise ValueError("Parity must be N, E, or O")
        if self.stopbits not in (1, 2):
            raise ValueError("Stop bits must be 1 or 2")
        if not 0 <= self.response_delay_ms <= 60_000:
            raise ValueError("Response delay must be between 0 and 60000 ms")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "BusSettings":
        raw = data or {}
        settings = cls(
            port=str(raw.get("port", "COM3")),
            baudrate=int(raw.get("baudrate", 9600)),
            parity=str(raw.get("parity", "N")),
            stopbits=int(raw.get("stopbits", 1)),
            response_delay_ms=int(raw.get("response_delay_ms", 20)),
        )
        settings.validate()
        return settings

    def to_dict(self) -> dict[str, Any]:
        return {
            "port": self.port,
            "baudrate": self.baudrate,
            "parity": self.parity,
            "stopbits": self.stopbits,
            "response_delay_ms": self.response_delay_ms,
        }


@dataclass(frozen=True)
class DispatchDecision:
    response: bytes | None
    description: str
    level: str
    device_id: str | None = None
    device_name: str | None = None
    sensor_type: str | None = None
    address: int | None = None
    response_delay_ms: int = 0


def signal_definition_map(sensor_type: SensorType) -> dict[str, SignalDefinition]:
    return {definition.key: definition for definition in SIGNAL_DEFINITIONS[sensor_type]}


def create_device(
    sensor_type: SensorType | str,
    address: int,
    *,
    name: str | None = None,
    mode: SignalMode | str = SignalMode.FIXED,
    seed: int | None = None,
) -> SensorDevice:
    parsed_type = (
        sensor_type
        if isinstance(sensor_type, SensorType)
        else SensorType(str(sensor_type).upper())
    )
    parsed_mode = mode if isinstance(mode, SignalMode) else SignalMode(str(mode))
    signals: dict[str, SignalProfile] = {}
    for definition in SIGNAL_DEFINITIONS[parsed_type]:
        signal_mode = (
            SignalMode.FIXED
            if definition.totalizer or definition.discrete
            else parsed_mode
        )
        signals[definition.key] = SignalProfile.from_definition(
            definition, signal_mode
        )
    return SensorDevice(
        sensor_type=parsed_type,
        address=int(address),
        name=name or f"{parsed_type.value}-{int(address):03d}",
        auto_totalizers=parsed_type in (SensorType.TUF, SensorType.SUPMEA),
        random_seed=int(seed if seed is not None else address),
        signals=signals,
    )


def create_default_devices() -> list[SensorDevice]:
    first_hnda = create_device(
        SensorType.HNDA, 1, name="HNDA field node 1", mode=SignalMode.RANDOM_WALK
    )
    second_hnda = create_device(
        SensorType.HNDA, 2, name="HNDA field node 2", mode=SignalMode.FIXED
    )
    second_hnda.signals["temperature_c"].value = 27.2
    second_hnda.signals["moisture_percent"].value = 48.5
    second_hnda.reset_runtime()
    return [
        first_hnda,
        second_hnda,
        create_device(
            SensorType.TUF, 10, name="TUF main line", mode=SignalMode.SINE
        ),
        create_device(
            SensorType.SUPMEA, 20, name="Supmea magnetic line", mode=SignalMode.RANDOM_WALK
        ),
        create_device(
            SensorType.SONDAS, 30, name="Sondas greenhouse", mode=SignalMode.RAMP
        ),
    ]


def parse_address_spec(specification: str) -> list[int]:
    """Parse comma-separated addresses and inclusive ranges such as 1,3,10-14."""

    text = str(specification).strip()
    if not text:
        return []
    addresses: list[int] = []
    for token in text.split(","):
        part = token.strip()
        if not part:
            raise ValueError("Address list contains an empty item")
        if "-" in part:
            pieces = part.split("-", 1)
            if len(pieces) != 2 or not pieces[0].strip() or not pieces[1].strip():
                raise ValueError(f"Invalid address range: {part}")
            start, end = (int(piece.strip()) for piece in pieces)
            if end < start:
                raise ValueError(f"Address range is reversed: {part}")
            addresses.extend(range(start, end + 1))
        else:
            addresses.append(int(part))
    if any(address < 1 or address > 247 for address in addresses):
        raise ValueError("Every Modbus address must be between 1 and 247")
    if len(set(addresses)) != len(addresses):
        raise ValueError("Address list contains a duplicate")
    return addresses


def validate_device_set(devices: Iterable[SensorDevice]) -> None:
    seen_addresses: dict[int, str] = {}
    seen_ids: set[str] = set()
    count = 0
    for device in devices:
        count += 1
        if device.device_id in seen_ids:
            raise ValueError(f"Duplicate internal device ID: {device.device_id}")
        seen_ids.add(device.device_id)
        if device.address in seen_addresses:
            raise ValueError(
                f"Modbus address {device.address} is used by both "
                f"'{seen_addresses[device.address]}' and '{device.name}'"
            )
        seen_addresses[device.address] = device.name
    if count > 247:
        raise ValueError("A Modbus RTU bus can contain at most 247 unicast addresses")


class SensorRegistry:
    """Thread-safe mutable fleet and Modbus request dispatcher."""

    def __init__(self, devices: Sequence[SensorDevice] | None = None) -> None:
        self._lock = threading.RLock()
        self._devices: dict[str, SensorDevice] = {}
        self.replace_all(list(devices or []))

    def replace_all(self, devices: Sequence[SensorDevice]) -> None:
        validate_device_set(devices)
        with self._lock:
            self._devices = {device.device_id: device for device in devices}

    def add(self, device: SensorDevice) -> None:
        with self._lock:
            validate_device_set([*self._devices.values(), device])
            self._devices[device.device_id] = device

    def add_many(self, devices: Sequence[SensorDevice]) -> None:
        with self._lock:
            validate_device_set([*self._devices.values(), *devices])
            for device in devices:
                self._devices[device.device_id] = device

    def update(self, device: SensorDevice) -> None:
        with self._lock:
            if device.device_id not in self._devices:
                raise KeyError(f"Unknown device ID: {device.device_id}")
            others = [
                existing
                for device_id, existing in self._devices.items()
                if device_id != device.device_id
            ]
            validate_device_set([*others, device])
            old_stats = self._devices[device.device_id].statistics
            device.statistics = old_stats
            self._devices[device.device_id] = device

    def remove(self, device_id: str) -> None:
        with self._lock:
            if device_id not in self._devices:
                raise KeyError(f"Unknown device ID: {device_id}")
            del self._devices[device_id]

    def get_config_copy(self, device_id: str) -> SensorDevice:
        with self._lock:
            original = self._devices[device_id]
            return SensorDevice.from_dict(original.to_config_dict())

    def snapshots(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                device.to_runtime_dict()
                for device in sorted(
                    self._devices.values(), key=lambda item: (item.address, item.name)
                )
            ]

    def config_devices(self) -> list[SensorDevice]:
        with self._lock:
            return [
                SensorDevice.from_dict(device.to_config_dict())
                for device in sorted(
                    self._devices.values(), key=lambda item: (item.address, item.name)
                )
            ]

    def address_in_use(self, address: int, excluding_device_id: str | None = None) -> bool:
        with self._lock:
            return any(
                device.address == int(address) and device_id != excluding_device_id
                for device_id, device in self._devices.items()
            )

    def set_enabled(self, device_id: str, enabled: bool) -> None:
        with self._lock:
            self._devices[device_id].enabled = bool(enabled)

    def set_muted(self, device_id: str, muted: bool) -> None:
        with self._lock:
            self._devices[device_id].muted = bool(muted)

    def reset_totalizers(self, device_id: str) -> bool:
        with self._lock:
            return self._devices[device_id].reset_totalizers()

    def clear_statistics(self) -> None:
        with self._lock:
            for device in self._devices.values():
                device.statistics = DeviceStatistics()

    def reset_supmea_reference(self, device_id, zone="Africa/Cairo", epoch=None):
        """Only reset the independent oracle, never the meter's wire totals."""
        reference = SupmeaReference(zone, epoch)
        with self._lock:
            device = self._devices[device_id]
            if device.sensor_type is not SensorType.SUPMEA:
                raise ValueError("Select a SUPMEA device")
            device.reference_timezone = zone
            device.reference = reference
            # A new session starts at this instant; do not include a prior partial tick.
            device._last_update = time.monotonic()

    def advance_all(self, now: float | None = None) -> int:
        with self._lock:
            return sum(device.advance(now) for device in self._devices.values())

    def dispatch(self, frame: bytes, global_delay_ms: int = 0) -> DispatchDecision:
        if len(frame) != 8:
            return DispatchDecision(
                None, f"ignored frame length {len(frame)}; expected 8", "error"
            )
        if not frame_has_valid_crc(frame):
            return DispatchDecision(None, "ignored request with invalid CRC", "crc")

        request_address = frame[0]
        function = frame[1]
        if request_address == 0:
            return DispatchDecision(
                None, "broadcast read/write request ignored", "ignored", address=0
            )

        with self._lock:
            device = next(
                (
                    item
                    for item in self._devices.values()
                    if item.address == request_address and item.enabled
                ),
                None,
            )
            if device is None:
                return DispatchDecision(
                    None,
                    f"no enabled simulated device at address {request_address}",
                    "ignored",
                    address=request_address,
                )

            stats = device.statistics
            stats.requests += 1
            stats.last_seen = utc_timestamp()
            stats.last_request = bytes_to_hex(frame)

            identity = {
                "device_id": device.device_id,
                "device_name": device.name,
                "sensor_type": device.sensor_type.value,
                "address": request_address,
                "response_delay_ms": int(global_delay_ms)
                + device.faults.extra_delay_ms,
            }

            if device.muted:
                stats.dropped += 1
                return DispatchDecision(
                    None, "response muted for this device", "dropped", **identity
                )
            if device._rng.random() * 100.0 < device.faults.drop_percent:
                stats.dropped += 1
                return DispatchDecision(
                    None, "response dropped by fault profile", "dropped", **identity
                )

            if device.faults.forced_exception:
                response = _exception_response(
                    request_address, function, device.faults.forced_exception
                )
                description = (
                    f"forced Modbus exception {device.faults.forced_exception}"
                )
                is_exception = True
            elif function == MODBUS_READ_HOLDING_REGISTERS:
                response, description, is_exception = _handle_read_request(
                    frame, device
                )
            elif function == MODBUS_WRITE_SINGLE_REGISTER:
                response, description, is_exception = self._handle_write_request(
                    frame, device
                )
            else:
                response = _exception_response(request_address, function, 0x01)
                description = f"illegal function 0x{function:02X}"
                is_exception = True

            if is_exception:
                stats.exceptions += 1
            if response is not None:
                stats.responses += 1
                if device._rng.random() * 100.0 < device.faults.crc_error_percent:
                    corrupted = bytearray(response)
                    corrupted[-1] ^= 0x01
                    response = bytes(corrupted)
                    description += "; CRC intentionally corrupted"

            return DispatchDecision(
                response,
                description,
                "exception" if is_exception else "response",
                **identity,
            )

    def _handle_write_request(
        self, frame: bytes, device: SensorDevice
    ) -> tuple[bytes, str, bool]:
        register = (frame[2] << 8) | frame[3]
        value = (frame[4] << 8) | frame[5]
        if device.sensor_type is not SensorType.HNDA:
            return (
                _exception_response(device.address, frame[1], 0x01),
                "write-single-register is supported only by the HNDA profile",
                True,
            )
        if register != 0x0030:
            return (
                _exception_response(device.address, frame[1], 0x02),
                f"illegal HNDA configuration register 0x{register:04X}",
                True,
            )
        if not 1 <= value <= 247:
            return (
                _exception_response(device.address, frame[1], 0x03),
                f"invalid HNDA address value {value}",
                True,
            )
        if any(
            other.device_id != device.device_id and other.address == value
            for other in self._devices.values()
        ):
            return (
                _exception_response(device.address, frame[1], 0x03),
                f"address {value} is already occupied on the simulated bus",
                True,
            )
        old_address = device.address
        response = append_crc(frame[:6])
        device.address = value
        return (
            response,
            f"HNDA address changed from {old_address} to {value}",
            False,
        )


def _exception_response(slave_id: int, function: int, code: int) -> bytes:
    return append_crc(bytes((slave_id, function | 0x80, code)))


def _handle_read_request(
    frame: bytes, device: SensorDevice
) -> tuple[bytes, str, bool]:
    start_address = (frame[2] << 8) | frame[3]
    count = (frame[4] << 8) | frame[5]
    if count < 1 or count > 125:
        return (
            _exception_response(device.address, frame[1], 0x03),
            f"illegal register count {count}",
            True,
        )
    registers = device.build_register_map()
    requested = range(start_address, start_address + count)
    if any(address not in registers for address in requested):
        return (
            _exception_response(device.address, frame[1], 0x02),
            f"illegal register range 0x{start_address:04X}-"
            f"0x{start_address + count - 1:04X}",
            True,
        )
    payload = bytearray((device.address, frame[1], count * 2))
    for address in requested:
        payload.extend(struct.pack(">H", registers[address] & 0xFFFF))
    return (
        append_crc(bytes(payload)),
        f"read 0x{start_address:04X}-0x{start_address + count - 1:04X} "
        f"({count} register{'s' if count != 1 else ''})",
        False,
    )


def _float32_words(value: float, low_word_first: bool) -> tuple[int, int]:
    numeric = _finite_float("Float32 register value", value)
    try:
        high, low = struct.unpack(">HH", struct.pack(">f", numeric))
    except OverflowError as exc:
        raise ValueError("Value is outside the Float32 range") from exc
    return (low, high) if low_word_first else (high, low)


def _signed_int16_register(value: float, scale: float) -> int:
    parsed = int(round(_finite_float("Signed register value", value) * scale))
    if not -32768 <= parsed <= 32767:
        raise ValueError("Signed scaled register is outside Int16 range")
    return parsed & 0xFFFF


def _unsigned_int16_register(value: float, scale: float) -> int:
    parsed = int(round(_finite_float("Unsigned register value", value) * scale))
    if not 0 <= parsed <= 0xFFFF:
        raise ValueError("Unsigned scaled register is outside UInt16 range")
    return parsed


def build_register_map(
    sensor_type: SensorType | str,
    values: Mapping[str, float],
) -> dict[int, int]:
    parsed_type = (
        sensor_type
        if isinstance(sensor_type, SensorType)
        else SensorType(str(sensor_type).upper())
    )
    registers: dict[int, int] = {}

    def put_float(address: int, key: str, low_word_first: bool) -> None:
        word0, word1 = _float32_words(values[key], low_word_first)
        registers[address] = word0
        registers[address + 1] = word1

    if parsed_type is SensorType.HNDA:
        registers[0x0000] = _signed_int16_register(values["temperature_c"], 10.0)
        registers[0x0001] = _unsigned_int16_register(
            values["moisture_percent"], 10.0
        )
        return registers

    if parsed_type is SensorType.SONDAS:
        registers[0x0000] = _signed_int16_register(values["temperature_c"], 10.0)
        registers[0x0001] = _unsigned_int16_register(
            values["moisture_percent"], 10.0
        )
        registers[0x0002] = _unsigned_int16_register(
            values["electrical_conductivity"], 1.0
        )
        return registers

    if parsed_type is SensorType.TUF:
        put_float(0x0000, "flow_rate_m3h", True)
        put_float(0x0002, "energy_flow_rate_gjh", True)
        put_float(0x0004, "velocity_mps", True)
        registers[0x0047] = _unsigned_int16_register(values["error_code"], 1.0)
        put_float(0x007C, "today_total_m3", True)
        put_float(0x007E, "month_total_m3", True)
        year_total = _finite_float("TUF year total", values["year_total_m3"])
        year_integer = math.trunc(year_total)
        if not -(2**31) <= year_integer <= 2**31 - 1:
            raise ValueError("TUF year total integer is outside Int32 range")
        unsigned = year_integer & 0xFFFFFFFF
        registers[0x0090] = unsigned & 0xFFFF
        registers[0x0091] = (unsigned >> 16) & 0xFFFF
        fraction_words = _float32_words(year_total - year_integer, True)
        registers[0x0092], registers[0x0093] = fraction_words
        return registers

    if parsed_type is SensorType.SUPMEA:
        put_float(90, "forward_total_m3", False)
        put_float(92, "reverse_total_m3", False)
        put_float(94, "net_total_m3", False)
        registers[96] = 0
        registers[97] = 0
        put_float(98, "flow_rate", False)
        put_float(100, "velocity_mps", False)
        put_float(102, "flow_ratio_percent", False)
        registers[104] = _unsigned_int16_register(values["epd_percent"], 1.0)
        unit_code = _unsigned_int16_register(values["flow_rate_unit"], 1.0)
        if unit_code > 11:
            raise ValueError("Supmea flow-rate unit code must be between 0 and 11")
        registers[105] = unit_code
        registers[106] = _unsigned_int16_register(values["epd_alarm"], 1.0)
        registers[107] = _unsigned_int16_register(
            values["excitation_alarm"], 1.0
        )
        return registers

    raise ValueError(f"Unsupported sensor type: {parsed_type}")


def configuration_to_dict(
    bus: BusSettings,
    devices: Sequence[SensorDevice],
) -> dict[str, Any]:
    bus.validate()
    validate_device_set(devices)
    counts = {
        sensor_type.value: sum(
            1 for device in devices if device.sensor_type is sensor_type
        )
        for sensor_type in SensorType
    }
    return {
        "schema_version": CONFIG_VERSION,
        "description": "WIOT multi-sensor RS485/Modbus simulator configuration",
        "bus": bus.to_dict(),
        "fleet_summary": counts,
        "devices": [device.to_config_dict() for device in devices],
    }


def save_configuration(
    path: str | Path,
    bus: BusSettings,
    devices: Sequence[SensorDevice],
) -> None:
    output = Path(path)
    output.write_text(
        json.dumps(configuration_to_dict(bus, devices), indent=2) + "\n",
        encoding="utf-8",
    )


def load_configuration(path: str | Path) -> tuple[BusSettings, list[SensorDevice]]:
    source = Path(path)
    data = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(data, Mapping):
        raise ValueError("Configuration root must be a JSON object")
    version = int(data.get("schema_version", 0))
    if version != CONFIG_VERSION:
        raise ValueError(
            f"Unsupported configuration schema {version}; expected {CONFIG_VERSION}"
        )
    bus = BusSettings.from_dict(data.get("bus"))
    raw_devices = data.get("devices")
    if not isinstance(raw_devices, list):
        raise ValueError("Configuration must contain a devices array")
    devices = [SensorDevice.from_dict(item) for item in raw_devices]
    validate_device_set(devices)
    summary = data.get("fleet_summary")
    if isinstance(summary, Mapping):
        for sensor_type in SensorType:
            if sensor_type.value in summary:
                expected = int(summary[sensor_type.value])
                actual = sum(
                    1 for device in devices if device.sensor_type is sensor_type
                )
                if expected != actual:
                    raise ValueError(
                        f"fleet_summary says {expected} {sensor_type.value} devices "
                        f"but the devices array contains {actual}"
                    )
    return bus, devices
