from __future__ import annotations

from datetime import datetime, timezone
import importlib
import math
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest


SERVER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_DIR))

import flow_schema  # noqa: E402
import messages_pb2  # noqa: E402
import protobuf_impl  # noqa: E402


class FlowSchemaTests(unittest.TestCase):
    def test_status_v2_round_trip_preserves_both_sensor_families(self):
        payload = protobuf_impl.build_status(
            node_id=7,
            sensor_id=9,
            timestamp=1_800_000_000,
            flow_rate=12.5,
            soil_temperature=21.5,
            soil_moisture=44.0,
            soil_moisture_temp_valid=1,
            ec_temperature=22.5,
            ec_moisture=48.0,
            electrical_conductivity=1.75,
            soil_moisture_temp_ec_valid=1,
            sensor_mask=0x000C,
            flow_meter_type=2,
            flow_period_source=2,
            flow_live_valid=True,
            flow_period_totals_valid=True,
            flow_cumulative_totals_valid=True,
            rtc_valid=True,
            forward_total_liters=1_250_750,
            reverse_total_liters=25_250,
            net_total_liters=1_225_500,
            flow_period_quality=1,
            flow_meter_alarm_flags=0x00010002,
        )
        msg = messages_pb2.Status_Message.FromString(payload)
        self.assertAlmostEqual(msg.soil_temperature, 21.5)
        self.assertAlmostEqual(msg.soil_moisture, 44.0)
        self.assertEqual(msg.soil_moisture_temp_valid, 1)
        self.assertAlmostEqual(msg.ec_temperature, 22.5)
        self.assertAlmostEqual(msg.ec_moisture, 48.0)
        self.assertAlmostEqual(msg.electrical_conductivity, 1.75)
        self.assertEqual(msg.soil_moisture_temp_ec_valid, 1)
        self.assertEqual(msg.flow_meter_type, 2)
        self.assertEqual(msg.forward_total_liters, 1_250_750)
        self.assertEqual(msg.net_total_liters, 1_225_500)

    def test_appended_field_numbers_are_stable(self):
        status = messages_pb2.Status_Message.DESCRIPTOR.fields_by_name
        telemetry = messages_pb2.Telemetry.DESCRIPTOR.fields_by_name
        self.assertEqual(status["soil_temperature"].number, 10)
        self.assertEqual(status["electrical_conductivity"].number, 15)
        self.assertEqual(status["sensor_mask"].number, 18)
        self.assertEqual(status["battery_voltage"].number, 19)
        self.assertEqual(status["flow_meter_type"].number, 20)
        self.assertEqual(status["flow_meter_alarm_flags"].number, 30)
        self.assertEqual(telemetry["soil_temperature"].number, 16)
        self.assertEqual(telemetry["electrical_conductivity"].number, 21)
        self.assertEqual(telemetry["sensor_mask"].number, 23)
        self.assertEqual(telemetry["flow_meter_type"].number, 24)
        self.assertEqual(telemetry["flow_meter_alarm_flags"].number, 34)

    def test_telemetry_v2_round_trip_preserves_signed_net_total(self):
        payload = protobuf_impl.build_telemetry(
            node_id=2,
            sensor_id=3,
            flow_rate=4.5,
            timestamp=1_800_000_000,
            sensor_mask=0x0003,
            soil_temperature=20.0,
            soil_moisture=40.0,
            soil_moisture_temp_valid=1,
            flow_meter_type=1,
            flow_period_source=1,
            flow_live_valid=True,
            flow_period_totals_valid=True,
            net_total_liters=-125,
            flow_period_quality=1,
        )
        msg = messages_pb2.Telemetry.FromString(payload)
        self.assertEqual(msg.flow_meter_type, 1)
        self.assertTrue(msg.flow_live_valid)
        self.assertEqual(msg.net_total_liters, -125)
        self.assertEqual(msg.soil_moisture_temp_valid, 1)

    def test_old_tuf_payload_is_identified_from_legacy_mask(self):
        msg = messages_pb2.Status_Message(sensor_mask=0x0001)
        metadata = flow_schema.extract_flow_metadata(msg)
        self.assertEqual(metadata["flow_meter_type"], 1)
        self.assertEqual(metadata["flow_period_source"], 1)
        self.assertEqual(metadata["flow_live_valid"], 1)
        self.assertEqual(metadata["flow_period_totals_valid"], 1)
        self.assertEqual(metadata["legacy_flow_schema"], 1)

    def test_period_keys_follow_cairo_calendar(self):
        measured_at = int(
            datetime(2026, 5, 1, 21, 30, tzinfo=timezone.utc).timestamp()
        )
        msg = messages_pb2.Status_Message(
            flow_rate_per_day=1.25,
            flow_rate_per_month=10.5,
            flow_rate_per_year=100.75,
        )
        metadata = {
            "flow_period_totals_valid": 1,
            "flow_period_source": 2,
            "flow_period_quality": 1,
        }
        rows = flow_schema.calendar_period_rows(msg, metadata, measured_at)
        self.assertEqual(
            [row["period_key"] for row in rows],
            ["2026-05-02", "2026-05", "2026"],
        )
        self.assertEqual(rows[0]["volume_liters"], 1250)

    def test_invalid_period_number_does_not_break_ingestion(self):
        msg = messages_pb2.Status_Message(
            flow_rate_per_day=math.nan,
            flow_rate_per_month=1.0,
            flow_rate_per_year=1.0,
        )
        metadata = {
            "flow_period_totals_valid": 1,
            "flow_period_source": 2,
            "flow_period_quality": 1,
        }
        self.assertEqual(
            flow_schema.calendar_period_rows(msg, metadata, 1_800_000_000),
            [],
        )

    def test_missing_timezone_data_does_not_drop_message_processing(self):
        msg = messages_pb2.Status_Message(flow_rate_per_day=1.0)
        metadata = {
            "flow_period_totals_valid": 1,
            "flow_period_source": 2,
            "flow_period_quality": 1,
        }
        self.assertEqual(
            flow_schema.calendar_period_rows(
                msg,
                metadata,
                1_800_000_000,
                timezone_name="Invalid/Timezone",
            ),
            [],
        )


class ServerDatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.secret_names = (
            "WIOT_FLASK_SECRET_KEY",
            "WIOT_ADMIN_PASSWORD",
            "WIOT_SUPERVISOR_PASSWORD",
            "WIOT_MONITOR_PASSWORD",
        )
        cls.original_secret_env = {
            name: os.environ.get(name) for name in cls.secret_names
        }
        for name in cls.secret_names:
            os.environ.setdefault(name, f"test-only-{name.lower()}")

        cls.temp_dir = tempfile.TemporaryDirectory()
        original_cwd = os.getcwd()
        os.chdir(cls.temp_dir.name)
        try:
            cls.server_web = importlib.import_module("server_web")
        finally:
            os.chdir(original_cwd)

        cls.server_web.MAIN_DB_FILE = str(
            Path(cls.temp_dir.name) / "iot_data.db"
        )
        cls.server_web.MESSAGE_DB_DIR = str(
            Path(cls.temp_dir.name) / "messages_dbs"
        )
        cls.server_web._initialized_company_dbs.clear()

    @classmethod
    def tearDownClass(cls):
        cls.server_web.logging.shutdown()
        cls.temp_dir.cleanup()
        for name, value in cls.original_secret_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    def setUp(self):
        self.server_web._initialized_company_dbs.clear()

    def test_consumption_api_returns_readable_m3_snapshot(self):
        company = "API Test"
        metadata = {
            "flow_meter_type": 2,
            "flow_period_source": 2,
            "flow_live_valid": 1,
            "flow_period_totals_valid": 1,
            "flow_cumulative_totals_valid": 1,
            "rtc_valid": 1,
            "forward_total_liters": 10_000,
            "reverse_total_liters": 0,
            "net_total_liters": 10_000,
            "flow_period_quality": 1,
            "flow_meter_alarm_flags": 0,
            "legacy_flow_schema": 0,
        }
        self.assertTrue(self.server_web.save_message(
            1_789_150_000, "Status", 1, 1, 2.0, 0.5,
            0.5, 1.0, 2.0, "", company,
            sensor_mask=0x000C,
            flow_metadata=metadata,
            measured_at=1_789_150_000,
            time_source="node_rtc",
            sample_fingerprint="api-sample",
            period_rows=[{
                "period_type": "day",
                "period_key": "2026-09-12",
                "volume_liters": 500,
                "source": 2,
                "quality": 1,
            }],
        ))
        with self.server_web.app.test_client() as client:
            with client.session_transaction() as session:
                session["role"] = "user"
                session["username"] = "tester"
                session["company"] = company
            response = client.get("/api/consumption?period=day&node_id=1")

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["rows"][0]["volume_m3"], 0.5)
        self.assertEqual(body["rows"][0]["flow_meter_name"], "Supmea")
        self.assertEqual(body["rows"][0]["source_name"], "Node RTC calculated")

    def test_v2_sample_is_idempotent_and_periods_are_upserted(self):
        company = "Flow Test"
        metadata = {
            "flow_meter_type": 2,
            "flow_period_source": 2,
            "flow_live_valid": 1,
            "flow_period_totals_valid": 1,
            "flow_cumulative_totals_valid": 1,
            "rtc_valid": 1,
            "forward_total_liters": 100_000,
            "reverse_total_liters": 2_000,
            "net_total_liters": 98_000,
            "flow_period_quality": 1,
            "flow_meter_alarm_flags": 0,
            "legacy_flow_schema": 0,
        }
        periods = [{
            "period_type": "day",
            "period_key": "2026-09-12",
            "volume_liters": 500,
            "source": 2,
            "quality": 1,
        }]
        args = (
            1_789_150_000, "Status", 4, 8, 3.0, 1.0,
            0.5, 10.0, 100.0, "", company,
        )
        for _ in range(2):
            self.assertTrue(self.server_web.save_message(
                *args,
                sensor_mask=0x000C,
                flow_metadata=metadata,
                measured_at=1_789_150_000,
                time_source="node_rtc",
                sample_fingerprint="same-sample",
                period_rows=periods,
            ))

        db_path = self.server_web.get_company_db_path(company)
        conn = sqlite3.connect(db_path)
        try:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0], 2
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM meter_samples").fetchone()[0], 1
            )
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM consumption_periods"
                ).fetchone()[0],
                1,
            )
        finally:
            conn.close()

    def test_node_latest_uses_row_id_when_timestamps_tie(self):
        company = "Latest Tie"
        common_args = (
            1_789_150_000, "Status", 12, 1,
        )
        live_metadata = {
            "flow_meter_type": 1,
            "flow_live_valid": 1,
        }
        self.assertTrue(self.server_web.save_message(
            *common_args, 1.0, 0.0, 0.0, 0.0, 0.0, "first", company,
            flow_metadata=live_metadata,
        ))
        self.assertTrue(self.server_web.save_message(
            *common_args, 2.0, 0.0, 0.0, 0.0, 0.0, "second", company,
            flow_metadata=live_metadata,
        ))

        with self.server_web.app.test_client() as client:
            with client.session_transaction() as session:
                session["role"] = "user"
                session["username"] = "tester"
                session["company"] = company
            response = client.get("/api/node_latest?history_node=12")

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(len(body["latest"]), 1)
        self.assertEqual(body["latest"][0]["flow"], 2.0)
        self.assertEqual(
            [row["flow"] for row in body["history"]],
            [1.0, 2.0],
        )

    def test_legacy_tuf_database_is_backfilled_without_fake_rtc(self):
        company = "Legacy"
        db_path = Path(self.server_web.get_company_db_path(company))
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path)
        try:
            conn.execute("""CREATE TABLE messages
                            (id INTEGER PRIMARY KEY AUTOINCREMENT,
                             timestamp INTEGER, type TEXT, node_id INTEGER,
                             sensor_id TEXT, flow REAL, velocity REAL,
                             flow_day REAL, flow_month REAL, flow_year REAL,
                             details TEXT, company TEXT, node_status INTEGER,
                             sensor_mask INTEGER)""")
            conn.execute(
                """INSERT INTO messages
                   (timestamp, type, node_id, sensor_id, flow, velocity,
                    flow_day, flow_month, flow_year, details, company,
                    node_status, sensor_mask)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    1_789_150_000, "Status", 1, "1", 2.0, 1.0,
                    3.0, 4.0, 5.0, "", company, 0, 0x0001,
                ),
            )
            conn.commit()
        finally:
            conn.close()

        self.server_web.ensure_message_db(company)
        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute(
                "SELECT measured_at, time_source, flow_meter_type, "
                "flow_period_source, flow_live_valid, "
                "flow_period_totals_valid, rtc_valid, legacy_flow_schema "
                "FROM messages"
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(
            row,
            (1_789_150_000, "server_received", 1, 1, 1, 1, 0, 1),
        )


if __name__ == "__main__":
    unittest.main()
