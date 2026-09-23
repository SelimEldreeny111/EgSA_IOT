import pathlib
import sys
import tkinter as tk
import unittest


SIMULATOR_DIR = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SIMULATOR_DIR))

from multi_sensor_core import SensorType  # noqa: E402
from multi_sensor_simulator import (  # noqa: E402
    APP_TITLE,
    DeviceEditorDialog,
    MultiSensorSimulatorApp,
)


class MultiSensorGuiSmokeTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk display is not available: {exc}")
        self.root.withdraw()

    def tearDown(self):
        if hasattr(self, "root") and self.root.winfo_exists():
            self.root.destroy()

    def test_main_dashboard_builds_with_starter_fleet(self):
        app = MultiSensorSimulatorApp(
            self.root, SIMULATOR_DIR / "default_config.json"
        )
        self.root.update_idletasks()
        self.assertEqual(self.root.title(), APP_TITLE)
        self.assertEqual(len(app.device_tree.get_children()), 5)
        self.assertEqual(app.count_vars[SensorType.HNDA].get(), "HNDA 2")
        self.assertEqual(app.count_vars[SensorType.TUF].get(), "TUF 1")
        self.assertEqual(app.count_vars[SensorType.SUPMEA].get(), "SUPMEA 1")
        self.assertEqual(app.count_vars[SensorType.SONDAS].get(), "SONDAS 1")
        self.assertTrue(app.measurement_tree.winfo_exists())
        self.assertTrue(app.log.winfo_exists())

    def test_add_dialog_uses_next_address_and_allows_type_selection(self):
        dialog = DeviceEditorDialog(
            self.root,
            None,
            lambda _address, _excluding_id: True,
            default_address=77,
        )
        dialog.withdraw()
        self.root.update_idletasks()
        self.assertFalse(dialog._editing)
        self.assertEqual(dialog.address_var.get(), "77")
        dialog.type_var.set(SensorType.SUPMEA.value)
        dialog._on_type_changed()
        self.assertEqual(dialog.type_var.get(), SensorType.SUPMEA.value)
        self.assertIn("flow_rate", dialog.signal_vars)
        dialog.destroy()


if __name__ == "__main__":
    unittest.main()
