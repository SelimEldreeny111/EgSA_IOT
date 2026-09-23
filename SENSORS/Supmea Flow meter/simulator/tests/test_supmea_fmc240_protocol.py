import pathlib
import sys
import unittest


SIMULATOR_DIR = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SIMULATOR_DIR))

from supmea_fmc240_protocol import (  # noqa: E402
    Fmc240Values,
    advance_totalizers,
    append_crc,
    bytes_to_hex,
    frame_has_valid_crc,
    handle_request,
    registers_to_float,
    reset_totalizers,
)


class SupmeaFmc240ProtocolTests(unittest.TestCase):
    def test_manual_flow_rate_request_crc(self):
        request = append_crc(bytes.fromhex("01 03 00 62 00 02"))
        self.assertEqual(bytes_to_hex(request), "01 03 00 62 00 02 65 D5")

    def test_manual_flow_rate_response_for_35(self):
        request = bytes.fromhex("01 03 00 62 00 02 65 D5")
        decision = handle_request(request, 1, Fmc240Values(flow_rate=35.0))
        self.assertEqual(
            bytes_to_hex(decision.response or b""),
            "01 03 04 42 0C 00 00 2E 48",
        )

    def test_live_block_matches_high_word_first_float_layout(self):
        request = append_crc(bytes.fromhex("04 03 00 62 00 0A"))
        values = Fmc240Values(
            flow_rate=12.5,
            velocity_mps=1.75,
            flow_ratio_percent=22.0,
            epd_percent=7,
            flow_rate_unit=3,
            epd_alarm=1,
            excitation_alarm=0,
        )
        response = handle_request(request, 4, values).response
        self.assertIsNotNone(response)
        assert response is not None
        self.assertTrue(frame_has_valid_crc(response))
        self.assertEqual(response[2], 20)
        registers = [
            (response[index] << 8) | response[index + 1]
            for index in range(3, 23, 2)
        ]
        self.assertAlmostEqual(registers_to_float(registers[0], registers[1]), 12.5)
        self.assertAlmostEqual(registers_to_float(registers[2], registers[3]), 1.75)
        self.assertAlmostEqual(registers_to_float(registers[4], registers[5]), 22.0)
        self.assertEqual(registers[6:], [7, 3, 1, 0])

    def test_wrong_slave_is_ignored(self):
        request = append_crc(bytes.fromhex("01 03 00 62 00 02"))
        self.assertIsNone(handle_request(request, 4, Fmc240Values()).response)

    def test_bad_crc_is_ignored(self):
        request = bytearray(append_crc(bytes.fromhex("04 03 00 62 00 02")))
        request[-1] ^= 0x01
        self.assertIsNone(handle_request(bytes(request), 4, Fmc240Values()).response)

    def test_illegal_address_returns_modbus_exception(self):
        request = append_crc(bytes.fromhex("04 03 00 6C 00 01"))
        response = handle_request(request, 4, Fmc240Values()).response
        self.assertIsNotNone(response)
        assert response is not None
        self.assertEqual(response[:3], bytes((4, 0x83, 0x02)))
        self.assertTrue(frame_has_valid_crc(response))

    def test_totalizer_advances_forward_volume_in_m3_per_hour(self):
        values = Fmc240Values(
            forward_total_m3=10.0,
            reverse_total_m3=2.0,
            net_total_m3=8.0,
            flow_rate=36.0,
            flow_rate_unit=3,
        )
        updated = advance_totalizers(values, elapsed_seconds=100.0)
        self.assertAlmostEqual(updated.forward_total_m3, 11.0)
        self.assertAlmostEqual(updated.reverse_total_m3, 2.0)
        self.assertAlmostEqual(updated.net_total_m3, 9.0)

    def test_totalizer_advances_reverse_and_supports_acceleration(self):
        values = Fmc240Values(
            forward_total_m3=10.0,
            reverse_total_m3=2.0,
            net_total_m3=8.0,
            flow_rate=-1.0,
            flow_rate_unit=3,
        )
        updated = advance_totalizers(
            values,
            elapsed_seconds=1.0,
            time_multiplier=3600.0,
        )
        self.assertAlmostEqual(updated.forward_total_m3, 10.0)
        self.assertAlmostEqual(updated.reverse_total_m3, 3.0)
        self.assertAlmostEqual(updated.net_total_m3, 7.0)

    def test_mass_flow_cannot_drive_volume_totalizer(self):
        with self.assertRaisesRegex(ValueError, "volumetric"):
            advance_totalizers(
                Fmc240Values(flow_rate=5.0, flow_rate_unit=6),
                elapsed_seconds=10.0,
            )

    def test_reset_totalizers_preserves_live_measurements(self):
        values = Fmc240Values(flow_rate=17.5, velocity_mps=0.8)
        reset = reset_totalizers(values)
        self.assertEqual(reset.forward_total_m3, 0.0)
        self.assertEqual(reset.reverse_total_m3, 0.0)
        self.assertEqual(reset.net_total_m3, 0.0)
        self.assertEqual(reset.flow_rate, 17.5)
        self.assertEqual(reset.velocity_mps, 0.8)


if __name__ == "__main__":
    unittest.main()
