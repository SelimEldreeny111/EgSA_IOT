"""Analytical oracle checks and proof that reference fields never enter Modbus."""
import unittest
from datetime import datetime, timezone
from supmea_reference import SupmeaReference, parse_utc_start
from multi_sensor_core import SensorRegistry, SensorType, create_device


class SupmeaReferenceTests(unittest.TestCase):
    def test_constant_flow_and_reverse(self):
        ref = SupmeaReference("UTC", parse_utc_start("2026-10-25T00:00:00Z"))
        ref.advance(60, 36)
        self.assertAlmostEqual(ref.day_m3, 0.6)
        ref.advance(60, -36)
        self.assertAlmostEqual(ref.day_m3, 0.6)  # Node measures forward consumption.
        ref.advance(60, None)
        self.assertAlmostEqual(ref.day_m3, 0.6)

    def test_year_boundary(self):
        ref = SupmeaReference("UTC", parse_utc_start("2026-12-31T23:59:30Z"))
        ref.advance(60, 36)
        self.assertEqual(ref.keys, ("2027-01-01", "2027-01", "2027"))
        for volume in (ref.day_m3, ref.month_m3, ref.year_m3):
            self.assertAlmostEqual(volume, .3)
        self.assertAlmostEqual(ref.session_m3, .6)

    def test_month_boundary_and_fixed_offset(self):
        ref = SupmeaReference("+02:00", parse_utc_start("2026-01-31T21:59:30Z"))
        ref.advance(60, 36)
        self.assertAlmostEqual(ref.day_m3, .3)
        self.assertAlmostEqual(ref.month_m3, .3)
        self.assertAlmostEqual(ref.year_m3, .6)

    def test_cairo_spring_dst(self):
        ref = SupmeaReference("Africa/Cairo", parse_utc_start("2026-04-23T21:59:30Z"))
        ref.advance(60, 36)
        self.assertEqual(ref.keys[0], "2026-04-24")
        self.assertAlmostEqual(ref.day_m3, .3)
        self.assertAlmostEqual(ref.month_m3, .6)

    def test_leap_day(self):
        ref = SupmeaReference("UTC", parse_utc_start("2028-02-28T23:59:30Z"))
        ref.advance(60, 36)
        self.assertEqual(ref.keys[0], "2028-02-29")
        self.assertAlmostEqual(ref.day_m3, .3)

    def test_invalid_inputs(self):
        for zone in ("+24:00", "+01:80", "not-a-zone"):
            with self.assertRaises(ValueError):
                SupmeaReference(zone)
        with self.assertRaises(ValueError):
            parse_utc_start("2026-10-25T00:00:00")
        ref = SupmeaReference("UTC", 1800000000)
        for value in (-1, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                ref.advance(value, 36)

    def test_reset_reference_does_not_change_registers(self):
        device = create_device(SensorType.SUPMEA, 2)
        registry = SensorRegistry([device])
        original = device.build_register_map()
        registry.reset_supmea_reference(device.device_id, "UTC", 1800000000)
        device.reference.advance(120, 36)
        self.assertEqual(device.build_register_map(), original)
        self.assertNotIn(124, original)  # No invented TUF-style D/M/Y map.
        self.assertEqual(registry.snapshots()[0]["supmea_reference"]["today_m3"], 1.2)

    def test_runtime_auto_totalizers_and_multiple_addresses(self):
        first, second = create_device("SUPMEA", 2), create_device("SUPMEA", 5)
        registry = SensorRegistry([first, second])
        for device in (first, second):
            device.runtime_values["flow_rate"] = device.signals["flow_rate"].value = 36
            registry.reset_supmea_reference(device.device_id, "UTC", 1800000000)
        first.advance(first._last_update + 60)
        self.assertAlmostEqual(first.reference.day_m3, .6)
        self.assertEqual(second.reference.day_m3, 0)
        first.auto_totalizers = False
        first.advance(first._last_update + 60)
        self.assertAlmostEqual(first.reference.day_m3, .6)
        self.assertIn("Paused", first.reference.status)
