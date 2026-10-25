import pathlib
import sys
import tkinter as tk
import unittest
from unittest.mock import patch


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
            for callback in self.root.tk.call("after", "info"):
                self.root.after_cancel(callback)
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

    def test_supmea_reference_is_visible_without_extra_registers(self):
        app = MultiSensorSimulatorApp(self.root, SIMULATOR_DIR / "stm32_four_sensor_config.json")
        selected = next(item for item in app.registry.snapshots() if item["type"] == "SUPMEA")
        device_id = selected["id"]
        app.device_tree.selection_set(device_id)
        app.registry.reset_supmea_reference(device_id, "UTC", 1800000000)
        # Configure stable 36 m3/h through the actual device for this UI fixture.
        device = app.registry._devices[device_id]
        device.signals["flow_rate"].value = device.runtime_values["flow_rate"] = 36
        device.signals["flow_rate_unit"].value = device.runtime_values["flow_rate_unit"] = 3
        device.advance(device._last_update + 60)
        app._refresh_selected_details()
        self.assertIn("Today: 0.600000", app.reference_summary_var.get())
        self.assertIn("never transmitted on RS485", app.reference_summary_var.get())
        self.assertNotIn(124, device.build_register_map())

    def test_edit_preserves_reference_calendar(self):
        from multi_sensor_core import create_device
        device = create_device("SUPMEA", 2)
        device.reference_timezone = "UTC"
        dialog = DeviceEditorDialog(self.root, device, lambda *_args: True)
        dialog.withdraw()
        with patch("multi_sensor_simulator.messagebox.showerror") as error:
            dialog._save()
            self.assertFalse(error.called, str(error.call_args))
        self.assertIsNotNone(dialog.result)
        self.assertEqual(dialog.result.reference_timezone, "UTC")


if __name__ == "__main__":
    unittest.main()
