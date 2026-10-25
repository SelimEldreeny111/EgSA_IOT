"""Professional desktop GUI for a multi-device WIOT Modbus RTU bus."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import queue
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk
import uuid
from typing import Any, Callable, Mapping, Sequence

from multi_sensor_bus import BusEvent, MultiSensorSerialSlave
from multi_sensor_core import (
    BusSettings,
    FaultProfile,
    FLOW_UNIT_NAMES,
    REGISTER_REFERENCE,
    SIGNAL_DEFINITIONS,
    SensorDevice,
    SensorRegistry,
    SensorType,
    SignalMode,
    SignalProfile,
    configuration_to_dict,
    create_default_devices,
    create_device,
    load_configuration,
    parse_address_spec,
    save_configuration,
    signal_definition_map,
)


APP_TITLE = "WIOT Multi-Sensor RS485 Lab"

COLORS = {
    "navy": "#102A43",
    "navy_2": "#173F5F",
    "teal": "#00A896",
    "teal_dark": "#00897B",
    "blue": "#2F80ED",
    "sky": "#EAF4FF",
    "background": "#F4F7FB",
    "card": "#FFFFFF",
    "border": "#D8E2EC",
    "text": "#243B53",
    "muted": "#627D98",
    "success": "#1F9D55",
    "warning": "#D97706",
    "danger": "#D64545",
    "disabled": "#9FB3C8",
    "log_bg": "#0D1B2A",
    "log_text": "#D9E2EC",
}


def default_configuration_paths() -> list[Path]:
    """Return editable and bundled default locations in priority order."""

    if getattr(sys, "frozen", False):
        paths = [Path(sys.executable).resolve().parent / "default_config.json"]
        frozen_root = getattr(sys, "_MEIPASS", None)
        if frozen_root:
            paths.append(Path(frozen_root) / "default_config.json")
        return paths
    return [Path(__file__).resolve().parent / "default_config.json"]


def format_number(value: float, integer: bool = False) -> str:
    if integer:
        return str(int(round(value)))
    magnitude = abs(value)
    if magnitude >= 1_000_000:
        return f"{value:,.1f}"
    if magnitude >= 1000:
        return f"{value:,.2f}"
    return f"{value:.3f}".rstrip("0").rstrip(".")


class DeviceEditorDialog(tk.Toplevel):
    """Create or edit one sensor, including every generated signal."""

    def __init__(
        self,
        parent: tk.Misc,
        device: SensorDevice | None,
        address_is_available: Callable[[int, str | None], bool],
        default_address: int = 1,
    ) -> None:
        super().__init__(parent)
        self.title("Edit virtual sensor" if device else "Add virtual sensor")
        self.geometry("1120x790")
        self.minsize(940, 650)
        self.transient(parent)
        self.grab_set()
        self.result: SensorDevice | None = None
        self._editing = device is not None
        self._original_id = device.device_id if device else None
        self._address_is_available = address_is_available
        self._source_device = device or create_device(
            SensorType.HNDA, default_address
        )
        self.signal_vars: dict[str, dict[str, tk.Variable]] = {}

        source = self._source_device
        self.type_var = tk.StringVar(value=source.sensor_type.value)
        self.name_var = tk.StringVar(value=source.name)
        self.address_var = tk.StringVar(value=str(source.address))
        self.enabled_var = tk.BooleanVar(value=source.enabled)
        self.muted_var = tk.BooleanVar(value=source.muted)
        self.update_interval_var = tk.StringVar(value=str(source.update_interval_s))
        self.auto_totalizers_var = tk.BooleanVar(value=source.auto_totalizers)
        self.time_multiplier_var = tk.StringVar(value=str(source.time_multiplier))
        self.seed_var = tk.StringVar(value=str(source.random_seed))
        self._reference_timezone = source.reference_timezone
        self.extra_delay_var = tk.StringVar(value=str(source.faults.extra_delay_ms))
        self.drop_var = tk.StringVar(value=str(source.faults.drop_percent))
        self.crc_error_var = tk.StringVar(value=str(source.faults.crc_error_percent))
        self.exception_var = tk.StringVar(
            value={
                0: "0 - Normal response",
                1: "1 - Illegal function",
                2: "2 - Illegal address",
                3: "3 - Illegal value",
                4: "4 - Device failure",
            }[source.faults.forced_exception]
        )

        self._build_ui()
        self._populate_signal_rows(source.sensor_type, source.signals)
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.after(50, lambda: self.name_entry.focus_set())

    def _build_ui(self) -> None:
        container = ttk.Frame(self, padding=16)
        container.pack(fill=tk.BOTH, expand=True)

        title = ttk.Label(
            container,
            text="Virtual sensor configuration",
            style="DialogTitle.TLabel",
        )
        title.pack(anchor=tk.W)
        ttk.Label(
            container,
            text=(
                "Each measurement can be fixed or generated independently. "
                "Addresses must be unique on the shared RTU bus."
            ),
            style="Muted.TLabel",
        ).pack(anchor=tk.W, pady=(2, 12))

        notebook = ttk.Notebook(container)
        notebook.pack(fill=tk.BOTH, expand=True)
        general_tab = ttk.Frame(notebook, padding=14)
        signals_tab = ttk.Frame(notebook, padding=8)
        notebook.add(general_tab, text="General & faults")
        notebook.add(signals_tab, text="Measurement profiles")

        identity = ttk.LabelFrame(general_tab, text="Identity", padding=12)
        identity.pack(fill=tk.X, pady=(0, 10))
        for col in (1, 3):
            identity.columnconfigure(col, weight=1)
        ttk.Label(identity, text="Sensor type").grid(row=0, column=0, sticky=tk.W)
        type_combo = ttk.Combobox(
            identity,
            textvariable=self.type_var,
            values=tuple(item.value for item in SensorType),
            state="disabled" if self._editing else "readonly",
            width=18,
        )
        type_combo.grid(row=0, column=1, sticky=tk.EW, padx=(8, 24))
        type_combo.bind("<<ComboboxSelected>>", self._on_type_changed)
        ttk.Label(identity, text="Modbus address").grid(
            row=0, column=2, sticky=tk.W
        )
        ttk.Entry(identity, textvariable=self.address_var, width=12).grid(
            row=0, column=3, sticky=tk.W, padx=(8, 0)
        )
        ttk.Label(identity, text="Device name").grid(
            row=1, column=0, sticky=tk.W, pady=(10, 0)
        )
        self.name_entry = ttk.Entry(identity, textvariable=self.name_var)
        self.name_entry.grid(
            row=1, column=1, columnspan=3, sticky=tk.EW, padx=(8, 0), pady=(10, 0)
        )
        ttk.Checkbutton(identity, text="Enabled", variable=self.enabled_var).grid(
            row=2, column=0, sticky=tk.W, pady=(10, 0)
        )
        ttk.Checkbutton(
            identity, text="Mute responses (timeout test)", variable=self.muted_var
        ).grid(row=2, column=1, columnspan=2, sticky=tk.W, pady=(10, 0))

        behavior = ttk.LabelFrame(
            general_tab, text="Simulation timing", padding=12
        )
        behavior.pack(fill=tk.X, pady=(0, 10))
        for col in (1, 3, 5):
            behavior.columnconfigure(col, weight=1)
        ttk.Label(behavior, text="Update interval (s)").grid(
            row=0, column=0, sticky=tk.W
        )
        ttk.Entry(behavior, textvariable=self.update_interval_var, width=12).grid(
            row=0, column=1, sticky=tk.EW, padx=(8, 18)
        )
        ttk.Label(behavior, text="Time multiplier").grid(
            row=0, column=2, sticky=tk.W
        )
        ttk.Entry(behavior, textvariable=self.time_multiplier_var, width=12).grid(
            row=0, column=3, sticky=tk.EW, padx=(8, 18)
        )
        ttk.Label(behavior, text="Random seed").grid(
            row=0, column=4, sticky=tk.W
        )
        ttk.Entry(behavior, textvariable=self.seed_var, width=12).grid(
            row=0, column=5, sticky=tk.EW, padx=(8, 0)
        )
        ttk.Checkbutton(
            behavior,
            text="Automatically integrate flow into cumulative totalizers",
            variable=self.auto_totalizers_var,
        ).grid(row=1, column=0, columnspan=6, sticky=tk.W, pady=(10, 0))

        faults = ttk.LabelFrame(
            general_tab, text="Fault injection (optional)", padding=12
        )
        faults.pack(fill=tk.X)
        for col in (1, 3):
            faults.columnconfigure(col, weight=1)
        ttk.Label(faults, text="Extra response delay (ms)").grid(
            row=0, column=0, sticky=tk.W
        )
        ttk.Entry(faults, textvariable=self.extra_delay_var).grid(
            row=0, column=1, sticky=tk.EW, padx=(8, 24)
        )
        ttk.Label(faults, text="Drop response (%)").grid(
            row=0, column=2, sticky=tk.W
        )
        ttk.Entry(faults, textvariable=self.drop_var).grid(
            row=0, column=3, sticky=tk.EW, padx=(8, 0)
        )
        ttk.Label(faults, text="Corrupt response CRC (%)").grid(
            row=1, column=0, sticky=tk.W, pady=(10, 0)
        )
        ttk.Entry(faults, textvariable=self.crc_error_var).grid(
            row=1, column=1, sticky=tk.EW, padx=(8, 24), pady=(10, 0)
        )
        ttk.Label(faults, text="Force Modbus exception").grid(
            row=1, column=2, sticky=tk.W, pady=(10, 0)
        )
        ttk.Combobox(
            faults,
            textvariable=self.exception_var,
            state="readonly",
            values=(
                "0 - Normal response",
                "1 - Illegal function",
                "2 - Illegal address",
                "3 - Illegal value",
                "4 - Device failure",
            ),
        ).grid(row=1, column=3, sticky=tk.EW, padx=(8, 0), pady=(10, 0))

        self.signal_canvas = tk.Canvas(
            signals_tab,
            highlightthickness=0,
            background=COLORS["card"],
        )
        signal_scrollbar = ttk.Scrollbar(
            signals_tab, orient=tk.VERTICAL, command=self.signal_canvas.yview
        )
        self.signal_canvas.configure(yscrollcommand=signal_scrollbar.set)
        signal_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.signal_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.signal_frame = ttk.Frame(self.signal_canvas)
        self.signal_window = self.signal_canvas.create_window(
            (0, 0), window=self.signal_frame, anchor=tk.NW
        )
        self.signal_frame.bind(
            "<Configure>",
            lambda _event: self.signal_canvas.configure(
                scrollregion=self.signal_canvas.bbox("all")
            ),
        )
        self.signal_canvas.bind(
            "<Configure>",
            lambda event: self.signal_canvas.itemconfigure(
                self.signal_window, width=event.width
            ),
        )

        actions = ttk.Frame(container)
        actions.pack(fill=tk.X, pady=(14, 0))
        ttk.Button(actions, text="Cancel", command=self.destroy).pack(
            side=tk.RIGHT
        )
        ttk.Button(
            actions,
            text="Save sensor",
            style="Accent.TButton",
            command=self._save,
        ).pack(side=tk.RIGHT, padx=(0, 8))

    def _on_type_changed(self, _event: tk.Event | None = None) -> None:
        sensor_type = SensorType(self.type_var.get())
        generated = create_device(sensor_type, int(self.address_var.get() or 1))
        if not self.name_var.get().strip() or self.name_var.get().startswith(
            tuple(item.value for item in SensorType)
        ):
            self.name_var.set(f"{sensor_type.value}-{int(self.address_var.get() or 1):03d}")
        self.auto_totalizers_var.set(generated.auto_totalizers)
        self._populate_signal_rows(sensor_type, generated.signals)

    def _populate_signal_rows(
        self,
        sensor_type: SensorType,
        profiles: Mapping[str, SignalProfile],
    ) -> None:
        for child in self.signal_frame.winfo_children():
            child.destroy()
        self.signal_vars.clear()

        headings = (
            "Measurement",
            "Unit",
            "Mode",
            "Initial / fixed",
            "Minimum",
            "Maximum",
            "Step / amplitude",
            "Period (s)",
        )
        for column, heading in enumerate(headings):
            ttk.Label(
                self.signal_frame, text=heading, style="TableHeader.TLabel"
            ).grid(row=0, column=column, sticky=tk.EW, padx=4, pady=(2, 8))
            self.signal_frame.columnconfigure(column, weight=2 if column == 0 else 1)

        definitions = SIGNAL_DEFINITIONS[sensor_type]
        for row, definition in enumerate(definitions, start=1):
            profile = profiles[definition.key]
            variables: dict[str, tk.Variable] = {
                "mode": tk.StringVar(value=profile.mode.value),
                # Editable numbers must round-trip through float(); display-only
                # thousands separators such as 1,250.75 are invalid input.
                "value": tk.StringVar(value=str(profile.value)),
                "minimum": tk.StringVar(
                    value=str(profile.minimum)
                ),
                "maximum": tk.StringVar(
                    value=str(profile.maximum)
                ),
                "step": tk.StringVar(value=str(profile.step)),
                "period_s": tk.StringVar(value=str(profile.period_s)),
            }
            self.signal_vars[definition.key] = variables
            ttk.Label(self.signal_frame, text=definition.label).grid(
                row=row, column=0, sticky=tk.W, padx=4, pady=3
            )
            ttk.Label(
                self.signal_frame, text=definition.unit, style="Muted.TLabel"
            ).grid(row=row, column=1, sticky=tk.W, padx=4, pady=3)
            ttk.Combobox(
                self.signal_frame,
                textvariable=variables["mode"],
                state="readonly",
                values=tuple(mode.value for mode in SignalMode),
                width=14,
            ).grid(row=row, column=2, sticky=tk.EW, padx=4, pady=3)
            for column, key in enumerate(
                ("value", "minimum", "maximum", "step", "period_s"), start=3
            ):
                ttk.Entry(
                    self.signal_frame,
                    textvariable=variables[key],
                    width=13,
                ).grid(row=row, column=column, sticky=tk.EW, padx=4, pady=3)

        ttk.Label(
            self.signal_frame,
            text=(
                "Sine: Initial is the center and Step is amplitude.  Random walk "
                "and ramp use Step per update.  Step mode alternates Minimum/Maximum."
            ),
            style="Muted.TLabel",
            wraplength=850,
        ).grid(
            row=len(definitions) + 1,
            column=0,
            columnspan=8,
            sticky=tk.W,
            padx=4,
            pady=(12, 4),
        )

    def _save(self) -> None:
        try:
            sensor_type = SensorType(self.type_var.get())
            address = int(self.address_var.get())
            if not 1 <= address <= 247:
                raise ValueError("Modbus address must be between 1 and 247")
            if not self._address_is_available(address, self._original_id):
                raise ValueError(f"Modbus address {address} is already in use")
            definitions = signal_definition_map(sensor_type)
            profiles: dict[str, SignalProfile] = {}
            for key, definition in definitions.items():
                variables = self.signal_vars[key]
                profile = SignalProfile(
                    mode=SignalMode(str(variables["mode"].get())),
                    value=float(variables["value"].get()),
                    minimum=float(variables["minimum"].get()),
                    maximum=float(variables["maximum"].get()),
                    step=float(variables["step"].get()),
                    period_s=float(variables["period_s"].get()),
                )
                profile.validate(definition)
                profiles[key] = profile

            faults = FaultProfile(
                extra_delay_ms=int(self.extra_delay_var.get()),
                drop_percent=float(self.drop_var.get()),
                crc_error_percent=float(self.crc_error_var.get()),
                forced_exception=int(self.exception_var.get().split(" ", 1)[0]),
            )
            faults.validate()
            self.result = SensorDevice(
                sensor_type=sensor_type,
                address=address,
                name=self.name_var.get().strip(),
                enabled=self.enabled_var.get(),
                muted=self.muted_var.get(),
                update_interval_s=float(self.update_interval_var.get()),
                auto_totalizers=self.auto_totalizers_var.get(),
                time_multiplier=float(self.time_multiplier_var.get()),
                random_seed=int(self.seed_var.get()),
                reference_timezone=self._reference_timezone,
                signals=profiles,
                faults=faults,
                device_id=self._original_id or uuid.uuid4().hex,
            )
        except (TypeError, ValueError) as exc:
            messagebox.showerror("Invalid sensor configuration", str(exc), parent=self)
            return
        self.destroy()


class BatchAddDialog(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        occupied_addresses: set[int],
    ) -> None:
        super().__init__(parent)
        self.title("Add a sensor fleet")
        self.geometry("620x470")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self.result: list[SensorDevice] | None = None
        self.occupied_addresses = occupied_addresses

        self.type_var = tk.StringVar(value=SensorType.HNDA.value)
        self.quantity_var = tk.StringVar(value="2")
        self.start_address_var = tk.StringVar(value="1")
        self.explicit_var = tk.StringVar(value="")
        self.prefix_var = tk.StringVar(value="HNDA field node")
        self.mode_var = tk.StringVar(value=SignalMode.RANDOM_WALK.value)
        self.enabled_var = tk.BooleanVar(value=True)
        self.summary_var = tk.StringVar(value="Addresses: 1, 2")

        self._build_ui()
        for variable in (
            self.quantity_var,
            self.start_address_var,
            self.explicit_var,
        ):
            variable.trace_add("write", lambda *_args: self._update_summary())
        self.type_var.trace_add("write", self._on_type_change)

    def _build_ui(self) -> None:
        frame = ttk.Frame(self, padding=18)
        frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frame, text="Create multiple devices", style="DialogTitle.TLabel").grid(
            row=0, column=0, columnspan=2, sticky=tk.W
        )
        ttk.Label(
            frame,
            text="Use sequential addresses or an explicit list such as 1,2,10-15.",
            style="Muted.TLabel",
        ).grid(row=1, column=0, columnspan=2, sticky=tk.W, pady=(2, 16))
        frame.columnconfigure(1, weight=1)

        labels = (
            ("Sensor type", self.type_var),
            ("Quantity", self.quantity_var),
            ("Start address", self.start_address_var),
            ("Explicit addresses (optional)", self.explicit_var),
            ("Name prefix", self.prefix_var),
            ("Initial signal mode", self.mode_var),
        )
        for row, (label, variable) in enumerate(labels, start=2):
            ttk.Label(frame, text=label).grid(
                row=row, column=0, sticky=tk.W, pady=7
            )
            if variable is self.type_var:
                widget = ttk.Combobox(
                    frame,
                    textvariable=variable,
                    values=tuple(item.value for item in SensorType),
                    state="readonly",
                )
            elif variable is self.mode_var:
                widget = ttk.Combobox(
                    frame,
                    textvariable=variable,
                    values=tuple(item.value for item in SignalMode),
                    state="readonly",
                )
            else:
                widget = ttk.Entry(frame, textvariable=variable)
            widget.grid(row=row, column=1, sticky=tk.EW, padx=(14, 0), pady=7)

        ttk.Checkbutton(frame, text="Create enabled", variable=self.enabled_var).grid(
            row=8, column=0, columnspan=2, sticky=tk.W, pady=(8, 4)
        )
        ttk.Label(frame, textvariable=self.summary_var, style="Info.TLabel").grid(
            row=9, column=0, columnspan=2, sticky=tk.EW, pady=(8, 16)
        )
        actions = ttk.Frame(frame)
        actions.grid(row=10, column=0, columnspan=2, sticky=tk.EW)
        ttk.Button(actions, text="Cancel", command=self.destroy).pack(side=tk.RIGHT)
        ttk.Button(
            actions,
            text="Create fleet",
            style="Accent.TButton",
            command=self._save,
        ).pack(side=tk.RIGHT, padx=(0, 8))

    def _on_type_change(self, *_args: object) -> None:
        self.prefix_var.set(f"{self.type_var.get()} field node")

    def _addresses(self) -> list[int]:
        explicit = self.explicit_var.get().strip()
        quantity = int(self.quantity_var.get())
        if not 1 <= quantity <= 247:
            raise ValueError("Quantity must be between 1 and 247")
        if explicit:
            addresses = parse_address_spec(explicit)
            if len(addresses) != quantity:
                raise ValueError(
                    f"Quantity is {quantity}, but the explicit list contains "
                    f"{len(addresses)} addresses"
                )
            return addresses
        start = int(self.start_address_var.get())
        addresses = list(range(start, start + quantity))
        if not addresses or addresses[-1] > 247 or addresses[0] < 1:
            raise ValueError("Generated addresses must remain inside 1..247")
        return addresses

    def _update_summary(self) -> None:
        try:
            addresses = self._addresses()
            self.summary_var.set(
                "Addresses: " + ", ".join(str(address) for address in addresses)
            )
        except (TypeError, ValueError):
            self.summary_var.set("Enter a valid quantity and address selection")

    def _save(self) -> None:
        try:
            addresses = self._addresses()
            collisions = sorted(set(addresses) & self.occupied_addresses)
            if collisions:
                raise ValueError(
                    "Already occupied address(es): "
                    + ", ".join(str(item) for item in collisions)
                )
            sensor_type = SensorType(self.type_var.get())
            mode = SignalMode(self.mode_var.get())
            prefix = self.prefix_var.get().strip()
            if not prefix:
                raise ValueError("Name prefix cannot be empty")
            devices = []
            for index, address in enumerate(addresses, start=1):
                device = create_device(
                    sensor_type,
                    address,
                    name=f"{prefix} {index}",
                    mode=mode,
                    seed=address * 1009 + index,
                )
                device.enabled = self.enabled_var.get()
                devices.append(device)
            self.result = devices
        except (TypeError, ValueError) as exc:
            messagebox.showerror("Invalid fleet configuration", str(exc), parent=self)
            return
        self.destroy()


class MultiSensorSimulatorApp:
    def __init__(self, root: tk.Tk, initial_config: Path | None = None) -> None:
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("1500x920")
        self.root.minsize(1180, 720)
        self._configure_style()

        self.event_queue: queue.Queue[BusEvent] = queue.Queue()
        self.worker: MultiSensorSerialSlave | None = None
        self._last_counters: dict[str, int] = {
            "received_frames": 0,
            "transmitted_frames": 0,
            "ignored_frames": 0,
            "exception_frames": 0,
            "dropped_frames": 0,
            "crc_or_noise_bytes": 0,
        }
        self.current_config_path: Path | None = None
        self.dirty = False

        self.bus_settings, devices = self._load_startup_configuration(initial_config)
        self.registry = SensorRegistry(devices)

        self.port_var = tk.StringVar(value=self.bus_settings.port)
        self.baud_var = tk.StringVar(value=str(self.bus_settings.baudrate))
        self.parity_var = tk.StringVar(value=self.bus_settings.parity)
        self.stopbits_var = tk.StringVar(value=str(self.bus_settings.stopbits))
        self.delay_var = tk.StringVar(value=str(self.bus_settings.response_delay_ms))
        self.status_var = tk.StringVar(value="STOPPED")
        self.config_var = tk.StringVar(value=self._config_display_name())
        self.selected_title_var = tk.StringVar(value="Select a device")
        self.selected_subtitle_var = tk.StringVar(
            value="Live values, signal modes, and request statistics appear here."
        )
        self.log_filter_var = tk.StringVar(value="All events")
        self.autoscroll_var = tk.BooleanVar(value=True)
        self.count_vars = {
            sensor_type: tk.StringVar(value="0") for sensor_type in SensorType
        }
        self.counter_vars = {
            "received_frames": tk.StringVar(value="0 RX"),
            "transmitted_frames": tk.StringVar(value="0 TX"),
            "exception_frames": tk.StringVar(value="0 exceptions"),
            "dropped_frames": tk.StringVar(value="0 dropped"),
        }

        self._build_ui()
        self._refresh_ports()
        self._refresh_all_views(force=True)
        self.root.after(100, self._drain_events)
        self.root.after(200, self._simulation_tick)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _configure_style(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(".", font=("Segoe UI", 10), foreground=COLORS["text"])
        style.configure("TFrame", background=COLORS["background"])
        style.configure("Card.TFrame", background=COLORS["card"])
        style.configure("TLabel", background=COLORS["background"])
        style.configure("Card.TLabel", background=COLORS["card"])
        style.configure(
            "Title.TLabel",
            background=COLORS["navy"],
            foreground="white",
            font=("Segoe UI Semibold", 20),
        )
        style.configure(
            "HeaderSub.TLabel",
            background=COLORS["navy"],
            foreground="#BFD7EA",
            font=("Segoe UI", 10),
        )
        style.configure(
            "DialogTitle.TLabel", font=("Segoe UI Semibold", 16)
        )
        style.configure("Muted.TLabel", foreground=COLORS["muted"])
        style.configure(
            "Info.TLabel",
            background=COLORS["sky"],
            foreground=COLORS["navy_2"],
            padding=8,
        )
        style.configure(
            "TableHeader.TLabel", font=("Segoe UI Semibold", 9)
        )
        style.configure(
            "Accent.TButton",
            background=COLORS["teal"],
            foreground="white",
            padding=(14, 7),
            font=("Segoe UI Semibold", 10),
        )
        style.map(
            "Accent.TButton",
            background=[("active", COLORS["teal_dark"]), ("disabled", COLORS["disabled"])],
        )
        style.configure("Danger.TButton", foreground=COLORS["danger"])
        style.configure(
            "Treeview",
            background=COLORS["card"],
            fieldbackground=COLORS["card"],
            rowheight=30,
            bordercolor=COLORS["border"],
        )
        style.configure(
            "Treeview.Heading",
            font=("Segoe UI Semibold", 9),
            background="#E9F0F7",
            foreground=COLORS["navy"],
            padding=7,
        )
        style.map(
            "Treeview",
            background=[("selected", COLORS["blue"])],
            foreground=[("selected", "white")],
        )
        style.configure("TNotebook", background=COLORS["background"], borderwidth=0)
        style.configure("TNotebook.Tab", padding=(15, 8))
        style.configure(
            "TLabelframe",
            background=COLORS["card"],
            bordercolor=COLORS["border"],
        )
        style.configure(
            "TLabelframe.Label",
            background=COLORS["card"],
            foreground=COLORS["navy"],
            font=("Segoe UI Semibold", 10),
        )

    def _load_startup_configuration(
        self, initial_config: Path | None
    ) -> tuple[BusSettings, list[SensorDevice]]:
        candidates = [initial_config] if initial_config else []
        candidates.extend(default_configuration_paths())
        for candidate in candidates:
            if candidate is None or not candidate.exists():
                continue
            try:
                bus, devices = load_configuration(candidate)
                self.current_config_path = candidate
                return bus, devices
            except Exception as exc:
                if initial_config:
                    messagebox.showerror(
                        "Configuration error",
                        f"Could not load {candidate}:\n\n{exc}",
                        parent=self.root,
                    )
        return BusSettings(), create_default_devices()

    def _build_ui(self) -> None:
        self.root.configure(background=COLORS["background"])
        header = tk.Frame(self.root, bg=COLORS["navy"], height=82)
        header.pack(fill=tk.X)
        header.pack_propagate(False)
        title_box = ttk.Frame(header, style="Card.TFrame")
        title_box.configure(style="Header.TFrame")
        style = ttk.Style(self.root)
        style.configure("Header.TFrame", background=COLORS["navy"])
        title_box.pack(side=tk.LEFT, fill=tk.Y, padx=22, pady=12)
        ttk.Label(title_box, text=APP_TITLE, style="Title.TLabel").pack(anchor=tk.W)
        ttk.Label(
            title_box,
            text="One physical bus - many realistic Modbus sensor slaves",
            style="HeaderSub.TLabel",
        ).pack(anchor=tk.W)

        status_box = tk.Frame(header, bg=COLORS["navy"])
        status_box.pack(side=tk.RIGHT, padx=22, pady=16)
        self.status_chip = tk.Label(
            status_box,
            textvariable=self.status_var,
            bg="#526D82",
            fg="white",
            font=("Segoe UI Semibold", 10),
            padx=14,
            pady=6,
        )
        self.status_chip.pack(side=tk.RIGHT)
        for key in (
            "dropped_frames",
            "exception_frames",
            "transmitted_frames",
            "received_frames",
        ):
            tk.Label(
                status_box,
                textvariable=self.counter_vars[key],
                bg=COLORS["navy"],
                fg="#D9EAF5",
                font=("Segoe UI", 9),
                padx=8,
            ).pack(side=tk.RIGHT)

        body = ttk.Frame(self.root, padding=(14, 12, 14, 10))
        body.pack(fill=tk.BOTH, expand=True)
        self._build_bus_bar(body)

        paned = ttk.Panedwindow(body, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
        left = ttk.Frame(paned, style="Card.TFrame", padding=10)
        right = ttk.Frame(paned, padding=(10, 0, 0, 0))
        paned.add(left, weight=3)
        paned.add(right, weight=2)
        self._build_device_panel(left)
        self._build_detail_notebook(right)

        footer = ttk.Frame(self.root, padding=(14, 5))
        footer.pack(fill=tk.X)
        ttk.Label(
            footer,
            textvariable=self.config_var,
            style="Muted.TLabel",
        ).pack(side=tk.LEFT)
        ttk.Label(
            footer,
            text="Function 0x03 | CRC-16/Modbus | addresses 1..247",
            style="Muted.TLabel",
        ).pack(side=tk.RIGHT)

    def _build_bus_bar(self, parent: ttk.Frame) -> None:
        card = ttk.LabelFrame(parent, text="RS485 / Modbus RTU bus", padding=10)
        card.pack(fill=tk.X)
        for column in (1, 4, 6, 8, 10):
            card.columnconfigure(column, weight=1)
        ttk.Label(card, text="Port", style="Card.TLabel").grid(
            row=0, column=0, sticky=tk.W
        )
        self.port_combo = ttk.Combobox(card, textvariable=self.port_var, width=16)
        self.port_combo.grid(row=0, column=1, sticky=tk.EW, padx=(6, 5))
        self.refresh_button = ttk.Button(
            card, text="Refresh", command=self._refresh_ports
        )
        self.refresh_button.grid(row=0, column=2, padx=(0, 16))

        ttk.Label(card, text="Baud", style="Card.TLabel").grid(
            row=0, column=3, sticky=tk.W
        )
        self.baud_combo = ttk.Combobox(
            card,
            textvariable=self.baud_var,
            values=("1200", "2400", "4800", "9600", "19200", "38400", "57600", "115200"),
            state="readonly",
            width=9,
        )
        self.baud_combo.grid(row=0, column=4, sticky=tk.EW, padx=(6, 14))
        ttk.Label(card, text="Parity", style="Card.TLabel").grid(
            row=0, column=5, sticky=tk.W
        )
        self.parity_combo = ttk.Combobox(
            card,
            textvariable=self.parity_var,
            values=("N", "E", "O"),
            state="readonly",
            width=5,
        )
        self.parity_combo.grid(row=0, column=6, sticky=tk.EW, padx=(6, 14))
        ttk.Label(card, text="Stop", style="Card.TLabel").grid(
            row=0, column=7, sticky=tk.W
        )
        self.stop_combo = ttk.Combobox(
            card,
            textvariable=self.stopbits_var,
            values=("1", "2"),
            state="readonly",
            width=5,
        )
        self.stop_combo.grid(row=0, column=8, sticky=tk.EW, padx=(6, 14))
        ttk.Label(card, text="Delay ms", style="Card.TLabel").grid(
            row=0, column=9, sticky=tk.W
        )
        self.delay_entry = ttk.Entry(card, textvariable=self.delay_var, width=8)
        self.delay_entry.grid(row=0, column=10, sticky=tk.EW, padx=(6, 14))

        self.start_button = ttk.Button(
            card,
            text="Start bus",
            style="Accent.TButton",
            command=self._toggle_bus,
        )
        self.start_button.grid(row=0, column=11, padx=(0, 8))
        ttk.Button(card, text="Load config", command=self._load_config).grid(
            row=0, column=12, padx=4
        )
        ttk.Button(card, text="Save config", command=self._save_config).grid(
            row=0, column=13, padx=(4, 0)
        )

        self.bus_widgets = (
            self.port_combo,
            self.refresh_button,
            self.baud_combo,
            self.parity_combo,
            self.stop_combo,
            self.delay_entry,
        )

    def _build_device_panel(self, parent: ttk.Frame) -> None:
        top = ttk.Frame(parent, style="Card.TFrame")
        top.pack(fill=tk.X)
        ttk.Label(
            top, text="Virtual sensor fleet", style="DialogTitle.TLabel"
        ).pack(side=tk.LEFT)
        count_box = ttk.Frame(top, style="Card.TFrame")
        count_box.pack(side=tk.RIGHT)
        for sensor_type in SensorType:
            tk.Label(
                count_box,
                textvariable=self.count_vars[sensor_type],
                bg={
                    SensorType.HNDA: "#E8F5E9",
                    SensorType.TUF: "#E3F2FD",
                    SensorType.SUPMEA: "#E0F7FA",
                    SensorType.SONDAS: "#FFF3E0",
                }[sensor_type],
                fg=COLORS["navy"],
                font=("Segoe UI Semibold", 8),
                padx=8,
                pady=4,
            ).pack(side=tk.LEFT, padx=2)

        toolbar = ttk.Frame(parent, style="Card.TFrame")
        toolbar.pack(fill=tk.X, pady=(10, 8))
        for text, command in (
            ("+ Sensor", self._add_device),
            ("+ Fleet", self._add_batch),
            ("Clone", self._clone_device),
            ("Edit", self._edit_device),
            ("Enable / disable", self._toggle_device_enabled),
            ("Mute / unmute", self._toggle_device_muted),
        ):
            ttk.Button(toolbar, text=text, command=command).pack(
                side=tk.LEFT, padx=(0, 5)
            )
        ttk.Button(
            toolbar,
            text="Remove",
            style="Danger.TButton",
            command=self._remove_device,
        ).pack(side=tk.RIGHT)

        columns = (
            "address",
            "type",
            "name",
            "state",
            "profile",
            "live",
            "requests",
            "last_seen",
        )
        self.device_tree = ttk.Treeview(
            parent, columns=columns, show="headings", selectmode="browse"
        )
        headings = {
            "address": "Address",
            "type": "Type",
            "name": "Device name",
            "state": "State",
            "profile": "Signal profile",
            "live": "Live values",
            "requests": "Requests",
            "last_seen": "Last seen",
        }
        widths = {
            "address": 68,
            "type": 75,
            "name": 180,
            "state": 100,
            "profile": 110,
            "live": 220,
            "requests": 72,
            "last_seen": 150,
        }
        for column in columns:
            self.device_tree.heading(column, text=headings[column])
            self.device_tree.column(
                column,
                width=widths[column],
                minwidth=55,
                stretch=column in ("name", "live", "last_seen"),
                anchor=tk.CENTER if column in ("address", "type", "state", "requests") else tk.W,
            )
        scrollbar = ttk.Scrollbar(
            parent, orient=tk.VERTICAL, command=self.device_tree.yview
        )
        self.device_tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.device_tree.pack(fill=tk.BOTH, expand=True)
        self.device_tree.bind("<<TreeviewSelect>>", self._on_device_selected)
        self.device_tree.bind("<Double-1>", lambda _event: self._edit_device())
        self.device_tree.tag_configure("disabled", foreground=COLORS["disabled"])
        self.device_tree.tag_configure("muted", foreground=COLORS["warning"])

    def _build_detail_notebook(self, parent: ttk.Frame) -> None:
        notebook = ttk.Notebook(parent)
        notebook.pack(fill=tk.BOTH, expand=True)
        live_tab = ttk.Frame(notebook, padding=10)
        traffic_tab = ttk.Frame(notebook, padding=10)
        reference_tab = ttk.Frame(notebook, padding=10)
        notebook.add(live_tab, text="Live device")
        notebook.add(traffic_tab, text="Bus traffic")
        notebook.add(reference_tab, text="Register reference")
        self._build_live_tab(live_tab)
        self._build_traffic_tab(traffic_tab)
        self._build_reference_tab(reference_tab)
        calendar_tab = ttk.Frame(notebook, padding=10)
        notebook.add(calendar_tab, text="SUPMEA RTC test")
        self._build_calendar_tab(calendar_tab)

    def _build_calendar_tab(self, parent):
        from supmea_reference import parse_utc_start
        self.reference_timezone_var = tk.StringVar(value="Africa/Cairo")
        self.reference_start_var = tk.StringVar(value="")
        self.reference_summary_var = tk.StringVar(value="Select a SUPMEA device.")
        ttk.Label(parent, text="Independent flow integral — display only",
                  style="DialogTitle.TLabel", wraplength=500).pack(anchor=tk.W)
        ttk.Label(parent, text="No day/month/year values are sent over RS485. "
                  "Match the node calendar and reference start. Use x1 time for real-node comparison.",
                  wraplength=500).pack(anchor=tk.W, pady=10)
        ttk.Label(parent, text="Calendar timezone (UTC, Africa/Cairo or +HH:MM)").pack(anchor=tk.W)
        ttk.Combobox(parent, textvariable=self.reference_timezone_var,
                     values=("Africa/Cairo", "UTC", "+02:00", "+03:00")).pack(fill=tk.X)
        ttk.Label(parent, text="Start UTC ISO time; blank = PC UTC now (e.g. 2026-10-25T10:00:00Z)").pack(anchor=tk.W, pady=(10,0))
        ttk.Entry(parent, textvariable=self.reference_start_var).pack(fill=tk.X)
        def reset():
            device_id = self._selected_device_id()
            if not device_id:
                return
            try:
                epoch = parse_utc_start(self.reference_start_var.get())
                self.registry.reset_supmea_reference(device_id, self.reference_timezone_var.get().strip(), epoch)
                self._refresh_selected_details()
            except (ValueError, KeyError) as exc:
                messagebox.showerror("SUPMEA reference", str(exc), parent=self.root)
        ttk.Button(parent, text="Start / reset comparison reference", command=reset).pack(anchor=tk.W, pady=10)
        ttk.Button(parent, text="Export selected SUPMEA reference JSON",
                   command=self._export_supmea_reference).pack(anchor=tk.W)
        ttk.Label(parent, textvariable=self.reference_summary_var, wraplength=520,
                  justify=tk.LEFT).pack(anchor=tk.W, pady=15)

    def _export_supmea_reference(self):
        snapshots = {item["id"]: item for item in self.registry.snapshots()}
        item = snapshots.get(self._selected_device_id())
        if not item or "supmea_reference" not in item:
            messagebox.showinfo("SUPMEA reference", "Select a SUPMEA device.", parent=self.root)
            return
        path = filedialog.asksaveasfilename(parent=self.root, defaultextension=".json",
                                           filetypes=[("Reference JSON", "*.json")])
        if path:
            import json
            Path(path).write_text(json.dumps(item, indent=2), encoding="utf-8")

    def _build_live_tab(self, parent: ttk.Frame) -> None:
        ttk.Label(
            parent, textvariable=self.selected_title_var, style="DialogTitle.TLabel"
        ).pack(anchor=tk.W)
        ttk.Label(
            parent,
            textvariable=self.selected_subtitle_var,
            style="Muted.TLabel",
            wraplength=500,
        ).pack(anchor=tk.W, pady=(2, 10))
        actions = ttk.Frame(parent)
        actions.pack(fill=tk.X, pady=(0, 8))
        ttk.Button(actions, text="Edit values", command=self._edit_device).pack(
            side=tk.LEFT, padx=(0, 5)
        )
        ttk.Button(
            actions, text="Reset totalizers", command=self._reset_totalizers
        ).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(
            actions, text="Clear device stats", command=self._clear_statistics
        ).pack(side=tk.LEFT)

        self.measurement_tree = ttk.Treeview(
            parent,
            columns=("measurement", "value", "unit", "mode", "range"),
            show="headings",
            height=13,
        )
        for column, heading, width in (
            ("measurement", "Measurement", 170),
            ("value", "Current", 100),
            ("unit", "Unit", 90),
            ("mode", "Mode", 105),
            ("range", "Configured range", 150),
        ):
            self.measurement_tree.heading(column, text=heading)
            self.measurement_tree.column(column, width=width, anchor=tk.W)
        self.measurement_tree.pack(fill=tk.BOTH, expand=True)

        stats_frame = ttk.LabelFrame(parent, text="Device diagnostics", padding=10)
        stats_frame.pack(fill=tk.X, pady=(10, 0))
        self.device_stats_var = tk.StringVar(value="No device selected")
        ttk.Label(
            stats_frame,
            textvariable=self.device_stats_var,
            style="Card.TLabel",
            wraplength=520,
        ).pack(anchor=tk.W)

    def _build_traffic_tab(self, parent: ttk.Frame) -> None:
        controls = ttk.Frame(parent)
        controls.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(controls, text="Show").pack(side=tk.LEFT)
        ttk.Combobox(
            controls,
            textvariable=self.log_filter_var,
            state="readonly",
            values=("All events", "Traffic only", "Errors / faults"),
            width=16,
        ).pack(side=tk.LEFT, padx=(6, 12))
        ttk.Checkbutton(
            controls, text="Auto-scroll", variable=self.autoscroll_var
        ).pack(side=tk.LEFT)
        ttk.Button(controls, text="Clear", command=self._clear_log).pack(
            side=tk.RIGHT
        )
        self.log = scrolledtext.ScrolledText(
            parent,
            wrap=tk.NONE,
            state=tk.DISABLED,
            font=("Cascadia Mono", 9),
            background=COLORS["log_bg"],
            foreground=COLORS["log_text"],
            insertbackground="white",
            relief=tk.FLAT,
        )
        self.log.pack(fill=tk.BOTH, expand=True)
        self.log.tag_configure("rx", foreground="#63B3ED")
        self.log.tag_configure("tx", foreground="#68D391")
        self.log.tag_configure("error", foreground="#FC8181")
        self.log.tag_configure("exception", foreground="#F6AD55")
        self.log.tag_configure("dropped", foreground="#F6AD55")
        self.log.tag_configure("noise", foreground="#A0AEC0")
        self.log.tag_configure("status", foreground="#B794F4")

    def _build_reference_tab(self, parent: ttk.Frame) -> None:
        text = scrolledtext.ScrolledText(
            parent,
            wrap=tk.WORD,
            state=tk.NORMAL,
            font=("Segoe UI", 10),
            relief=tk.FLAT,
            background=COLORS["card"],
            foreground=COLORS["text"],
            padx=8,
            pady=8,
        )
        text.pack(fill=tk.BOTH, expand=True)
        text.insert(tk.END, "WIOT SENSOR REGISTER REFERENCE\n\n", "heading")
        for sensor_type in SensorType:
            text.insert(tk.END, f"{sensor_type.value} - {sensor_type.display_name}\n", "subheading")
            for line in REGISTER_REFERENCE[sensor_type]:
                text.insert(tk.END, f"  - {line}\n")
            text.insert(tk.END, "\n")
        text.insert(
            tk.END,
            "Important bus rule\n",
            "subheading",
        )
        text.insert(
            tk.END,
            "Every enabled slave must have a unique address. Use one Modbus master "
            "at a time. All devices on a physical bus must use the same baud, parity, "
            "and stop-bit settings.\n\n",
        )
        text.insert(tk.END, "Supmea flow unit codes\n", "subheading")
        for index, unit in enumerate(FLOW_UNIT_NAMES):
            text.insert(tk.END, f"  {index}: {unit}\n")
        text.tag_configure("heading", font=("Segoe UI Semibold", 14), foreground=COLORS["navy"])
        text.tag_configure("subheading", font=("Segoe UI Semibold", 11), foreground=COLORS["teal_dark"])
        text.configure(state=tk.DISABLED)

    def _collect_bus_settings(self) -> BusSettings:
        settings = BusSettings(
            port=self.port_var.get(),
            baudrate=int(self.baud_var.get()),
            parity=self.parity_var.get(),
            stopbits=int(self.stopbits_var.get()),
            response_delay_ms=int(self.delay_var.get()),
        )
        settings.validate()
        return settings

    def _toggle_bus(self) -> None:
        if self.worker and self.worker.running:
            self._stop_bus()
        else:
            self._start_bus()

    def _start_bus(self) -> None:
        try:
            self.bus_settings = self._collect_bus_settings()
            if not any(item["enabled"] for item in self.registry.snapshots()):
                raise ValueError("Enable at least one virtual sensor before starting")
            self.worker = MultiSensorSerialSlave(
                self.bus_settings,
                self.registry,
                self.event_queue.put,
            )
            self.worker.start()
        except (TypeError, ValueError, RuntimeError) as exc:
            messagebox.showerror("Cannot start bus", str(exc), parent=self.root)
            return
        self.status_var.set("CONNECTING")
        self.status_chip.configure(bg=COLORS["warning"])
        self.start_button.configure(text="Stop bus")
        self._set_bus_inputs_enabled(False)

    def _stop_bus(self) -> None:
        if self.worker:
            self._last_counters = self.worker.counters()
            self.worker.stop()
        self.status_var.set("STOPPED")
        self.status_chip.configure(bg="#526D82")
        self.start_button.configure(text="Start bus")
        self._set_bus_inputs_enabled(True)

    def _set_bus_inputs_enabled(self, enabled: bool) -> None:
        for widget in self.bus_widgets:
            if isinstance(widget, ttk.Combobox):
                widget.configure(state="readonly" if enabled and widget is not self.port_combo else ("normal" if enabled else "disabled"))
            else:
                widget.configure(state="normal" if enabled else "disabled")

    def _refresh_ports(self) -> None:
        current = self.port_var.get()
        ports: list[str] = []
        try:
            from serial.tools import list_ports

            ports = [item.device for item in list_ports.comports()]
        except ImportError:
            pass
        values = sorted(set([*ports, current, "loop://"]))
        self.port_combo.configure(values=values)

    def _selected_device_id(self) -> str | None:
        selection = self.device_tree.selection()
        return selection[0] if selection else None

    def _address_available(self, address: int, excluding_id: str | None) -> bool:
        return not self.registry.address_in_use(address, excluding_id)

    def _add_device(self) -> None:
        used = {item["address"] for item in self.registry.snapshots()}
        address = next((item for item in range(1, 248) if item not in used), None)
        if address is None:
            messagebox.showerror("Bus full", "All Modbus addresses are occupied")
            return
        dialog = DeviceEditorDialog(
            self.root,
            None,
            self._address_available,
            default_address=address,
        )
        dialog.wait_window()
        if dialog.result:
            self.registry.add(dialog.result)
            self._mark_dirty()
            self._refresh_all_views(force=True)
            self.device_tree.selection_set(dialog.result.device_id)

    def _add_batch(self) -> None:
        occupied = {item["address"] for item in self.registry.snapshots()}
        dialog = BatchAddDialog(self.root, occupied)
        dialog.wait_window()
        if dialog.result:
            self.registry.add_many(dialog.result)
            self._mark_dirty()
            self._refresh_all_views(force=True)

    def _edit_device(self) -> None:
        device_id = self._selected_device_id()
        if not device_id:
            messagebox.showinfo("Select a device", "Select one virtual sensor first")
            return
        source = self.registry.get_config_copy(device_id)
        dialog = DeviceEditorDialog(
            self.root, source, self._address_available
        )
        dialog.wait_window()
        if dialog.result:
            self.registry.update(dialog.result)
            self._mark_dirty()
            self._refresh_all_views(force=True)
            self.device_tree.selection_set(device_id)

    def _clone_device(self) -> None:
        device_id = self._selected_device_id()
        if not device_id:
            messagebox.showinfo("Select a device", "Select a sensor to clone")
            return
        used = {item["address"] for item in self.registry.snapshots()}
        address = next((item for item in range(1, 248) if item not in used), None)
        if address is None:
            messagebox.showerror("Bus full", "All Modbus addresses are occupied")
            return
        data = self.registry.get_config_copy(device_id).to_config_dict()
        data.pop("id", None)
        data["address"] = address
        data["name"] = f"{data['name']} copy"
        clone = SensorDevice.from_dict(data)
        self.registry.add(clone)
        self._mark_dirty()
        self._refresh_all_views(force=True)
        self.device_tree.selection_set(clone.device_id)

    def _remove_device(self) -> None:
        device_id = self._selected_device_id()
        if not device_id:
            messagebox.showinfo("Select a device", "Select a sensor to remove")
            return
        snapshot = next(
            item for item in self.registry.snapshots() if item["id"] == device_id
        )
        if not messagebox.askyesno(
            "Remove virtual sensor",
            f"Remove '{snapshot['name']}' at address {snapshot['address']}?",
            parent=self.root,
        ):
            return
        self.registry.remove(device_id)
        self._mark_dirty()
        self._refresh_all_views(force=True)

    def _toggle_device_enabled(self) -> None:
        device_id = self._selected_device_id()
        if not device_id:
            return
        snapshot = next(
            item for item in self.registry.snapshots() if item["id"] == device_id
        )
        self.registry.set_enabled(device_id, not snapshot["enabled"])
        self._mark_dirty()
        self._refresh_all_views(force=True)

    def _toggle_device_muted(self) -> None:
        device_id = self._selected_device_id()
        if not device_id:
            return
        snapshot = next(
            item for item in self.registry.snapshots() if item["id"] == device_id
        )
        self.registry.set_muted(device_id, not snapshot["muted"])
        self._mark_dirty()
        self._refresh_all_views(force=True)

    def _reset_totalizers(self) -> None:
        device_id = self._selected_device_id()
        if not device_id:
            return
        if not self.registry.reset_totalizers(device_id):
            messagebox.showinfo(
                "No totalizers",
                "The selected soil sensor has no flow totalizers.",
                parent=self.root,
            )
            return
        self._mark_dirty()
        self._refresh_all_views(force=True)

    def _clear_statistics(self) -> None:
        self.registry.clear_statistics()
        if self.worker:
            self.worker.clear_counters()
        self._last_counters = {key: 0 for key in self._last_counters}
        self._refresh_all_views(force=True)

    def _load_config(self) -> None:
        path_text = filedialog.askopenfilename(
            parent=self.root,
            title="Load WIOT simulator configuration",
            filetypes=(("WIOT JSON configuration", "*.json"), ("All files", "*.*")),
        )
        if not path_text:
            return
        try:
            bus, devices = load_configuration(path_text)
        except Exception as exc:
            messagebox.showerror("Configuration error", str(exc), parent=self.root)
            return
        if self.worker and self.worker.running:
            self._stop_bus()
        self.bus_settings = bus
        self.registry.replace_all(devices)
        self.current_config_path = Path(path_text)
        self.port_var.set(bus.port)
        self.baud_var.set(str(bus.baudrate))
        self.parity_var.set(bus.parity)
        self.stopbits_var.set(str(bus.stopbits))
        self.delay_var.set(str(bus.response_delay_ms))
        self.dirty = False
        self.config_var.set(self._config_display_name())
        self._refresh_all_views(force=True)
        self._append_log(
            BusEvent("status", f"Loaded configuration: {self.current_config_path}")
        )

    def _save_config(self) -> None:
        initial = (
            self.current_config_path.name
            if self.current_config_path
            else "wiot_bus_config.json"
        )
        path_text = filedialog.asksaveasfilename(
            parent=self.root,
            title="Save WIOT simulator configuration",
            defaultextension=".json",
            initialfile=initial,
            filetypes=(("WIOT JSON configuration", "*.json"),),
        )
        if not path_text:
            return
        try:
            bus = self._collect_bus_settings()
            save_configuration(path_text, bus, self.registry.config_devices())
        except Exception as exc:
            messagebox.showerror("Could not save configuration", str(exc), parent=self.root)
            return
        self.bus_settings = bus
        self.current_config_path = Path(path_text)
        self.dirty = False
        self.config_var.set(self._config_display_name())
        self._append_log(BusEvent("status", f"Saved configuration: {path_text}"))

    def _config_display_name(self) -> str:
        label = str(self.current_config_path) if self.current_config_path else "Unsaved configuration"
        return f"Config: {label}{' *' if self.dirty else ''}"

    def _mark_dirty(self) -> None:
        self.dirty = True
        self.config_var.set(self._config_display_name())

    def _simulation_tick(self) -> None:
        self.registry.advance_all()
        self._refresh_all_views()
        self.root.after(200, self._simulation_tick)

    def _refresh_all_views(self, force: bool = False) -> None:
        snapshots = self.registry.snapshots()
        selected = self._selected_device_id() if hasattr(self, "device_tree") else None
        existing = set(self.device_tree.get_children()) if hasattr(self, "device_tree") else set()
        incoming = {item["id"] for item in snapshots}
        for stale in existing - incoming:
            self.device_tree.delete(stale)
        counts = {sensor_type: 0 for sensor_type in SensorType}

        for item in snapshots:
            sensor_type = SensorType(item["type"])
            counts[sensor_type] += 1
            definitions = signal_definition_map(sensor_type)
            primary_keys = list(definitions)[:2]
            live = ", ".join(
                f"{definitions[key].label}: "
                f"{format_number(item['values'][key], definitions[key].integer)}"
                for key in primary_keys
            )
            modes = {
                data["mode"]
                for key, data in item["signals"].items()
                if not definitions[key].totalizer and not definitions[key].discrete
            }
            profile = next(iter(modes)) if len(modes) == 1 else "mixed"
            state = "Disabled" if not item["enabled"] else ("Muted" if item["muted"] else "Online")
            values = (
                item["address"],
                item["type"],
                item["name"],
                state,
                profile,
                live,
                item["statistics"]["requests"],
                item["statistics"]["last_seen"],
            )
            tags = ("disabled",) if not item["enabled"] else (("muted",) if item["muted"] else ())
            if item["id"] in existing:
                self.device_tree.item(item["id"], values=values, tags=tags)
            else:
                self.device_tree.insert("", tk.END, iid=item["id"], values=values, tags=tags)

        for sensor_type, count in counts.items():
            self.count_vars[sensor_type].set(f"{sensor_type.value} {count}")

        if selected and selected in incoming:
            self.device_tree.selection_set(selected)
        elif snapshots and force:
            self.device_tree.selection_set(snapshots[0]["id"])
        self._refresh_selected_details()
        self._refresh_counters()

    def _on_device_selected(self, _event: tk.Event | None = None) -> None:
        self._refresh_selected_details()

    def _refresh_selected_details(self) -> None:
        device_id = self._selected_device_id()
        for row in self.measurement_tree.get_children():
            self.measurement_tree.delete(row)
        if not device_id:
            self.reference_summary_var.set("Select a SUPMEA device.")
            self.selected_title_var.set("Select a device")
            self.selected_subtitle_var.set(
                "Live values, signal modes, and request statistics appear here."
            )
            self.device_stats_var.set("No device selected")
            return
        snapshots = {item["id"]: item for item in self.registry.snapshots()}
        item = snapshots.get(device_id)
        if item is None:
            return
        sensor_type = SensorType(item["type"])
        reference = item.get("supmea_reference")
        if reference:
            self.reference_summary_var.set(
                f"Today: {reference['today_m3']:.6f} m³\n"
                f"Month: {reference['month_m3']:.6f} m³\nYear: {reference['year_m3']:.6f} m³\n\n"
                f"UTC: {reference['clock_utc']}\nLocal: {reference['clock_local']}\n"
                f"Calendar: {reference['timezone']}\nStarted: {reference['started_utc']}\n"
                f"{reference['status']}\n{reference['scope']}\n{reference['wire']}")
        else:
            self.reference_summary_var.set("Select a SUPMEA device. Other sensor types are unchanged.")
        state = "disabled" if not item["enabled"] else ("muted" if item["muted"] else "active")
        self.selected_title_var.set(
            f"{item['name']}  |  address {item['address']}"
        )
        self.selected_subtitle_var.set(
            f"{sensor_type.display_name} - {state} - updates every "
            f"{item['update_interval_s']} s - time x{item['time_multiplier']}"
        )
        definitions = signal_definition_map(sensor_type)
        for definition in SIGNAL_DEFINITIONS[sensor_type]:
            profile = item["signals"][definition.key]
            current = item["values"][definition.key]
            self.measurement_tree.insert(
                "",
                tk.END,
                iid=f"measurement-{definition.key}",
                values=(
                    definition.label,
                    format_number(current, definition.integer),
                    definition.unit,
                    profile["mode"],
                    f"{format_number(profile['minimum'], definition.integer)} .. "
                    f"{format_number(profile['maximum'], definition.integer)}",
                ),
            )
        stats = item["statistics"]
        fault = item["faults"]
        self.device_stats_var.set(
            f"Requests {stats['requests']}  |  Responses {stats['responses']}  |  "
            f"Exceptions {stats['exceptions']}  |  Dropped {stats['dropped']}\n"
            f"Last request: {stats['last_request']}\n"
            f"Faults: +{fault['extra_delay_ms']} ms, drop {fault['drop_percent']}%, "
            f"CRC {fault['crc_error_percent']}%, forced exception {fault['forced_exception']}"
        )

    def _refresh_counters(self) -> None:
        counters = self.worker.counters() if self.worker else self._last_counters
        self.counter_vars["received_frames"].set(f"{counters['received_frames']} RX")
        self.counter_vars["transmitted_frames"].set(f"{counters['transmitted_frames']} TX")
        self.counter_vars["exception_frames"].set(
            f"{counters['exception_frames']} exceptions"
        )
        self.counter_vars["dropped_frames"].set(f"{counters['dropped_frames']} dropped")

    def _drain_events(self) -> None:
        for _ in range(200):
            try:
                event = self.event_queue.get_nowait()
            except queue.Empty:
                break
            self._append_log(event)
            if event.level == "status":
                self.status_var.set("RUNNING")
                self.status_chip.configure(bg=COLORS["success"])
            elif event.level == "error":
                self.status_var.set("ERROR")
                self.status_chip.configure(bg=COLORS["danger"])
                self.start_button.configure(text="Start bus")
                self._set_bus_inputs_enabled(True)
            elif event.level == "stopped":
                self.status_var.set("STOPPED")
                self.status_chip.configure(bg="#526D82")
                self.start_button.configure(text="Start bus")
                self._set_bus_inputs_enabled(True)
        self.root.after(100, self._drain_events)

    def _event_visible(self, level: str) -> bool:
        selected = self.log_filter_var.get()
        if selected == "Traffic only":
            return level in ("rx", "tx")
        if selected == "Errors / faults":
            return level in ("error", "exception", "dropped", "noise")
        return True

    def _append_log(self, event: BusEvent) -> None:
        if not self._event_visible(event.level):
            return
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        label = event.level.upper()[:9]
        identity = ""
        if event.address is not None:
            identity = f" [{event.sensor_type or 'BUS'}:{event.address}]"
        raw = f" | {event.raw_hex}" if event.raw_hex else ""
        line = f"{timestamp}  {label:<9}{identity}  {event.message}{raw}\n"
        self.log.configure(state=tk.NORMAL)
        self.log.insert(tk.END, line, event.level)
        line_count = int(self.log.index("end-1c").split(".")[0])
        if line_count > 5000:
            self.log.delete("1.0", "501.0")
        if self.autoscroll_var.get():
            self.log.see(tk.END)
        self.log.configure(state=tk.DISABLED)

    def _clear_log(self) -> None:
        self.log.configure(state=tk.NORMAL)
        self.log.delete("1.0", tk.END)
        self.log.configure(state=tk.DISABLED)

    def _on_close(self) -> None:
        if self.worker and self.worker.running:
            self._stop_bus()
        if self.dirty and not messagebox.askyesno(
            "Unsaved configuration",
            "The fleet configuration has unsaved changes. Exit anyway?",
            parent=self.root,
        ):
            return
        self.root.destroy()


def validate_config(path: Path) -> int:
    bus, devices = load_configuration(path)
    payload = configuration_to_dict(bus, devices)
    print(
        json.dumps(
            {
                "valid": True,
                "path": str(path.resolve()),
                "bus": payload["bus"],
                "fleet_summary": payload["fleet_summary"],
                "total_devices": len(devices),
            },
            indent=2,
        )
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=APP_TITLE)
    parser.add_argument(
        "--config",
        type=Path,
        help="JSON configuration to load at startup",
    )
    parser.add_argument(
        "--validate-config",
        type=Path,
        help="Validate a configuration and exit without opening the GUI",
    )
    args = parser.parse_args(argv)
    if args.validate_config:
        return validate_config(args.validate_config)

    root = tk.Tk()
    MultiSensorSimulatorApp(root, args.config)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
