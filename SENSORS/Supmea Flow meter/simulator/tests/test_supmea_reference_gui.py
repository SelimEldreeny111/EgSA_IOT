import tkinter as tk
from types import SimpleNamespace
from unittest.mock import patch
import unittest
from supmea_fmc240_simulator import SimulatorGui
from supmea_reference import SupmeaReference
from dataclasses import replace


class StandaloneReferenceGuiTests(unittest.TestCase):
    def test_gui_reference_integrates_without_adding_wire_values(self):
        root = tk.Tk()
        root.withdraw()
        try:
            app = SimulatorGui(root)
            app.current_values = replace(app.current_values, flow_rate=36)
            app.reference = SupmeaReference("UTC", 1800000000)
            app._last_totalizer_time = 100
            values = []
            app.worker = SimpleNamespace(update_values=values.append)
            with patch("supmea_fmc240_simulator.time.monotonic", return_value=160):
                app._advance_totalizers()
            self.assertAlmostEqual(app.reference.day_m3, .6)
            self.assertIn("0.600000", app.reference_summary.get())
            self.assertFalse(hasattr(values[-1], "today_m3"))
            before = app.current_values
            app.reference_zone.set("UTC")
            app._reset_reference()
            self.assertEqual(app.current_values, before)
            self.assertEqual(app.reference.day_m3, 0)
        finally:
            root.destroy()
