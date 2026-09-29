"""
command_impl.py
===============
Command parser / applier for inbound MQTT commands.

Supported command IDs (from WIOT command list):
- 0: NA     -> reserved / no action
- 1: SRATE  -> configure sampling rate
- 2: STRAN  -> configure transmission rate
- 3: STIME  -> configure system time
- 4: GOSTM  -> request system telemetry
- 5: VALVE  -> control valve (0=close, 1=open)
- 6: WAKE   -> STM32 REMOTE_WAKE active lease (simulator does not emulate CPU sleep)
"""

from dataclasses import dataclass
import time
import messages_pb2

CMD_NAMES = {
    0: "NA",
    1: "SRATE",
    2: "STRAN",
    3: "STIME",
    4: "GOSTM",
    5: "VALVE",
    6: "WAKE",
}

@dataclass
class SimState:
    valve_open: bool = False
    sampling_rate_sec: int = 1
    tx_period_sec: int = 5
    system_time: int = 0
    telemetry_requested: bool = False


def apply_command(state: SimState, cmd_bytes: bytes):
    msg = messages_pb2.CMD_Message()
    msg.ParseFromString(cmd_bytes)

    result = "unknown"
    state.telemetry_requested = False

    if msg.cmd_id == 0:
        result = "reserved"
    elif msg.cmd_id == 1:
        state.sampling_rate_sec = max(1, int(msg.cmd_data))
        result = f"sampling_rate={state.sampling_rate_sec}s"
    elif msg.cmd_id == 2:
        state.tx_period_sec = max(1, int(msg.cmd_data))
        result = f"tx_period={state.tx_period_sec}s"
    elif msg.cmd_id == 3:
        state.system_time = int(msg.cmd_data) if int(msg.cmd_data) > 0 else int(time.time())
        result = f"system_time={state.system_time}"
    elif msg.cmd_id == 4:
        state.telemetry_requested = True
        result = "get_system_telemetry"
    elif msg.cmd_id == 5:
        state.valve_open = bool(int(msg.cmd_data))
        result = "valve_opened" if state.valve_open else "valve_closed"
    elif msg.cmd_id == 6:
        result = "wake_not_supported_by_legacy_node_simulator"

    summary = {
        "node_id": msg.node_id,
        "cmd_id": msg.cmd_id,
        "cmd_name": CMD_NAMES.get(msg.cmd_id, "UNKNOWN"),
        "cmd_data": msg.cmd_data,
        "result": result,
        "sampling_rate_sec": state.sampling_rate_sec,
        "tx_period_sec": state.tx_period_sec,
        "system_time": state.system_time,
        "telemetry_requested": state.telemetry_requested,
        "valve_state": state.valve_open,
    }
    return state, summary
