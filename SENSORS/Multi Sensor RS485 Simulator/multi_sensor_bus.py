"""Serial transport worker for the WIOT multi-sensor Modbus simulator."""

from __future__ import annotations

from dataclasses import dataclass
import threading
import time
from typing import Callable

from multi_sensor_core import (
    BusSettings,
    SensorRegistry,
    bytes_to_hex,
    frame_has_valid_crc,
)


@dataclass(frozen=True)
class BusEvent:
    level: str
    message: str
    raw_hex: str = ""
    device_id: str | None = None
    address: int | None = None
    sensor_type: str | None = None


@dataclass
class BusCounters:
    received_frames: int = 0
    transmitted_frames: int = 0
    ignored_frames: int = 0
    exception_frames: int = 0
    dropped_frames: int = 0
    crc_or_noise_bytes: int = 0

    def snapshot(self) -> dict[str, int]:
        return {
            "received_frames": self.received_frames,
            "transmitted_frames": self.transmitted_frames,
            "ignored_frames": self.ignored_frames,
            "exception_frames": self.exception_frames,
            "dropped_frames": self.dropped_frames,
            "crc_or_noise_bytes": self.crc_or_noise_bytes,
        }


EventCallback = Callable[[BusEvent], None]


class MultiSensorSerialSlave:
    """Serve every enabled virtual sensor through one physical serial port.

    The WIOT firmware uses eight-byte function 0x03 requests.  HNDA address
    writes use the same eight-byte shape with function 0x06.  The parser scans
    for a valid CRC window so it can recover from line noise or attaching in
    the middle of a frame.
    """

    def __init__(
        self,
        settings: BusSettings,
        registry: SensorRegistry,
        on_event: EventCallback,
    ) -> None:
        settings.validate()
        self.settings = settings
        self.registry = registry
        self._on_event = on_event
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._serial = None
        self._counter_lock = threading.Lock()
        self._counters = BusCounters()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            raise RuntimeError("The RS485 simulator is already running")
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="wiot-multi-sensor-modbus-slave",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        serial_port = self._serial
        if serial_port is not None:
            try:
                serial_port.cancel_read()
            except Exception:
                pass
        if self._thread is not None:
            self._thread.join(timeout=3.0)
        self._thread = None

    def counters(self) -> dict[str, int]:
        with self._counter_lock:
            return self._counters.snapshot()

    def clear_counters(self) -> None:
        with self._counter_lock:
            self._counters = BusCounters()

    def _increment(self, field_name: str, amount: int = 1) -> None:
        with self._counter_lock:
            setattr(
                self._counters,
                field_name,
                getattr(self._counters, field_name) + amount,
            )

    def _emit(
        self,
        level: str,
        message: str,
        *,
        raw_hex: str = "",
        device_id: str | None = None,
        address: int | None = None,
        sensor_type: str | None = None,
    ) -> None:
        self._on_event(
            BusEvent(
                level=level,
                message=message,
                raw_hex=raw_hex,
                device_id=device_id,
                address=address,
                sensor_type=sensor_type,
            )
        )

    def _open_serial(self):
        try:
            import serial
        except ImportError as exc:
            raise RuntimeError(
                "pyserial is not installed. Run: "
                "python -m pip install -r requirements.txt"
            ) from exc

        parity = {
            "N": serial.PARITY_NONE,
            "E": serial.PARITY_EVEN,
            "O": serial.PARITY_ODD,
        }[self.settings.parity]
        stopbits = (
            serial.STOPBITS_ONE
            if self.settings.stopbits == 1
            else serial.STOPBITS_TWO
        )
        kwargs = dict(
            baudrate=self.settings.baudrate,
            bytesize=serial.EIGHTBITS,
            parity=parity,
            stopbits=stopbits,
            timeout=0.025,
            write_timeout=2.0,
        )
        if "://" in self.settings.port:
            return serial.serial_for_url(self.settings.port, **kwargs)
        return serial.Serial(port=self.settings.port, **kwargs)

    def _run(self) -> None:
        try:
            self._serial = self._open_serial()
            self._emit(
                "status",
                f"Bus online: {self.settings.port}, {self.settings.baudrate} "
                f"8{self.settings.parity}{self.settings.stopbits}",
            )
            self._serve(self._serial)
        except Exception as exc:
            self._emit("error", str(exc))
        finally:
            if self._serial is not None:
                try:
                    self._serial.close()
                except Exception:
                    pass
            self._serial = None
            self._emit("stopped", "RS485 bus stopped")

    def _serve(self, serial_port) -> None:
        receive_buffer = bytearray()

        while not self._stop_event.is_set():
            chunk = serial_port.read(256)
            if chunk:
                receive_buffer.extend(chunk)

            while len(receive_buffer) >= 8:
                valid_offset = self._find_valid_request_offset(receive_buffer)
                if valid_offset is None:
                    # Preserve the final seven bytes because they may be the
                    # beginning of a request split across serial reads.
                    discard_count = max(0, len(receive_buffer) - 7)
                    if discard_count:
                        del receive_buffer[:discard_count]
                        self._increment("crc_or_noise_bytes", discard_count)
                        self._emit(
                            "noise",
                            f"discarded {discard_count} byte(s) without a valid RTU CRC",
                        )
                    break

                if valid_offset:
                    del receive_buffer[:valid_offset]
                    self._increment("crc_or_noise_bytes", valid_offset)
                    self._emit(
                        "noise",
                        f"discarded {valid_offset} leading noise byte(s)",
                    )

                request = bytes(receive_buffer[:8])
                del receive_buffer[:8]
                self._process_request(serial_port, request)

    @staticmethod
    def _find_valid_request_offset(buffer: bytearray) -> int | None:
        last_start = len(buffer) - 8
        for offset in range(last_start + 1):
            candidate = bytes(buffer[offset : offset + 8])
            if frame_has_valid_crc(candidate):
                return offset
        return None

    def _process_request(self, serial_port, request: bytes) -> None:
        self._increment("received_frames")
        self._emit("rx", "Modbus request", raw_hex=bytes_to_hex(request))

        decision = self.registry.dispatch(
            request,
            global_delay_ms=self.settings.response_delay_ms,
        )
        if decision.response is None:
            if decision.level == "dropped":
                self._increment("dropped_frames")
            else:
                self._increment("ignored_frames")
            self._emit(
                decision.level,
                decision.description,
                device_id=decision.device_id,
                address=decision.address,
                sensor_type=decision.sensor_type,
            )
            return

        if decision.level == "exception":
            self._increment("exception_frames")

        if decision.response_delay_ms > 0:
            if self._stop_event.wait(decision.response_delay_ms / 1000.0):
                return

        serial_port.write(decision.response)
        serial_port.flush()
        self._increment("transmitted_frames")
        self._emit(
            "tx",
            f"{decision.device_name}: {decision.description}",
            raw_hex=bytes_to_hex(decision.response),
            device_id=decision.device_id,
            address=decision.address,
            sensor_type=decision.sensor_type,
        )


class InMemorySerial:
    """Small deterministic serial double used by unit tests."""

    def __init__(self, incoming: bytes = b"") -> None:
        self.incoming = bytearray(incoming)
        self.outgoing = bytearray()
        self.closed = False

    def read(self, size: int) -> bytes:
        if not self.incoming:
            time.sleep(0.001)
            return b""
        result = bytes(self.incoming[:size])
        del self.incoming[:size]
        return result

    def write(self, data: bytes) -> int:
        self.outgoing.extend(data)
        return len(data)

    def flush(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True
