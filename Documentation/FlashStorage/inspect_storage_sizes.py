"""Reproduce documented byte counts using the checked-in WIOT protobuf schema.

Run with Python from any folder. This reads generated code and performs no I/O
to hardware, user databases, credentials or MQTT brokers.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'Server/WIOT-Server-Web v1.31 - Fixed Sensor Readings in Dashboard'))
import messages_pb2 as wire


def encrypted_size(protobuf_size):
    return 17 + 16 * (protobuf_size // 16 + 1)


def sample():
    """A defined four-sensor example. Actual measurements change the encoded length."""
    result = wire.Telemetry(node_id=3, timestamp=1795000000, sampling_rate=60000,
        Transmission_rate=60000, battery_voltage=3.7, active_sensor_count=4, sensor_id=1,
        flow_rate=12.5, velocity=1.25, flow_rate_per_day=93.64,
        flow_rate_per_month=408.89, flow_rate_per_year=1068.14, node_status=2,
        soil_temperature=25, soil_moisture=40, soil_moisture_temp_valid=1,
        ec_temperature=24, ec_moisture=42, electrical_conductivity=850,
        soil_moisture_temp_ec_valid=1, sensor_mask=15, flow_meter_type=1,
        flow_period_source=1, flow_live_valid=True, flow_period_totals_valid=True,
        flow_cumulative_totals_valid=True, rtc_valid=True, forward_total_liters=11515865,
        reverse_total_liters=25250, net_total_liters=11490615, flow_period_quality=1,
        power_mode=5, power_state=1, wdt_reset_count=2, power_reset_count=5,
        sample_time_valid=True)
    result.secondary_flow_meter.CopyFrom(wire.FlowReading(flow_rate=35, velocity=4,
        flow_rate_per_day=30, flow_rate_per_month=300, flow_rate_per_year=3000,
        flow_meter_type=2, flow_period_source=2, flow_live_valid=True,
        flow_period_totals_valid=True, flow_cumulative_totals_valid=True,
        rtc_valid=True, forward_total_liters=1200000, net_total_liters=1200000,
        flow_period_quality=1))
    return result


if __name__ == '__main__':
    canonical_size = len(sample().SerializeToString())
    heartbeat = wire.Gateway_Status(gateway_id=1, uptime_seconds=3600,
        heartbeat_sequence=61, heartbeat_interval_seconds=60, uplink_transport=1,
        wdt_reset_count=2, power_reset_count=5, lora_aux_high=True)
    print(f'Example four-sensor canonical protobuf = {canonical_size} bytes')
    print(f'Example canonical protobuf encrypted for transmission = {encrypted_size(canonical_size)} bytes')
    print('Each sample occupies 512 flash bytes, including its header, padding, CRC and commit marker')
    print('8 MiB geometry = 2048 sectors, 2 metadata sectors, 2046 data sectors, 14322 record slots')
    print(f'Example gateway heartbeat without node reports = {len(heartbeat.SerializeToString())} protobuf bytes')
    print(f'Example encrypted gateway heartbeat = {encrypted_size(len(heartbeat.SerializeToString()))} bytes')
