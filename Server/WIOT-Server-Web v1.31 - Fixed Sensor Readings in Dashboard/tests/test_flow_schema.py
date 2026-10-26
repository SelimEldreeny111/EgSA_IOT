from __future__ import annotations

from datetime import datetime, timezone
from contextlib import closing
import importlib
import math
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch


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
        self.assertEqual(status["secondary_flow_meter"].number, 31)
        self.assertEqual(telemetry["soil_temperature"].number, 16)
        self.assertEqual(telemetry["electrical_conductivity"].number, 21)
        self.assertEqual(telemetry["sensor_mask"].number, 23)
        self.assertEqual(telemetry["flow_meter_type"].number, 24)
        self.assertEqual(telemetry["flow_meter_alarm_flags"].number, 34)
        self.assertEqual(telemetry["secondary_flow_meter"].number, 35)

    def test_four_sensor_status_keeps_both_flow_meters_distinct(self):
        msg = messages_pb2.Status_Message(
            node_id=12, sensor_id=1, timestamp=1_800_000_000,
            sensor_mask=0x000F, active_sensor_count=4,
            soil_temperature=21.0, soil_moisture=42.0,
            soil_moisture_temp_valid=1, ec_temperature=22.0,
            ec_moisture=43.0, electrical_conductivity=1.5,
            soil_moisture_temp_ec_valid=1,
            flow_meter_type=1, flow_rate=3.25,
            flow_rate_per_day=4.0, flow_period_totals_valid=True,
        )
        msg.secondary_flow_meter.flow_meter_type = 2
        msg.secondary_flow_meter.flow_rate = 2.5
        msg.secondary_flow_meter.flow_rate_per_day = 6.0
        msg.secondary_flow_meter.flow_period_totals_valid = True
        decoded = messages_pb2.Status_Message.FromString(msg.SerializeToString())
        secondary = flow_schema.secondary_flow_reading(decoded)
        self.assertEqual(decoded.active_sensor_count, 4)
        self.assertEqual(decoded.sensor_mask, 0x000F)
        self.assertAlmostEqual(decoded.flow_rate, 3.25)
        self.assertEqual(decoded.flow_meter_type, 1)
        self.assertEqual(secondary.flow_meter_type, 2)
        self.assertAlmostEqual(secondary.flow_rate, 2.5)
        self.assertEqual(flow_schema.flow_reading_snapshot(secondary)["flow_meter_name"], "Supmea")
        self.assertIsNone(flow_schema.secondary_flow_reading(messages_pb2.Status_Message()))

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

    def test_watchdog_counter_status_telemetry_database_api_and_export(self):
        import csv
        import io
        company = "WDT Counter"
        for kind, message_class, count in (
            ("Status", messages_pb2.Status_Message, 27),
            ("Telemetry", messages_pb2.Telemetry, 4294967295),
        ):
            msg = message_class(node_id=35, sensor_id=1, timestamp=1_800_000_000,
                                wdt_reset_count=count, power_reset_count=123)
            with patch.object(self.server_web, "emit_iot_message") as emit, \
                 patch.object(self.server_web, "dispatch_queued_command"):
                self.server_web.on_mqtt_plaintext(
                    f"wiot/{company}/Region_1/35/{'data' if kind == 'Telemetry' else 'status'}", msg.SerializeToString())
            self.assertEqual(emit.call_args.args[0]["WDT Resets"], count)
            self.assertEqual(emit.call_args.args[0]["Power Resets"], 123)
        with closing(sqlite3.connect(self.server_web.get_company_db_path(company))) as db:
            self.assertEqual(db.execute("SELECT wdt_reset_count FROM messages ORDER BY id").fetchall(),
                             [(27,), (4294967295,)])
        with patch.dict(self.server_web.app.config, TESTING=True), self.server_web.app.test_client() as client:
            with client.session_transaction() as session:
                session.update(role="user", username="tester", company=company)
            latest = client.get("/api/node_latest")
            history = client.get("/export_csv?start=2026-01-01%2000:00:00&end=2030-12-31%2023:59:59", buffered=True)
            self.assertEqual(history.status_code, 200, history.get_data(as_text=True)[:300])
        self.assertEqual(latest.status_code, 200)
        self.assertEqual(latest.get_json()["latest"][0]["wdt_reset_count"], 4294967295)
        self.assertEqual(latest.get_json()["latest"][0]["power_reset_count"], 123)
        rows = list(csv.DictReader(io.StringIO(history.get_data(as_text=True))))
        self.assertIn("WDT Resets", rows[0], history.get_data(as_text=True)[:300])
        self.assertEqual([row["WDT Resets"] for row in rows], ["4294967295", "27"])
        self.assertEqual([row["Power Resets"] for row in rows], ["123", "123"])

    def test_timestamp_migration_preserves_existing_watchdog_count(self):
        company = "WDT Text Timestamp"
        db_path = self.server_web.get_company_db_path(company)
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(db_path)) as db:
            db.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, timestamp TEXT, "
                       "type TEXT, node_id INTEGER, sensor_id TEXT, details TEXT, "
                       "company TEXT, wdt_reset_count INTEGER, power_reset_count INTEGER, region TEXT)")
            db.execute("INSERT INTO messages VALUES (1,'2026-10-01 10:00:00',"
                       "'Status',35,'1','keep',?,12,9,'Region_2')", (company,))
            db.commit()
        self.server_web.ensure_message_db(company)
        with closing(sqlite3.connect(db_path)) as db:
            self.assertEqual(db.execute("SELECT details,wdt_reset_count,power_reset_count,region FROM messages").fetchone(),
                             ("keep", 12, 9, "Region_2"))

    def test_dual_flow_samples_and_periods_are_stored_separately(self):
        company = "Dual Flow"
        measured_at = 1_800_000_000
        msg = messages_pb2.Status_Message(
            node_id=17, sensor_id=1, timestamp=measured_at,
            sensor_mask=0x000F, active_sensor_count=4,
            flow_meter_type=1, flow_rate=3.0,
            flow_rate_per_day=2.0, flow_rate_per_month=10.0,
            flow_rate_per_year=40.0, flow_period_source=1,
            flow_live_valid=True, flow_period_totals_valid=True,
            flow_period_quality=1, rtc_valid=True,
        )
        secondary = msg.secondary_flow_meter
        secondary.flow_meter_type = 2
        secondary.flow_rate = 4.0
        secondary.flow_rate_per_day = 5.0
        secondary.flow_rate_per_month = 12.0
        secondary.flow_rate_per_year = 45.0
        secondary.flow_period_source = 2
        secondary.flow_live_valid = True
        secondary.flow_period_totals_valid = True
        secondary.flow_period_quality = 1
        secondary.rtc_valid = True
        secondary.forward_total_liters = 50000

        primary_metadata = flow_schema.extract_flow_metadata(msg)
        secondary_data = self.server_web._secondary_flow_data(msg, company, measured_at)
        for _ in range(2):
            self.assertTrue(self.server_web.save_message(
                measured_at, "Status", 17, 1, msg.flow_rate, 0.0,
                msg.flow_rate_per_day, msg.flow_rate_per_month,
                msg.flow_rate_per_year, "", company,
                sensor_mask=msg.sensor_mask,
                flow_metadata=primary_metadata,
                measured_at=measured_at,
                sample_fingerprint=flow_schema.build_sample_fingerprint(
                    company, msg, primary_metadata, measured_at
                ),
                period_rows=flow_schema.calendar_period_rows(
                    msg, primary_metadata, measured_at
                ),
                secondary_flow=secondary_data,
            ))

        db_path = self.server_web.get_company_db_path(company)
        conn = sqlite3.connect(db_path)
        try:
            samples = conn.execute(
                "SELECT flow_meter_type, flow_rate FROM meter_samples ORDER BY flow_meter_type"
            ).fetchall()
            periods = conn.execute(
                "SELECT flow_meter_type, volume_liters FROM consumption_periods "
                "WHERE period_type='day' ORDER BY flow_meter_type"
            ).fetchall()
            saved_secondary = conn.execute(
                "SELECT secondary_flow_json FROM messages ORDER BY id DESC LIMIT 1"
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(samples, [(1, 3.0), (2, 4.0)])
        self.assertEqual(periods, [(1, 2000), (2, 5000)])
        self.assertIn('"flow_meter_name": "Supmea"', saved_secondary)

        with self.server_web.app.test_client() as client:
            with client.session_transaction() as session:
                session["role"] = "user"
                session["username"] = "tester"
                session["company"] = company
            response = client.get("/api/consumption?period=day&flow_meter_type=2")
            latest = client.get("/api/node_latest")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.get_json()["rows"]), 1)
        self.assertEqual(response.get_json()["rows"][0]["volume_m3"], 5.0)
        self.assertEqual(latest.get_json()["latest"][0]["secondary_flow_meter"]["flow_rate"], 4.0)

    def test_mqtt_status_ingestion_persists_all_four_sensor_fields(self):
        company = "Four Ingest"
        msg = messages_pb2.Status_Message(
            node_id=33, sensor_id=1, timestamp=1_800_000_000,
            sensor_mask=0x000F, active_sensor_count=4,
            flow_meter_type=1, flow_rate=1.5, flow_live_valid=True,
            soil_temperature=20.0, soil_moisture=35.0,
            soil_moisture_temp_valid=1, ec_temperature=21.0,
            ec_moisture=36.0, electrical_conductivity=2.25,
            soil_moisture_temp_ec_valid=1,
        )
        msg.secondary_flow_meter.flow_meter_type = 2
        msg.secondary_flow_meter.flow_rate = 2.5
        msg.secondary_flow_meter.flow_live_valid = True
        with patch.object(self.server_web, "emit_iot_message") as emit, \
             patch.object(self.server_web, "log_event"):
            self.server_web.on_mqtt_plaintext(
                f"wiot/{company}/Region_1/33/status", msg.SerializeToString()
            )
        payload = emit.call_args.args[0]
        self.assertEqual(payload["Active Sensors"], 4)
        self.assertEqual(payload["Sensor Mask"], 0x000F)
        self.assertAlmostEqual(payload["Soil Temp"], 20.0)
        self.assertAlmostEqual(payload["EC Cond"], 2.25)
        self.assertAlmostEqual(payload["Secondary Flow Meter"]["flow_rate"], 2.5)
        conn = sqlite3.connect(self.server_web.get_company_db_path(company))
        try:
            types = [row[0] for row in conn.execute(
                "SELECT flow_meter_type FROM meter_samples ORDER BY flow_meter_type"
            ).fetchall()]
        finally:
            conn.close()
        self.assertEqual(types, [1, 2])

    def test_failed_poll_replaces_latest_values_with_zero_without_erasing_history(self):
        company = "Unavailable Sensors"
        good = messages_pb2.Status_Message(
            node_id=34, sensor_id=1, timestamp=1_800_000_000,
            sensor_mask=15, active_sensor_count=4,
            flow_meter_type=1, flow_period_source=1, flow_rate=12,
            flow_live_valid=True, flow_rate_per_day=3,
            flow_period_totals_valid=True, flow_period_quality=1,
            soil_temperature=22, soil_moisture=55, soil_moisture_temp_valid=1,
            ec_temperature=23, ec_moisture=56, electrical_conductivity=1500,
            soil_moisture_temp_ec_valid=1)
        good.secondary_flow_meter.flow_meter_type = 2
        good.secondary_flow_meter.flow_period_source = 2
        good.secondary_flow_meter.flow_rate = 36
        good.secondary_flow_meter.flow_live_valid = True
        bad = messages_pb2.Status_Message(
            node_id=34, sensor_id=1, timestamp=1_800_000_060,
            sensor_mask=15, active_sensor_count=4,
            flow_meter_type=1, flow_period_source=1)
        bad.secondary_flow_meter.flow_meter_type = 2
        bad.secondary_flow_meter.flow_period_source = 2
        with patch.object(self.server_web, "emit_iot_message") as emit, \
             patch.object(self.server_web, "log_event"), \
             patch.object(self.server_web, "dispatch_queued_command"):
            for msg in (good, bad):
                self.server_web.on_mqtt_plaintext(
                    f"wiot/{company}/Region_1/34/status", msg.SerializeToString())
        payload = emit.call_args.args[0]
        for field in ("Flow", "Velocity", "Flow Day", "Flow Month", "Flow Year",
                      "Soil Temp", "Soil Moist", "EC Temp", "EC Moist", "EC Cond",
                      "Flow Live Valid", "Soil Valid", "EC Valid"):
            self.assertEqual(payload[field], 0, field)
        self.assertEqual(payload["Secondary Flow Meter"]["flow_rate"], 0)
        with closing(sqlite3.connect(self.server_web.get_company_db_path(company))) as db:
            self.assertEqual(db.execute(
                'SELECT flow, soil_temperature, electrical_conductivity, flow_live_valid '
                'FROM messages ORDER BY id DESC LIMIT 1').fetchone(), (0, 0, 0, 0))
            self.assertEqual(db.execute('SELECT COUNT(*) FROM messages').fetchone()[0], 2)
            self.assertEqual(db.execute('SELECT volume_liters FROM consumption_periods '
                                       "WHERE period_type='day'").fetchone()[0], 3000)

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

    def test_old_period_unique_key_migrates_without_losing_rows(self):
        company = "Period Migration"
        db_path = Path(self.server_web.get_company_db_path(company))
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path)
        try:
            conn.execute('''CREATE TABLE consumption_periods
                            (id INTEGER PRIMARY KEY AUTOINCREMENT,
                             node_id INTEGER NOT NULL, sensor_id TEXT NOT NULL,
                             flow_meter_type INTEGER NOT NULL,
                             period_type TEXT NOT NULL, period_key TEXT NOT NULL,
                             volume_liters INTEGER NOT NULL, source INTEGER NOT NULL,
                             quality INTEGER NOT NULL, measured_at INTEGER NOT NULL,
                             updated_at INTEGER NOT NULL,
                             UNIQUE(node_id, sensor_id, period_type, period_key))''')
            conn.execute('''INSERT INTO consumption_periods
                            (node_id, sensor_id, flow_meter_type, period_type,
                             period_key, volume_liters, source, quality,
                             measured_at, updated_at)
                            VALUES (1, '1', 1, 'day', '2026-09-23',
                                    1000, 1, 1, 1800000000, 1800000000)''')
            conn.commit()
        finally:
            conn.close()

        self.server_web.ensure_message_db(company)
        conn = sqlite3.connect(db_path)
        try:
            conn.execute('''INSERT INTO consumption_periods
                            (node_id, sensor_id, flow_meter_type, period_type,
                             period_key, volume_liters, source, quality,
                             measured_at, updated_at)
                            VALUES (1, '1', 2, 'day', '2026-09-23',
                                    2000, 2, 1, 1800000000, 1800000000)''')
            rows = conn.execute(
                "SELECT flow_meter_type, volume_liters FROM consumption_periods "
                "ORDER BY flow_meter_type"
            ).fetchall()
        finally:
            conn.close()
        self.assertEqual(rows, [(1, 1000), (2, 2000)])


if __name__ == "__main__":
    unittest.main()
