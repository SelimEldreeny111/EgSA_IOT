import pathlib
import struct
import sys
import tempfile
import unittest


SIMULATOR_DIR = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SIMULATOR_DIR))

from multi_sensor_core import (  # noqa: E402
    BusSettings,
    SensorRegistry,
    SensorType,
    SignalMode,
    append_crc,
    build_register_map,
    create_device,
    frame_has_valid_crc,
    load_configuration,
    parse_address_spec,
    save_configuration,
    validate_device_set,
)


def read_request(address: int, start: int, count: int) -> bytes:
    return append_crc(
        bytes(
            (
                address,
                0x03,
                (start >> 8) & 0xFF,
                start & 0xFF,
                (count >> 8) & 0xFF,
                count & 0xFF,
            )
        )
    )


def response_registers(response: bytes) -> list[int]:
    payload = response[3 : 3 + response[2]]
    return [
        (payload[index] << 8) | payload[index + 1]
        for index in range(0, len(payload), 2)
    ]


def low_word_first_float(registers: list[int]) -> float:
    return struct.unpack(">f", struct.pack(">HH", registers[1], registers[0]))[0]


def high_word_first_float(registers: list[int]) -> float:
    return struct.unpack(">f", struct.pack(">HH", registers[0], registers[1]))[0]


class MultiSensorCoreTests(unittest.TestCase):
    def test_two_hnda_devices_on_one_bus_answer_independently(self):
        hnda_1 = create_device(SensorType.HNDA, 1, name="HNDA node 1")
        hnda_2 = create_device(SensorType.HNDA, 2, name="HNDA node 2")
        hnda_1.signals["temperature_c"].value = 15.1
        hnda_1.signals["moisture_percent"].value = 35.6
        hnda_2.signals["temperature_c"].value = 28.4
        hnda_2.signals["moisture_percent"].value = 71.2
        hnda_1.reset_runtime()
        hnda_2.reset_runtime()
        registry = SensorRegistry([hnda_1, hnda_2])

        reply_1 = registry.dispatch(read_request(1, 0, 2)).response
        reply_2 = registry.dispatch(read_request(2, 0, 2)).response

        self.assertIsNotNone(reply_1)
        self.assertIsNotNone(reply_2)
        assert reply_1 is not None and reply_2 is not None
        self.assertEqual(response_registers(reply_1), [151, 356])
        self.assertEqual(response_registers(reply_2), [284, 712])
        self.assertTrue(frame_has_valid_crc(reply_1))
        self.assertTrue(frame_has_valid_crc(reply_2))

    def test_all_four_profiles_share_one_registry(self):
        devices = [
            create_device(SensorType.HNDA, 1),
            create_device(SensorType.TUF, 10),
            create_device(SensorType.SUPMEA, 20),
            create_device(SensorType.SONDAS, 30),
        ]
        registry = SensorRegistry(devices)
        cases = (
            (1, 0x0000, 2),
            (10, 0x0000, 6),
            (20, 0x005A, 18),
            (30, 0x0000, 3),
        )
        for address, start, count in cases:
            with self.subTest(address=address):
                decision = registry.dispatch(read_request(address, start, count))
                self.assertEqual(decision.level, "response")
                self.assertIsNotNone(decision.response)
                assert decision.response is not None
                self.assertEqual(decision.response[0], address)
                self.assertEqual(decision.response[2], count * 2)
                self.assertTrue(frame_has_valid_crc(decision.response))

    def test_full_247_address_bus_routes_without_cross_talk(self):
        devices = [
            create_device(
                SensorType.HNDA,
                address,
                name=f"HNDA scale device {address}",
                seed=address,
            )
            for address in range(1, 248)
        ]
        for device in devices:
            device.signals["moisture_percent"].value = float(
                device.address % 101
            )
            device.reset_runtime()
        registry = SensorRegistry(devices)

        for address in range(1, 248):
            with self.subTest(address=address):
                decision = registry.dispatch(read_request(address, 0, 2))
                self.assertIsNotNone(decision.response)
                assert decision.response is not None
                self.assertEqual(decision.response[0], address)
                self.assertEqual(
                    response_registers(decision.response)[1],
                    (address % 101) * 10,
                )

    def test_tuf_matches_low_word_first_layout(self):
        device = create_device(SensorType.TUF, 10)
        device.signals["flow_rate_m3h"].value = -17.25
        device.signals["energy_flow_rate_gjh"].value = 3.5
        device.signals["velocity_mps"].value = 1.75
        device.reset_runtime()
        reply = SensorRegistry([device]).dispatch(read_request(10, 0, 6)).response
        self.assertIsNotNone(reply)
        assert reply is not None
        registers = response_registers(reply)
        self.assertAlmostEqual(low_word_first_float(registers[0:2]), -17.25)
        self.assertAlmostEqual(low_word_first_float(registers[2:4]), 3.5)
        self.assertAlmostEqual(low_word_first_float(registers[4:6]), 1.75)

    def test_supmea_matches_high_word_first_layout(self):
        device = create_device(SensorType.SUPMEA, 20)
        device.signals["flow_rate"].value = 35.0
        device.signals["velocity_mps"].value = 1.75
        device.signals["flow_ratio_percent"].value = 42.5
        device.signals["epd_percent"].value = 7
        device.signals["flow_rate_unit"].value = 3
        device.signals["epd_alarm"].value = 1
        device.reset_runtime()
        reply = SensorRegistry([device]).dispatch(
            read_request(20, 0x0062, 10)
        ).response
        self.assertIsNotNone(reply)
        assert reply is not None
        registers = response_registers(reply)
        self.assertAlmostEqual(high_word_first_float(registers[0:2]), 35.0)
        self.assertAlmostEqual(high_word_first_float(registers[2:4]), 1.75)
        self.assertAlmostEqual(high_word_first_float(registers[4:6]), 42.5)
        self.assertEqual(registers[6:], [7, 3, 1, 0])

    def test_sondas_wiot_compatibility_registers(self):
        registers = build_register_map(
            SensorType.SONDAS,
            {
                "temperature_c": -4.2,
                "moisture_percent": 63.7,
                "electrical_conductivity": 1350,
            },
        )
        self.assertEqual(registers, {0: 0xFFD6, 1: 637, 2: 1350})

    def test_duplicate_addresses_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "address 7"):
            validate_device_set(
                [
                    create_device(SensorType.HNDA, 7),
                    create_device(SensorType.TUF, 7),
                ]
            )

    def test_wrong_disabled_and_muted_addresses_do_not_reply(self):
        device = create_device(SensorType.HNDA, 5)
        registry = SensorRegistry([device])
        self.assertIsNone(registry.dispatch(read_request(6, 0, 2)).response)
        registry.set_enabled(device.device_id, False)
        self.assertIsNone(registry.dispatch(read_request(5, 0, 2)).response)
        registry.set_enabled(device.device_id, True)
        registry.set_muted(device.device_id, True)
        decision = registry.dispatch(read_request(5, 0, 2))
        self.assertIsNone(decision.response)
        self.assertEqual(decision.level, "dropped")

    def test_hnda_address_write_moves_only_target_device(self):
        device = create_device(SensorType.HNDA, 1)
        registry = SensorRegistry([device])
        request = append_crc(bytes.fromhex("01 06 00 30 00 11"))
        decision = registry.dispatch(request)
        self.assertEqual(decision.response, request)
        self.assertIsNone(registry.dispatch(read_request(1, 0, 2)).response)
        self.assertIsNotNone(registry.dispatch(read_request(17, 0, 2)).response)

    def test_hnda_address_write_rejects_an_occupied_address(self):
        registry = SensorRegistry(
            [create_device(SensorType.HNDA, 1), create_device(SensorType.TUF, 10)]
        )
        request = append_crc(bytes.fromhex("01 06 00 30 00 0A"))
        decision = registry.dispatch(request)
        self.assertEqual(decision.level, "exception")
        assert decision.response is not None
        self.assertEqual(decision.response[:3], bytes((1, 0x86, 0x03)))

    def test_illegal_register_returns_standard_exception(self):
        registry = SensorRegistry([create_device(SensorType.HNDA, 1)])
        decision = registry.dispatch(read_request(1, 0x0010, 1))
        self.assertEqual(decision.level, "exception")
        assert decision.response is not None
        self.assertEqual(decision.response[:3], bytes((1, 0x83, 0x02)))

    def test_tuf_auto_totalizers_follow_flow_and_time_multiplier(self):
        device = create_device(SensorType.TUF, 10)
        device.update_interval_s = 0.05
        device.time_multiplier = 3600.0
        device.signals["flow_rate_m3h"].value = 2.0
        for key in ("today_total_m3", "month_total_m3", "year_total_m3"):
            device.signals[key].value = 10.0
        device.reset_runtime()
        device.advance(device._last_update + 1.0)
        for key in ("today_total_m3", "month_total_m3", "year_total_m3"):
            self.assertAlmostEqual(device.runtime_values[key], 12.0)

    def test_signal_modes_are_deterministic_per_device_seed(self):
        first = create_device(SensorType.HNDA, 1, mode=SignalMode.RANDOM, seed=99)
        second = create_device(SensorType.HNDA, 2, mode=SignalMode.RANDOM, seed=99)
        first.update_interval_s = second.update_interval_s = 0.05
        first.advance(first._last_update + 1.0)
        second.advance(second._last_update + 1.0)
        self.assertEqual(first.runtime_values, second.runtime_values)

    def test_fault_profiles_support_drop_crc_and_exception_testing(self):
        dropped = create_device(SensorType.HNDA, 1)
        dropped.faults.drop_percent = 100.0
        self.assertEqual(
            SensorRegistry([dropped]).dispatch(read_request(1, 0, 2)).level,
            "dropped",
        )

        bad_crc = create_device(SensorType.HNDA, 2)
        bad_crc.faults.crc_error_percent = 100.0
        reply = SensorRegistry([bad_crc]).dispatch(read_request(2, 0, 2)).response
        assert reply is not None
        self.assertFalse(frame_has_valid_crc(reply))

        exception = create_device(SensorType.HNDA, 3)
        exception.faults.forced_exception = 4
        decision = SensorRegistry([exception]).dispatch(read_request(3, 0, 2))
        self.assertEqual(decision.level, "exception")
        assert decision.response is not None
        self.assertEqual(decision.response[:3], bytes((3, 0x83, 4)))

    def test_address_list_parser_supports_ranges(self):
        self.assertEqual(parse_address_spec("1, 3, 10-13"), [1, 3, 10, 11, 12, 13])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            parse_address_spec("1,1")
        with self.assertRaisesRegex(ValueError, "between 1 and 247"):
            parse_address_spec("248")

    def test_configuration_round_trip_preserves_fleet(self):
        devices = [
            create_device(SensorType.HNDA, 1, mode=SignalMode.RANDOM_WALK),
            create_device(SensorType.HNDA, 2),
            create_device(SensorType.TUF, 10, mode=SignalMode.SINE),
            create_device(SensorType.SUPMEA, 20),
            create_device(SensorType.SONDAS, 30),
        ]
        settings = BusSettings(
            port="COM21", baudrate=9600, parity="N", stopbits=1,
            response_delay_ms=15,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "fleet.json"
            save_configuration(path, settings, devices)
            restored_bus, restored_devices = load_configuration(path)
        self.assertEqual(restored_bus.to_dict(), settings.to_dict())
        self.assertEqual(
            [(item.sensor_type, item.address) for item in restored_devices],
            [(item.sensor_type, item.address) for item in devices],
        )


if __name__ == "__main__":
    unittest.main()
