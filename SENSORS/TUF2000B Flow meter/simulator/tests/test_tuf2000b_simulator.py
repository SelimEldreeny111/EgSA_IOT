import pathlib
import sys
import unittest


SIMULATOR_DIR = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SIMULATOR_DIR))

from tuf2000b_protocol import Tuf2000bValues  # noqa: E402
from tuf2000b_simulator import SerialSettings, TufSerialSlave  # noqa: E402


class Tuf2000bSimulatorTests(unittest.TestCase):
    def test_running_slave_address_setting_can_be_changed(self):
        worker = TufSerialSlave(
            SerialSettings(
                port="loop://",
                baudrate=9600,
                parity="N",
                slave_id=2,
                response_delay_ms=0,
            ),
            Tuf2000bValues(),
            lambda _level, _message: None,
        )
        self.assertEqual(worker._slave_id_snapshot(), 2)
        worker.update_slave_id(17)
        self.assertEqual(worker._slave_id_snapshot(), 17)

    def test_invalid_runtime_slave_address_is_rejected(self):
        worker = TufSerialSlave(
            SerialSettings("loop://", 9600, "N", 2, 0),
            Tuf2000bValues(),
            lambda _level, _message: None,
        )
        with self.assertRaisesRegex(ValueError, "1 and 247"):
            worker.update_slave_id(0)
        with self.assertRaisesRegex(ValueError, "1 and 247"):
            worker.update_slave_id(248)


if __name__ == "__main__":
    unittest.main()
