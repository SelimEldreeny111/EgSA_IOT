import pathlib
import sys
import unittest


SIMULATOR_DIR = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SIMULATOR_DIR))

from tuf2000b_protocol import (  # noqa: E402
    ERROR_BIT_NAMES,
    REG_ERROR_CODE,
    REG_FLOW_RATE,
    REG_MONTH_TOTAL,
    REG_TODAY_TOTAL,
    REG_VELOCITY,
    REG_YEAR_FRACTION,
    REG_YEAR_INTEGER,
    Tuf2000bValues,
    advance_period_totals,
    append_crc,
    build_register_map,
    bytes_to_hex,
    frame_has_valid_crc,
    handle_request,
    registers_low_word_first_to_float,
    registers_low_word_first_to_int32,
    reset_period_total,
    split_year_total,
)


def response_registers(response: bytes) -> list[int]:
    byte_count = response[2]
    payload = response[3 : 3 + byte_count]
    return [
        (payload[index] << 8) | payload[index + 1]
        for index in range(0, len(payload), 2)
    ]


class Tuf2000bProtocolTests(unittest.TestCase):
    def test_exact_stm32_request_frames(self):
        cases = {
            "02 03 00 00 00 06": "02 03 00 00 00 06 C5 FB",
            "02 03 00 7C 00 04": "02 03 00 7C 00 04 85 E2",
            "02 03 00 90 00 04": "02 03 00 90 00 04 44 17",
            "02 03 00 47 00 01": "02 03 00 47 00 01 34 2C",
        }
        for payload, expected in cases.items():
            with self.subTest(payload=payload):
                self.assertEqual(bytes_to_hex(append_crc(bytes.fromhex(payload))), expected)

    def test_default_live_response_is_exact(self):
        request = bytes.fromhex("02 03 00 00 00 06 C5 FB")
        decision = handle_request(request, 2, Tuf2000bValues())
        self.assertEqual(
            bytes_to_hex(decision.response or b""),
            "02 03 0C 00 00 41 48 00 00 00 00 00 00 3F A0 C4 EB",
        )

    def test_live_block_matches_stm32_low_word_first_decoder(self):
        values = Tuf2000bValues(
            flow_rate_m3h=-17.25,
            energy_flow_rate_gjh=3.5,
            velocity_mps=1.75,
        )
        request = append_crc(bytes.fromhex("02 03 00 00 00 06"))
        response = handle_request(request, 2, values).response
        self.assertIsNotNone(response)
        assert response is not None
        self.assertTrue(frame_has_valid_crc(response))
        registers = response_registers(response)
        self.assertAlmostEqual(
            registers_low_word_first_to_float(registers[0], registers[1]), -17.25
        )
        self.assertAlmostEqual(
            registers_low_word_first_to_float(registers[2], registers[3]), 3.5
        )
        self.assertAlmostEqual(
            registers_low_word_first_to_float(registers[4], registers[5]), 1.75
        )

    def test_today_and_month_block(self):
        values = Tuf2000bValues(today_total_m3=123.625, month_total_m3=9876.5)
        request = append_crc(bytes.fromhex("02 03 00 7C 00 04"))
        response = handle_request(request, 2, values).response
        self.assertIsNotNone(response)
        assert response is not None
        registers = response_registers(response)
        self.assertAlmostEqual(
            registers_low_word_first_to_float(registers[0], registers[1]), 123.625
        )
        self.assertAlmostEqual(
            registers_low_word_first_to_float(registers[2], registers[3]), 9876.5
        )

    def test_year_block_matches_integer_plus_fraction_decoder(self):
        values = Tuf2000bValues(year_total_m3=654321.875)
        request = append_crc(bytes.fromhex("02 03 00 90 00 04"))
        response = handle_request(request, 2, values).response
        self.assertIsNotNone(response)
        assert response is not None
        registers = response_registers(response)
        integer = registers_low_word_first_to_int32(registers[0], registers[1])
        fraction = registers_low_word_first_to_float(registers[2], registers[3])
        self.assertEqual(integer, 654321)
        self.assertAlmostEqual(integer + fraction, 654321.875)

    def test_negative_year_total_round_trips(self):
        integer, fraction = split_year_total(-12.75)
        self.assertEqual(integer, -12)
        self.assertAlmostEqual(fraction, -0.75)
        values = Tuf2000bValues(year_total_m3=-12.75)
        registers = build_register_map(values)
        decoded_integer = registers_low_word_first_to_int32(
            registers[REG_YEAR_INTEGER], registers[REG_YEAR_INTEGER + 1]
        )
        decoded_fraction = registers_low_word_first_to_float(
            registers[REG_YEAR_FRACTION], registers[REG_YEAR_FRACTION + 1]
        )
        self.assertAlmostEqual(decoded_integer + decoded_fraction, -12.75)

    def test_error_code_exposes_all_documented_bits(self):
        self.assertEqual(len(ERROR_BIT_NAMES), 16)
        values = Tuf2000bValues(error_code=(1 << 0) | (1 << 3) | (1 << 15))
        request = append_crc(bytes.fromhex("02 03 00 47 00 01"))
        response = handle_request(request, 2, values).response
        self.assertIsNotNone(response)
        assert response is not None
        self.assertEqual(response_registers(response), [0x8009])

    def test_register_map_contains_every_node_register(self):
        registers = build_register_map(Tuf2000bValues())
        expected = {
            REG_FLOW_RATE,
            REG_FLOW_RATE + 1,
            REG_FLOW_RATE + 2,
            REG_FLOW_RATE + 3,
            REG_VELOCITY,
            REG_VELOCITY + 1,
            REG_ERROR_CODE,
            REG_TODAY_TOTAL,
            REG_TODAY_TOTAL + 1,
            REG_MONTH_TOTAL,
            REG_MONTH_TOTAL + 1,
            REG_YEAR_INTEGER,
            REG_YEAR_INTEGER + 1,
            REG_YEAR_FRACTION,
            REG_YEAR_FRACTION + 1,
        }
        self.assertEqual(set(registers), expected)

    def test_address_is_changeable(self):
        request_for_17 = append_crc(bytes.fromhex("11 03 00 47 00 01"))
        self.assertIsNotNone(
            handle_request(request_for_17, 17, Tuf2000bValues()).response
        )
        self.assertIsNone(handle_request(request_for_17, 2, Tuf2000bValues()).response)

    def test_wrong_slave_and_broadcast_are_ignored(self):
        wrong = append_crc(bytes.fromhex("01 03 00 47 00 01"))
        broadcast = append_crc(bytes.fromhex("00 03 00 47 00 01"))
        self.assertIsNone(handle_request(wrong, 2, Tuf2000bValues()).response)
        self.assertIsNone(handle_request(broadcast, 2, Tuf2000bValues()).response)

    def test_bad_crc_is_ignored(self):
        request = bytearray(append_crc(bytes.fromhex("02 03 00 47 00 01")))
        request[-1] ^= 0x01
        self.assertIsNone(handle_request(bytes(request), 2, Tuf2000bValues()).response)

    def test_illegal_address_returns_exception_02(self):
        request = append_crc(bytes.fromhex("02 03 00 10 00 01"))
        response = handle_request(request, 2, Tuf2000bValues()).response
        self.assertIsNotNone(response)
        assert response is not None
        self.assertEqual(response[:3], bytes((2, 0x83, 0x02)))
        self.assertTrue(frame_has_valid_crc(response))

    def test_illegal_function_returns_exception_01(self):
        request = append_crc(bytes.fromhex("02 04 00 47 00 01"))
        response = handle_request(request, 2, Tuf2000bValues()).response
        self.assertIsNotNone(response)
        assert response is not None
        self.assertEqual(response[:3], bytes((2, 0x84, 0x01)))

    def test_illegal_count_returns_exception_03(self):
        request = append_crc(bytes.fromhex("02 03 00 47 00 00"))
        response = handle_request(request, 2, Tuf2000bValues()).response
        self.assertIsNotNone(response)
        assert response is not None
        self.assertEqual(response[:3], bytes((2, 0x83, 0x03)))

    def test_period_totals_advance_at_flow_rate(self):
        values = Tuf2000bValues(
            flow_rate_m3h=36.0,
            today_total_m3=10.0,
            month_total_m3=20.0,
            year_total_m3=30.0,
        )
        updated = advance_period_totals(values, elapsed_seconds=100.0)
        self.assertAlmostEqual(updated.today_total_m3, 11.0)
        self.assertAlmostEqual(updated.month_total_m3, 21.0)
        self.assertAlmostEqual(updated.year_total_m3, 31.0)

    def test_period_totals_support_reverse_flow_and_time_acceleration(self):
        values = Tuf2000bValues(
            flow_rate_m3h=-1.0,
            today_total_m3=10.0,
            month_total_m3=20.0,
            year_total_m3=30.0,
        )
        updated = advance_period_totals(
            values, elapsed_seconds=1.0, time_multiplier=3600.0
        )
        self.assertAlmostEqual(updated.today_total_m3, 9.0)
        self.assertAlmostEqual(updated.month_total_m3, 19.0)
        self.assertAlmostEqual(updated.year_total_m3, 29.0)

    def test_period_resets_are_independent(self):
        values = Tuf2000bValues(
            today_total_m3=10.0, month_total_m3=20.0, year_total_m3=30.0
        )
        today = reset_period_total(values, "today")
        self.assertEqual(today.today_total_m3, 0.0)
        self.assertEqual(today.month_total_m3, 20.0)
        self.assertEqual(today.year_total_m3, 30.0)
        all_reset = reset_period_total(values, "all")
        self.assertEqual(
            (all_reset.today_total_m3, all_reset.month_total_m3, all_reset.year_total_m3),
            (0.0, 0.0, 0.0),
        )

    def test_invalid_values_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "finite"):
            build_register_map(Tuf2000bValues(flow_rate_m3h=float("nan")))
        with self.assertRaisesRegex(ValueError, "Int32"):
            build_register_map(Tuf2000bValues(year_total_m3=float(2**31)))
        with self.assertRaisesRegex(ValueError, "0xFFFF"):
            build_register_map(Tuf2000bValues(error_code=0x10000))


if __name__ == "__main__":
    unittest.main()
