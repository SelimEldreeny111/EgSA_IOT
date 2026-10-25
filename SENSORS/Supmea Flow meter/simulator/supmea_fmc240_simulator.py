"""Tkinter Modbus RTU slave simulator for the Supmea SUP-FMC240 meter."""

from __future__ import annotations

import dataclasses
from datetime import datetime
import threading
import time
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk
from typing import Callable

from supmea_fmc240_protocol import (
    FLOW_UNIT_NAMES,
    Fmc240Values,
    advance_totalizers,
    bytes_to_hex,
    frame_has_valid_crc,
    handle_request,
    reset_totalizers,
)


EventCallback = Callable[[str, str], None]


@dataclasses.dataclass(frozen=True)
class SerialSettings:
    port: str
    baudrate: int
    parity: str
    slave_id: int
    response_delay_ms: int


class Fmc240SerialSlave:
    """Background serial worker; no Tk calls are made from this thread."""

    def __init__(
        self,
        settings: SerialSettings,
        values: Fmc240Values,
        on_event: EventCallback,
    ) -> None:
        self.settings = settings
        self._values = values
        self._values_lock = threading.Lock()
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
            name="fmc240-modbus-slave",
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

    def update_values(self, values: Fmc240Values) -> None:
        with self._values_lock:
            self._values = values

    def set_mute_responses(self, mute: bool) -> None:
        if mute:
            self._mute_responses.set()
        else:
            self._mute_responses.clear()

    def _values_snapshot(self) -> Fmc240Values:
        with self._values_lock:
            return self._values

    def _emit(self, level: str, message: str) -> None:
        self._on_event(level, message)

    def _open_serial(self):
        try:
            import serial
        except ImportError as exc:
            raise RuntimeError(
                "pyserial is not installed. Run: python -m pip install -r requirements.txt"
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
                f"slave {self.settings.slave_id}",
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

            while len(receive_buffer) >= 8:
                candidate = bytes(receive_buffer[:8])
                if not frame_has_valid_crc(candidate):
                    del receive_buffer[0]
                    continue

                del receive_buffer[:8]
                self._emit("rx", bytes_to_hex(candidate))
                decision = handle_request(
                    candidate,
                    self.settings.slave_id,
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


from supmea_reference import SupmeaReference
from supmea_fmc240_protocol import flow_rate_to_m3_per_hour


class SimulatorGui:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Supmea SUP-FMC240 RS485 Simulator")
        self.root.geometry("1050x800")
        self.root.minsize(900, 650)
        self.worker: Fmc240SerialSlave | None = None

        self.port_var = tk.StringVar(value="COM3")
        self.baud_var = tk.StringVar(value="9600")
        self.parity_var = tk.StringVar(value="N")
        self.slave_var = tk.StringVar(value="1")
        self.delay_var = tk.StringVar(value="20")
        self.mute_var = tk.BooleanVar(value=False)
        self.auto_totalizer_var = tk.BooleanVar(value=True)
        self.time_multiplier_var = tk.StringVar(value="1")
        self.status_var = tk.StringVar(value="Stopped")

        defaults = Fmc240Values()
        self.current_values = defaults
        self._last_totalizer_time = time.monotonic()
        self.reference = SupmeaReference()
        self.reference_zone = tk.StringVar(value="Africa/Cairo")
        self.reference_summary = tk.StringVar(value="Reference starts with first active totalizer tick.")
        self.value_vars = {
            "forward_total_m3": tk.StringVar(value=str(defaults.forward_total_m3)),
            "reverse_total_m3": tk.StringVar(value=str(defaults.reverse_total_m3)),
            "net_total_m3": tk.StringVar(value=str(defaults.net_total_m3)),
            "flow_rate": tk.StringVar(value=str(defaults.flow_rate)),
            "velocity_mps": tk.StringVar(value=str(defaults.velocity_mps)),
            "flow_ratio_percent": tk.StringVar(value=str(defaults.flow_ratio_percent)),
            "epd_percent": tk.StringVar(value=str(defaults.epd_percent)),
            "epd_alarm": tk.StringVar(value=str(defaults.epd_alarm)),
            "excitation_alarm": tk.StringVar(value=str(defaults.excitation_alarm)),
        }
        self.unit_var = tk.StringVar(value="3 - m3/h")

        self._build_ui()
        self._refresh_ports()
        self.root.after(1000, self._advance_totalizers)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=12)
        outer.pack(fill=tk.BOTH, expand=True)

        connection = ttk.LabelFrame(outer, text="RS485 / Modbus RTU", padding=10)
        connection.pack(fill=tk.X)
        for column in range(9):
            connection.columnconfigure(column, weight=1 if column in (1, 3, 5, 7) else 0)

        ttk.Label(connection, text="Port").grid(row=0, column=0, sticky=tk.W)
        self.port_combo = ttk.Combobox(
            connection, textvariable=self.port_var, width=14
        )
        self.port_combo.grid(row=0, column=1, sticky=tk.EW, padx=(5, 12))
        ttk.Button(connection, text="Refresh", command=self._refresh_ports).grid(
            row=0, column=2, padx=(0, 14)
        )
        ttk.Label(connection, text="Baud").grid(row=0, column=3, sticky=tk.W)
        ttk.Combobox(
            connection,
            textvariable=self.baud_var,
            values=("300", "600", "1200", "2400", "4800", "9600", "19200"),
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
        ttk.Entry(connection, textvariable=self.slave_var, width=6).grid(
            row=0, column=8, sticky=tk.EW, padx=(5, 0)
        )

        ttk.Label(connection, text="Response delay (ms)").grid(
            row=1, column=0, sticky=tk.W, pady=(10, 0)
        )
        ttk.Entry(connection, textvariable=self.delay_var, width=8).grid(
            row=1, column=1, sticky=tk.W, padx=(5, 12), pady=(10, 0)
        )
        ttk.Checkbutton(
            connection,
            text="Simulate timeout (receive but do not reply)",
            variable=self.mute_var,
            command=self._update_mute,
        ).grid(row=1, column=3, columnspan=4, sticky=tk.W, pady=(10, 0))
        self.start_button = ttk.Button(connection, text="Start", command=self._start)
        self.start_button.grid(row=1, column=7, sticky=tk.EW, pady=(10, 0))
        self.stop_button = ttk.Button(
            connection, text="Stop", command=self._stop, state=tk.DISABLED
        )
        self.stop_button.grid(row=1, column=8, sticky=tk.EW, padx=(5, 0), pady=(10, 0))

        values_frame = ttk.LabelFrame(
            outer, text="Simulated FMC240 measurements", padding=10
        )
        values_frame.pack(fill=tk.X, pady=(12, 0))
        for column in range(6):
            values_frame.columnconfigure(column, weight=1 if column in (1, 3, 5) else 0)

        fields = (
            ("Forward total (m3)", "forward_total_m3"),
            ("Reverse total (m3)", "reverse_total_m3"),
            ("Net total (m3)", "net_total_m3"),
            ("Flow rate", "flow_rate"),
            ("Velocity (m/s)", "velocity_mps"),
            ("Flow ratio (%)", "flow_ratio_percent"),
            ("EPD value (%)", "epd_percent"),
            ("EPD alarm", "epd_alarm"),
            ("Excitation alarm", "excitation_alarm"),
        )
        for index, (label, key) in enumerate(fields):
            row = index // 3
            pair = (index % 3) * 2
            ttk.Label(values_frame, text=label).grid(
                row=row, column=pair, sticky=tk.W, pady=4
            )
            ttk.Entry(values_frame, textvariable=self.value_vars[key], width=16).grid(
                row=row, column=pair + 1, sticky=tk.EW, padx=(6, 18), pady=4
            )

        ttk.Label(values_frame, text="Flow-rate unit").grid(
            row=3, column=0, sticky=tk.W, pady=(8, 0)
        )
        ttk.Combobox(
            values_frame,
            textvariable=self.unit_var,
            values=tuple(f"{index} - {name}" for index, name in enumerate(FLOW_UNIT_NAMES)),
            state="readonly",
            width=16,
        ).grid(row=3, column=1, sticky=tk.EW, padx=(6, 18), pady=(8, 0))
        ttk.Button(values_frame, text="Apply values", command=self._apply_values).grid(
            row=3, column=4, columnspan=2, sticky=tk.E, pady=(8, 0)
        )

        ttk.Checkbutton(
            values_frame,
            text="Advance cumulative totals from flow rate",
            variable=self.auto_totalizer_var,
            command=self._restart_totalizer_clock,
        ).grid(row=4, column=0, columnspan=2, sticky=tk.W, pady=(10, 0))
        ttk.Label(values_frame, text="Time acceleration").grid(
            row=4, column=2, sticky=tk.E, pady=(10, 0)
        )
        ttk.Combobox(
            values_frame,
            textvariable=self.time_multiplier_var,
            values=("1", "60", "3600"),
            state="readonly",
            width=9,
        ).grid(row=4, column=3, sticky=tk.W, padx=(6, 18), pady=(10, 0))
        ttk.Button(
            values_frame,
            text="Reset meter totals",
            command=self._reset_totalizers,
        ).grid(row=4, column=4, columnspan=2, sticky=tk.E, pady=(10, 0))

        ref = ttk.LabelFrame(outer, text="Independent RTC comparison — NOT sent on RS485", padding=8)
        ref.pack(fill=tk.X, pady=(8, 0))
        ttk.Combobox(ref, textvariable=self.reference_zone,
                     values=("Africa/Cairo", "UTC", "+02:00", "+03:00"), width=18).pack(side=tk.LEFT)
        ttk.Button(ref, text="Reset comparison only", command=self._reset_reference).pack(side=tk.LEFT, padx=8)
        ttk.Label(ref, textvariable=self.reference_summary, wraplength=600).pack(side=tk.LEFT)
        log_frame = ttk.LabelFrame(outer, text="Raw Modbus traffic", padding=8)
        log_frame.pack(fill=tk.BOTH, expand=True, pady=(12, 0))
        self.log = scrolledtext.ScrolledText(
            log_frame,
            height=18,
            wrap=tk.WORD,
            state=tk.DISABLED,
            font=("Consolas", 10),
        )
        self.log.pack(fill=tk.BOTH, expand=True)
        self.log.tag_configure("rx", foreground="#145DA0")
        self.log.tag_configure("tx", foreground="#0A7A36")
        self.log.tag_configure("error", foreground="#B00020")
        self.log.tag_configure("info", foreground="#555555")

        status_bar = ttk.Frame(outer)
        status_bar.pack(fill=tk.X, pady=(8, 0))
        ttk.Label(status_bar, text="Status:").pack(side=tk.LEFT)
        ttk.Label(status_bar, textvariable=self.status_var).pack(side=tk.LEFT, padx=(5, 0))
        ttk.Button(status_bar, text="Clear log", command=self._clear_log).pack(side=tk.RIGHT)

    def _refresh_ports(self) -> None:
        try:
            from serial.tools import list_ports

            ports = tuple(port.device for port in list_ports.comports())
        except ImportError:
            ports = ()
        self.port_combo["values"] = ports
        if ports and self.port_var.get() not in ports:
            self.port_var.set(ports[0])

    def _read_settings(self) -> SerialSettings:
        port = self.port_var.get().strip()
        if not port:
            raise ValueError("Select or enter a COM port")
        slave_id = int(self.slave_var.get())
        if not 1 <= slave_id <= 255:
            raise ValueError("Slave ID must be between 1 and 255")
        response_delay = int(self.delay_var.get())
        if not 0 <= response_delay <= 5000:
            raise ValueError("Response delay must be between 0 and 5000 ms")
        return SerialSettings(
            port=port,
            baudrate=int(self.baud_var.get()),
            parity=self.parity_var.get(),
            slave_id=slave_id,
            response_delay_ms=response_delay,
        )

    def _read_values(self) -> Fmc240Values:
        unit_code = int(self.unit_var.get().split("-", 1)[0].strip())
        return Fmc240Values(
            forward_total_m3=float(self.value_vars["forward_total_m3"].get()),
            reverse_total_m3=float(self.value_vars["reverse_total_m3"].get()),
            net_total_m3=float(self.value_vars["net_total_m3"].get()),
            flow_rate=float(self.value_vars["flow_rate"].get()),
            velocity_mps=float(self.value_vars["velocity_mps"].get()),
            flow_ratio_percent=float(self.value_vars["flow_ratio_percent"].get()),
            epd_percent=int(self.value_vars["epd_percent"].get()),
            flow_rate_unit=unit_code,
            epd_alarm=int(self.value_vars["epd_alarm"].get()),
            excitation_alarm=int(self.value_vars["excitation_alarm"].get()),
        )

    def _validated_values(self) -> Fmc240Values:
        values = self._read_values()
        # Build once to validate Float32 ranges, unit, and unsigned registers.
        from supmea_fmc240_protocol import build_register_map

        build_register_map(values)
        return values

    def _start(self) -> None:
        if self.worker is not None:
            return
        try:
            settings = self._read_settings()
            values = self._validated_values()
        except (TypeError, ValueError) as exc:
            messagebox.showerror("Invalid configuration", str(exc), parent=self.root)
            return

        self.worker = Fmc240SerialSlave(settings, values, self._thread_event)
        self.current_values = values
        self._set_totalizer_fields(values)
        self._restart_totalizer_clock()
        self._reset_reference()
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
        if self.worker is not None:
            self.worker.update_values(values)
        self.current_values = values
        self._set_totalizer_fields(values)
        self._restart_totalizer_clock()
        self._append_log("info", "Measurement values applied")

    def _set_totalizer_fields(self, values: Fmc240Values) -> None:
        self.value_vars["forward_total_m3"].set(f"{values.forward_total_m3:.6f}")
        self.value_vars["reverse_total_m3"].set(f"{values.reverse_total_m3:.6f}")
        self.value_vars["net_total_m3"].set(f"{values.net_total_m3:.6f}")

    def _restart_totalizer_clock(self) -> None:
        self._last_totalizer_time = time.monotonic()

    def _advance_totalizers(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_totalizer_time
        self._last_totalizer_time = now
        reference_flow = None
        elapsed_sim = elapsed
        if self.worker is not None and self.auto_totalizer_var.get():
            try:
                elapsed_sim = elapsed * float(self.time_multiplier_var.get())
                reference_flow = flow_rate_to_m3_per_hour(
                    self.current_values.flow_rate, self.current_values.flow_rate_unit)
                self.current_values = advance_totalizers(
                    self.current_values,
                    elapsed,
                    float(self.time_multiplier_var.get()),
                )
                self._set_totalizer_fields(self.current_values)
                self.worker.update_values(self.current_values)
            except ValueError as exc:
                reference_flow = None
                elapsed_sim = elapsed
                self.auto_totalizer_var.set(False)
                self._append_log("error", f"Automatic totalizer stopped: {exc}")
        try:
            self.reference.advance(elapsed_sim, reference_flow)
        except ValueError as exc:
            self.auto_totalizer_var.set(False)
            self._append_log("error", f"Reference clock stopped: {exc}")
        snapshot = self.reference.snapshot()
        self.reference_summary.set(
            f"Today {snapshot['today_m3']:.6f} | Month {snapshot['month_m3']:.6f} | "
            f"Year {snapshot['year_m3']:.6f} m³\n"
            f"{snapshot['clock_local']} — since session start; "
            f"{'integrating' if reference_flow is not None else 'paused'}")
        self.root.after(1000, self._advance_totalizers)

    def _reset_reference(self):
        try:
            self.reference = SupmeaReference(self.reference_zone.get().strip())
            self._restart_totalizer_clock()
            self.reference_summary.set("Comparison totals zeroed; meter registers are unchanged.")
        except ValueError as exc:
            messagebox.showerror("Reference timezone", str(exc), parent=self.root)

    def _reset_totalizers(self) -> None:
        self.current_values = reset_totalizers(self.current_values)
        self._set_totalizer_fields(self.current_values)
        if self.worker is not None:
            self.worker.update_values(self.current_values)
        self._restart_totalizer_clock()
        self._append_log("info", "Forward, reverse, and net totals reset to zero")

    def _update_mute(self) -> None:
        if self.worker is not None:
            self.worker.set_mute_responses(self.mute_var.get())

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
        prefix = {"rx": "RX", "tx": "TX", "error": "ERROR"}.get(level, "INFO")
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
