import pathlib
import sys
import unittest


SIMULATOR_DIR = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SIMULATOR_DIR))

from multi_sensor_bus import InMemorySerial, MultiSensorSerialSlave  # noqa: E402
from multi_sensor_core import (  # noqa: E402
    BusSettings,
    SensorRegistry,
    SensorType,
    append_crc,
    create_device,
    frame_has_valid_crc,
)


def request(address: int, start: int, count: int) -> bytes:
    return append_crc(
        bytes(
            (
                address,
                3,
                (start >> 8) & 0xFF,
                start & 0xFF,
                (count >> 8) & 0xFF,
                count & 0xFF,
            )
        )
    )


class MultiSensorBusTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.registry = SensorRegistry(
            [
                create_device(SensorType.HNDA, 1),
                create_device(SensorType.TUF, 10),
            ]
        )
        self.worker = MultiSensorSerialSlave(
            BusSettings(port="loop://", response_delay_ms=0),
            self.registry,
            self.events.append,
        )

    def test_process_request_routes_to_correct_virtual_device(self):
        serial_port = InMemorySerial()
        self.worker._process_request(serial_port, request(10, 0, 6))
        response = bytes(serial_port.outgoing)
        self.assertEqual(response[0], 10)
        self.assertEqual(response[2], 12)
        self.assertTrue(frame_has_valid_crc(response))
        self.assertEqual(self.worker.counters()["received_frames"], 1)
        self.assertEqual(self.worker.counters()["transmitted_frames"], 1)
        self.assertEqual([event.level for event in self.events], ["rx", "tx"])

    def test_unknown_address_is_counted_as_ignored(self):
        serial_port = InMemorySerial()
        self.worker._process_request(serial_port, request(99, 0, 2))
        self.assertEqual(bytes(serial_port.outgoing), b"")
        counters = self.worker.counters()
        self.assertEqual(counters["received_frames"], 1)
        self.assertEqual(counters["ignored_frames"], 1)

    def test_exception_response_is_counted(self):
        serial_port = InMemorySerial()
        self.worker._process_request(serial_port, request(1, 0x1234, 1))
        response = bytes(serial_port.outgoing)
        self.assertEqual(response[:3], bytes((1, 0x83, 0x02)))
        self.assertEqual(self.worker.counters()["exception_frames"], 1)

    def test_parser_recovers_after_leading_noise(self):
        valid = request(1, 0, 2)
        buffer = bytearray(b"\xAA\x55\x00" + valid)
        self.assertEqual(self.worker._find_valid_request_offset(buffer), 3)

    def test_clear_counters(self):
        serial_port = InMemorySerial()
        self.worker._process_request(serial_port, request(1, 0, 2))
        self.worker.clear_counters()
        self.assertTrue(all(value == 0 for value in self.worker.counters().values()))


if __name__ == "__main__":
    unittest.main()
