"""Flow-meter schema helpers shared by MQTT ingestion and tests.

The deployed protobuf field numbers remain unchanged. This module translates
the appended flow schema into explicit database and dashboard values, while
also recognizing legacy TUF nodes from sensor_mask bit 0.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import math
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


FLOW_METER_NAMES = {
    0: "None/Unknown",
    1: "TUF",
    2: "Supmea",
}

PERIOD_SOURCE_NAMES = {
    0: "Unknown",
    1: "Meter native",
    2: "Node RTC calculated",
}

PERIOD_QUALITY_NAMES = {
    0: "Invalid",
    1: "Valid",
    2: "Partial",
    3: "Estimated",
    4: "Counter reset",
    5: "Anomaly",
    6: "Time uncertain",
}

SENSOR_MASK_TUF = 0x0001
SENSOR_MASK_SUPMEA = 0x0008
MINIMUM_TRUSTED_RTC_EPOCH = 1_704_067_200  # 2024-01-01 UTC
DEFAULT_CALENDAR_TIMEZONE = "Africa/Cairo"


def flow_meter_name(value: int) -> str:
    return FLOW_METER_NAMES.get(int(value), f"Unknown ({int(value)})")


def period_source_name(value: int) -> str:
    return PERIOD_SOURCE_NAMES.get(int(value), f"Unknown ({int(value)})")


def period_quality_name(value: int) -> str:
    return PERIOD_QUALITY_NAMES.get(int(value), f"Unknown ({int(value)})")


def extract_flow_metadata(message) -> dict:
    """Return normalized flow-v2 values from a Status or Telemetry message.

    Old TUF firmware has no v2 fields. Its established TUF mask allows a safe
    compatibility inference without treating soil-only nodes as flow meters.
    """

    sensor_mask = int(getattr(message, "sensor_mask", 0))
    meter_type = int(getattr(message, "flow_meter_type", 0))
    source = int(getattr(message, "flow_period_source", 0))
    live_valid = bool(getattr(message, "flow_live_valid", False))
    period_valid = bool(getattr(message, "flow_period_totals_valid", False))
    cumulative_valid = bool(
        getattr(message, "flow_cumulative_totals_valid", False)
    )
    quality = int(getattr(message, "flow_period_quality", 0))
    legacy = False

    if meter_type == 0 and sensor_mask & SENSOR_MASK_TUF:
        meter_type = 1
        source = 1
        live_valid = True
        period_valid = True
        quality = 1
        legacy = True
    elif meter_type == 0 and sensor_mask & SENSOR_MASK_SUPMEA:
        meter_type = 2

    return {
        "flow_meter_type": meter_type,
        "flow_meter_name": flow_meter_name(meter_type),
        "flow_period_source": source,
        "flow_period_source_name": period_source_name(source),
        "flow_live_valid": int(live_valid),
        "flow_period_totals_valid": int(period_valid),
        "flow_cumulative_totals_valid": int(cumulative_valid),
        "rtc_valid": int(bool(getattr(message, "rtc_valid", False))),
        "forward_total_liters": int(getattr(message, "forward_total_liters", 0)),
        "reverse_total_liters": int(getattr(message, "reverse_total_liters", 0)),
        "net_total_liters": int(getattr(message, "net_total_liters", 0)),
        "flow_period_quality": quality,
        "flow_period_quality_name": period_quality_name(quality),
        "flow_meter_alarm_flags": int(
            getattr(message, "flow_meter_alarm_flags", 0)
        ),
        "legacy_flow_schema": int(legacy),
    }


def select_measurement_timestamp(message, received_at: int) -> tuple[int, str]:
    """Use node time only when the node explicitly marks its RTC trusted."""

    node_timestamp = int(getattr(message, "timestamp", 0))
    rtc_valid = bool(getattr(message, "rtc_valid", False))
    if (
        rtc_valid
        and node_timestamp >= MINIMUM_TRUSTED_RTC_EPOCH
        and node_timestamp <= int(received_at) + 7 * 86400
    ):
        return node_timestamp, "node_rtc"
    return int(received_at), "server_received"


def build_sample_fingerprint(
    company: str,
    message,
    metadata: dict,
    measured_at: int,
) -> str:
    """Generate an idempotency key for QoS retries and duplicate forwards."""

    canonical = "|".join(
        str(value)
        for value in (
            company,
            int(getattr(message, "node_id", 0)),
            int(getattr(message, "sensor_id", 0)),
            int(measured_at),
            metadata["flow_meter_type"],
            metadata["forward_total_liters"],
            metadata["reverse_total_liters"],
            metadata["net_total_liters"],
            round(float(getattr(message, "flow_rate", 0.0)), 6),
        )
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def calendar_period_rows(
    message,
    metadata: dict,
    measured_at: int,
    timezone_name: str = DEFAULT_CALENDAR_TIMEZONE,
) -> list[dict]:
    """Build current day/month/year snapshot rows from valid node values."""

    if not metadata["flow_period_totals_valid"]:
        return []

    try:
        calendar_zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        # Period snapshots are optional derived data. Never reject the raw
        # Status/Telemetry packet merely because the host lacks tzdata.
        return []

    local = datetime.fromtimestamp(
        int(measured_at), tz=timezone.utc
    ).astimezone(calendar_zone)
    values = (
        ("day", local.strftime("%Y-%m-%d"), message.flow_rate_per_day),
        ("month", local.strftime("%Y-%m"), message.flow_rate_per_month),
        ("year", local.strftime("%Y"), message.flow_rate_per_year),
    )
    normalized = []
    for period_type, period_key, raw_volume_m3 in values:
        volume_m3 = float(raw_volume_m3)
        if not math.isfinite(volume_m3) or volume_m3 < 0.0:
            return []
        normalized.append((period_type, period_key, volume_m3))

    return [
        {
            "period_type": period_type,
            "period_key": period_key,
            "volume_liters": round(float(volume_m3) * 1000.0),
            "source": metadata["flow_period_source"],
            "quality": metadata["flow_period_quality"],
        }
        for period_type, period_key, volume_m3 in normalized
    ]


def dashboard_flow_fields(metadata: dict) -> dict:
    return {
        "Flow Meter Type": metadata["flow_meter_type"],
        "Flow Meter": metadata["flow_meter_name"],
        "Period Source": metadata["flow_period_source_name"],
        "Flow Live Valid": metadata["flow_live_valid"],
        "Period Totals Valid": metadata["flow_period_totals_valid"],
        "Cumulative Totals Valid": metadata[
            "flow_cumulative_totals_valid"
        ],
        "RTC Valid": metadata["rtc_valid"],
        "Forward Total Liters": metadata["forward_total_liters"],
        "Reverse Total Liters": metadata["reverse_total_liters"],
        "Net Total Liters": metadata["net_total_liters"],
        "Period Quality": metadata["flow_period_quality_name"],
        "Flow Alarm Flags": metadata["flow_meter_alarm_flags"],
    }
