"""
protobuf_impl.py
================
Builders for outgoing protobuf payloads.

This project now uses two application payload types:
- Status_Message: sent during normal publish/start-transmission actions
- Telemetry: sent as the response to GOSTM
"""

import time
import messages_pb2


def _set_flow_v2(
    msg,
    *,
    flow_meter_type: int,
    flow_period_source: int,
    flow_live_valid: bool,
    flow_period_totals_valid: bool,
    flow_cumulative_totals_valid: bool,
    rtc_valid: bool,
    forward_total_liters: int,
    reverse_total_liters: int,
    net_total_liters: int,
    flow_period_quality: int,
    flow_meter_alarm_flags: int,
) -> None:
    """Populate the appended, wire-compatible flow-schema-v2 fields."""

    msg.flow_meter_type = int(flow_meter_type)
    msg.flow_period_source = int(flow_period_source)
    msg.flow_live_valid = bool(flow_live_valid)
    msg.flow_period_totals_valid = bool(flow_period_totals_valid)
    msg.flow_cumulative_totals_valid = bool(flow_cumulative_totals_valid)
    msg.rtc_valid = bool(rtc_valid)
    msg.forward_total_liters = int(forward_total_liters)
    msg.reverse_total_liters = int(reverse_total_liters)
    msg.net_total_liters = int(net_total_liters)
    msg.flow_period_quality = int(flow_period_quality)
    msg.flow_meter_alarm_flags = int(flow_meter_alarm_flags)


def build_status(
    node_id: int,
    sensor_id: int,
    flow_rate: float,
    timestamp: int | None = None,
    velocity: float = 0.0,
    flow_rate_per_day: float = 0.0,
    flow_rate_per_month: float = 0.0,
    flow_rate_per_year: float = 0.0,
    node_status: int = 0,
    soil_temperature: float = 0.0,
    soil_moisture: float = 0.0,
    soil_moisture_temp_valid: int = 0,
    ec_temperature: float = 0.0,
    ec_moisture: float = 0.0,
    electrical_conductivity: float = 0.0,
    soil_moisture_temp_ec_valid: int = 0,
    active_sensor_count: int = 1,
    sensor_mask: int = 1,
    battery_voltage: float = 0.0,
    flow_meter_type: int = 0,
    flow_period_source: int = 0,
    flow_live_valid: bool = False,
    flow_period_totals_valid: bool = False,
    flow_cumulative_totals_valid: bool = False,
    rtc_valid: bool = False,
    forward_total_liters: int = 0,
    reverse_total_liters: int = 0,
    net_total_liters: int = 0,
    flow_period_quality: int = 0,
    flow_meter_alarm_flags: int = 0,
) -> bytes:
    """Serialize one Status_Message using the new .proto layout."""
    msg = messages_pb2.Status_Message()
    msg.node_id = int(node_id)
    msg.sensor_id = int(sensor_id)
    msg.timestamp = int(timestamp if timestamp is not None else time.time())
    msg.flow_rate = float(flow_rate)
    msg.velocity = float(velocity)
    msg.flow_rate_per_day = float(flow_rate_per_day)
    msg.flow_rate_per_month = float(flow_rate_per_month)
    msg.flow_rate_per_year = float(flow_rate_per_year)
    msg.node_status = int(node_status)
    msg.soil_temperature = float(soil_temperature)
    msg.soil_moisture = float(soil_moisture)
    msg.soil_moisture_temp_valid = int(soil_moisture_temp_valid)
    msg.ec_temperature = float(ec_temperature)
    msg.ec_moisture = float(ec_moisture)
    msg.electrical_conductivity = float(electrical_conductivity)
    msg.soil_moisture_temp_ec_valid = int(soil_moisture_temp_ec_valid)
    msg.active_sensor_count = int(active_sensor_count)
    msg.sensor_mask = int(sensor_mask)
    msg.battery_voltage = float(battery_voltage)
    _set_flow_v2(
        msg,
        flow_meter_type=flow_meter_type,
        flow_period_source=flow_period_source,
        flow_live_valid=flow_live_valid,
        flow_period_totals_valid=flow_period_totals_valid,
        flow_cumulative_totals_valid=flow_cumulative_totals_valid,
        rtc_valid=rtc_valid,
        forward_total_liters=forward_total_liters,
        reverse_total_liters=reverse_total_liters,
        net_total_liters=net_total_liters,
        flow_period_quality=flow_period_quality,
        flow_meter_alarm_flags=flow_meter_alarm_flags,
    )
    return msg.SerializeToString()


def build_telemetry(
    node_id: int,
    sensor_id: int,
    flow_rate: float,
    timestamp: int | None = None,
    sampling_rate: int = 1,
    transmission_rate: int = 5,
    battery_voltage: float = 0.0,
    reserved2: int = 0,
    reserved3: int = 0,
    active_sensor_count: int = 1,
    velocity: float = 0.0,
    flow_rate_per_day: float = 0.0,
    flow_rate_per_month: float = 0.0,
    flow_rate_per_year: float = 0.0,
    node_status: int = 0,
    soil_temperature: float = 0.0,
    soil_moisture: float = 0.0,
    soil_moisture_temp_valid: int = 0,
    ec_temperature: float = 0.0,
    ec_moisture: float = 0.0,
    electrical_conductivity: float = 0.0,
    soil_moisture_temp_ec_valid: int = 0,
    sensor_mask: int = 1,
    flow_meter_type: int = 0,
    flow_period_source: int = 0,
    flow_live_valid: bool = False,
    flow_period_totals_valid: bool = False,
    flow_cumulative_totals_valid: bool = False,
    rtc_valid: bool = False,
    forward_total_liters: int = 0,
    reverse_total_liters: int = 0,
    net_total_liters: int = 0,
    flow_period_quality: int = 0,
    flow_meter_alarm_flags: int = 0,
) -> bytes:
    """Serialize one Telemetry message using the new .proto layout."""
    msg = messages_pb2.Telemetry()
    msg.node_id = int(node_id)
    msg.timestamp = int(timestamp if timestamp is not None else time.time())
    msg.sampling_rate = max(1, int(sampling_rate))
    msg.Transmission_rate = max(1, int(transmission_rate))
    msg.battery_voltage = float(battery_voltage)
    msg.reserved2 = int(reserved2)
    msg.reserved3 = int(reserved3)
    msg.active_sensor_count = max(0, int(active_sensor_count))
    msg.sensor_id = int(sensor_id)
    msg.flow_rate = float(flow_rate)
    msg.velocity = float(velocity)
    msg.flow_rate_per_day = float(flow_rate_per_day)
    msg.flow_rate_per_month = float(flow_rate_per_month)
    msg.flow_rate_per_year = float(flow_rate_per_year)
    msg.node_status = int(node_status)
    msg.soil_temperature = float(soil_temperature)
    msg.soil_moisture = float(soil_moisture)
    msg.soil_moisture_temp_valid = int(soil_moisture_temp_valid)
    msg.ec_temperature = float(ec_temperature)
    msg.ec_moisture = float(ec_moisture)
    msg.electrical_conductivity = float(electrical_conductivity)
    msg.soil_moisture_temp_ec_valid = int(soil_moisture_temp_ec_valid)
    msg.sensor_mask = int(sensor_mask)
    _set_flow_v2(
        msg,
        flow_meter_type=flow_meter_type,
        flow_period_source=flow_period_source,
        flow_live_valid=flow_live_valid,
        flow_period_totals_valid=flow_period_totals_valid,
        flow_cumulative_totals_valid=flow_cumulative_totals_valid,
        rtc_valid=rtc_valid,
        forward_total_liters=forward_total_liters,
        reverse_total_liters=reverse_total_liters,
        net_total_liters=net_total_liters,
        flow_period_quality=flow_period_quality,
        flow_meter_alarm_flags=flow_meter_alarm_flags,
    )
    return msg.SerializeToString()
