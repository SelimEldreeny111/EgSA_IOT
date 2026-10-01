"""Wire-level remote-wake validation and display metadata (no broker side effects)."""

WAKE_COMMAND_ID = 6
MAX_WAKE_SECONDS = 86400
POWER_MODES = {0: "Unknown / legacy", 1: "NORMAL", 2: "RTC_PERIODIC",
               3: "REMOTE_WAKE", 4: "RTC_QUEUED", 5: "LORA_WOR_STOP"}
POWER_STATES = {0: "Unknown / legacy", 1: "ACTIVE", 2: "REACHABLE_IDLE"}


def validate_wake_seconds(value) -> int:
    """Accept whole seconds 0..86400; never truncate floats or booleans."""
    if isinstance(value, bool) or isinstance(value, float):
        raise ValueError("WAKE duration must be a whole number of seconds")
    if isinstance(value, str):
        value = value.strip()
        if not value.isascii() or not value.isdecimal():
            raise ValueError("WAKE duration must be 0 (node default) or 1..86400 seconds")
    if not isinstance(value, (int, str)):
        raise ValueError("WAKE duration must be a whole number of seconds")
    seconds = int(value)
    if not 0 <= seconds <= MAX_WAKE_SECONDS:
        raise ValueError("WAKE duration must be 0 (node default) or 1..86400 seconds")
    return seconds


def power_metadata(message) -> dict:
    """Legacy protobufs decode new fields as zero, never as confirmed remote wake."""
    mode = int(getattr(message, "power_mode", 0))
    state = int(getattr(message, "power_state", 0))
    remaining = int(getattr(message, "wake_remaining_seconds", 0))
    return {
        "power_mode": mode,
        "power_state": state,
        "wake_remaining_seconds": remaining,
        "wake_command_ack": int(bool(getattr(message, "wake_command_ack", False))),
        "wake_request_id": int(getattr(message, "wake_request_id", 0)),
        "wdt_reset_count": int(getattr(message, "wdt_reset_count", 0)),
    }


def power_dashboard_fields(metadata: dict) -> dict:
    return {
        "Power Mode": POWER_MODES.get(metadata["power_mode"], "Unknown"),
        "Power State": POWER_STATES.get(metadata["power_state"], "Unknown"),
        "Wake Remaining Seconds": metadata["wake_remaining_seconds"],
        "Wake Command ACK": bool(metadata["wake_command_ack"]),
        "Wake Request ID": metadata["wake_request_id"],
        "WDT Resets": metadata.get("wdt_reset_count", 0),
    }


def is_confirmed_wake(metadata: dict) -> bool:
    return bool(metadata["wake_command_ack"] and metadata["power_mode"] in (3, 4, 5)
                and metadata["power_state"] == 1 and metadata["wake_request_id"] != 0)
