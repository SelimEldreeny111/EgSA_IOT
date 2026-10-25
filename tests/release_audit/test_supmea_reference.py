"""Compare the independent flow integral against actual production C++ RTC code."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
NODE = ROOT / "Node/IoT_Node_Encrypted"
sys.path.insert(0, str(ROOT / "SENSORS/Multi Sensor RS485 Simulator"))
from supmea_reference import SupmeaReference


class SupmeaNodeOracleComparison(unittest.TestCase):
    def test_actual_node_utc_and_cairo_year_rollover(self):
        compiler = shutil.which("g++")
        if not compiler:
            self.fail("g++ is required for the production-node/reference comparison")
        fakes = NODE / "tests/rtc_supmea/fakes"
        environment = dict(os.environ, PATH=str(Path(compiler).parent) + os.pathsep + os.environ["PATH"])
        with tempfile.TemporaryDirectory(prefix="wiot-oracle-") as directory:
            executable = Path(directory) / "oracle.exe"
            subprocess.run([compiler, "-std=c++14", "-Wall", "-Wextra", "-Werror", "-pedantic",
                "-I", str(fakes), "-include", str(fakes / "TestAppConfig.h"),
                str(NODE / "src/devices/RTC.cpp"), str(NODE / "src/app/SupmeaPeriodAccumulator.cpp"),
                str(NODE / "tests/rtc_supmea/rtc_supmea_test.cpp"), "-o", str(executable)],
                check=True, env=environment, capture_output=True, text=True)
            for zone, scenario in (("UTC", "reference_trace_utc"), ("Africa/Cairo", "reference_trace_cairo"),
                    ("Africa/Cairo", "reference_trace_cairo_spring"),
                    ("Africa/Cairo", "reference_trace_cairo_fall")):
                output = subprocess.check_output([str(executable), scenario], env=environment, text=True)
                samples = [list(map(int, line.split()[1:])) for line in output.splitlines() if line.startswith("TRACE ")]
                self.assertEqual(len(samples), 125 if scenario.endswith("_fall") else 5)
                reference = SupmeaReference(zone, samples[0][0])
                previous = samples[0][0]
                for epoch, day, month, year in samples:
                    reference.advance(epoch - previous, 36)
                    for actual, expected in zip((day, month, year),
                            (reference.day_m3, reference.month_m3, reference.year_m3)):
                        self.assertAlmostEqual(actual / 1000, expected, places=6)
                    previous = epoch

    def test_both_simulators_use_identical_reference_math(self):
        first = ROOT / "SENSORS/Multi Sensor RS485 Simulator/supmea_reference.py"
        second = ROOT / "SENSORS/Supmea Flow meter/simulator/supmea_reference.py"
        self.assertEqual(first.read_bytes(), second.read_bytes())
