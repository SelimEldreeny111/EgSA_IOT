import sys
import time
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime
from collections import deque
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

import messages_pb2
from mqtt_impl import MqttNodeClient

CMD_NAMES = {
    "SRATE": 1,
    "STRAN": 2,
    "STIME": 3,
    "GOSTM": 4,
}

CMD_NAMES_REV = {v: k for k, v in CMD_NAMES.items()}

class ServerApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("IoT Server Dashboard")
        self.root.geometry("1100x800")
        
        try:
            ttk.Style().theme_use("clam")
        except Exception:
            pass

        self.mqtt: MqttNodeClient | None = None

        # Queue for safe cross-thread GUI updates
        import queue
        self._ui_queue = queue.Queue()
        self.root.after(100, self._drain_ui_queue)

        # Build UI
        self._build_config_frame(self.root)
        
        # Node latest data tracking
        self.node_latest_data = {}
        
        # Node history data for plotting
        self.node_history_data = {}
        self.MAX_POINTS = 50
        
        # Setup Notebook for tabs
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=5)
        
        self.tab_live = ttk.Frame(self.notebook)
        self.tab_graph = ttk.Frame(self.notebook)
        self.tab_tabular = ttk.Frame(self.notebook)
        self.tab_cmd = ttk.Frame(self.notebook)
        self.tab_log = ttk.Frame(self.notebook)
        
        self.notebook.add(self.tab_live, text="Live Status")
        self.notebook.add(self.tab_graph, text="Live Graphs")
        self.notebook.add(self.tab_tabular, text="Tabular Data")
        self.notebook.add(self.tab_cmd, text="Commands")
        self.notebook.add(self.tab_log, text="Logs")
        
        self._build_live_status_tab(self.tab_live)
        self._build_graph_tab(self.tab_graph)
        self._build_treeview_frame(self.tab_tabular)
        self._build_cmd_frame(self.tab_cmd)
        self._build_log_frame(self.tab_log)

        self._refresh_status()

    def _build_config_frame(self, parent):
        f = ttk.LabelFrame(parent, text="Server Configuration", padding=10)
        f.pack(fill="x", padx=10, pady=5)
        
        self.broker_var = tk.StringVar(value="broker.hivemq.com")
        self.port_var = tk.StringVar(value="1883")
        self.company_id_var = tk.StringVar(value="Company_ID")
        self.key_var = tk.StringVar(value="")
        self.code_ver_var = tk.StringVar(value="01")
        self.client_id_var = tk.StringVar(value=f"iot_server_{int(time.time())}")

        row = 0
        ttk.Label(f, text="Broker Host:").grid(row=row, column=0, sticky="w")
        ttk.Entry(f, textvariable=self.broker_var, width=30).grid(row=row, column=1, padx=5, pady=2, sticky="w")
        
        ttk.Label(f, text="Port:").grid(row=row, column=2, sticky="w", padx=10)
        ttk.Entry(f, textvariable=self.port_var, width=10).grid(row=row, column=3, padx=5, pady=2, sticky="w")

        ttk.Label(f, text="Client ID:").grid(row=row, column=4, sticky="w", padx=10)
        ttk.Entry(f, textvariable=self.client_id_var, width=30).grid(row=row, column=5, padx=5, pady=2, sticky="w")

        row += 1
        ttk.Label(f, text="Company ID:").grid(row=row, column=0, sticky="w")
        ttk.Entry(f, textvariable=self.company_id_var, width=30).grid(row=row, column=1, padx=5, pady=2, sticky="w")
        
        ttk.Label(f, text="AES Key (16 bytes hex):").grid(row=row, column=2, sticky="w", padx=10)
        ttk.Entry(f, textvariable=self.key_var, show="*", width=35).grid(row=row, column=3, columnspan=3, padx=5, pady=2, sticky="w")

        row += 1
        btns = ttk.Frame(f)
        btns.grid(row=row, column=0, columnspan=6, pady=10, sticky="w")
        
        self.connect_btn = ttk.Button(btns, text="Connect to Broker", command=self.on_connect)
        self.connect_btn.pack(side="left", padx=5)
        
        self.disconnect_btn = ttk.Button(btns, text="Disconnect", command=self.on_disconnect, state="disabled")
        self.disconnect_btn.pack(side="left", padx=5)

    def _build_live_status_tab(self, parent):
        f = ttk.LabelFrame(parent, text="Live Node Metrics", padding=10)
        f.pack(fill="both", expand=True, padx=10, pady=5)
        
        # Top bar: Node Selector
        sel_frame = ttk.Frame(f)
        sel_frame.pack(fill="x", pady=5)
        ttk.Label(sel_frame, text="Select Node ID:").pack(side="left")
        
        self.selected_node_var = tk.StringVar()
        self.node_selector = ttk.Combobox(sel_frame, textvariable=self.selected_node_var, state="readonly", width=15)
        self.node_selector.pack(side="left", padx=10)
        self.node_selector.bind("<<ComboboxSelected>>", self._on_node_selected)
        
        # Metrics Display Grid
        grid_f = ttk.Frame(f)
        grid_f.pack(fill="both", expand=True, pady=10)
        
        # Display variables
        self.live_vars = {
            "Time": tk.StringVar(value="-"),
            "Sensor ID": tk.StringVar(value="-"),
            "Flow (m3/h)": tk.StringVar(value="-"),
            "Velocity (m/s)": tk.StringVar(value="-"),
            "Today (m3)": tk.StringVar(value="-"),
            "Month (m3)": tk.StringVar(value="-"),
            "Year (m3)": tk.StringVar(value="-"),
            "Details": tk.StringVar(value="-"),
        }
        
        row = 0
        col = 0
        for label, var in self.live_vars.items():
            ttk.Label(grid_f, text=f"{label}:", font=("Arial", 10, "bold")).grid(row=row, column=col, sticky="e", padx=10, pady=10)
            ttk.Label(grid_f, textvariable=var, font=("Arial", 10)).grid(row=row, column=col+1, sticky="w", padx=10, pady=10)
            row += 1
            if row > 3:
                row = 0
                col += 2

    def _on_node_selected(self, event=None):
        node_id = self.selected_node_var.get()
        if node_id in self.node_latest_data:
            data = self.node_latest_data[node_id]
            self.live_vars["Time"].set(data.get("Time", "-"))
            self.live_vars["Sensor ID"].set(str(data.get("Sensor ID", "-")))
            self.live_vars["Flow (m3/h)"].set(f"{data.get('Flow', 0.0):.2f}")
            self.live_vars["Velocity (m/s)"].set(f"{data.get('Velocity', 0.0):.2f}")
            self.live_vars["Today (m3)"].set(f"{data.get('Flow/Day', 0.0):.2f}")
            self.live_vars["Month (m3)"].set(f"{data.get('Flow/Month', 0.0):.2f}")
            self.live_vars["Year (m3)"].set(f"{data.get('Flow/Year', 0.0):.2f}")
            self.live_vars["Details"].set(data.get("Details", "-"))

    def _update_live_data(self, node_id, data):
        # Update combo list if new node
        str_node = str(node_id)
        
        if str_node not in self.node_history_data:
            self.node_history_data[str_node] = {
                "flows": deque(maxlen=self.MAX_POINTS), 
                "velocities": deque(maxlen=self.MAX_POINTS)
            }
            
        if "Flow" in data:
            self.node_history_data[str_node]["flows"].append(data["Flow"])
        if "Velocity" in data:
            self.node_history_data[str_node]["velocities"].append(data["Velocity"])

        if str_node not in self.node_latest_data:
            self.node_latest_data[str_node] = data
            current_vals = list(self.node_selector["values"])
            current_vals.append(str_node)
            sorted_vals = sorted(current_vals, key=lambda x: int(x))
            self.node_selector["values"] = sorted_vals
            if hasattr(self, 'graph_combo'):
                self.graph_combo["values"] = sorted_vals
            
            # Auto select if it's the first node
            if not self.selected_node_var.get():
                self.selected_node_var.set(str_node)
                self._on_node_selected()
            if hasattr(self, 'graph_node_var') and not self.graph_node_var.get():
                self.graph_node_var.set(str_node)
                self._on_graph_node_selected()
        else:
            self.node_latest_data[str_node].update(data)
            
        # Update UI if this node is currently selected
        if self.selected_node_var.get() == str_node:
            self._on_node_selected()
            
        if hasattr(self, 'graph_node_var') and self.graph_node_var.get() == str_node:
            self._refresh_graph()

    def _build_graph_tab(self, parent):
        f = ttk.LabelFrame(parent, text="Real-time Flow and Velocity", padding=10)
        f.pack(fill="both", expand=True, padx=10, pady=5)
        
        sel_frame = ttk.Frame(f)
        sel_frame.pack(fill="x", pady=5)
        ttk.Label(sel_frame, text="Select Node ID:").pack(side="left")
        
        self.graph_node_var = tk.StringVar()
        self.graph_combo = ttk.Combobox(sel_frame, textvariable=self.graph_node_var, state="readonly", width=15)
        self.graph_combo.pack(side="left", padx=10)
        self.graph_combo.bind("<<ComboboxSelected>>", self._on_graph_node_selected)
        
        # Setup Figure
        self.fig = Figure(figsize=(7, 5), dpi=100)
        
        self.ax_flow = self.fig.add_subplot(211)
        self.ax_flow.set_ylabel("Flow (m3/h)")
        self.ax_flow.set_title("Live Node Metrics")
        self.line_flow, = self.ax_flow.plot([], [], 'b-')
        
        self.ax_vel = self.fig.add_subplot(212)
        self.ax_vel.set_ylabel("Velocity (m/s)")
        self.ax_vel.set_xlabel("Updates")
        self.line_vel, = self.ax_vel.plot([], [], 'r-')
        
        self.fig.tight_layout()
        
        self.canvas = FigureCanvasTkAgg(self.fig, master=f)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

    def _on_graph_node_selected(self, event=None):
        self._refresh_graph()
        
    def _refresh_graph(self):
        node_id = self.graph_node_var.get()
        if node_id in self.node_history_data:
            history = self.node_history_data[node_id]
            x_data = list(range(len(history["flows"])))
            flows = list(history["flows"])
            vels = list(history["velocities"])
            
            self.line_flow.set_data(x_data, flows)
            if flows:
                self.ax_flow.set_xlim(0, max(self.MAX_POINTS - 1, len(x_data) - 1))
                self.ax_flow.set_ylim(min(flows) * 0.9, max(flows) * 1.1 + 0.1)
                
            self.line_vel.set_data(x_data, vels)
            if vels:
                self.ax_vel.set_xlim(0, max(self.MAX_POINTS - 1, len(x_data) - 1))
                self.ax_vel.set_ylim(min(vels) * 0.9, max(vels) * 1.1 + 0.1)
                
            self.canvas.draw_idle()

    def _build_treeview_frame(self, parent):
        f = ttk.LabelFrame(parent, text="Received Messages (Status & Telemetry)", padding=10)
        f.pack(fill="both", expand=True, padx=10, pady=5)

        cols = ("Time", "Type", "Node ID", "Sensor ID", "Flow", "Velocity", "Day", "Month", "Year", "Details")
        self.tree = ttk.Treeview(f, columns=cols, show="headings", height=12)
        
        col_widths = {
            "Time": 100, "Type": 80, "Node ID": 60, "Sensor ID": 60, 
            "Flow": 70, "Velocity": 80, "Day": 80, "Month": 80, "Year": 80, "Details": 300
        }

        for col in cols:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=col_widths[col], anchor="center")
            
        self.tree.column("Details", anchor="w")

        scroll = ttk.Scrollbar(f, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)

        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

    def _build_cmd_frame(self, parent):
        f = ttk.LabelFrame(parent, text="Send Command", padding=10)
        f.pack(fill="x", padx=10, pady=5)
        
        self.cmd_node_var = tk.StringVar(value="1")
        self.cmd_type_var = tk.StringVar(value="SRATE")
        self.cmd_data_var = tk.StringVar(value="5")

        ttk.Label(f, text="Target Node ID:").grid(row=0, column=0, sticky="w")
        ttk.Entry(f, textvariable=self.cmd_node_var, width=15).grid(row=0, column=1, padx=5, pady=2, sticky="w")

        ttk.Label(f, text="Command:").grid(row=0, column=2, sticky="w", padx=10)
        self.cmd_cb = ttk.Combobox(f, textvariable=self.cmd_type_var, values=list(CMD_NAMES.keys()), state="readonly", width=15)
        self.cmd_cb.grid(row=0, column=3, padx=5, pady=2, sticky="w")
        self.cmd_cb.bind("<<ComboboxSelected>>", self._on_cmd_type_changed)

        ttk.Label(f, text="Command Data:").grid(row=0, column=4, sticky="w", padx=10)
        self.cmd_data_entry = ttk.Entry(f, textvariable=self.cmd_data_var, width=15)
        self.cmd_data_entry.grid(row=0, column=5, padx=5, pady=2, sticky="w")

        self.send_cmd_btn = ttk.Button(f, text="Send Command", command=self.on_send_cmd, state="disabled")
        self.send_cmd_btn.grid(row=0, column=6, padx=15)
        
        # Broadcast button
        self.broadcast_cmd_btn = ttk.Button(f, text="Broadcast Command", command=self.on_broadcast_cmd, state="disabled")
        self.broadcast_cmd_btn.grid(row=0, column=7, padx=5)

    def _on_cmd_type_changed(self, event=None):
        cmd = self.cmd_type_var.get()
        if cmd in ["STIME", "GOSTM"]:
            self.cmd_data_entry.config(state="disabled")
            self.cmd_data_var.set("Epoch Time")
        else:
            self.cmd_data_entry.config(state="normal")
            if self.cmd_data_var.get() == "Epoch Time":
                self.cmd_data_var.set("5")

    def _build_log_frame(self, parent):
        f = ttk.LabelFrame(parent, text="System Logs", padding=10)
        f.pack(fill="both", expand=True, padx=10, pady=5)
        
        self.log_text = tk.Text(f, height=8, font=("Consolas", 9))
        
        scroll = ttk.Scrollbar(f, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll.set)
        
        self.log_text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        
        ttk.Button(f, text="Clear Log", command=lambda: self.log_text.delete("1.0", "end")).pack(side="bottom", anchor="se", pady=5)

    def _log(self, msg: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self._ui_queue.put(lambda: self._append_log(f"[{timestamp}] {msg}"))

    def _append_log(self, msg: str):
        self.log_text.insert("end", msg + "\n")
        self.log_text.see("end")

    def _drain_ui_queue(self):
        try:
            while True:
                task = self._ui_queue.get_nowait()
                task()
        except Exception:
            pass
        self.root.after(100, self._drain_ui_queue)

    def on_connect(self):
        broker = self.broker_var.get().strip()
        port = int(self.port_var.get().strip() or "1883")
        company = self.company_id_var.get().strip()
        client_id = self.client_id_var.get().strip()
        key_hex = self.key_var.get().strip()
        
        try:
            aes_key = bytes.fromhex(key_hex)
        except ValueError as e:
            messagebox.showerror("Key Error", f"Invalid hex for key: {e}")
            return
            
        topics = [
            f"EgSA/{company}/+/Status",
            f"EgSA/{company}/+/TELEMETRY",
            f"EgSA/{company}/+/Telemetry",  # handle case variations
        ]
        
        self._log(f"Connecting to {broker}:{port} as {client_id}...")
        
        self.mqtt = MqttNodeClient(
            broker_host=broker,
            broker_port=port,
            aes_key_16=aes_key,
            client_id=client_id,
            subscribe_topics=topics,
            on_plaintext=self.on_mqtt_plaintext,
            on_status=self.on_mqtt_status
        )
        
        try:
            self.mqtt.connect()
            self._log(f"Subscribing to: {', '.join(topics)}")
            self._refresh_status()
        except Exception as e:
            messagebox.showerror("Connection Error", str(e))
            self.mqtt = None
            self._refresh_status()

    def on_disconnect(self):
        if self.mqtt:
            self.mqtt.disconnect()
            self.mqtt = None
            self._log("Disconnected from broker.")
            self._refresh_status()

    def _refresh_status(self):
        if self.mqtt:
            self.connect_btn.config(state="disabled")
            self.disconnect_btn.config(state="normal")
            self.send_cmd_btn.config(state="normal")
            self.broadcast_cmd_btn.config(state="normal")
            
            self.broker_var.set(self.broker_var.get())  # keep value but you'd normally disable entry
        else:
            self.connect_btn.config(state="normal")
            self.disconnect_btn.config(state="disabled")
            self.send_cmd_btn.config(state="disabled")
            self.broadcast_cmd_btn.config(state="disabled")

    def on_mqtt_status(self, msg: str):
        if msg:
            self._log(msg)

    def on_mqtt_plaintext(self, topic: str, plaintext: bytes):
        # We process plaintext bytes in the background thread from mqtt
        # So we queue GUI payload update
        self._ui_queue.put(lambda: self._handle_plaintext(topic, plaintext))
        
    def _handle_plaintext(self, topic: str, plaintext: bytes):
        self._log(f"Received {len(plaintext)} bytes on {topic}")
        
        t = datetime.now().strftime("%H:%M:%S")
        
        try:
            # Simple heuristic guessing message type from topic string
            if "status" in topic.lower():
                msg = messages_pb2.Status_Message()
                msg.ParseFromString(plaintext)
                self.tree.insert("", 0, values=(
                    t, "Status", msg.node_id, msg.sensor_id, 
                    f"{msg.flow_rate:.2f}", f"{msg.velocity:.2f}", 
                    f"{msg.flow_rate_per_day:.2f}", f"{msg.flow_rate_per_month:.2f}", f"{msg.flow_rate_per_year:.2f}",
                    ""
                ))
                self._update_live_data(msg.node_id, {
                    "Time": t,
                    "Type": "Status",
                    "Sensor ID": msg.sensor_id,
                    "Battery Voltage": msg.battery_voltage,
                    "Flow": msg.flow_rate,
                    "Velocity": msg.velocity,
                    "Flow/Day": msg.flow_rate_per_day,
                    "Flow/Month": msg.flow_rate_per_month,
                    "Flow/Year": msg.flow_rate_per_year,
                    "Details": ""
                })
            elif "telemetry" in topic.lower():
                msg = messages_pb2.Telemetry()
                msg.ParseFromString(plaintext)
                details = f"Node-TS:{msg.timestamp} S-Rate:{msg.sampling_rate} T-Rate:{msg.Transmission_rate} sensors:{msg.active_sensor_count}"
                self.tree.insert("", 0, values=(
                    t, "Telemetry", msg.node_id, msg.sensor_id, 
                    f"{msg.flow_rate:.2f}", f"{msg.velocity:.2f}", 
                    f"{msg.flow_rate_per_day:.2f}", f"{msg.flow_rate_per_month:.2f}", f"{msg.flow_rate_per_year:.2f}",
                    details
                ))
                self._update_live_data(msg.node_id, {
                    "Time": t,
                    "Type": "Telemetry",
                    "Sensor ID": msg.sensor_id,
                    "Battery Voltage": msg.battery_voltage,
                    "Flow": msg.flow_rate,
                    "Velocity": msg.velocity,
                    "Flow/Day": msg.flow_rate_per_day,
                    "Flow/Month": msg.flow_rate_per_month,
                    "Flow/Year": msg.flow_rate_per_year,
                    "Details": details
                })
            elif "cmd" in topic.lower():
                msg = messages_pb2.CMD_Message()
                msg.ParseFromString(plaintext)
                cmd_name = CMD_NAMES_REV.get(msg.cmd_id, str(msg.cmd_id))
                self.tree.insert("", 0, values=(
                    t, "Command", msg.node_id, "-", "-", "-", "-", "-", "-", 
                    f"Cmd={cmd_name}({msg.cmd_id}), Data={msg.cmd_data}"
                ))
            else:
                self._log(f"Unknown topic structure, cannot parse protobuf: {topic}")
        except Exception as e:
            self._log(f"Failed to parse protobuf payload from {topic}: {e}")

    def on_send_cmd(self):
        self._publish_cmd(broadcast=False)
        
    def on_broadcast_cmd(self):
        self._publish_cmd(broadcast=True)
        
    def _publish_cmd(self, broadcast=False):
        if not self.mqtt:
            return
            
        try:
            node_id = int(self.cmd_node_var.get())
            cmd_type = self.cmd_type_var.get()
            cmd_id = CMD_NAMES.get(cmd_type, 0)
            
            if cmd_type in ["STIME", "GOSTM"]:
                cmd_data = int(time.time())
            else:
                cmd_data = int(self.cmd_data_var.get())
                
            company = self.company_id_var.get().strip()
            
            msg = messages_pb2.CMD_Message()
            msg.node_id = node_id
            msg.cmd_id = cmd_id
            msg.cmd_data = cmd_data
            
            plain = msg.SerializeToString()
            
            if broadcast:
                topic = f"EgSA/{company}/BroadCast/CMD"
            else:
                topic = f"EgSA/{company}/{node_id}/CMD"
                
            self._log(f"Publishing CMD '{cmd_type}' to '{topic}' with Data={cmd_data}...")
            self.mqtt.publish_plaintext(topic, plain)
            self._log("Command successfully encrypted and published.")
            
            if cmd_type == "GOSTM":
                self.notebook.select(self.tab_tabular)
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to send command: {e}")

if __name__ == "__main__":
    root = tk.Tk()
    app = ServerApp(root)
    root.mainloop()
