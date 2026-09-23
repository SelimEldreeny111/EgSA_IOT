"""Desktop Modbus RTU slave simulator for the TUF-2000M/TUF-2000B."""

from __future__ import annotations

import dataclasses
from datetime import datetime
import threading
import time
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk
from typing import Callable

from tuf2000b_protocol import (
    ERROR_BIT_NAMES,
    Tuf2000bValues,
    advance_period_totals,
    build_register_map,
    bytes_to_hex,
    frame_has_valid_crc,
    handle_request,
    reset_period_total,
)


EventCallback = Callable[[str, str], None]


@dataclasses.dataclass(frozen=True)
class SerialSettings:
    port: str
    baudrate: int
    parity: str
    slave_id: int
    response_delay_ms: int


class TufSerialSlave:
    """Background serial worker; it never calls Tk from its worker thread."""

    def __init__(
        self,
        settings: SerialSettings,
        values: Tuf2000bValues,
        on_event: EventCallback,
    ) -> None:
        self.settings = settings
        self._values = values
        self._values_lock = threading.Lock()
        self._slave_id = settings.slave_id
        self._slave_id_lock = threading.Lock()
        self._on_event = on_event
        self._stop_event = threading.Event()
        self._mute_responses = threading.Event()
        self._thread: threading.Thread | None = None
        self._serial = None

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("Simulator is already running")
        self._thread = threading.Thread(
            target=self._run,
            name="tuf2000b-modbus-slave",
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
            self._thread.join(timeout=2.0)
        self._thread = None

    def update_values(self, values: Tuf2000bValues) -> None:
        with self._values_lock:
            self._values = values

    def update_slave_id(self, slave_id: int) -> None:
        parsed = int(slave_id)
        if not 1 <= parsed <= 247:
            raise ValueError("Slave ID must be between 1 and 247")
        with self._slave_id_lock:
            self._slave_id = parsed

    def _slave_id_snapshot(self) -> int:
        with self._slave_id_lock:
            return self._slave_id

    def set_mute_responses(self, mute: bool) -> None:
        if mute:
            self._mute_responses.set()
        else:
            self._mute_responses.clear()

    def _values_snapshot(self) -> Tuf2000bValues:
        with self._values_lock:
            return self._values

    def _emit(self, level: str, message: str) -> None:
        self._on_event(level, message)

    def _open_serial(self):
        try:
            import serial
        except ImportError as exc:
            raise RuntimeError(
                "pyserial is not installed. Run: "
                "python -m pip install -r requirements.txt"
            ) from exc

        kwargs = dict(
            baudrate=self.settings.baudrate,
            bytesize=serial.EIGHTBITS,
            parity=self.settings.parity,
            stopbits=serial.STOPBITS_ONE,
            timeout=0.05,
            write_timeout=1.0,
        )
        if "://" in self.settings.port:
            return serial.serial_for_url(self.settings.port, **kwargs)
        return serial.Serial(port=self.settings.port, **kwargs)

    def _run(self) -> None:
        try:
            self._serial = self._open_serial()
            self._emit(
                "status",
                f"Listening on {self.settings.port} at "
                f"{self.settings.baudrate} 8{self.settings.parity}1, "
                f"slave {self._slave_id_snapshot()}",
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
            self._emit("stopped", "Simulator stopped")

    def _serve(self, serial_port) -> None:
        receive_buffer = bytearray()

        while not self._stop_event.is_set():
            chunk = serial_port.read(64)
            if chunk:
                receive_buffer.extend(chunk)

            # All read requests made by the node are eight-byte RTU frames.
            # Dropping one byte at a time on a CRC failure lets the parser
            # recover cleanly after noise or after starting mid-frame.
            while len(receive_buffer) >= 8:
                candidate = bytes(receive_buffer[:8])
                if not frame_has_valid_crc(candidate):
                    del receive_buffer[0]
                    continue

                del receive_buffer[:8]
                self._emit("rx", bytes_to_hex(candidate))
                decision = handle_request(
                    candidate,
                    self._slave_id_snapshot(),
                    self._values_snapshot(),
                )

                if decision.response is None:
                    self._emit("info", decision.description)
                    continue
                if self._mute_responses.is_set():
                    self._emit("info", f"response muted: {decision.description}")
                    continue

                if self.settings.response_delay_ms:
                    time.sleep(self.settings.response_delay_ms / 1000.0)
                serial_port.write(decision.response)
                serial_port.flush()
                self._emit("tx", bytes_to_hex(decision.response))
                self._emit("info", decision.description)


class SimulatorGui:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("TUF-2000B / TUF-2000M RS485 Simulator")
        self.root.geometry("1160x900")
        self.root.minsize(980, 720)
        self.worker: TufSerialSlave | None = None

        self.port_var = tk.StringVar(value="COM3")
        self.baud_var = tk.StringVar(value="9600")
        self.parity_var = tk.StringVar(value="N")
        self.slave_var = tk.StringVar(value="2")
        self.delay_var = tk.StringVar(value="20")
        self.mute_var = tk.BooleanVar(value=False)
        self.auto_totals_var = tk.BooleanVar(value=True)
        self.time_multiplier_var = tk.StringVar(value="1")
        self.status_var = tk.StringVar(value="Stopped")
        self.error_code_var = tk.StringVar(value="0x0000")

        defaults = Tuf2000bValues()
        self.current_values = defaults
        self._last_totalizer_time = time.monotonic()
        self.value_vars = {
            "flow_rate_m3h": tk.StringVar(value=str(defaults.flow_rate_m3h)),
            "energy_flow_rate_gjh": tk.StringVar(
                value=str(defaults.energy_flow_rate_gjh)
            ),
            "velocity_mps": tk.StringVar(value=str(defaults.velocity_mps)),
            "today_total_m3": tk.StringVar(value=str(defaults.today_total_m3)),
            "month_total_m3": tk.StringVar(value=str(defaults.month_total_m3)),
            "year_total_m3": tk.StringVar(value=str(defaults.year_total_m3)),
        }
        self.error_vars = [tk.BooleanVar(value=False) for _ in range(16)]

        self._build_ui()
        self._refresh_ports()
        self.root.after(500, self._advance_totals)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=12)
        outer.pack(fill=tk.BOTH, expand=True)

        connection = ttk.LabelFrame(outer, text="RS485 / Modbus RTU", padding=10)
        connection.pack(fill=tk.X)
        for column in range(9):
            connection.columnconfigure(
                column, weight=1 if column in (1, 4, 6, 8) else 0
            )

        ttk.Label(connection, text="Port").grid(row=0, column=0, sticky=tk.W)
        self.port_combo = ttk.Combobox(
            connection, textvariable=self.port_var, width=14
        )
        self.port_combo.grid(row=0, column=1, sticky=tk.EW, padx=(5, 8))
        ttk.Button(connection, text="Refresh", command=self._refresh_ports).grid(
            row=0, column=2, padx=(0, 14)
        )
        ttk.Label(connection, text="Baud").grid(row=0, column=3, sticky=tk.W)
        ttk.Combobox(
            connection,
            textvariable=self.baud_var,
            values=(
                "300",
                "600",
                "1200",
                "2400",
                "4800",
                "9600",
                "19200",
                "38400",
                "57600",
                "115200",
            ),
            state="readonly",
            width=9,
        ).grid(row=0, column=4, sticky=tk.EW, padx=(5, 12))
        ttk.Label(connection, text="Parity").grid(row=0, column=5, sticky=tk.W)
        ttk.Combobox(
            connection,
            textvariable=self.parity_var,
            values=("N", "E", "O"),
            state="readonly",
            width=5,
        ).grid(row=0, column=6, sticky=tk.EW, padx=(5, 12))
        ttk.Label(connection, text="Slave ID").grid(row=0, column=7, sticky=tk.W)
        slave_controls = ttk.Frame(connection)
        slave_controls.grid(row=0, column=8, sticky=tk.EW, padx=(5, 0))
        slave_controls.columnconfigure(0, weight=1)
        ttk.Entry(slave_controls, textvariable=self.slave_var, width=7).grid(
            row=0, column=0, sticky=tk.EW
        )
        ttk.Button(
            slave_controls, text="Apply", command=self._apply_slave_id
        ).grid(row=0, column=1, padx=(5, 0))

        ttk.Label(connection, text="Response delay (ms)").grid(
            row=1, column=0, sticky=tk.W, pady=(10, 0)
        )
        ttk.Entry(connection, textvariable=self.delay_var, width=8).grid(
            row=1, column=1, sticky=tk.W, padx=(5, 12), pady=(10, 0)
        )
        ttk.Checkbutton(
            connection,
            text="Simulate timeout (receive requests but do not reply)",
            variable=self.mute_var,
            command=self._update_mute,
        ).grid(row=1, column=3, columnspan=4, sticky=tk.W, pady=(10, 0))
        self.start_button = ttk.Button(connection, text="Start", command=self._start)
        self.start_button.grid(row=1, column=7, sticky=tk.EW, pady=(10, 0))
        self.stop_button = ttk.Button(
            connection, text="Stop", command=self._stop, state=tk.DISABLED
        )
        self.stop_button.grid(
            row=1, column=8, sticky=tk.EW, padx=(5, 0), pady=(10, 0)
        )

        values_frame = ttk.LabelFrame(
            outer, text="Simulated TUF measurements", padding=10
        )
        values_frame.pack(fill=tk.X, pady=(12, 0))
        for column in range(6):
            values_frame.columnconfigure(
                column, weight=1 if column in (1, 3, 5) else 0
            )

        fields = (
            ("Flow rate (m3/h)", "flow_rate_m3h"),
            ("Energy flow (GJ/h)", "energy_flow_rate_gjh"),
            ("Velocity (m/s)", "velocity_mps"),
            ("Flow today (m3)", "today_total_m3"),
            ("Flow this month (m3)", "month_total_m3"),
            ("Flow this year (m3)", "year_total_m3"),
        )
        for index, (label, key) in enumerate(fields):
            row = index // 3
            pair = (index % 3) * 2
            ttk.Label(values_frame, text=label).grid(
                row=row, column=pair, sticky=tk.W, pady=4
            )
            ttk.Entry(values_frame, textvariable=self.value_vars[key], width=16).grid(
                row=row,
                column=pair + 1,
                sticky=tk.EW,
                padx=(6, 18 if pair < 4 else 0),
                pady=4,
            )

        totals_controls = ttk.Frame(values_frame)
        totals_controls.grid(row=2, column=0, columnspan=6, sticky=tk.EW, pady=(8, 0))
        ttk.Checkbutton(
            totals_controls,
            text="Advance day/month/year totals from flow rate",
            variable=self.auto_totals_var,
            command=self._restart_totalizer_clock,
        ).pack(side=tk.LEFT)
        ttk.Label(totals_controls, text="Time speed").pack(side=tk.LEFT, padx=(18, 5))
        ttk.Combobox(
            totals_controls,
            textvariable=self.time_multiplier_var,
            values=("1", "60", "3600"),
            width=8,
        ).pack(side=tk.LEFT)
        ttk.Label(totals_controls, text="x").pack(side=tk.LEFT, padx=(3, 18))
        ttk.Button(
            totals_controls,
            text="Reset today",
            command=lambda: self._reset_total("today"),
        ).pack(side=tk.LEFT, padx=3)
        ttk.Button(
            totals_controls,
            text="Reset month",
            command=lambda: self._reset_total("month"),
        ).pack(side=tk.LEFT, padx=3)
        ttk.Button(
            totals_controls,
            text="Reset year",
            command=lambda: self._reset_total("year"),
        ).pack(side=tk.LEFT, padx=3)
        ttk.Button(
            totals_controls,
            text="Reset all",
            command=lambda: self._reset_total("all"),
        ).pack(side=tk.LEFT, padx=3)

        error_frame = ttk.LabelFrame(
            outer, text="TUF error register 0072 (zero-based address 0x0047)", padding=10
        )
        error_frame.pack(fill=tk.X, pady=(12, 0))
        for column in range(4):
            error_frame.columnconfigure(column, weight=1)

        for bit, name in enumerate(ERROR_BIT_NAMES):
            row = bit // 4
            column = bit % 4
            ttk.Checkbutton(
                error_frame,
                text=f"Bit {bit}: {name}",
                variable=self.error_vars[bit],
                command=self._update_error_code_label,
            ).grid(row=row, column=column, sticky=tk.W, padx=(0, 12), pady=2)

        error_controls = ttk.Frame(error_frame)
        error_controls.grid(row=4, column=0, columnspan=4, sticky=tk.EW, pady=(7, 0))
        ttk.Label(error_controls, text="Encoded value:").pack(side=tk.LEFT)
        ttk.Label(error_controls, textvariable=self.error_code_var).pack(
            side=tk.LEFT, padx=(5, 20)
        )
        ttk.Button(error_controls, text="Clear all errors", command=self._clear_errors).pack(
            side=tk.LEFT
        )
        ttk.Button(
            error_controls, text="Apply values", command=self._apply_values
        ).pack(side=tk.RIGHT)

        log_frame = ttk.LabelFrame(outer, text="Modbus traffic", padding=8)
        log_frame.pack(fill=tk.BOTH, expand=True, pady=(12, 0))
        log_toolbar = ttk.Frame(log_frame)
        log_toolbar.pack(fill=tk.X)
        ttk.Label(log_toolbar, textvariable=self.status_var).pack(side=tk.LEFT)
        ttk.Button(log_toolbar, text="Clear log", command=self._clear_log).pack(
            side=tk.RIGHT
        )
        self.log = scrolledtext.ScrolledText(
            log_frame,
            height=14,
            wrap=tk.NONE,
            font=("Consolas", 10),
            state=tk.DISABLED,
        )
        self.log.pack(fill=tk.BOTH, expand=True, pady=(7, 0))
        self.log.tag_configure("rx", foreground="#1f5fbf")
        self.log.tag_configure("tx", foreground="#16723a")
        self.log.tag_configure("error", foreground="#b00020")
        self.log.tag_configure("info", foreground="#444444")
        self.log.tag_configure("status", foreground="#5d3a9b")
        self.log.tag_configure("stopped", foreground="#666666")

    def _refresh_ports(self) -> None:
        try:
            from serial.tools import list_ports

            ports = [port.device for port in list_ports.comports()]
        except Exception:
            ports = []
        self.port_combo.configure(values=ports)
        if ports and self.port_var.get() == "COM3" and "COM3" not in ports:
            self.port_var.set(ports[0])

    def _validated_serial_settings(self) -> SerialSettings:
        port = self.port_var.get().strip()
        if not port:
            raise ValueError("Select or enter a serial port")
        baudrate = int(self.baud_var.get())
        if not 75 <= baudrate <= 115200:
            raise ValueError("Baud rate must be between 75 and 115200")
        parity = self.parity_var.get().strip().upper()
        if parity not in ("N", "E", "O"):
            raise ValueError("Parity must be N, E, or O")
        slave_id = int(self.slave_var.get())
        if not 1 <= slave_id <= 247:
            raise ValueError("Slave ID must be between 1 and 247")
        response_delay_ms = int(self.delay_var.get())
        if not 0 <= response_delay_ms <= 10000:
            raise ValueError("Response delay must be between 0 and 10000 ms")
        return SerialSettings(
            port=port,
            baudrate=baudrate,
            parity=parity,
            slave_id=slave_id,
            response_delay_ms=response_delay_ms,
        )

    def _error_code_from_ui(self) -> int:
        result = 0
        for bit, variable in enumerate(self.error_vars):
            if variable.get():
                result |= 1 << bit
        return result

    def _validated_values(self) -> Tuf2000bValues:
        values = Tuf2000bValues(
            flow_rate_m3h=float(self.value_vars["flow_rate_m3h"].get()),
            energy_flow_rate_gjh=float(
                self.value_vars["energy_flow_rate_gjh"].get()
            ),
            velocity_mps=float(self.value_vars["velocity_mps"].get()),
            today_total_m3=float(self.value_vars["today_total_m3"].get()),
            month_total_m3=float(self.value_vars["month_total_m3"].get()),
            year_total_m3=float(self.value_vars["year_total_m3"].get()),
            error_code=self._error_code_from_ui(),
        )
        build_register_map(values)
        return values

    def _start(self) -> None:
        if self.worker is not None:
            return
        try:
            settings = self._validated_serial_settings()
            values = self._validated_values()
        except (TypeError, ValueError) as exc:
            messagebox.showerror("Invalid configuration", str(exc), parent=self.root)
            return

        self.worker = TufSerialSlave(settings, values, self._thread_event)
        self.current_values = values
        self._set_total_fields(values)
        self._restart_totalizer_clock()
        self.worker.set_mute_responses(self.mute_var.get())
        self.worker.start()
        self.start_button.configure(state=tk.DISABLED)
        self.stop_button.configure(state=tk.NORMAL)
        self.status_var.set("Starting...")

    def _stop(self) -> None:
        worker = self.worker
        self.worker = None
        if worker is not None:
            worker.stop()
        self.start_button.configure(state=tk.NORMAL)
        self.stop_button.configure(state=tk.DISABLED)
        self.status_var.set("Stopped")

    def _apply_values(self) -> None:
        try:
            values = self._validated_values()
        except (TypeError, ValueError) as exc:
            messagebox.showerror("Invalid measurement", str(exc), parent=self.root)
            return
        self.current_values = values
        if self.worker is not None:
            self.worker.update_values(values)
        self._set_total_fields(values)
        self._restart_totalizer_clock()
        self._append_log(
            "info", f"Measurement values applied; error code 0x{values.error_code:04X}"
        )

    def _apply_slave_id(self) -> None:
        try:
            slave_id = int(self.slave_var.get())
            if not 1 <= slave_id <= 247:
                raise ValueError("Slave ID must be between 1 and 247")
            if self.worker is not None:
                self.worker.update_slave_id(slave_id)
        except (TypeError, ValueError) as exc:
            messagebox.showerror("Invalid slave address", str(exc), parent=self.root)
            return
        state = "immediately" if self.worker is not None else "on next start"
        self._append_log("info", f"Modbus slave address set to {slave_id} ({state})")

    def _set_total_fields(self, values: Tuf2000bValues) -> None:
        self.value_vars["today_total_m3"].set(f"{values.today_total_m3:.6f}")
        self.value_vars["month_total_m3"].set(f"{values.month_total_m3:.6f}")
        self.value_vars["year_total_m3"].set(f"{values.year_total_m3:.6f}")

    def _restart_totalizer_clock(self) -> None:
        self._last_totalizer_time = time.monotonic()

    def _advance_totals(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_totalizer_time
        self._last_totalizer_time = now
        if self.worker is not None and self.auto_totals_var.get():
            try:
                self.current_values = advance_period_totals(
                    self.current_values,
                    elapsed,
                    float(self.time_multiplier_var.get()),
                )
                self._set_total_fields(self.current_values)
                self.worker.update_values(self.current_values)
            except ValueError as exc:
                self.auto_totals_var.set(False)
                self._append_log("error", f"Automatic totals stopped: {exc}")
        self.root.after(500, self._advance_totals)

    def _reset_total(self, period: str) -> None:
        try:
            base_values = self._validated_values()
            self.current_values = reset_period_total(base_values, period)
        except (TypeError, ValueError) as exc:
            messagebox.showerror("Invalid measurement", str(exc), parent=self.root)
            return
        self._set_total_fields(self.current_values)
        if self.worker is not None:
            self.worker.update_values(self.current_values)
        self._restart_totalizer_clock()
        self._append_log("info", f"{period.capitalize()} total reset")

    def _update_mute(self) -> None:
        if self.worker is not None:
            self.worker.set_mute_responses(self.mute_var.get())

    def _update_error_code_label(self) -> None:
        self.error_code_var.set(f"0x{self._error_code_from_ui():04X}")

    def _clear_errors(self) -> None:
        for variable in self.error_vars:
            variable.set(False)
        self._update_error_code_label()

    def _thread_event(self, level: str, message: str) -> None:
        self.root.after(0, self._handle_event, level, message)

    def _handle_event(self, level: str, message: str) -> None:
        if level == "status":
            self.status_var.set(message)
        elif level == "error":
            self.status_var.set(f"Error: {message}")
            self.start_button.configure(state=tk.NORMAL)
            self.stop_button.configure(state=tk.DISABLED)
            self.worker = None
        elif level == "stopped" and self.worker is not None:
            self.status_var.set(message)
            self.start_button.configure(state=tk.NORMAL)
            self.stop_button.configure(state=tk.DISABLED)
            self.worker = None
        self._append_log(level, message)

    def _append_log(self, level: str, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        prefix = {"rx": "RX", "tx": "TX", "error": "ERROR"}.get(
            level, "INFO"
        )
        self.log.configure(state=tk.NORMAL)
        self.log.insert(tk.END, f"{timestamp}  {prefix:<5} {message}\n", level)
        self.log.see(tk.END)
        self.log.configure(state=tk.DISABLED)

    def _clear_log(self) -> None:
        self.log.configure(state=tk.NORMAL)
        self.log.delete("1.0", tk.END)
        self.log.configure(state=tk.DISABLED)

    def _on_close(self) -> None:
        self._stop()
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    try:
        ttk.Style(root).theme_use("vista")
    except tk.TclError:
        pass
    SimulatorGui(root)
    root.mainloop()


if __name__ == "__main__":
    main()
