"""
main_gui.py
-----------
Annotated Tkinter desktop UI for the IoT Node Simulator.

Purpose of this file:
- Build the full desktop GUI.
- Collect settings from the user.
- Connect GUI actions to MQTT logic and RS-485 logic.
- Display three different logs: RX commands, sensor serial traffic, and published TX telemetry.
- Show framing/debug metadata so encrypted MQTT traffic stays traceable.

Why this file matters:
- It is the top-level coordinator of the whole project.
- Most user-triggered actions begin here, then call into mqtt_impl.py,
  protobuf_impl.py, or rs485_tuf2000b.py.

High-level flow:
    Button click / timer
        -> build or read data
        -> call helper module
        -> update GUI state and logs

The GUI is intentionally split into small helper methods so each section
of the window can be maintained independently.
"""

import json
import queue
import os
import re
import time
from datetime import datetime
import tkinter as tk
from tkinter import ttk, messagebox

import protobuf_impl
import messages_pb2
import command_impl
from mqtt_impl import MqttNodeClient

try:
    from rs485_tuf2000b import Tuf2000bConfig, Tuf2000bRtuClient, Rs485DependencyError
except Exception:
    Tuf2000bConfig = None
    Tuf2000bRtuClient = None

    class Rs485DependencyError(Exception):
        pass


CMD_NAMES = {
    0: "NA",
    1: "SRATE",
    2: "STRAN",
    3: "STIME",
    4: "GOSTM",
}


def _now_ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _hex_bytes(b: bytes, group: int = 1) -> str:
    # Space-separated hex for readability
    return b.hex(" ")


# Main application controller: owns all widgets, runtime objects, and callbacks.
class App:
    """
    Top-level GUI controller.

    This class stores:
    - all Tkinter variables and widgets
    - runtime MQTT / RS-485 objects
    - button callbacks
    - periodic .after() jobs for telemetry TX and sensor polling

    If you want to understand the project from the UI side, this is the main
    class to read from top to bottom.
    """
    def __init__(self, root: tk.Tk):
        """
        Build the full window and initialize runtime state.

        Block-by-block inside __init__:
        1) configure the root window
        2) load configuration defaults
        3) initialize runtime objects/state flags
        4) create the header and main layout containers
        5) build each GUI section
        6) refresh button states
        """
        self.root = root
        self._ui_queue = queue.Queue()
        self.root.after(50, self._drain_ui_queue)
        root.title("IoT Node Simulator (MQTT + Protobuf + AES-CBC/PKCS7 + RS-485)")
        screen_w = root.winfo_screenwidth()
        screen_h = root.winfo_screenheight()
        win_w = min(max(1180, int(screen_w * 0.88)), max(1180, screen_w - 80))
        win_h = min(max(700, int(screen_h * 0.84)), max(700, screen_h - 100))
        root.geometry(f"{win_w}x{win_h}")
        root.minsize(980, 640)

        # ttk theme
        try:
            ttk.Style().theme_use("clam")
        except Exception:
            pass

        # Non-obvious path choice: keep config file next to this script for portable deployment.
        self.cfg_path = os.path.join(os.path.dirname(__file__), "node_config.json")
        self.cfg = self._load_cfg()

        # runtime objects
        self.mqtt: MqttNodeClient | None = None
        self.rs: Tuf2000bRtuClient | None = None

        self.command_state = command_impl.SimState(
            sampling_rate_sec=max(1, int(float(self.cfg.get("rs485", {}).get("poll_period_ms", 1000)) / 1000)),
            tx_period_sec=max(1, int(self.cfg.get("mqtt", {}).get("tx_period_s", 5))),
            system_time=int(time.time()),
        )

        self.tx_running = False
        self.tx_job = None

        self.rs_poll_running = False
        self.rs_poll_job = None
        self.last_flow: float | None = None
        self.last_measurements: dict | None = None
        self._last_error_msg = "No errors."

        # fonts
        self.bold_font = ("Segoe UI", 10, "bold")
        self.mono_font = ("Consolas", 9)

        # Log-header state used before the RS-485 config panel is built.
        # It must exist before _build_logs_frame() because the Sensor tab
        # shows this StringVar in its header.
        self.sensor_last_read_var = tk.StringVar(value="Last read: --")
        self.rs_instant_flow_var = tk.StringVar(value="--")
        self.rs_velocity_var = tk.StringVar(value="--")
        self.rs_flow_today_var = tk.StringVar(value="--")
        self.rs_flow_month_var = tk.StringVar(value="--")
        self.rs_flow_year_var = tk.StringVar(value="--")
        self.sampling_rate_var = tk.StringVar(value=str(int(self.cfg.get("mqtt", {}).get("sampling_rate_sec", 1))))

        # ===== Header =====
        header = ttk.Frame(root, padding=(12, 10, 12, 6))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)

        ttk.Label(header, text="IoT Node Simulator", font=("Segoe UI", 16, "bold")).grid(
            row=0, column=0, sticky="w"
        )

        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(header, textvariable=self.status_var).grid(row=1, column=0, sticky="w", pady=(4, 0))

        ttk.Button(header, text="Load Config", command=self.on_load_config).grid(row=0, column=1, rowspan=2, sticky="e")

        # ===== Main grid =====
        body = ttk.Frame(root, padding=(12, 6, 12, 10))
        body.grid(row=1, column=0, sticky="nsew")
        root.rowconfigure(1, weight=1)
        root.columnconfigure(0, weight=1)
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=3)
        body.rowconfigure(0, weight=1)

        # Left side: all logs in one tabbed view.
        self._build_config_panel(body).grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        # Right side: all configuration sections stacked vertically.
        self._build_logs_frame(body).grid(row=0, column=1, sticky="nsew")
        self._refresh_status()
        self._bind_cmd_publish_helpers()

    # =========================
    # Config
    # =========================
    # Read configuration from node_config.json. If the file is missing,
    # fall back to safe defaults so the GUI can still start.
    def _load_cfg(self) -> dict:
        try:
            with open(self.cfg_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            # safe defaults
            return {
                "mqtt": {
                    "broker": "broker.hivemq.com",
                    "port": 1883,
                    "pub_topic": "EgSA/Company_ID/Node_ID/Status",
                    "cmd_pub_topic": "EgSA/Company_ID/Node_ID/CMD",
                    "sub_topic_1": "EgSA/Company_ID/Node_ID/CMD",
                    "sub_topic_2": "EgSA/Company_ID/BroadCast/CMD",
                                        "client_id": "stm32_pubsub_01",
                    "keepalive": 60,
                    "tx_period_s": 5,
                },
                "encryption": {"key_hex": "00"*16, "code_version_hex": "01"},
                "device_defaults": {"node_id": 1, "sensor_id": 1, "battery_voltage": 8.0},
                "rs485": {"enabled": False, "port": "COM3", "baudrate": 9600, "parity": "N", "stopbits": 1, "bytesize": 8, "timeout_s": 1.0, "unit_id": 1, "address_base": 0, "poll_period_ms": 1000, "registers": {"flow_rate": 0}},
            }

    # Reload configuration from disk and push values into the visible GUI controls.
    def on_load_config(self):
        self.cfg = self._load_cfg()
        # update GUI fields
        m = self.cfg.get("mqtt", {})
        e = self.cfg.get("encryption", {})
        d = self.cfg.get("device_defaults", {})
        r = self.cfg.get("rs485", {})

        self.mqtt_host_var.set(m.get("broker", ""))
        self.mqtt_port_var.set(str(m.get("port", 1883)))
        self.mqtt_pub_var.set(m.get("pub_topic", ""))
        self.mqtt_cmd_pub_var.set(m.get("cmd_pub_topic", m.get("sub_topic_1", m.get("sub_topic", ""))))
        self.mqtt_sub1_var.set(m.get("sub_topic_1", m.get("sub_topic", "")))
        self.mqtt_sub2_var.set(m.get("sub_topic_2", ""))
        self.mqtt_client_id_var.set(m.get("client_id", "stm32_pubsub_01"))
        self.tx_period_var.set(str(int(float(m.get("tx_period_s", 5)))))

        self.key_hex_var.set(e.get("key_hex", ""))

        self.node_id_var.set(str(d.get("node_id", 1)))
        self.sensor_id_var.set(str(d.get("sensor_id", 1)))
        self.battery_voltage_var.set(str(d.get("battery_voltage", 8.0)))
        self.valve_state_var.set(bool(False))

        self.rs_enabled_var.set(bool(r.get("enabled", False)))
        self.rs_port_var.set(r.get("port", "COM3"))
        self.rs_baud_var.set(str(r.get("baudrate", 9600)))
        self.rs_parity_var.set(r.get("parity", "N"))
        self.rs_stopbits_var.set(str(r.get("stopbits", 1)))
        self.rs_unit_var.set(str(r.get("unit_id", 1)))
        self.rs_poll_ms_var.set(str(r.get("poll_period_ms", 1000)))
        self.command_state.sampling_rate_sec = max(1, int(float(r.get("poll_period_ms", 1000)) / 1000))
        self.command_state.tx_period_sec = max(1, int(float(m.get("tx_period_s", 5))))

        try:
            self.tx_period_ms_display_var.set(str(int(float(m.get("tx_period_s", 1.0)) * 1000)))
        except Exception:
            self.tx_period_ms_display_var.set("1000")

        self._refresh_status()

    # =========================
    # UI Builders
    # =========================
    # Create the MQTT settings section: broker, topics, and transmission controls.
    def _build_config_panel(self, parent: ttk.Frame) -> ttk.Frame:
        panel = ttk.Frame(parent)
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(0, weight=1)

        canvas = tk.Canvas(panel, highlightthickness=0)
        canvas.grid(row=0, column=0, sticky="nsew")

        vscroll = ttk.Scrollbar(panel, orient="vertical", command=canvas.yview)
        vscroll.grid(row=0, column=1, sticky="ns")
        canvas.configure(yscrollcommand=vscroll.set)

        inner = ttk.Frame(canvas, padding=(0, 0, 2, 0))
        inner.columnconfigure(0, weight=1)
        window_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _sync_scroll_region(_event=None):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _sync_inner_width(event):
            canvas.itemconfigure(window_id, width=event.width)

        inner.bind("<Configure>", _sync_scroll_region)
        canvas.bind("<Configure>", _sync_inner_width)

        self._build_mqtt_frame(inner).grid(row=0, column=0, sticky="ew")
        self._build_crypto_frame(inner).grid(row=1, column=0, sticky="ew", pady=(10, 0))
        self._build_payload_frame(inner).grid(row=2, column=0, sticky="ew", pady=(10, 0))
        self._build_rs485_frame(inner).grid(row=3, column=0, sticky="ew", pady=(10, 0))

        return panel

    def _build_mqtt_frame(self, parent: ttk.Frame) -> ttk.LabelFrame:
        f = ttk.LabelFrame(parent, text="MQTT Settings", padding=10)
        f.columnconfigure(1, weight=1)

        self.mqtt_host_var = tk.StringVar(value=self.cfg["mqtt"].get("broker", "broker.hivemq.com"))
        self.mqtt_port_var = tk.StringVar(value=str(self.cfg["mqtt"].get("port", 1883)))
        self.mqtt_pub_var = tk.StringVar(value=self.cfg["mqtt"].get("pub_topic", ""))
        self.mqtt_cmd_pub_var = tk.StringVar(value=self.cfg["mqtt"].get("cmd_pub_topic", self.cfg["mqtt"].get("sub_topic_1", self.cfg["mqtt"].get("sub_topic", ""))))
        self.mqtt_sub1_var = tk.StringVar(value=self.cfg["mqtt"].get("sub_topic_1", self.cfg["mqtt"].get("sub_topic", "")))
        self.mqtt_sub2_var = tk.StringVar(value=self.cfg["mqtt"].get("sub_topic_2", ""))
        self.mqtt_client_id_var = tk.StringVar(value=self.cfg["mqtt"].get("client_id", "stm32_pubsub_01"))

        self.tx_period_var = tk.StringVar(value=str(int(self.cfg["mqtt"].get("tx_period_s", 5))))

        row = 0
        ttk.Label(f, text="Broker:").grid(row=row, column=0, sticky="w")
        ttk.Entry(f, textvariable=self.mqtt_host_var).grid(row=row, column=1, sticky="ew", padx=(8, 0))
        row += 1

        ttk.Label(f, text="Port:").grid(row=row, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(f, textvariable=self.mqtt_port_var, width=10).grid(row=row, column=1, sticky="w", padx=(8, 0), pady=(6, 0))
        row += 1

        ttk.Label(f, text="Publish topic:").grid(row=row, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(f, textvariable=self.mqtt_pub_var).grid(row=row, column=1, sticky="ew", padx=(8, 0), pady=(6, 0))
        row += 1

        ttk.Label(f, text="CMD publish topic:").grid(row=row, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(f, textvariable=self.mqtt_cmd_pub_var).grid(row=row, column=1, sticky="ew", padx=(8, 0), pady=(6, 0))
        row += 1

        ttk.Label(f, text="Subscribe topic 1:").grid(row=row, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(f, textvariable=self.mqtt_sub1_var).grid(row=row, column=1, sticky="ew", padx=(8, 0), pady=(6, 0))
        row += 1

        ttk.Label(f, text="Subscribe topic 2:").grid(row=row, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(f, textvariable=self.mqtt_sub2_var).grid(row=row, column=1, sticky="ew", padx=(8, 0), pady=(6, 0))
        row += 1

        ttk.Label(f, text="Client ID:").grid(row=row, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(f, textvariable=self.mqtt_client_id_var).grid(row=row, column=1, sticky="ew", padx=(8, 0), pady=(6, 0))
        row += 1

        # Transmission controls: period seconds
        ttk.Separator(f).grid(row=row, column=0, columnspan=2, sticky="ew", pady=(10, 10))
        row += 1

        ttk.Label(f, text="Transmission period (sec):").grid(row=row, column=0, sticky="w")
        ttk.Entry(f, textvariable=self.tx_period_var, width=10).grid(row=row, column=1, sticky="w", padx=(8, 0))
        row += 1
        ttk.Label(f, text="Sampling rate (sec):").grid(row=row, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(f, textvariable=self.sampling_rate_var, width=10).grid(row=row, column=1, sticky="w", padx=(8, 0), pady=(6, 0))
        ttk.Label(f, text="Enter whole-number seconds for transmission and sampling.").grid(row=row+1, column=0, columnspan=2, sticky="w", pady=(4, 0))
        row += 2

        btns = ttk.Frame(f)
        btns.grid(row=row, column=0, columnspan=2, sticky="w", pady=(10, 0))
        self.mqtt_connect_btn = ttk.Button(btns, text="Connect", command=self.on_mqtt_connect)
        self.mqtt_disconnect_btn = ttk.Button(btns, text="Disconnect", command=self.on_mqtt_disconnect, state="disabled")
        self.tx_start_btn = ttk.Button(btns, text="Start Transmission", command=self.on_tx_start, state="disabled")
        self.tx_stop_btn = ttk.Button(btns, text="Stop Transmission", command=self.on_tx_stop, state="disabled")
        self.tx_once_btn = ttk.Button(btns, text="Publish Status", command=self.on_tx_once, state="disabled")
        self.mqtt_connect_btn.grid(row=0, column=0, padx=(0, 6))
        self.mqtt_disconnect_btn.grid(row=0, column=1, padx=6)
        self.tx_start_btn.grid(row=0, column=2, padx=6)
        self.tx_stop_btn.grid(row=0, column=3, padx=6)
        self.tx_once_btn.grid(row=0, column=4, padx=6)

        ttk.Separator(f).grid(row=row + 1, column=0, columnspan=2, sticky="ew", pady=(10, 10))
        row += 2

        ttk.Label(f, text="CMD Publish Test", font=self.bold_font).grid(row=row, column=0, columnspan=2, sticky="w")
        row += 1

        self.cmd_name_var = tk.StringVar(value="SRATE")
        self.cmd_data_var = tk.StringVar(value="1")

        ttk.Label(f, text="Command:").grid(row=row, column=0, sticky="w", pady=(6, 0))
        self.cmd_name_combo = ttk.Combobox(
            f,
            textvariable=self.cmd_name_var,
            values=("NA", "SRATE", "STRAN", "STIME", "GOSTM"),
            state="readonly",
            width=18,
        )
        self.cmd_name_combo.grid(row=row, column=1, sticky="w", padx=(8, 0), pady=(6, 0))
        row += 1

        ttk.Label(f, text="CMD data:").grid(row=row, column=0, sticky="w", pady=(6, 0))
        self.cmd_data_entry = ttk.Entry(f, textvariable=self.cmd_data_var, width=18)
        self.cmd_data_entry.grid(row=row, column=1, sticky="w", padx=(8, 0), pady=(6, 0))
        row += 1

        ttk.Label(
            f,
            text="Uses Node ID from Message Payload section and publishes encrypted CMD_Message to the CMD topic.",
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(4, 0))
        row += 1


        self.cmd_publish_btn = ttk.Button(f, text="Publish CMD", command=self.on_cmd_publish, state="disabled")
        self.cmd_publish_btn.grid(row=row, column=0, columnspan=2, sticky="w", pady=(8, 0))

        ttk.Separator(f).grid(row=row + 1, column=0, columnspan=2, sticky="ew", pady=(10, 10))
        row += 2

        ttk.Label(f, text="Error Injection", font=self.bold_font).grid(row=row, column=0, columnspan=2, sticky="w")
        row += 1

        self.error_target_var = tk.StringVar(value="Telemetry")
        self.error_case_var = tk.StringVar(value="wrong / zero data")
        self.error_value_var = tk.StringVar(value="")

        ttk.Label(f, text="Target:").grid(row=row, column=0, sticky="w", pady=(6, 0))
        ttk.Combobox(
            f,
            textvariable=self.error_target_var,
            values=("Telemetry", "CMD"),
            state="readonly",
            width=18,
        ).grid(row=row, column=1, sticky="w", padx=(8, 0), pady=(6, 0))
        row += 1

        ttk.Label(f, text="Scenario:").grid(row=row, column=0, sticky="w", pady=(6, 0))
        self.error_case_combo = ttk.Combobox(
            f,
            textvariable=self.error_case_var,
            values=(
        "wrong / zero data",
        "invalid data bytes length",
        "invalid cmd id",
        "invalid iv length",
        "invalid key length",
        "wrong AES key",
        "invalid code version length",
        "wrong code version",
        "invalid sampling rate",
        "invalid transmission period",
        "payload shorter than 17 bytes",
        "invalid ciphertext length",
        "corrupted ciphertext",
            ),
            state="readonly",
            width=34,
        )
        self.error_case_combo.grid(row=row, column=1, sticky="w", padx=(8, 0), pady=(6, 0))
        row += 1

        ttk.Label(f, text="Optional value:").grid(row=row, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(f, textvariable=self.error_value_var, width=24).grid(row=row, column=1, sticky="w", padx=(8, 0), pady=(6, 0))
        row += 1

        ttk.Label(
            f,
            text="Examples: invalid CMD ID, key hex, code version hex, IV length, bad SRATE/STRAN value, or malformed payload length.",
            wraplength=420,
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(4, 0))
        row += 1

        self.error_inject_btn = ttk.Button(
            f,
            text="Inject Error Payload",
            command=self.on_inject_error,
            state="disabled",
        )
        self.error_inject_btn.grid(row=row, column=0, columnspan=2, sticky="w", pady=(8, 0))

        return f

    # Create the encryption section showing AES-CBC/PKCS7 parameters and framing info.
    def _build_crypto_frame(self, parent: ttk.Frame) -> ttk.LabelFrame:
        f = ttk.LabelFrame(parent, text="Encryption Settings (AES-128-CBC + PKCS7)", padding=10)
        f.columnconfigure(1, weight=1)

        self.key_hex_var = tk.StringVar(value=self.cfg["encryption"].get("key_hex", ""))
        self.code_version_var = tk.StringVar(value=self.cfg["encryption"].get("code_version_hex", "01"))

        ttk.Label(f, text="Key (hex, 16 bytes):").grid(row=0, column=0, sticky="w")
        ttk.Entry(f, textvariable=self.key_hex_var).grid(row=0, column=1, sticky="ew", padx=(8, 0))
        ttk.Label(f, text="IV mode:").grid(row=1, column=0, sticky="w", pady=(6, 0))
        iv_mode = ttk.Entry(f, state="readonly")
        iv_mode.insert(0, "Random per MQTT frame (automatic)")
        iv_mode.grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=(6, 0))
        ttk.Label(f, text="Code version (1 byte hex):").grid(row=2, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(f, textvariable=self.code_version_var, width=8).grid(row=2, column=1, sticky="w", padx=(8, 0), pady=(6, 0))

        note = ttk.Label(
            f,
            text="PKCS7 padding is standard. Each MQTT transmission prepends: 1-byte code version + 16-byte random IV + ciphertext. No fixed-IV fallback is used.",
            wraplength=420,
        )
        note.grid(row=3, column=0, columnspan=2, sticky="w", pady=(10, 0))

        self.framing_var = tk.StringVar(value="cipher=?   proto_len=?   pad_len=?   iv=?")
        ttk.Label(f, text="Framing:").grid(row=4, column=0, sticky="w", pady=(12, 0))
        framing_entry = ttk.Entry(f, textvariable=self.framing_var, state="readonly")
        framing_entry.grid(row=4, column=1, sticky="ew", padx=(8, 0), pady=(12, 0))

        return f

    # Create the message payload section and the payload preview area.
    def _build_payload_frame(self, parent: ttk.Frame) -> ttk.LabelFrame:
        f = ttk.LabelFrame(parent, text="Message Payload", padding=10)
        for c in range(4):
            f.columnconfigure(c, weight=1 if c in (1, 3) else 0)

        self.node_id_var = tk.StringVar(value=str(self.cfg.get("device_defaults", {}).get("node_id", 1)))
        self.sensor_id_var = tk.StringVar(value=str(self.cfg.get("device_defaults", {}).get("sensor_id", 1)))
        self.valve_state_var = tk.BooleanVar(value=False)
        self.flow_override_var = tk.StringVar(value="0.0")
        self.velocity_override_var = tk.StringVar(value="0.0")
        self.flow_day_override_var = tk.StringVar(value="0.0")
        self.flow_month_override_var = tk.StringVar(value="0.0")
        self.flow_year_override_var = tk.StringVar(value="0.0")
        self.tx_counter_var = tk.StringVar(value="0")
        try:
            ms0 = int(float(self.cfg["mqtt"].get("tx_period_s", 5)) * 1000)
        except Exception:
            ms0 = 5000
        self.tx_period_ms_display_var = tk.StringVar(value=str(ms0))
        self.payload_status_var = tk.StringVar(value="Not connected")
        self.error_display_var = tk.StringVar(value="No errors.")

        # New Soil & EC sensor variables
        self.soil_temp_override_var = tk.StringVar(value="25.0")
        self.soil_moist_override_var = tk.StringVar(value="45.0")
        self.soil_valid_var = tk.BooleanVar(value=True)
        self.ec_temp_override_var = tk.StringVar(value="24.5")
        self.ec_moist_override_var = tk.StringVar(value="42.0")
        self.ec_cond_override_var = tk.StringVar(value="350.0")
        self.ec_valid_var = tk.BooleanVar(value=True)
        self.sensor_mask_var = tk.StringVar(value="7")
        self.active_sensor_count_var = tk.StringVar(value="3")
        self.battery_voltage_var = tk.StringVar(
            value=str(self.cfg.get("device_defaults", {}).get("battery_voltage", 8.0))
        )

        ttk.Label(f, text="Node ID:").grid(row=0, column=0, sticky="w")
        ttk.Entry(f, textvariable=self.node_id_var, width=12).grid(row=0, column=1, sticky="w", padx=(8, 0))

        ttk.Label(f, text="Sensor ID:").grid(row=0, column=2, sticky="w", padx=(16, 0))
        ttk.Entry(f, textvariable=self.sensor_id_var, width=12).grid(row=0, column=3, sticky="w", padx=(8, 0))

        ttk.Label(f, text="Flow fallback:").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(f, textvariable=self.flow_override_var, width=12).grid(row=1, column=1, sticky="w", padx=(8, 0), pady=(8, 0))

        ttk.Label(f, text="Velocity fallback:").grid(row=1, column=2, sticky="w", padx=(16, 0), pady=(8, 0))
        ttk.Entry(f, textvariable=self.velocity_override_var, width=12).grid(row=1, column=3, sticky="w", padx=(8, 0), pady=(8, 0))

        ttk.Label(f, text="Flow/day fallback:").grid(row=2, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(f, textvariable=self.flow_day_override_var, width=12).grid(row=2, column=1, sticky="w", padx=(8, 0), pady=(8, 0))

        ttk.Label(f, text="Flow/month fallback:").grid(row=2, column=2, sticky="w", padx=(16, 0), pady=(8, 0))
        ttk.Entry(f, textvariable=self.flow_month_override_var, width=12).grid(row=2, column=3, sticky="w", padx=(8, 0), pady=(8, 0))

        ttk.Label(f, text="Flow/year fallback:").grid(row=3, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(f, textvariable=self.flow_year_override_var, width=12).grid(row=3, column=1, sticky="w", padx=(8, 0), pady=(8, 0))

        ttk.Label(f, text="TX Counter:").grid(row=3, column=2, sticky="w", padx=(16, 0), pady=(8, 0))
        ent_cnt = ttk.Entry(f, textvariable=self.tx_counter_var, width=12)
        ent_cnt.grid(row=3, column=3, sticky="w", padx=(8, 0), pady=(8, 0))
        ent_cnt.state(["readonly"])

        # Soil Sensor inputs
        ttk.Label(f, text="Soil Temp:").grid(row=4, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(f, textvariable=self.soil_temp_override_var, width=12).grid(row=4, column=1, sticky="w", padx=(8, 0), pady=(8, 0))

        ttk.Label(f, text="Soil Moist:").grid(row=4, column=2, sticky="w", padx=(16, 0), pady=(8, 0))
        ttk.Entry(f, textvariable=self.soil_moist_override_var, width=12).grid(row=4, column=3, sticky="w", padx=(8, 0), pady=(8, 0))

        ttk.Checkbutton(f, text="Soil Valid", variable=self.soil_valid_var).grid(row=5, column=0, columnspan=2, sticky="w", pady=(8, 0))

        ttk.Label(f, text="Sensor Mask:").grid(row=5, column=2, sticky="w", padx=(16, 0), pady=(8, 0))
        ttk.Entry(f, textvariable=self.sensor_mask_var, width=12).grid(row=5, column=3, sticky="w", padx=(8, 0), pady=(8, 0))

        # EC Sensor inputs
        ttk.Label(f, text="EC Temp:").grid(row=6, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(f, textvariable=self.ec_temp_override_var, width=12).grid(row=6, column=1, sticky="w", padx=(8, 0), pady=(8, 0))

        ttk.Label(f, text="EC Moist:").grid(row=6, column=2, sticky="w", padx=(16, 0), pady=(8, 0))
        ttk.Entry(f, textvariable=self.ec_moist_override_var, width=12).grid(row=6, column=3, sticky="w", padx=(8, 0), pady=(8, 0))

        ttk.Label(f, text="EC Cond:").grid(row=7, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(f, textvariable=self.ec_cond_override_var, width=12).grid(row=7, column=1, sticky="w", padx=(8, 0), pady=(8, 0))

        ttk.Checkbutton(f, text="EC Valid", variable=self.ec_valid_var).grid(row=7, column=2, columnspan=2, sticky="w", padx=(16, 0), pady=(8, 0))

        ttk.Label(f, text="Active Sensors:").grid(row=8, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(f, textvariable=self.active_sensor_count_var, width=12).grid(row=8, column=1, sticky="w", padx=(8, 0), pady=(8, 0))

        ttk.Label(f, text="Battery Voltage:").grid(row=8, column=2, sticky="w", padx=(16, 0), pady=(8, 0))
        ttk.Entry(f, textvariable=self.battery_voltage_var, width=12).grid(row=8, column=3, sticky="w", padx=(8, 0), pady=(8, 0))

        ttk.Label(
            f,
            text="The app reads RS-485 before TX. If sensor values are unavailable, these fallback values are used.",
            wraplength=420,
        ).grid(row=9, column=0, columnspan=4, sticky="w", pady=(8, 0))

        ttk.Label(f, textvariable=self.payload_status_var).grid(row=10, column=0, columnspan=4, sticky="w", pady=(10, 0))

        ttk.Separator(f).grid(row=11, column=0, columnspan=4, sticky="ew", pady=(10, 8))
        ttk.Label(f, text="ERROR Display", font=self.bold_font).grid(row=12, column=0, columnspan=4, sticky="w")
        self.error_display_text = tk.Text(f, height=4, wrap="word")
        self.error_display_text.configure(font=self.bold_font, foreground="#8b0000")
        self.error_display_text.grid(row=13, column=0, columnspan=4, sticky="ew", pady=(6, 0))
        self.error_display_text.insert("1.0", self.error_display_var.get())
        self.error_display_text.configure(state="disabled")

        return f

    # Create the RS-485 sensor section with live flow display, limits, and polling controls.
    def _build_rs485_frame(self, parent: ttk.Frame) -> ttk.LabelFrame:
        f = ttk.LabelFrame(parent, text="RS-485 Sensor (TUF-2000B)", padding=10)
        for c in range(6):
            f.columnconfigure(c, weight=1 if c in (1, 4) else 0)

        self.rs_enabled_var = tk.BooleanVar(value=bool(self.cfg.get("rs485", {}).get("enabled", False)))
        self.rs_port_var = tk.StringVar(value=self.cfg.get("rs485", {}).get("port", "COM3"))
        self.rs_baud_var = tk.StringVar(value=str(self.cfg.get("rs485", {}).get("baudrate", 9600)))
        self.rs_parity_var = tk.StringVar(value=self.cfg.get("rs485", {}).get("parity", "N"))
        self.rs_stopbits_var = tk.StringVar(value=str(self.cfg.get("rs485", {}).get("stopbits", 1)))
        self.rs_unit_var = tk.StringVar(value=str(self.cfg.get("rs485", {}).get("unit_id", 1)))
        self.rs_poll_ms_var = tk.StringVar(value=str(self.cfg.get("rs485", {}).get("poll_period_ms", 1000)))

        self.flow_min_var = tk.StringVar(value="")
        self.flow_max_var = tk.StringVar(value="")

        # Live value display (updated on Read / Poll)
        self.rs_flow_var = tk.StringVar(value="--")
        self.sensor_last_read_var.set("Last read: --")

        ttk.Checkbutton(f, text="Enable RS-485", variable=self.rs_enabled_var, command=self._refresh_status).grid(
            row=0, column=0, columnspan=2, sticky="w"
        )

        ttk.Label(f, text="Instant Flow:").grid(row=0, column=3, sticky="e")
        flow_lbl = ttk.Label(f, textvariable=self.rs_instant_flow_var)
        flow_lbl.grid(row=0, column=4, columnspan=2, sticky="w", padx=(8, 0))
        flow_lbl.configure(font=("Segoe UI", 11, "bold"))

        ttk.Label(f, text="COM Port:").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(f, textvariable=self.rs_port_var, width=12).grid(row=1, column=1, sticky="w", padx=(8, 0), pady=(8, 0))

        ttk.Label(f, text="Baudrate:").grid(row=1, column=3, sticky="e", padx=(16, 0), pady=(8, 0))
        ttk.Combobox(f, textvariable=self.rs_baud_var, values=["9600", "19200", "38400"], state="readonly", width=8).grid(
            row=1, column=4, sticky="w", padx=(8, 0), pady=(8, 0)
        )

        ttk.Label(f, text="Slave ID:").grid(row=2, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(f, textvariable=self.rs_unit_var, width=8).grid(row=2, column=1, sticky="w", padx=(8, 0), pady=(8, 0))

        ttk.Label(f, text="Poll (ms):").grid(row=2, column=3, sticky="e", padx=(16, 0), pady=(8, 0))
        ttk.Entry(f, textvariable=self.rs_poll_ms_var, width=10).grid(row=2, column=4, sticky="w", padx=(8, 0), pady=(8, 0))

        # Flow thresholds + flags
        ttk.Label(f, text="Flow Min:").grid(row=3, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(f, textvariable=self.flow_min_var, width=10).grid(row=3, column=1, sticky="w", padx=(8, 0), pady=(8, 0))
        # LED-style flag (min)
        self.flow_min_flag = tk.Canvas(f, width=22, height=22, highlightthickness=0)
        self._min_led = self.flow_min_flag.create_oval(3, 3, 19, 19, fill="gray", outline="#444")
        self.flow_min_flag.grid(row=3, column=2, sticky="w", padx=(8, 0), pady=(8, 0))

        ttk.Label(f, text="Flow Max:").grid(row=3, column=3, sticky="e", padx=(16, 0), pady=(8, 0))
        ttk.Entry(f, textvariable=self.flow_max_var, width=10).grid(row=3, column=4, sticky="w", padx=(8, 0), pady=(8, 0))
        # LED-style flag (max)
        self.flow_max_flag = tk.Canvas(f, width=22, height=22, highlightthickness=0)
        self._max_led = self.flow_max_flag.create_oval(3, 3, 19, 19, fill="gray", outline="#444")
        self.flow_max_flag.grid(row=3, column=5, sticky="w", padx=(8, 0), pady=(8, 0))

        values_box = ttk.LabelFrame(f, text="Values from received response frames", padding=8)
        values_box.grid(row=4, column=0, columnspan=6, sticky="ew", pady=(10, 0))
        for c in range(4):
            values_box.columnconfigure(c, weight=1)

        ttk.Label(values_box, text="Instant Flow:", font=self.bold_font).grid(row=0, column=0, sticky="w")
        ttk.Label(values_box, textvariable=self.rs_instant_flow_var).grid(row=0, column=1, sticky="w", padx=(8, 16))
        ttk.Label(values_box, text="Velocity:", font=self.bold_font).grid(row=0, column=2, sticky="w")
        ttk.Label(values_box, textvariable=self.rs_velocity_var).grid(row=0, column=3, sticky="w", padx=(8, 0))

        ttk.Label(values_box, text="Flow Today:", font=self.bold_font).grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Label(values_box, textvariable=self.rs_flow_today_var).grid(row=1, column=1, sticky="w", padx=(8, 16), pady=(6, 0))
        ttk.Label(values_box, text="Flow Month:", font=self.bold_font).grid(row=1, column=2, sticky="w", pady=(6, 0))
        ttk.Label(values_box, textvariable=self.rs_flow_month_var).grid(row=1, column=3, sticky="w", padx=(8, 0), pady=(6, 0))

        ttk.Label(values_box, text="Flow Year:", font=self.bold_font).grid(row=2, column=0, sticky="w", pady=(6, 0))
        ttk.Label(values_box, textvariable=self.rs_flow_year_var).grid(row=2, column=1, sticky="w", padx=(8, 16), pady=(6, 0))

        btns = ttk.Frame(f)
        btns.grid(row=5, column=0, columnspan=6, sticky="w", pady=(10, 0))
        self.rs_connect_btn = ttk.Button(btns, text="Connect Sensor", command=self.on_rs_connect)
        self.rs_disconnect_btn = ttk.Button(btns, text="Disconnect Sensor", command=self.on_rs_disconnect, state="disabled")
        self.rs_read_btn = ttk.Button(btns, text="Read", command=self.on_rs_read_once, state="disabled")
        self.rs_poll_btn = ttk.Button(btns, text="Start Polling", command=self.on_rs_toggle_poll, state="disabled")
        self.rs_connect_btn.grid(row=0, column=0, padx=(0, 6))
        self.rs_disconnect_btn.grid(row=0, column=1, padx=6)
        self.rs_read_btn.grid(row=0, column=2, padx=6)
        self.rs_poll_btn.grid(row=0, column=3, padx=6)

        self.rs_status_var = tk.StringVar(value="Sensor: disabled")
        ttk.Label(f, textvariable=self.rs_status_var).grid(row=6, column=0, columnspan=6, sticky="w", pady=(8, 0))

        return f

    # Create notebook-style log panels so the UI fits smaller laptop screens better.
    def _build_logs_frame(self, parent: ttk.Frame) -> ttk.Frame:
        logs = ttk.LabelFrame(parent, text="Logs", padding=8)
        logs.columnconfigure(0, weight=1)
        logs.rowconfigure(0, weight=1)

        notebook = ttk.Notebook(logs)
        notebook.grid(row=0, column=0, sticky="nsew")

        def _make_log_panel(container, title, clear_cmd, header_var=None):
            frame = ttk.Frame(container, padding=6)
            frame.columnconfigure(0, weight=1)
            frame.rowconfigure(1, weight=1)

            btns = ttk.Frame(frame)
            btns.grid(row=0, column=0, sticky="ew")
            ttk.Button(btns, text="Clear", command=clear_cmd).pack(side="left")
            if header_var is not None:
                ttk.Label(btns, textvariable=header_var).pack(side="left", padx=(8, 0))

            txt = tk.Text(frame, wrap="none")
            txt.configure(font=self.mono_font)
            txt.grid(row=1, column=0, sticky="nsew", pady=(6, 0))

            vscroll = ttk.Scrollbar(frame, orient="vertical", command=txt.yview)
            vscroll.grid(row=1, column=1, sticky="ns", pady=(6, 0))
            hscroll = ttk.Scrollbar(frame, orient="horizontal", command=txt.xview)
            hscroll.grid(row=2, column=0, sticky="ew")
            txt.configure(yscrollcommand=vscroll.set, xscrollcommand=hscroll.set)
            return frame, txt

        rx_frame, self.rx_text = _make_log_panel(notebook, "RX Commands", lambda: self._clear_text(self.rx_text))
        notebook.add(rx_frame, text="MQTT RX")

        sensor_frame, self.sensor_text = _make_log_panel(
            notebook,
            "Sensor TX Log",
            lambda: self._clear_text(self.sensor_text),
            header_var=self.sensor_last_read_var,
        )
        notebook.add(sensor_frame, text="Sensor")

        tx_frame, self.tx_text = _make_log_panel(notebook, "Published TX Messages", lambda: self._clear_text(self.tx_text))
        notebook.add(tx_frame, text="MQTT TX")

        return logs

    # =========================
    # Logging helpers
    # =========================
    # Clear all text from one log widget.
    def _clear_text(self, widget: tk.Text):
        widget.delete("1.0", "end")

    # Append one line (or a blank separator) to a log widget and auto-scroll to the end.
    def _append(self, widget: tk.Text, line: str):
        if line:
            widget.insert("end", line + "\n")
        else:
            widget.insert("end", "\n")
        widget.see("end")

    def _ui_safe_append(self, widget: tk.Text, line: str):
        # Tkinter widgets must only be touched from the main UI thread.
        self._ui_queue.put((widget, line))

    def _drain_ui_queue(self):
        try:
            while True:
                widget, line = self._ui_queue.get_nowait()
                self._append(widget, line)
        except queue.Empty:
            pass
        self.root.after(50, self._drain_ui_queue)

    def log_rx(self, line: str):
        if line:
            self._ui_safe_append(self.rx_text, f"[{_now_ts()}] {line}")
        else:
            self._ui_safe_append(self.rx_text, "")

    def log_sensor(self, line: str):
        if line:
            self._ui_safe_append(self.sensor_text, f"[{_now_ts()}] {line}")
        else:
            self._ui_safe_append(self.sensor_text, "")

    def log_tx(self, line: str):
        if line:
            self._ui_safe_append(self.tx_text, f"[{_now_ts()}] {line}")
        else:
            self._ui_safe_append(self.tx_text, "")

    # =========================
    # Status / Payload preview
    # =========================
    # Refresh top-level status text and enable/disable buttons depending on runtime state.
    def _refresh_status(self):
        mqtt_ok = "ON" if self.mqtt else "OFF"
        rs_ok = "ON" if (self.rs and self.rs.is_connected) else "OFF"
        self.status_var.set(f"MQTT: {mqtt_ok}   RS-485: {rs_ok}")

        # enable/disable controls
        if self.mqtt:
            self.mqtt_connect_btn.config(state="disabled")
            self.mqtt_disconnect_btn.config(state="normal")
            self.tx_once_btn.config(state="normal")
            self.tx_start_btn.config(state="normal")
            if hasattr(self, "cmd_publish_btn"):
                self.cmd_publish_btn.config(state="normal")
            if hasattr(self, "error_inject_btn"):
                self.error_inject_btn.config(state="normal")
            self.payload_status_var.set("Connected")
        else:
            self.mqtt_connect_btn.config(state="normal")
            self.mqtt_disconnect_btn.config(state="disabled")
            self.tx_once_btn.config(state="disabled")
            self.tx_start_btn.config(state="disabled")
            self.tx_stop_btn.config(state="disabled")
            if hasattr(self, "cmd_publish_btn"):
                self.cmd_publish_btn.config(state="disabled")
            if hasattr(self, "error_inject_btn"):
                self.error_inject_btn.config(state="disabled")
            self.payload_status_var.set("Not connected")

        self._sync_period_ms_display()
        self._clear_error()

        if self.rs_enabled_var.get():
            self.rs_connect_btn.config(state="normal")
        else:
            self.rs_connect_btn.config(state="disabled")
            self.rs_disconnect_btn.config(state="disabled")
            self.rs_read_btn.config(state="disabled")
            self.rs_poll_btn.config(state="disabled")
            self.rs_status_var.set("Sensor: disabled")
            self._set_flag(self.flow_min_flag, "gray")
            self._set_flag(self.flow_max_flag, "gray")

    # Keep the "Periodic Publish (ms)" readout synchronized with the period-in-seconds control.
    def _sync_period_ms_display(self):
        try:
            self.tx_period_ms_display_var.set(str(int(float(self.tx_period_var.get().strip()) * 1000)))
        except Exception:
            pass


    # Rebuild the payload preview from the latest GUI values and/or latest sensor flow reading.
    def _update_error_display(self):
        msg = getattr(self, "_last_error_msg", "No errors.") or "No errors."
        self.error_display_var.set(msg)
        if hasattr(self, "error_display_text"):
            self.error_display_text.configure(state="normal")
            self.error_display_text.delete("1.0", "end")
            self.error_display_text.insert("1.0", msg)
            self.error_display_text.configure(state="disabled")

    def _set_error(self, msg: str):
        self._last_error_msg = msg or "No errors."
        self._update_error_display()

    def _clear_error(self):
        self._last_error_msg = "No errors."
        self._update_error_display()
    # =========================
    # MQTT
    # =========================
    # Parse the AES key and code version entered by the user.
    def _parse_key_config(self) -> bytes:
        key_hex = self.key_hex_var.get().strip().replace(" ", "")
        key = bytes.fromhex(key_hex)
        if len(key) != 16:
            raise ValueError("AES key must be 16 bytes (32 hex chars).")
        return key

    # Connect to the MQTT broker and wire RX callbacks into the GUI logs.
    def on_mqtt_connect(self):
        try:
            key = self._parse_key_config()
            host = self.mqtt_host_var.get().strip()
            port = int(self.mqtt_port_var.get().strip())
            client_id = self.mqtt_client_id_var.get().strip() or "stm32_pubsub_01"
            sub = [t for t in [self.mqtt_sub1_var.get().strip(), self.mqtt_sub2_var.get().strip()] if t]

            def on_status(line: str):
                # Route every inbound-MQTT diagnostic to the RX tab.
                rx_markers = (
                    "[RX",
                    "MQTT frame bytes:",
                    "Frame header:",
                    "RAW MQTT RX",
                    "Subscribed to:",
                )
                if (not line) or any(line.startswith(marker) for marker in rx_markers):
                    self.log_rx(line)
                else:
                    self.log_tx(line)
                
            self.mqtt = MqttNodeClient(
                broker_host=host,
                broker_port=port,
                aes_key_16=key,
                client_id=client_id,
                subscribe_topics=sub,
                on_plaintext=self.on_mqtt_plaintext,
                on_status=on_status,
                debug=True,
            )
            self.mqtt.connect(keepalive=int(self.cfg.get("mqtt", {}).get("keepalive", 60)))
            self._clear_error()
            self.log_tx("MQTT connected.")
            self._refresh_status()
        except Exception as e:
            self._set_error(str(e))
            messagebox.showerror("MQTT Connect Error", str(e))

    # Disconnect from MQTT and stop any active periodic telemetry transmission.
    def on_mqtt_disconnect(self):
        try:
            self.on_tx_stop()
            if self.mqtt:
                self.mqtt.disconnect()
                self.mqtt = None
            self.framing_var.set("cipher=?   proto_len=?   pad_len=?   iv=?")
            self.log_tx("MQTT disconnected.")
            self._refresh_status()
        except Exception as e:
            self._set_error(str(e))
            messagebox.showerror("MQTT Disconnect Error", str(e))

    def on_mqtt_plaintext(self, topic: str, plain: bytes):
        """
        Application-layer callback invoked after mqtt_impl has already decrypted RX payload.

        At this point the bytes are plaintext protobuf, so this function only tries to
        parse them for a readable RX summary in the GUI.
        """
        try:
            import messages_pb2
            cmd = messages_pb2.CMD_Message()
            cmd.ParseFromString(plain)
            name = CMD_NAMES.get(cmd.cmd_id, "UNKNOWN")
            self.log_rx(f"CMD parsed: node={cmd.node_id} cmd={cmd.cmd_id}({name}) data={cmd.cmd_data}")
            self.command_state, summary = command_impl.apply_command(self.command_state, plain)
            if summary["cmd_id"] == 1:
                self.rs_poll_ms_var.set(str(summary["sampling_rate_sec"] * 1000))
                self.sampling_rate_var.set(str(summary["sampling_rate_sec"]))
            elif summary["cmd_id"] == 2:
                self.tx_period_var.set(str(summary["tx_period_sec"]))
                self.tx_period_ms_display_var.set(str(summary["tx_period_sec"] * 1000))
            elif summary["cmd_id"] == 3:
                self.command_state.system_time = summary["system_time"]
            self.log_rx(f"CMD action: {summary['result']}")
            if summary["telemetry_requested"] and self.mqtt:
                self.log_rx("CMD action: publishing TelemetryMessage response for GOSTM.")
                self._publish_telemetry_response("GOSTM")
        except Exception:
            pass

    # =========================
    # Telemetry TX
    # =========================

# Validate a positive whole-number seconds field.
    def _validate_positive_seconds(self, raw: str, label: str) -> int:
        raw = (raw or "").strip()
        if not raw:
            raise ValueError(f"{label} is required.")
        if any(ch in raw for ch in (".", "e", "E")):
            raise ValueError(f"{label} must be a whole number of seconds.")
        try:
            value = int(raw)
        except Exception:
            raise ValueError(f"{label} must be a whole number of seconds.")
        if value < 1:
            raise ValueError(f"{label} must be at least 1 second.")
        return value

    # Validate the transmission period control while enforcing the requested rate range.

    def _validate_tx_period(self) -> int:
        return self._validate_positive_seconds(self.tx_period_var.get(), "Transmission period")

    # Validate the sampling-rate control used by command publishing and telemetry metadata.

    def _validate_sampling_rate(self) -> int:
        return self._validate_positive_seconds(self.sampling_rate_var.get(), "Sampling rate")

        # Build the plaintext protobuf telemetry bytes before padding and AES encryption.

    def _collect_measurements(self) -> dict:
        node_id = int(self.node_id_var.get())
        sensor_id = int(self.sensor_id_var.get())

        last = self.last_measurements or {}

        flow = last.get("flow_rate")
        if flow is None:
            if self.rs and self.rs.is_connected and self.last_flow is not None:
                flow = float(self.last_flow)
            else:
                flow = self._safe_float_from_var(self.flow_override_var, 0.0)

        velocity = last.get("velocity")
        if velocity is None:
            velocity = self._safe_float_from_var(
                self.rs_velocity_var,
                self._safe_float_from_var(self.velocity_override_var, 0.0),
            )

        flow_per_day = last.get("flow_rate_per_day")
        if flow_per_day is None:
            flow_per_day = self._safe_float_from_var(
                self.rs_flow_today_var,
                self._safe_float_from_var(self.flow_day_override_var, 0.0),
            )

        flow_per_month = last.get("flow_rate_per_month")
        if flow_per_month is None:
            flow_per_month = self._safe_float_from_var(
                self.rs_flow_month_var,
                self._safe_float_from_var(self.flow_month_override_var, 0.0),
            )

        flow_per_year = last.get("flow_rate_per_year")
        if flow_per_year is None:
            flow_per_year = self._safe_float_from_var(
                self.rs_flow_year_var,
                self._safe_float_from_var(self.flow_year_override_var, 0.0),
            )

        # Collect new soil and EC fields
        soil_temp = self._safe_float_from_var(self.soil_temp_override_var, 25.0)
        soil_moist = self._safe_float_from_var(self.soil_moist_override_var, 45.0)
        soil_valid = 1 if self.soil_valid_var.get() else 0

        ec_temp = self._safe_float_from_var(self.ec_temp_override_var, 24.5)
        ec_moist = self._safe_float_from_var(self.ec_moist_override_var, 42.0)
        ec_cond = self._safe_float_from_var(self.ec_cond_override_var, 350.0)
        ec_valid = 1 if self.ec_valid_var.get() else 0

        try:
            sensor_mask = int(self.sensor_mask_var.get())
        except Exception:
            sensor_mask = 7

        try:
            active_sensor_count = int(self.active_sensor_count_var.get())
        except Exception:
            active_sensor_count = 3

        battery_voltage = self._safe_float_from_var(self.battery_voltage_var, 8.0)

        timestamp = int(time.time())
        return {
            "node_id": node_id,
            "sensor_id": sensor_id,
            "flow_rate": float(flow),
            "velocity": float(velocity),
            "flow_rate_per_day": float(flow_per_day),
            "flow_rate_per_month": float(flow_per_month),
            "flow_rate_per_year": float(flow_per_year),
            "timestamp": timestamp,
            "soil_temperature": float(soil_temp),
            "soil_moisture": float(soil_moist),
            "soil_moisture_temp_valid": int(soil_valid),
            "ec_temperature": float(ec_temp),
            "ec_moisture": float(ec_moist),
            "electrical_conductivity": float(ec_cond),
            "soil_moisture_temp_ec_valid": int(ec_valid),
            "sensor_mask": int(sensor_mask),
            "active_sensor_count": int(active_sensor_count),
            "battery_voltage": float(battery_voltage)
        }

    def _safe_float_from_var(self, var, default: float = 0.0) -> float:
        try:
            raw = var.get() if hasattr(var, "get") else var
            raw = str(raw).strip()
            if not raw or raw == "--":
                return float(default)
            match = re.search(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?", raw.replace(",", ""))
            if not match:
                return float(default)
            return float(match.group(0))
        except Exception:
            return float(default)

    def _ensure_sensor_data(self) -> bool:
        if self.rs and self.rs.is_connected:
            ok = self.on_rs_read_once()
            if not ok:
                self.log_tx("[WARN] Sensor read failed before TX; using last/fallback values if available.")
            return bool(ok)
        return False

    def _require_meaningful_measurements(self, values: dict):
        numeric_keys = (
            "flow_rate",
            "velocity",
            "flow_rate_per_day",
            "flow_rate_per_month",
            "flow_rate_per_year",
        )
        if all(abs(float(values.get(k, 0.0))) < 1e-12 for k in numeric_keys):
            raise ValueError("No valid sensor or fallback data available for TX.")

    def _build_status_plain(self) -> bytes:
        values = self._collect_measurements()
        self._require_meaningful_measurements(values)
        return protobuf_impl.build_status(
            node_id=values["node_id"],
            sensor_id=values["sensor_id"],
            flow_rate=values["flow_rate"],
            timestamp=values["timestamp"],
            velocity=values["velocity"],
            flow_rate_per_day=values["flow_rate_per_day"],
            flow_rate_per_month=values["flow_rate_per_month"],
            flow_rate_per_year=values["flow_rate_per_year"],
            node_status=1 if self.valve_state_var.get() else 0,
            soil_temperature=values["soil_temperature"],
            soil_moisture=values["soil_moisture"],
            soil_moisture_temp_valid=values["soil_moisture_temp_valid"],
            ec_temperature=values["ec_temperature"],
            ec_moisture=values["ec_moisture"],
            electrical_conductivity=values["electrical_conductivity"],
            soil_moisture_temp_ec_valid=values["soil_moisture_temp_ec_valid"],
            active_sensor_count=values["active_sensor_count"],
            sensor_mask=values["sensor_mask"],
            battery_voltage=values["battery_voltage"]
        )

    def _build_telemetry_plain(self) -> bytes:
        values = self._collect_measurements()
        self._require_meaningful_measurements(values)
        try:
            sampling_rate_sec = self._validate_sampling_rate()
        except Exception:
            try:
                sampling_rate_sec = max(1, int(float(self.rs_poll_ms_var.get()) / 1000))
            except Exception:
                sampling_rate_sec = max(1, int(self.command_state.sampling_rate_sec))
        transmission_rate_sec = self._validate_tx_period()
        self.command_state.sampling_rate_sec = sampling_rate_sec
        self.command_state.tx_period_sec = transmission_rate_sec
        plain = protobuf_impl.build_telemetry(
            node_id=values["node_id"],
            sensor_id=values["sensor_id"],
            flow_rate=values["flow_rate"],
            timestamp=values["timestamp"],
            sampling_rate=sampling_rate_sec,
            transmission_rate=transmission_rate_sec,
            battery_voltage=values["battery_voltage"],
            reserved2=0,
            reserved3=0,
            active_sensor_count=values["active_sensor_count"],
            velocity=values["velocity"],
            flow_rate_per_day=values["flow_rate_per_day"],
            flow_rate_per_month=values["flow_rate_per_month"],
            flow_rate_per_year=values["flow_rate_per_year"],
            node_status=1 if self.valve_state_var.get() else 0,
            soil_temperature=values["soil_temperature"],
            soil_moisture=values["soil_moisture"],
            soil_moisture_temp_valid=values["soil_moisture_temp_valid"],
            ec_temperature=values["ec_temperature"],
            ec_moisture=values["ec_moisture"],
            electrical_conductivity=values["electrical_conductivity"],
            soil_moisture_temp_ec_valid=values["soil_moisture_temp_ec_valid"],
            sensor_mask=values["sensor_mask"]
        )
        return plain

    # Publish one telemetry frame immediately and log framing metadata plus raw ciphertext bytes.

    def _build_cmd_plain(self) -> tuple[bytes, int, int, int]:
        """
        Build a plaintext CMD_Message from the GUI controls in the MQTT section.

        Returns:
        - serialized protobuf bytes
        - node_id
        - cmd_id
        - cmd_data
        """
        cmd_name = (self.cmd_name_var.get().strip() or "NA").upper()
        name_to_id = {v: k for k, v in CMD_NAMES.items()}
        if cmd_name not in name_to_id:
            raise ValueError(f"Unsupported command name: {cmd_name}")

        node_id = int(self.node_id_var.get().strip())
        cmd_id = int(name_to_id[cmd_name])

        if cmd_name == "GOSTM":
            cmd_data = 0
        elif cmd_name == "SRATE":
            cmd_data = self._validate_positive_seconds(self.cmd_data_var.get(), "Sampling rate")
        elif cmd_name == "STRAN":
            cmd_data = self._validate_positive_seconds(self.cmd_data_var.get(), "Transmission period")
        elif cmd_name == "STIME":
            raw_data = self.cmd_data_var.get().strip()
            if not raw_data:
                raw_data = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self.cmd_data_var.set(raw_data)
            try:
                cmd_data = int(datetime.strptime(raw_data, "%Y-%m-%d %H:%M:%S").timestamp())
            except Exception:
                cmd_data = int(raw_data)
        else:
            raw_data = self.cmd_data_var.get().strip()
            cmd_data = int(raw_data) if raw_data else 0

        msg = messages_pb2.CMD_Message()
        msg.node_id = node_id
        msg.cmd_id = cmd_id
        msg.cmd_data = cmd_data
        return msg.SerializeToString(), node_id, cmd_id, cmd_data

    def on_cmd_publish(self):
        if not self.mqtt:
            return
        try:
            cmd_name_ui = (self.cmd_name_var.get() or "").strip().upper()
            if cmd_name_ui == "SRATE":
                self.cmd_data_var.set(str(self._validate_sampling_rate()))
            elif cmd_name_ui == "STRAN":
                self.cmd_data_var.set(str(self._validate_tx_period()))
            elif cmd_name_ui == "STIME":
                self.cmd_data_var.set(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            elif cmd_name_ui == "GOSTM":
                self.cmd_data_var.set("")

            plain, node_id, cmd_id, cmd_data = self._build_cmd_plain()
            topic = self.mqtt_cmd_pub_var.get().strip()
            if not topic:
                raise ValueError("CMD publish topic is empty.")

            frame = self.mqtt.publish_plaintext(topic, plain, qos=1)
            cmd_name = CMD_NAMES.get(cmd_id, "UNKNOWN")
            self._clear_error()
            self.framing_var.set(
                f"cipher={frame['cipher_len']}   proto_len={frame['proto_len']}   pad_len={frame['pad_len']}   iv={frame['iv_hex']}"
            )

            if cmd_name_ui == "GOSTM":
                self.log_tx(
                    f"[CMD TX#{frame['tx_counter']}] topic={topic} node={node_id} cmd={cmd_id}({cmd_name}) no-data "
                    f"proto_len={frame['proto_len']} pad_len={frame['pad_len']} cipher_len={frame['cipher_len']} frame_len={frame['frame_len']}"
                )
            elif cmd_name_ui == "STIME":
                self.log_tx(
                    f"[CMD TX#{frame['tx_counter']}] topic={topic} node={node_id} cmd={cmd_id}({cmd_name}) data={cmd_data} time='{self.cmd_data_var.get()}' "
                    f"proto_len={frame['proto_len']} pad_len={frame['pad_len']} cipher_len={frame['cipher_len']} frame_len={frame['frame_len']}"
                )
            else:
                self.log_tx(
                    f"[CMD TX#{frame['tx_counter']}] topic={topic} node={node_id} cmd={cmd_id}({cmd_name}) data={cmd_data} "
                    f"proto_len={frame['proto_len']} pad_len={frame['pad_len']} cipher_len={frame['cipher_len']} frame_len={frame['frame_len']}"
                )

            self.log_tx(f"MQTT frame bytes: {_hex_bytes(frame['payload'])}")
            self.log_tx(f"Frame header: code_ver={frame['code_version']} iv={frame['iv_hex']}")
            self.log_tx(f"Ciphertext bytes: {_hex_bytes(frame['ciphertext'])}")
            self.log_tx(f"Proto frame bytes: {_hex_bytes(plain)}")
            self.log_tx("")
        except Exception as e:
            self._set_error(str(e))
            self.log_tx(f"[CMD TX][ERROR] {e}")

    def _build_command_plain_override(self, cmd_name: str, raw_value: str) -> bytes:
        """
        Build a command payload for error injection.

        For values that cannot be represented by the uint64 protobuf field
        (for example "-1" or "abc"), we intentionally send non-protobuf bytes
        so the receiver exercises its parse-failure path after decryption.
        """
        cmd_name = (cmd_name or "").strip().upper()
        name_to_id = {v: k for k, v in CMD_NAMES.items()}
        if cmd_name not in name_to_id:
            raise ValueError(f"Unsupported command name for injection: {cmd_name}")

        raw_value = (raw_value or "").strip()
        if raw_value and (raw_value.startswith("-") or not raw_value.isdigit()):
            return f"{cmd_name}={raw_value}".encode("utf-8")

        msg = messages_pb2.CMD_Message()
        msg.node_id = int(self.node_id_var.get().strip())
        msg.cmd_id = int(name_to_id[cmd_name])
        msg.cmd_data = int(raw_value or "0")
        return msg.SerializeToString()

    def _current_error_target(self) -> tuple[str, str]:
        target = (self.error_target_var.get() or "Telemetry").strip()
        if target == "CMD":
            topic = self.mqtt_cmd_pub_var.get().strip()
        else:
            target = "Telemetry"
            topic = self.mqtt_pub_var.get().strip()
        if not topic:
            raise ValueError("Error-injection publish topic is empty.")
        return target, topic

    def _build_base_plain_for_injection(self, target: str) -> bytes:
        if target == "CMD":
            return self._build_cmd_plain()[0]
        return self._build_telemetry_plain()

    def _publish_injected_payload(self, topic: str, payload: bytes, case_name: str, extra_lines: list[str] | None = None):
        result = self.mqtt.publish_raw(topic, payload, qos=1, note=case_name)
        self.tx_counter_var.set(str(result["tx_counter"]))
        self.framing_var.set(f"cipher=?   proto_len=?   pad_len=?   iv=?   frame_len={result['frame_len']}")
        self.log_tx(
            f"[ERR TX#{result['tx_counter']}] case={case_name} topic={topic} frame_len={result['frame_len']}"
        )
        self.log_tx(f"MQTT frame bytes: {_hex_bytes(result['payload'])}")
        self.log_tx("")
        for line in (extra_lines or []):
            self.log_tx(line)
        self.log_tx("")

    def on_inject_error(self):
        if not self.mqtt:
            return
        try:
            case_name = (self.error_case_var.get() or "").strip()
            target, topic = self._current_error_target()
            raw_value = (self.error_value_var.get() or "").strip()

            base_plain = self._build_base_plain_for_injection(target)
            good_frame = self.mqtt.encrypt_frame_static(
                plaintext=base_plain,
                aes_key_16=self.mqtt.aes_key_16,
                code_version_1=self.mqtt.code_version_1,
            )
            payload = good_frame["payload"]
            extra_lines = [f"Injection target={target}"]

            if case_name == "wrong / zero data":
                payload = self.mqtt.encrypt_frame_static(
                    plaintext=(b"\x00" * 16),
                    aes_key_16=self.mqtt.aes_key_16,
                    code_version_1=self.mqtt.code_version_1,
                )["payload"]
                extra_lines.append("Injected 16 zero plaintext bytes before encryption.")
            elif case_name == "invalid data bytes length":
                bad_len = int(raw_value or "3")
                payload = self.mqtt.encrypt_frame_static(
                    plaintext=os.urandom(max(1, bad_len)),
                    aes_key_16=self.mqtt.aes_key_16,
                    code_version_1=self.mqtt.code_version_1,
                )["payload"]
                extra_lines.append(f"Injected random plaintext length={max(1, bad_len)}.")
            elif case_name == "invalid cmd id":
                bad_cmd_id = int(raw_value or "255")
                if target != "CMD":
                    raise ValueError("invalid cmd id scenario is valid only when Target=CMD.")
                cmd_msg = messages_pb2.CMD_Message()
                cmd_msg.ParseFromString(base_plain)
                cmd_msg.cmd_id = bad_cmd_id
                payload = self.mqtt.encrypt_frame_static(
                    plaintext=cmd_msg.SerializeToString(),
                    aes_key_16=self.mqtt.aes_key_16,
                    code_version_1=self.mqtt.code_version_1,
                )["payload"]
                extra_lines.append(f"Injected CMD_Message with cmd_id={bad_cmd_id}.")
            elif case_name == "invalid iv length":
                iv_len = int(raw_value or "8")
                iv = os.urandom(max(0, iv_len))
                payload = self.mqtt.code_version_1 + iv + good_frame["ciphertext"]
                extra_lines.append(f"Injected IV length={len(iv)} bytes.")
            elif case_name == "invalid key length":
                bad_key_hex = raw_value.replace(" ", "") or "0011"
                bad_key = bytes.fromhex(bad_key_hex)
                if len(bad_key) == 16:
                    raise ValueError("Optional value must decode to a non-16-byte AES key for this scenario.")
                # Exercise the local guard intentionally; this scenario should be blocked before publish.
                try:
                    self.mqtt.encrypt_frame_static(
                        plaintext=base_plain,
                        aes_key_16=bad_key,
                        code_version_1=self.mqtt.code_version_1,
                    )
                except Exception as e:
                    self._clear_error()
                    self.log_tx(f"[ERR INJECT][LOCAL] invalid key length blocked before publish: {e}")
                    self.log_tx("")
                    return
            elif case_name == "wrong AES key":
                bad_key_hex = raw_value.replace(" ", "") or ("FF" * 16)
                bad_key = bytes.fromhex(bad_key_hex)
                payload = self.mqtt.encrypt_frame_static(
                    plaintext=base_plain,
                    aes_key_16=bad_key,
                    code_version_1=self.mqtt.code_version_1,
                )["payload"]
                extra_lines.append(f"Encrypted with alternate AES key={bad_key.hex()}.")
            elif case_name == "invalid code version length":
                code_len = int(raw_value or "0")
                bad_code = os.urandom(max(0, code_len))
                payload = bad_code + good_frame["payload"][1:]
                extra_lines.append(f"Injected code-version length={len(bad_code)} bytes.")
            elif case_name == "wrong code version":
                bad_code_hex = raw_value.replace(" ", "") or "FF"
                bad_code = bytes.fromhex(bad_code_hex)
                if len(bad_code) != 1:
                    raise ValueError("Wrong code version must still be exactly 1 byte (2 hex chars).")
                payload = bad_code + good_frame["payload"][1:]
                extra_lines.append(f"Injected alternate code version={bad_code.hex()}.")
            elif case_name == "invalid sampling rate":
                topic = self.mqtt_cmd_pub_var.get().strip()
                bad_value = raw_value or "0"
                plain = self._build_command_plain_override("SRATE", bad_value)
                payload = self.mqtt.encrypt_frame_static(
                    plaintext=plain,
                    aes_key_16=self.mqtt.aes_key_16,
                    code_version_1=self.mqtt.code_version_1,
                )["payload"]
                extra_lines.append(f"Injected SRATE value={bad_value!r}.")
            elif case_name == "invalid transmission period":
                topic = self.mqtt_cmd_pub_var.get().strip()
                bad_value = raw_value or "0"
                plain = self._build_command_plain_override("STRAN", bad_value)
                payload = self.mqtt.encrypt_frame_static(
                    plaintext=plain,
                    aes_key_16=self.mqtt.aes_key_16,
                    code_version_1=self.mqtt.code_version_1,
                )["payload"]
                extra_lines.append(f"Injected STRAN value={bad_value!r}.")
            elif case_name == "payload shorter than 17 bytes":
                short_len = int(raw_value or "8")
                payload = os.urandom(max(1, min(short_len, 16)))
                extra_lines.append(f"Injected raw payload length={len(payload)} (<17).")
            elif case_name == "invalid ciphertext length":
                cipher_len = int(raw_value or "15")
                payload = self.mqtt.code_version_1 + os.urandom(16) + os.urandom(max(0, cipher_len))
                extra_lines.append(f"Injected ciphertext length={max(0, cipher_len)} bytes.")
            elif case_name == "corrupted ciphertext":
                mutable = bytearray(payload)
                if len(mutable) <= 17:
                    raise ValueError("Base frame too short to corrupt.")
                mutable[-1] ^= 0x01
                payload = bytes(mutable)
                extra_lines.append("Flipped the last ciphertext bit.")
            else:
                raise ValueError(f"Unsupported error-injection case: {case_name}")

            self._clear_error()
            self._publish_injected_payload(topic, payload, case_name, extra_lines)
        except Exception as e:
            self._set_error(str(e))
            self.log_tx(f"[ERR INJECT][ERROR] {e}")
            self.log_tx("")

    def _publish_application_plain(self, plain: bytes, message_name: str, reason: str) -> dict:
        if not self.mqtt:
            raise ValueError("MQTT is not connected.")
        topic = self.mqtt_pub_var.get().strip()
        
        if message_name == "TELEMETRY":
            if topic.endswith("Status"):
                topic = topic[:-6] + "Telemetry"
            elif topic.lower().endswith("status"):
                topic = topic[:-6] + "Telemetry"
                
        if not topic:
            raise ValueError("Publish topic is empty.")
        frame = self.mqtt.publish_plaintext(topic, plain, qos=1)
        self.tx_counter_var.set(str(frame["tx_counter"]))
        self._clear_error()
        self.framing_var.set(
            f"cipher={frame['cipher_len']}   proto_len={frame['proto_len']}   pad_len={frame['pad_len']}   iv={frame['iv_hex']}"
        )
        self.log_tx(
            f"[{message_name} TX#{frame['tx_counter']}] reason={reason} code_ver={frame['code_version']} proto_len={frame['proto_len']} pad_len={frame['pad_len']} "
            f"padded_len={frame['padded_len']} cipher_len={frame['cipher_len']} frame_len={frame['frame_len']} topic={topic}"
        )
        self.log_tx(f"MQTT frame bytes: {_hex_bytes(frame['payload'])}")
        self.log_tx(f"Frame header: code_ver={frame['code_version']} iv={frame['iv_hex']}")
        self.log_tx(f"Ciphertext bytes: {_hex_bytes(frame['ciphertext'])}")
        self.log_tx(f"Proto frame bytes: {_hex_bytes(plain)}")
        self.log_tx("")
        return frame

    def _publish_telemetry_response(self, reason: str = "GOSTM") -> dict:
        self._ensure_sensor_data()
        plain = self._build_telemetry_plain()
        return self._publish_application_plain(plain, "TELEMETRY", reason)

    def on_tx_once(self):
        if not self.mqtt:
            return
        try:
            self._ensure_sensor_data()
            plain = self._build_status_plain()
            self._publish_application_plain(plain, "STATUS", "manual publish")
        except Exception as e:
            self._set_error(str(e))
            self.log_tx(f"[TX][ERROR] {e}")

    # Start periodic telemetry publishing using the configured transmission period.

    def on_tx_start(self):
        if not self.mqtt:
            return
        try:
            period = self._validate_tx_period()
            self.tx_running = True
            self.tx_start_btn.config(state="disabled")
            self.tx_stop_btn.config(state="normal")
            self._clear_error()
            self.log_tx(f"Transmission started: every {period} sec (publishing StatusMessage)")
            self._tx_loop()
        except Exception as e:
            self._set_error(str(e))
            messagebox.showerror("Transmission Error", str(e))

    # Stop periodic telemetry publishing and cancel the pending Tkinter timer.

    def on_tx_stop(self):
        self.tx_running = False
        if self.tx_job is not None:
            try:
                self.root.after_cancel(self.tx_job)
            except Exception:
                pass
            self.tx_job = None
        self.tx_start_btn.config(state="normal" if self.mqtt else "disabled")
        self.tx_stop_btn.config(state="disabled")
        if self.mqtt:
            self.log_tx("Transmission stopped.")

    # Periodic publish loop scheduled by Tkinter .after().

    def _tx_loop(self):
        """
        Tkinter timer loop for periodic telemetry publish.

        Important behavior:
        - on_tx_once() performs the actual publish now
        - root.after(...) schedules the next iteration later
        - this is cooperative scheduling, not a Python thread
        """
        if not self.tx_running:
            return
        try:
            self.on_tx_once()
        finally:
            try:
                period = self._validate_tx_period()
            except Exception:
                period = 1
            self.tx_job = self.root.after(period * 1000, self._tx_loop)

    # =========================
    # RS-485
    # =========================
    # Connect to the RS-485 sensor using the GUI settings.

    def on_rs_connect(self):
        if not self.rs_enabled_var.get():
            return
        if Tuf2000bRtuClient is None:
            messagebox.showerror("RS-485 Error", "RS-485 module not available. Ensure rs485_tuf2000b.py exists.")
            return
        try:
            cfg = Tuf2000bConfig(
                port=self.rs_port_var.get().strip(),
                baudrate=int(self.rs_baud_var.get().strip()),
                parity=self.rs_parity_var.get().strip().upper() or "N",
                stopbits=int(self.rs_stopbits_var.get().strip()),
                bytesize=8,
                timeout_s=1.0,
                unit_id=int(self.rs_unit_var.get().strip()),
                address_base=0,  # fixed default
                reg_flow=0,  # fixed: start from address 0
            )
            self.rs = Tuf2000bRtuClient(cfg)
            self.rs.connect()
            self.rs_status_var.set("Sensor: connected")
            self.rs_connect_btn.config(state="disabled")
            self.rs_disconnect_btn.config(state="normal")
            self.rs_read_btn.config(state="normal")
            # polling button stays disabled until first successful Read (per your request)
            self.rs_poll_btn.config(state="disabled")
            self._clear_error()
            self.log_sensor("RS-485 connected.")
            self._refresh_status()
        except Rs485DependencyError as e:
            self._set_error(str(e))
            messagebox.showerror("RS-485 Dependencies", str(e))
        except Exception as e:
            self._set_error(str(e))
            messagebox.showerror("RS-485 Connect Error", str(e))

    # Disconnect from the RS-485 sensor and reset related UI indicators.

    def on_rs_disconnect(self):
        self._rs_stop_polling(silent=True)
        if self.rs:
            try:
                self.rs.close()
            except Exception:
                pass
        self.rs = None
        self.last_flow = None
        self.last_measurements = None
        self._clear_error()
        if hasattr(self, "rs_flow_var"):
            self.rs_flow_var.set("--")
        if hasattr(self, "rs_instant_flow_var"):
            self.rs_instant_flow_var.set("--")
            self.rs_velocity_var.set("--")
            self.rs_flow_today_var.set("--")
            self.rs_flow_month_var.set("--")
            self.rs_flow_year_var.set("--")
        if hasattr(self, "sensor_last_read_var"):
            self.sensor_last_read_var.set("Last read: --")
        self.rs_status_var.set("Sensor: disconnected")
        self.rs_connect_btn.config(state="normal" if self.rs_enabled_var.get() else "disabled")
        self.rs_disconnect_btn.config(state="disabled")
        self.rs_read_btn.config(state="disabled")
        self.rs_poll_btn.config(state="disabled")
        self._set_flag(self.flow_min_flag, "gray")
        self._set_flag(self.flow_max_flag, "gray")
        self.log_sensor("RS-485 disconnected.")
        self._refresh_status()

    # Perform one sensor read and update the live-flow view, preview, limits, and sensor log.

    def on_rs_read_once(self):
        if not self.rs or not self.rs.is_connected:
            return False
        try:
            meas = self.rs.read_measurements()
            instant_flow = float(meas["instant_flow"])
            velocity = float(meas["velocity"])
            flow_today = float(meas["flow_today"])
            flow_month = float(meas["flow_month"])
            flow_year = float(meas["flow_year"])
            req_hex = meas.get("request_hex", {})
            resp_hex = meas.get("response_hex", {})
            self.last_flow = instant_flow
            self.last_measurements = {
                "flow_rate": instant_flow,
                "velocity": velocity,
                "flow_rate_per_day": flow_today,
                "flow_rate_per_month": flow_month,
                "flow_rate_per_year": flow_year,
            }
            self._clear_error()
            if hasattr(self, "rs_flow_var"):
                self.rs_flow_var.set(f"{instant_flow:.3f} m³/h")
            if hasattr(self, "rs_instant_flow_var"):
                self.rs_instant_flow_var.set(f"{instant_flow:.3f} m³/h")
                self.rs_velocity_var.set(f"{velocity:.3f} m/s")
                self.rs_flow_today_var.set(f"{flow_today:.3f} m³")
                self.rs_flow_month_var.set(f"{flow_month:.3f} m³")
                self.rs_flow_year_var.set(f"{flow_year:.3f} m³")
            if hasattr(self, "sensor_last_read_var"):
                self.sensor_last_read_var.set(
                    f"Last read: flow={instant_flow:.3f} m³/h | vel={velocity:.3f} m/s | today={flow_today:.3f} m³ | month={flow_month:.3f} m³ | year={flow_year:.3f} m³"
                )
            self._update_flow_flags(instant_flow)
            self.log_sensor(f"TX cmd bytes [0001-0006]: {req_hex.get('frame_0001_0006', '')}")
            self.log_sensor(
                f"RX rsp bytes [0001-0006]: {resp_hex.get('frame_0001_0006', '')}   instant_flow={instant_flow:.3f} m3/h   velocity={velocity:.3f} m/s"
            )
            self.log_sensor(f"TX cmd bytes [0125-0128]: {req_hex.get('frame_0125_0128', '')}")
            self.log_sensor(
                f"RX rsp bytes [0125-0128]: {resp_hex.get('frame_0125_0128', '')}   flow_today={flow_today:.3f} m3   flow_month={flow_month:.3f} m3"
            )
            self.log_sensor(f"TX cmd bytes [0145-0148]: {req_hex.get('frame_0145_0148', '')}")
            self.log_sensor(
                f"RX rsp bytes [0145-0148]: {resp_hex.get('frame_0145_0148', '')}   flow_year={flow_year:.3f} m3"
            )
            self.log_sensor("")
            # enable polling button after first successful read
            if str(self.rs_poll_btn["state"]) == "disabled":
                self.rs_poll_btn.config(state="normal")
            return True
        except Exception as e:
            self._set_error(str(e))
            self.log_sensor(f"[RS485][ERROR] {e}")
            return False

    # Toggle background sensor polling on/off from the GUI button.

    def on_rs_toggle_poll(self):
        if not self.rs or not self.rs.is_connected:
            return
        if not self.rs_poll_running:
            self._rs_start_polling()
        else:
            self._rs_stop_polling()

    # Start periodic RS-485 polling.

    def _rs_start_polling(self):
        try:
            ms = int(self.rs_poll_ms_var.get().strip())
            if ms < 50:
                ms = 50
            self.rs_poll_running = True
            self.rs_poll_btn.config(text="Stop Polling")
            self.log_sensor(f"Polling started: period={ms} ms")
            self._rs_poll_loop()
        except Exception as e:
            self._set_error(str(e))
            messagebox.showerror("Polling Error", str(e))

    # Stop periodic RS-485 polling and optionally suppress the log line.

    def _rs_stop_polling(self, silent: bool = False):
        self.rs_poll_running = False
        if self.rs_poll_job is not None:
            try:
                self.root.after_cancel(self.rs_poll_job)
            except Exception:
                pass
            self.rs_poll_job = None
        self.rs_poll_btn.config(text="Start Polling")
        if not silent:
            self.log_sensor("Polling stopped.")

    # Tkinter .after() loop that performs repeated sensor reads.

    def _rs_poll_loop(self):
        """
        Tkinter timer loop for repeated sensor reads.

        Similar to _tx_loop(), this is GUI event-loop scheduling rather than a
        background thread. That distinction matters during debugging.
        """
        if not self.rs_poll_running:
            return
        # read and log every poll tick
        self.on_rs_read_once()
        try:
            ms = int(self.rs_poll_ms_var.get().strip())
        except Exception:
            ms = 1000
        if ms < 50:
            ms = 50
        self.rs_poll_job = self.root.after(ms, self._rs_poll_loop)

    # Update one LED indicator to the requested color.

    def _set_flag(self, widget, color: str):
        """Set LED flag color (supports Canvas-oval or Label)."""
        try:
            # Canvas LED
            if isinstance(widget, tk.Canvas):
                if widget == getattr(self, "flow_min_flag", None):
                    widget.itemconfig(getattr(self, "_min_led", None), fill=color)
                elif widget == getattr(self, "flow_max_flag", None):
                    widget.itemconfig(getattr(self, "_max_led", None), fill=color)
                return
        except Exception:
            pass
        try:
            widget.configure(bg=color)
        except Exception:
            pass

    # Parse a numeric flow limit from the GUI, returning None for blank/invalid input.

    def _parse_limit(self, s: str) -> float | None:
        s = (s or "").strip()
        if not s:
            return None
        try:
            return float(s)
        except Exception:
            return None

    # Compare the latest flow reading against min/max limits and update the LED colors.

    def _update_flow_flags(self, flow: float):
        mn = self._parse_limit(self.flow_min_var.get())
        mx = self._parse_limit(self.flow_max_var.get())

        # Min flag
        if mn is None:
            self._set_flag(self.flow_min_flag, "gray")
        else:
            self._set_flag(self.flow_min_flag, "green" if flow >= mn else "red")

        # Max flag
        if mx is None:
            self._set_flag(self.flow_max_flag, "gray")
        else:
            self._set_flag(self.flow_max_flag, "green" if flow <= mx else "red")


    # Program entry point: create the Tk root window and launch the event loop.

    def _refresh_cmd_publish_ui(self, *_args):
        cmd = (self.cmd_name_var.get() or "").strip().upper()
        if cmd == "SRATE":
            self.cmd_data_entry.configure(state="normal")
            self.cmd_data_var.set((self.sampling_rate_var.get() or "1").strip())
        elif cmd == "STRAN":
            self.cmd_data_entry.configure(state="normal")
            self.cmd_data_var.set((self.tx_period_var.get() or "1").strip())
        elif cmd == "STIME":
            self.cmd_data_var.set(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            self.cmd_data_entry.configure(state="readonly")
        elif cmd == "GOSTM":
            self.cmd_data_var.set("")
            self.cmd_data_entry.configure(state="disabled")
        else:
            self.cmd_data_entry.configure(state="normal")

    def _bind_cmd_publish_helpers(self):
        try:
            self.cmd_name_var.trace_add("write", self._refresh_cmd_publish_ui)
        except Exception:
            pass
        try:
            self.tx_period_var.trace_add("write", self._refresh_cmd_publish_ui)
        except Exception:
            pass
        try:
            self.sampling_rate_var.trace_add("write", self._refresh_cmd_publish_ui)
        except Exception:
            pass
        self._refresh_cmd_publish_ui()

def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
