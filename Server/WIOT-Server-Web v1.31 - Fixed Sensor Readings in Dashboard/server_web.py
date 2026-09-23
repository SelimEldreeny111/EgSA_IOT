import time
import json
import sqlite3
import logging
import csv
import os
import secrets
import glob
import re
from io import StringIO
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, Response, send_file
from flask_socketio import SocketIO, join_room
from werkzeug.security import generate_password_hash, check_password_hash

import messages_pb2
from flow_schema import (
    build_sample_fingerprint,
    calendar_period_rows,
    dashboard_flow_fields,
    extract_flow_metadata,
    flow_meter_name,
    period_quality_name,
    period_source_name,
    select_measurement_timestamp,
)
from mqtt_impl import MqttNodeClient

MAIN_DB_FILE = 'iot_data.db'
MESSAGE_DB_DIR = 'messages_dbs'
_initialized_company_dbs = set()  # track which company DBs are already set up

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('WIOT_FLASK_SECRET_KEY') or secrets.token_hex(32)
socketio = SocketIO(app, async_mode='threading', cors_allowed_origins="*")

# Configure Logging
logging.basicConfig(filename='system.log', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
mqtt_client = None


def _required_secret(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(
            f"{name} must be set before creating the initial server users"
        )
    return value
# Admins/supervisor join this room and receive every company's live messages.
GLOBAL_ROOM = '__all__'
CMD_NAMES = {"SRATE": 1, "STRAN": 2, "STIME": 3, "GOSTM": 4, "VALVE": 5}
CMD_NAMES_REV = {v: k for k, v in CMD_NAMES.items()}

def log_event(msg: str):
    timestamp = datetime.now().strftime("%H:%M:%S")
    formatted = f"[{timestamp}] {msg}"
    print(formatted)
    logging.info(msg)
    socketio.emit('system_log', {'message': formatted})


@socketio.on('client_log')
def handle_client_log(data):
    """Handle logging messages from the client side"""
    msg = data.get('message', 'Unknown client event')
    timestamp = datetime.now().strftime("%H:%M:%S")
    formatted = f"[CLIENT] [{timestamp}] {msg}"
    print(formatted)
    logging.info(f"CLIENT: {msg}")
    socketio.emit('system_log', {'message': formatted})


@socketio.on('connect')
def handle_connect():
    """Scope each socket to its tenant. Only the EgSA_Supervisor joins the
    global room and sees every company's live data; everyone else (regular
    admins and users) joins only their own company room. Unauthenticated
    sockets are rejected."""
    if 'role' not in session:
        return False
    if session.get('username') == 'EgSA_Supervisor':
        join_room(GLOBAL_ROOM)
    else:
        join_room(session.get('company') or 'Unknown')


def emit_iot_message(payload, company):
    """Deliver a live message to the owning company and to the supervisor.
    Company members are never in GLOBAL_ROOM and the supervisor is never in a
    company room, so neither audience receives the message twice."""
    socketio.emit('iot_message', payload, room=company)
    socketio.emit('iot_message', payload, room=GLOBAL_ROOM)



def safe_company_name(company: str) -> str:
    if not company:
        company = 'Unknown'
    safe = re.sub(r'[^A-Za-z0-9_-]+', '_', company)
    return safe or 'Unknown'


def get_company_db_path(company: str) -> str:
    return os.path.join(MESSAGE_DB_DIR, f"{safe_company_name(company)}.db")


def normalize_db_timestamp(value):
    if value is None or value == '':
        return int(time.time())
    if isinstance(value, (int, float)):
        return int(value)
    try:
        return int(value)
    except (ValueError, TypeError):
        try:
            return int(datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S").timestamp())
        except ValueError:
            try:
                return int(datetime.fromisoformat(str(value)).timestamp())
            except ValueError:
                return int(time.time())


def _format_row_timestamp(row):
    ts = row.get('timestamp')
    epoch = normalize_db_timestamp(ts)
    try:
        row['timestamp'] = datetime.fromtimestamp(epoch).strftime("%Y-%m-%d %H:%M:%S")
    except (OSError, OverflowError):
        row['timestamp'] = str(ts)
    row['timestamp_epoch'] = epoch
    return row


def _migrate_messages_table_to_integer_timestamp(conn):
    c = conn.cursor()
    old_columns = {
        row[1] for row in c.execute("PRAGMA table_info(messages)").fetchall()
    }
    c.execute('DROP TABLE IF EXISTS messages_new')
    c.execute('''CREATE TABLE IF NOT EXISTS messages_new
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  timestamp INTEGER,
                  type TEXT,
                  node_id INTEGER,
                  sensor_id TEXT,
                  flow REAL,
                  velocity REAL,
                  flow_day REAL,
                  flow_month REAL,
                  flow_year REAL,
                   details TEXT,
                   company TEXT,
                   node_status INTEGER DEFAULT 0,
                   soil_temperature REAL,
                   soil_moisture REAL,
                   soil_moisture_temp_valid INTEGER,
                   ec_temperature REAL,
                   ec_moisture REAL,
                   electrical_conductivity REAL,
                   soil_moisture_temp_ec_valid INTEGER,
                   active_sensor_count INTEGER,
                   sensor_mask INTEGER,
                   battery_voltage REAL,
                   measured_at INTEGER,
                   time_source TEXT,
                   flow_meter_type INTEGER DEFAULT 0,
                   flow_period_source INTEGER DEFAULT 0,
                   flow_live_valid INTEGER DEFAULT 0,
                   flow_period_totals_valid INTEGER DEFAULT 0,
                   flow_cumulative_totals_valid INTEGER DEFAULT 0,
                   rtc_valid INTEGER DEFAULT 0,
                   forward_total_liters INTEGER DEFAULT 0,
                   reverse_total_liters INTEGER DEFAULT 0,
                   net_total_liters INTEGER DEFAULT 0,
                   flow_period_quality INTEGER DEFAULT 0,
                   flow_meter_alarm_flags INTEGER DEFAULT 0,
                   legacy_flow_schema INTEGER DEFAULT 0)''')

    target_columns = [
        "timestamp", "type", "node_id", "sensor_id", "flow", "velocity",
        "flow_day", "flow_month", "flow_year", "details", "company",
        "node_status", "soil_temperature", "soil_moisture",
        "soil_moisture_temp_valid", "ec_temperature", "ec_moisture",
        "electrical_conductivity", "soil_moisture_temp_ec_valid",
        "active_sensor_count", "sensor_mask", "battery_voltage",
        "measured_at", "time_source", "flow_meter_type",
        "flow_period_source", "flow_live_valid", "flow_period_totals_valid",
        "flow_cumulative_totals_valid", "rtc_valid", "forward_total_liters",
        "reverse_total_liters", "net_total_liters", "flow_period_quality",
        "flow_meter_alarm_flags", "legacy_flow_schema",
    ]
    copy_columns = [column for column in target_columns if column in old_columns]
    select_expressions = []
    for column in copy_columns:
        if column == "timestamp":
            select_expressions.append(
                "CASE "
                "WHEN typeof(timestamp)='integer' THEN timestamp "
                "WHEN typeof(timestamp)='real' THEN CAST(timestamp AS INTEGER) "
                "ELSE COALESCE(CAST(strftime('%s', timestamp) AS INTEGER), "
                "CAST(timestamp AS INTEGER), 0) END"
            )
        else:
            select_expressions.append(f'"{column}"')
    if copy_columns:
        quoted_columns = ", ".join(f'"{column}"' for column in copy_columns)
        c.execute(
            f"INSERT INTO messages_new ({quoted_columns}) "
            f"SELECT {', '.join(select_expressions)} FROM messages"
        )
    c.execute('DROP TABLE IF EXISTS messages')
    c.execute('ALTER TABLE messages_new RENAME TO messages')
    conn.commit()


def ensure_message_db(company: str) -> str:
    db_path = get_company_db_path(company)
    if company in _initialized_company_dbs:
        return db_path
    os.makedirs(MESSAGE_DB_DIR, exist_ok=True)
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS messages
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  timestamp INTEGER,
                  type TEXT,
                  node_id INTEGER,
                  sensor_id TEXT,
                  flow REAL,
                  velocity REAL,
                  flow_day REAL,
                  flow_month REAL,
                  flow_year REAL,
                  details TEXT,
                  company TEXT,
                  node_status INTEGER DEFAULT 0,
                  soil_temperature REAL,
                  soil_moisture REAL,
                  soil_moisture_temp_valid INTEGER,
                  ec_temperature REAL,
                  ec_moisture REAL,
                  electrical_conductivity REAL,
                   soil_moisture_temp_ec_valid INTEGER,
                   active_sensor_count INTEGER,
                   sensor_mask INTEGER,
                   battery_voltage REAL,
                   measured_at INTEGER,
                   time_source TEXT,
                   flow_meter_type INTEGER DEFAULT 0,
                   flow_period_source INTEGER DEFAULT 0,
                   flow_live_valid INTEGER DEFAULT 0,
                   flow_period_totals_valid INTEGER DEFAULT 0,
                   flow_cumulative_totals_valid INTEGER DEFAULT 0,
                   rtc_valid INTEGER DEFAULT 0,
                   forward_total_liters INTEGER DEFAULT 0,
                   reverse_total_liters INTEGER DEFAULT 0,
                   net_total_liters INTEGER DEFAULT 0,
                   flow_period_quality INTEGER DEFAULT 0,
                   flow_meter_alarm_flags INTEGER DEFAULT 0,
                   legacy_flow_schema INTEGER DEFAULT 0)''')
    conn.commit()
    c.execute("PRAGMA table_info(messages)")
    cols = {row[1].lower(): row[2].upper() for row in c.fetchall()}
    if 'timestamp' not in cols or cols.get('timestamp') != 'INTEGER':
        _migrate_messages_table_to_integer_timestamp(conn)
        c.execute("PRAGMA table_info(messages)")
        cols = {row[1].lower(): row[2].upper() for row in c.fetchall()}

    # Migrate columns for older databases
    new_cols = [
        ("soil_temperature", "REAL"),
        ("soil_moisture", "REAL"),
        ("soil_moisture_temp_valid", "INTEGER"),
        ("ec_temperature", "REAL"),
        ("ec_moisture", "REAL"),
        ("electrical_conductivity", "REAL"),
        ("soil_moisture_temp_ec_valid", "INTEGER"),
        ("active_sensor_count", "INTEGER"),
        ("sensor_mask", "INTEGER"),
        ("battery_voltage", "REAL"),
        ("measured_at", "INTEGER"),
        ("time_source", "TEXT"),
        ("flow_meter_type", "INTEGER DEFAULT 0"),
        ("flow_period_source", "INTEGER DEFAULT 0"),
        ("flow_live_valid", "INTEGER DEFAULT 0"),
        ("flow_period_totals_valid", "INTEGER DEFAULT 0"),
        ("flow_cumulative_totals_valid", "INTEGER DEFAULT 0"),
        ("rtc_valid", "INTEGER DEFAULT 0"),
        ("forward_total_liters", "INTEGER DEFAULT 0"),
        ("reverse_total_liters", "INTEGER DEFAULT 0"),
        ("net_total_liters", "INTEGER DEFAULT 0"),
        ("flow_period_quality", "INTEGER DEFAULT 0"),
        ("flow_meter_alarm_flags", "INTEGER DEFAULT 0"),
        ("legacy_flow_schema", "INTEGER DEFAULT 0")
    ]
    for col_name, col_type in new_cols:
        if col_name not in cols:
            try:
                c.execute(f"ALTER TABLE messages ADD COLUMN {col_name} {col_type}")
                cols[col_name] = col_type.upper()
            except sqlite3.OperationalError:
                pass

    # Preserve old deployments without pretending that their timestamp came
    # from a trusted node RTC. The established TUF sensor-mask bit is the only
    # legacy inference; Supmea never existed in the old production payload.
    c.execute('''UPDATE messages
                 SET measured_at = timestamp
                 WHERE measured_at IS NULL OR measured_at <= 0''')
    c.execute("""UPDATE messages
                 SET time_source = 'server_received'
                 WHERE time_source IS NULL OR time_source = ''""")
    c.execute('''UPDATE messages
                 SET flow_meter_type = 1,
                     flow_period_source = 1,
                     flow_live_valid = 1,
                     flow_period_totals_valid = 1,
                     flow_period_quality = 1,
                     legacy_flow_schema = 1
                 WHERE flow_meter_type = 0
                   AND (COALESCE(sensor_mask, 0) & 1) != 0
                   AND type IN ('Status', 'Telemetry')''')

    c.execute('''CREATE TABLE IF NOT EXISTS meter_samples
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  received_at INTEGER NOT NULL,
                  measured_at INTEGER NOT NULL,
                  time_source TEXT NOT NULL,
                  message_type TEXT NOT NULL,
                  node_id INTEGER NOT NULL,
                  sensor_id TEXT NOT NULL,
                  flow_meter_type INTEGER NOT NULL,
                  flow_rate REAL,
                  velocity REAL,
                  volume_day REAL,
                  volume_month REAL,
                  volume_year REAL,
                  forward_total_liters INTEGER,
                  reverse_total_liters INTEGER,
                  net_total_liters INTEGER,
                  flow_live_valid INTEGER NOT NULL,
                  period_totals_valid INTEGER NOT NULL,
                  cumulative_totals_valid INTEGER NOT NULL,
                  rtc_valid INTEGER NOT NULL,
                  period_source INTEGER NOT NULL,
                  period_quality INTEGER NOT NULL,
                  alarm_flags INTEGER NOT NULL,
                  sample_fingerprint TEXT NOT NULL UNIQUE)''')
    c.execute('''CREATE INDEX IF NOT EXISTS idx_meter_samples_node_time
                 ON meter_samples(node_id, sensor_id, measured_at)''')
    c.execute('''CREATE TABLE IF NOT EXISTS consumption_periods
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  node_id INTEGER NOT NULL,
                  sensor_id TEXT NOT NULL,
                  flow_meter_type INTEGER NOT NULL,
                  period_type TEXT NOT NULL,
                  period_key TEXT NOT NULL,
                  volume_liters INTEGER NOT NULL,
                  source INTEGER NOT NULL,
                  quality INTEGER NOT NULL,
                  measured_at INTEGER NOT NULL,
                  updated_at INTEGER NOT NULL,
                  UNIQUE(node_id, sensor_id, period_type, period_key))''')
    c.execute('''CREATE INDEX IF NOT EXISTS idx_consumption_periods_lookup
                 ON consumption_periods(node_id, sensor_id, period_type, period_key)''')
    conn.commit()
    conn.close()
    _initialized_company_dbs.add(company)
    logging.info(f"Ensured company database: {db_path}")
    return db_path


def migrate_legacy_messages_to_company_dbs():
    if not os.path.exists(MAIN_DB_FILE):
        return
    conn = sqlite3.connect(MAIN_DB_FILE)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    try:
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='messages'")
        if not c.fetchone():
            return
        rows = c.execute("SELECT * FROM messages").fetchall()
        if not rows:
            return

        # Group rows by company first, then write each company in one transaction
        by_company = {}
        for row in rows:
            company = row['company'] if 'company' in row.keys() and row['company'] else 'Unknown'
            node_status = row['node_status'] if 'node_status' in row.keys() else 0
            by_company.setdefault(company, []).append((
                normalize_db_timestamp(row['timestamp']), row['type'], row['node_id'], row['sensor_id'],
                row['flow'], row['velocity'], row['flow_day'], row['flow_month'],
                row['flow_year'], row['details'], company, node_status
            ))

        for company, records in by_company.items():
            ensure_message_db(company)
            dest_conn = sqlite3.connect(get_company_db_path(company))
            dest_c = dest_conn.cursor()
            dest_c.executemany(
                '''INSERT INTO messages
                   (timestamp, type, node_id, sensor_id, flow, velocity, flow_day, flow_month, flow_year, details, company, node_status)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
                records
            )
            dest_conn.commit()
            dest_conn.close()
        logging.info(f"Migrated {len(rows)} legacy rows across {len(by_company)} company DB(s).")
    except Exception as e:
        logging.warning(f"Legacy message migration failed: {e}")
    finally:
        conn.close()


def query_messages_db(db_path: str, start: str, end: str, msg_type: str = None, limit: int = None, offset: int = 0):
    if not os.path.exists(db_path):
        return []
    start_ts = normalize_db_timestamp(start)
    end_ts = normalize_db_timestamp(end)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    query = "SELECT * FROM messages WHERE timestamp BETWEEN ? AND ?"
    params = [start_ts, end_ts]
    if msg_type:
        query += " AND type = ?"
        params.append(msg_type)
    # SQLite timestamps are stored with one-second resolution.  Use the
    # monotonic row id as a tie-breaker so pagination is deterministic when
    # multiple packets arrive during the same second.
    query += " ORDER BY timestamp DESC, id DESC"
    if limit is not None:
        query += " LIMIT ? OFFSET ?"
        params.extend([limit, offset])
    c.execute(query, params)
    rows = [dict(ix) for ix in c.fetchall()]
    conn.close()
    return [_format_row_timestamp(r) for r in rows]


def count_messages_db(db_path: str, start: str, end: str, msg_type: str = None):
    if not os.path.exists(db_path):
        return 0
    start_ts = normalize_db_timestamp(start)
    end_ts = normalize_db_timestamp(end)
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    query = "SELECT COUNT(*) FROM messages WHERE timestamp BETWEEN ? AND ?"
    params = [start_ts, end_ts]
    if msg_type:
        query += " AND type = ?"
        params.append(msg_type)
    c.execute(query, params)
    count = c.fetchone()[0]
    conn.close()
    return count


def query_messages_from_all_company_dbs(start: str, end: str, msg_type: str = None, limit: int = None, offset: int = 0):
    if not os.path.isdir(MESSAGE_DB_DIR):
        return []
    all_rows = []
    for db_path in sorted(glob.glob(os.path.join(MESSAGE_DB_DIR, '*.db'))):
        all_rows.extend(query_messages_db(db_path, start, end, msg_type))
    all_rows.sort(key=lambda r: r.get('timestamp_epoch', 0), reverse=True)
    if limit is not None:
        all_rows = all_rows[offset:offset + limit]
    return all_rows


def count_messages_from_all_company_dbs(start: str, end: str, msg_type: str = None):
    if not os.path.isdir(MESSAGE_DB_DIR):
        return 0
    total = 0
    for db_path in sorted(glob.glob(os.path.join(MESSAGE_DB_DIR, '*.db'))):
        total += count_messages_db(db_path, start, end, msg_type)
    return total


# Database Init
def init_db():
    conn = sqlite3.connect(MAIN_DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  username TEXT UNIQUE,
                  password TEXT,
                  role TEXT,
                  company TEXT DEFAULT 'Company_1')''')
    c.execute('''CREATE TABLE IF NOT EXISTS companies
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  name TEXT UNIQUE,
                  created_at TEXT)''')

    # Add missing columns for existing databases created by older versions.
    try:
        c.execute("ALTER TABLE users ADD COLUMN company TEXT DEFAULT 'Company_1'")
    except sqlite3.OperationalError:
        pass  # Column already exists

    # Initialize default companies if they don't exist
    c.execute("SELECT COUNT(*) FROM companies")
    if c.fetchone()[0] == 0:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        c.execute("INSERT INTO companies (name, created_at) VALUES (?, ?)", ('Company_1', now))
        c.execute("INSERT INTO companies (name, created_at) VALUES (?, ?)", ('Company_2', now))

    c.execute("SELECT * FROM users WHERE role='admin'")
    if not c.fetchone():
        c.execute("INSERT INTO users (username, password, role, company) VALUES (?, ?, ?, ?)", 
                  ('admin', generate_password_hash(_required_secret("WIOT_ADMIN_PASSWORD")), 'admin', 'Company_1'))

    # Ensure built-in special accounts are present.
    c.execute("SELECT * FROM users WHERE username='EgSA_Supervisor'")
    if not c.fetchone():
        c.execute("INSERT INTO users (username, password, role, company) VALUES (?, ?, ?, ?)",
                  ('EgSA_Supervisor', generate_password_hash(_required_secret("WIOT_SUPERVISOR_PASSWORD")), 'admin', ''))

    # Ensure a built-in monitoring user exists. This user is not an admin
    # but is allowed to switch the active company for monitoring purposes
    # and cannot be deleted via the user management API.
    c.execute("SELECT * FROM users WHERE username='Super_User'")
    if not c.fetchone():
        c.execute("INSERT INTO users (username, password, role, company) VALUES (?, ?, ?, ?)",
                  ('Super_User', generate_password_hash(_required_secret("WIOT_MONITOR_PASSWORD")), 'monitor', 'Company_1'))
    conn.commit()
    conn.close()

    migrate_legacy_messages_to_company_dbs()

    conn = sqlite3.connect(MAIN_DB_FILE)
    c = conn.cursor()
    c.execute("SELECT name FROM companies")
    for row in c.fetchall():
        ensure_message_db(row[0])
    conn.close()


init_db()

def save_message(t, m_type, n_id, s_id, flow, vel, fday, fmonth, fyear, det, company, node_status=0,
                 soil_temp=0.0, soil_moist=0.0, soil_valid=0,
                 ec_temp=0.0, ec_moist=0.0, ec_cond=0.0, ec_valid=0,
                 active_sensors=1, sensor_mask=1, battery_voltage=None,
                 flow_metadata=None, measured_at=None, time_source="server_received",
                 sample_fingerprint=None, period_rows=None):
    conn = None
    try:
        flow_metadata = flow_metadata or {}
        period_rows = period_rows or []
        db_path = ensure_message_db(company)
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        epoch_ts = normalize_db_timestamp(t)
        measured_epoch = normalize_db_timestamp(
            measured_at if measured_at is not None else epoch_ts
        )
        c.execute('''INSERT INTO messages 
                      (timestamp, type, node_id, sensor_id, flow, velocity, flow_day, flow_month, flow_year, details, company, node_status,
                       soil_temperature, soil_moisture, soil_moisture_temp_valid,
                       ec_temperature, ec_moisture, electrical_conductivity, soil_moisture_temp_ec_valid,
                       active_sensor_count, sensor_mask, battery_voltage, measured_at, time_source,
                       flow_meter_type, flow_period_source, flow_live_valid, flow_period_totals_valid,
                       flow_cumulative_totals_valid, rtc_valid, forward_total_liters, reverse_total_liters,
                       net_total_liters, flow_period_quality, flow_meter_alarm_flags, legacy_flow_schema)
                      VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                  (epoch_ts, m_type, n_id, str(s_id), flow, vel, fday, fmonth, fyear, det, company, node_status,
                   soil_temp, soil_moist, soil_valid, ec_temp, ec_moist, ec_cond, ec_valid, active_sensors, sensor_mask,
                   battery_voltage, measured_epoch, time_source,
                   flow_metadata.get("flow_meter_type", 0),
                   flow_metadata.get("flow_period_source", 0),
                   flow_metadata.get("flow_live_valid", 0),
                   flow_metadata.get("flow_period_totals_valid", 0),
                   flow_metadata.get("flow_cumulative_totals_valid", 0),
                   flow_metadata.get("rtc_valid", 0),
                   flow_metadata.get("forward_total_liters", 0),
                   flow_metadata.get("reverse_total_liters", 0),
                   flow_metadata.get("net_total_liters", 0),
                   flow_metadata.get("flow_period_quality", 0),
                   flow_metadata.get("flow_meter_alarm_flags", 0),
                   flow_metadata.get("legacy_flow_schema", 0)))

        if flow_metadata.get("flow_meter_type", 0) and sample_fingerprint:
            c.execute('''INSERT OR IGNORE INTO meter_samples
                         (received_at, measured_at, time_source, message_type,
                          node_id, sensor_id, flow_meter_type, flow_rate, velocity,
                          volume_day, volume_month, volume_year,
                          forward_total_liters, reverse_total_liters, net_total_liters,
                          flow_live_valid, period_totals_valid, cumulative_totals_valid,
                          rtc_valid, period_source, period_quality, alarm_flags,
                          sample_fingerprint)
                         VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                      (epoch_ts, measured_epoch, time_source, m_type,
                       n_id, str(s_id), flow_metadata["flow_meter_type"], flow, vel,
                       fday, fmonth, fyear,
                       flow_metadata.get("forward_total_liters", 0),
                       flow_metadata.get("reverse_total_liters", 0),
                       flow_metadata.get("net_total_liters", 0),
                       flow_metadata.get("flow_live_valid", 0),
                       flow_metadata.get("flow_period_totals_valid", 0),
                       flow_metadata.get("flow_cumulative_totals_valid", 0),
                       flow_metadata.get("rtc_valid", 0),
                       flow_metadata.get("flow_period_source", 0),
                       flow_metadata.get("flow_period_quality", 0),
                       flow_metadata.get("flow_meter_alarm_flags", 0),
                       sample_fingerprint))

            for period in period_rows:
                c.execute('''INSERT INTO consumption_periods
                             (node_id, sensor_id, flow_meter_type, period_type,
                              period_key, volume_liters, source, quality,
                              measured_at, updated_at)
                             VALUES (?,?,?,?,?,?,?,?,?,?)
                             ON CONFLICT(node_id, sensor_id, period_type, period_key)
                             DO UPDATE SET
                                 flow_meter_type=excluded.flow_meter_type,
                                 volume_liters=excluded.volume_liters,
                                 source=excluded.source,
                                 quality=excluded.quality,
                                 measured_at=excluded.measured_at,
                                 updated_at=excluded.updated_at
                             WHERE excluded.measured_at >= consumption_periods.measured_at''',
                          (n_id, str(s_id), flow_metadata["flow_meter_type"],
                           period["period_type"], period["period_key"],
                           period["volume_liters"], period["source"],
                           period["quality"], measured_epoch, epoch_ts))
        conn.commit()
        logging.info(f"Saved {m_type} message for Node {n_id} (Company: {company}) to database")
        return True
    except Exception as e:
        if conn is not None:
            conn.rollback()
        log_event(f"Database error: {e}")
        return False
    finally:
        if conn is not None:
            conn.close()

def on_mqtt_status(msg: str):
    """Handle MQTT status messages from the MqttNodeClient."""
    if msg:
        log_event(msg)
        logging.info(f"[MQTT_STATUS] {msg}")
        
        # Parse connection status and emit to clients
        if 'Connected rc=0' in msg:
            socketio.emit('broker_status', {'connected': True, 'status': 'Connected'})
        elif 'Connected rc=' in msg and 'rc=0' not in msg:
            # Extract error code
            socketio.emit('broker_status', {'connected': False, 'status': 'Connection failed'})
        elif 'Disconnected' in msg or 'Disconnected rc' in msg:
            socketio.emit('broker_status', {'connected': False, 'status': 'Disconnected'})

def on_mqtt_plaintext(topic: str, plaintext: bytes):
    """Handle successfully decrypted MQTT messages."""
    log_event(f"[PLAINTEXT] Received {len(plaintext)} bytes on topic: {topic}")
    logging.info(f"[PLAINTEXT] topic={topic} len={len(plaintext)} type={type(plaintext)}")
    
    if not plaintext:
        log_event(f"[PLAINTEXT] WARNING: Empty plaintext payload on topic {topic}")
        logging.warning(f"[PLAINTEXT] Empty payload on {topic}")
        return
    
    timestamp_epoch = int(time.time())
    t = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    topic_parts = topic.split('/')
    company = topic_parts[1] if len(topic_parts) > 1 else "Unknown"
    
    log_event(f"[PLAINTEXT] Topic parts: {topic_parts}, Company: {company}")
    logging.info(f"[PLAINTEXT] Parsing - parts={topic_parts} company={company}")

    try:
        if "status" in topic.lower():
            log_event(f"[PLAINTEXT] Parsing as Status_Message...")
            msg = messages_pb2.Status_Message()
            msg.ParseFromString(plaintext)
            logging.info(f"[PLAINTEXT] Parsed Status_Message: node_id={msg.node_id} sensor_id={msg.sensor_id}")
            
            # Validate node ID matches topic
            if len(topic_parts) >= 3:
                try:
                    topic_node_id = int(topic_parts[2])
                    if msg.node_id != topic_node_id:
                        log_event(f"[VALIDATION ERROR] Status: Node ID mismatch - topic={topic_node_id}, payload={msg.node_id}")
                        logging.error(f"[PLAINTEXT] DROPPED - Node ID mismatch: topic={topic_node_id} vs payload={msg.node_id}")
                        return
                    log_event(f"[PLAINTEXT] Node ID validated: {msg.node_id}")
                except ValueError:
                    log_event(f"[PARSE ERROR] Status: Cannot extract node ID from topic: {topic}")
                    logging.error(f"[PLAINTEXT] DROPPED - Cannot parse node ID from {topic}")
                    return
            
            log_event(f"[PLAINTEXT] Saving Status message - node={msg.node_id}, flow={msg.flow_rate}")
            flow_metadata = extract_flow_metadata(msg)
            measured_at, time_source = select_measurement_timestamp(
                msg, timestamp_epoch
            )
            sample_fingerprint = build_sample_fingerprint(
                company, msg, flow_metadata, measured_at
            )
            period_rows = calendar_period_rows(msg, flow_metadata, measured_at)
            save_message(timestamp_epoch, "Status", msg.node_id, msg.sensor_id, msg.flow_rate, msg.velocity,
                         msg.flow_rate_per_day, msg.flow_rate_per_month, msg.flow_rate_per_year, "", company, msg.node_status,
                         msg.soil_temperature, msg.soil_moisture, msg.soil_moisture_temp_valid,
                         msg.ec_temperature, msg.ec_moisture, msg.electrical_conductivity, msg.soil_moisture_temp_ec_valid,
                         msg.active_sensor_count, msg.sensor_mask, msg.battery_voltage,
                         flow_metadata=flow_metadata, measured_at=measured_at,
                         time_source=time_source,
                         sample_fingerprint=sample_fingerprint,
                         period_rows=period_rows)
            
            payload = {
                "Time": t, "Epoch": timestamp_epoch, "Type": "Status", "Node ID": msg.node_id, "Sensor ID": msg.sensor_id,
                "Flow": msg.flow_rate, "Velocity": msg.velocity, "Flow Day": msg.flow_rate_per_day,
                "Flow Month": msg.flow_rate_per_month, "Flow Year": msg.flow_rate_per_year,
                "Node Status": msg.node_status, "Details": "", "Company": company,
                "Battery Voltage": msg.battery_voltage,
                "Soil Temp": msg.soil_temperature, "Soil Moist": msg.soil_moisture, "Soil Valid": msg.soil_moisture_temp_valid,
                "EC Temp": msg.ec_temperature, "EC Moist": msg.ec_moisture, "EC Cond": msg.electrical_conductivity, "EC Valid": msg.soil_moisture_temp_ec_valid,
                "Active Sensors": msg.active_sensor_count, "Sensor Mask": msg.sensor_mask,
                "Measured Epoch": measured_at, "Time Source": time_source
            }
            payload.update(dashboard_flow_fields(flow_metadata))
            emit_iot_message(payload, company)

        elif "telemetry" in topic.lower():
            log_event(f"[PLAINTEXT] Parsing as Telemetry...")
            msg = messages_pb2.Telemetry()
            msg.ParseFromString(plaintext)
            logging.info(f"[PLAINTEXT] Parsed Telemetry: node_id={msg.node_id} sensor_id={msg.sensor_id}")
            
            # Validate node ID matches topic
            if len(topic_parts) >= 3:
                try:
                    topic_node_id = int(topic_parts[2])
                    if msg.node_id != topic_node_id:
                        log_event(f"[VALIDATION ERROR] Telemetry: Node ID mismatch - topic={topic_node_id}, payload={msg.node_id}")
                        logging.error(f"[PLAINTEXT] DROPPED - Node ID mismatch: topic={topic_node_id} vs payload={msg.node_id}")
                        return
                    log_event(f"[PLAINTEXT] Node ID validated: {msg.node_id}")
                except ValueError:
                    log_event(f"[PARSE ERROR] Telemetry: Cannot extract node ID from topic: {topic}")
                    logging.error(f"[PLAINTEXT] DROPPED - Cannot parse node ID from {topic}")
                    return
            
            flow_metadata = extract_flow_metadata(msg)
            measured_at, time_source = select_measurement_timestamp(
                msg, timestamp_epoch
            )
            sample_fingerprint = build_sample_fingerprint(
                company, msg, flow_metadata, measured_at
            )
            period_rows = calendar_period_rows(msg, flow_metadata, measured_at)
            details = (f"Node-TS:{msg.timestamp} S-Rate:{msg.sampling_rate} "
                       f"T-Rate:{msg.Transmission_rate} sensors:{msg.active_sensor_count} "
                       f"meter:{flow_metadata['flow_meter_name']} "
                       f"period:{flow_metadata['flow_period_source_name']}")
            log_event(f"[PLAINTEXT] Saving Telemetry message - node={msg.node_id}, details={details}")
            save_message(timestamp_epoch, "Telemetry", msg.node_id, msg.sensor_id, msg.flow_rate, msg.velocity,
                         msg.flow_rate_per_day, msg.flow_rate_per_month, msg.flow_rate_per_year, details, company, msg.node_status,
                         msg.soil_temperature, msg.soil_moisture, msg.soil_moisture_temp_valid,
                         msg.ec_temperature, msg.ec_moisture, msg.electrical_conductivity, msg.soil_moisture_temp_ec_valid,
                         msg.active_sensor_count, msg.sensor_mask, msg.battery_voltage,
                         flow_metadata=flow_metadata, measured_at=measured_at,
                         time_source=time_source,
                         sample_fingerprint=sample_fingerprint,
                         period_rows=period_rows)
            
            payload = {
                "Time": t, "Epoch": timestamp_epoch, "Type": "Telemetry", "Node ID": msg.node_id, "Sensor ID": msg.sensor_id,
                "Flow": msg.flow_rate, "Velocity": msg.velocity, "Flow Day": msg.flow_rate_per_day,
                "Flow Month": msg.flow_rate_per_month, "Flow Year": msg.flow_rate_per_year,
                "Node Status": msg.node_status, "Details": details, "Company": company,
                "Battery Voltage": msg.battery_voltage,
                "Soil Temp": msg.soil_temperature, "Soil Moist": msg.soil_moisture, "Soil Valid": msg.soil_moisture_temp_valid,
                "EC Temp": msg.ec_temperature, "EC Moist": msg.ec_moisture, "EC Cond": msg.electrical_conductivity, "EC Valid": msg.soil_moisture_temp_ec_valid,
                "Active Sensors": msg.active_sensor_count, "Sensor Mask": msg.sensor_mask,
                "Measured Epoch": measured_at, "Time Source": time_source
            }
            payload.update(dashboard_flow_fields(flow_metadata))
            emit_iot_message(payload, company)

        elif "cmd" in topic.lower():
            log_event(f"[PLAINTEXT] Parsing as CMD_Message...")
            msg = messages_pb2.CMD_Message()
            msg.ParseFromString(plaintext)
            logging.info(f"[PLAINTEXT] Parsed CMD_Message: node_id={msg.node_id} cmd_id={msg.cmd_id} cmd_data={msg.cmd_data}")
            
            # Validate node ID matches topic
            topic_parts = topic.split('/')
            if len(topic_parts) >= 3:
                try:
                    topic_node_id = int(topic_parts[2])
                    if msg.node_id != topic_node_id:
                        log_event(f"[VALIDATION ERROR] CMD: Node ID mismatch - topic={topic_node_id}, payload={msg.node_id}")
                        logging.error(f"[PLAINTEXT] DROPPED - Node ID mismatch: topic={topic_node_id} vs payload={msg.node_id}")
                        return
                    log_event(f"[PLAINTEXT] Node ID validated: {msg.node_id}")
                except ValueError:
                    log_event(f"[PARSE ERROR] CMD: Cannot extract node ID from topic: {topic}")
                    logging.error(f"[PLAINTEXT] DROPPED - Cannot parse node ID from {topic}")
                    return
            
            cmd_name = CMD_NAMES_REV.get(msg.cmd_id, str(msg.cmd_id))
            det = f"Cmd={cmd_name}({msg.cmd_id}), Data={msg.cmd_data}"
            log_event(f"[PLAINTEXT] Saving CMD message - node={msg.node_id}, {det}")
            save_message(timestamp_epoch, "Command", msg.node_id, "-", 0, 0, 0, 0, 0, det, company, 0)
            
            payload = {
                "Time": t, "Epoch": timestamp_epoch, "Type": "Command", "Node ID": msg.node_id, "Sensor ID": "-",
                "Flow": "-", "Velocity": "-", "Flow Day": "-", "Flow Month": "-", "Flow Year": "-", "Node Status": 0, "Details": det, "Company": company
            }
            emit_iot_message(payload, company)
        else:
            log_event(f"[PLAINTEXT] WARNING - Unknown topic structure: {topic}")
            logging.warning(f"[PLAINTEXT] Unknown topic type: {topic}")
            
    except AttributeError as e:
        error_msg = f"[PLAINTEXT] DROPPED - Message missing field: {e}"
        logging.error(error_msg)
        log_event(error_msg)
    except ValueError as e:
        error_msg = f"[PLAINTEXT] DROPPED - Parse error: {e}"
        logging.error(error_msg)
        log_event(error_msg)
    except Exception as e:
        error_msg = f"[PLAINTEXT] DROPPED - Unexpected error: {type(e).__name__}: {e}"
        logging.exception(error_msg)
        log_event(error_msg)

# AUTH DECORATORS
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'role' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'role' not in session or session['role'] != 'admin':
            return jsonify({"success": False, "error": "Admin privileges required"}), 403
        return f(*args, **kwargs)
    return decorated_function

def can_manage_company(target_company: str) -> bool:
    if session.get('username') == 'EgSA_Supervisor':
        return True
    return target_company == session.get('company')

@app.route('/', methods=['GET', 'POST'])
def login():
    if 'role' in session:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        conn = sqlite3.connect('iot_data.db')
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE username=?", (username,))
        user = c.fetchone()
        conn.close()
        
        if user and check_password_hash(user['password'], password):
            session['role'] = user['role']
            session['username'] = user['username']
            session['company'] = user['company']
            return redirect(url_for('dashboard'))
        else:
            return render_template('login.html', error="Invalid username or password")
            
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/change_password', methods=['GET', 'POST'])
@login_required
def change_password():
    message = None
    if request.method == 'POST':
        old_pw = request.form.get('old_password', '').strip()
        new_pw = request.form.get('new_password', '').strip()
        confirm_pw = request.form.get('confirm_password', '').strip()

        if not old_pw or not new_pw or not confirm_pw:
            message = 'All fields are required.'
            return render_template('change_password.html', message=message)

        if new_pw != confirm_pw:
            message = 'New password and confirmation do not match.'
            return render_template('change_password.html', message=message)

        try:
            conn = sqlite3.connect('iot_data.db')
            c = conn.cursor()
            c.execute('SELECT password FROM users WHERE username=?', (session.get('username'),))
            row = c.fetchone()
            if not row:
                conn.close()
                message = 'User not found.'
                return render_template('change_password.html', message=message)
            stored_pw = row[0]
            if not check_password_hash(stored_pw, old_pw):
                conn.close()
                message = 'Old password is incorrect.'
                return render_template('change_password.html', message=message)

            # Update password
            c.execute('UPDATE users SET password=? WHERE username=?', (generate_password_hash(new_pw), session.get('username')))
            conn.commit()
            conn.close()
            message = 'Password changed successfully.'
            return render_template('change_password.html', message=message)
        except Exception as e:
            message = f'Error updating password: {e}'
            return render_template('change_password.html', message=message)

    return render_template('change_password.html')

@app.route('/dashboard')
@login_required
def dashboard():
    users = []
    if session['role'] == 'admin':
        conn = sqlite3.connect('iot_data.db')
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        if session.get('username') == 'EgSA_Supervisor':
            c.execute("SELECT id, username, role, company FROM users ORDER BY id ASC")
        else:
            c.execute("SELECT id, username, role, company FROM users WHERE company = ? ORDER BY id ASC", (session.get('company'),))
        users = [dict(ix) for ix in c.fetchall()]
        conn.close()
    allow_company_edit = session.get('username') in ('EgSA_Supervisor', 'Super_User')
    # Provide a display-only role name for specific usernames (e.g. Supervisor)
    display_role = 'supervisor' if session.get('username') == 'EgSA_Supervisor' else session['role']
    return render_template(
        'index.html',
        role=session['role'],
        display_role=display_role,
        username=session.get('username', 'Unknown'),
        company=session.get('company', 'Company_1'),
        users=users,
        allow_company_edit=allow_company_edit
    )

# USER MANAGEMENT APIS
@app.route('/api/users', methods=['GET'])
@admin_required
def get_users():
    conn = sqlite3.connect('iot_data.db')
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    if session.get('username') == 'EgSA_Supervisor':
        c.execute("SELECT id, username, role, company FROM users ORDER BY id ASC")
    else:
        c.execute("SELECT id, username, role, company FROM users WHERE company = ? ORDER BY id ASC", (session.get('company'),))
    users = [dict(ix) for ix in c.fetchall()]
    conn.close()
    return jsonify({"success": True, "users": users})

@app.route('/api/users', methods=['POST'])
@admin_required
def create_user():
    data = request.json
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    role = data.get('role', 'user').strip().lower()
    if session.get('username') == 'EgSA_Supervisor':
        company = data.get('company', '').strip() or session.get('company')
    else:
        company = session.get('company')
    
    if not username or not password or role not in ['admin', 'user', 'monitor'] or not company:
        return jsonify({"success": False, "error": "Invalid input"})
        
    try:
        conn = sqlite3.connect('iot_data.db')
        c = conn.cursor()
        c.execute("INSERT INTO users (username, password, role, company) VALUES (?, ?, ?, ?)", 
                  (username, generate_password_hash(password), role, company))
        conn.commit()
        conn.close()
        return jsonify({"success": True, "message": "User created"})
    except sqlite3.IntegrityError:
        return jsonify({"success": False, "error": "Username already exists"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/api/users/<int:user_id>', methods=['DELETE'])
@admin_required
def delete_user(user_id):
    try:
        conn = sqlite3.connect('iot_data.db')
        c = conn.cursor()
        user_to_delete = c.execute("SELECT username, company FROM users WHERE id=?", (user_id,)).fetchone()
        if not user_to_delete:
            return jsonify({"success": False, "error": "User not found"})
        # Protect the built-in monitoring user from deletion
        if user_to_delete[0] == 'Super_User':
            return jsonify({"success": False, "error": "Cannot delete protected user"}), 403
        if not can_manage_company(user_to_delete[1]):
            return jsonify({"success": False, "error": "Cannot delete users from other companies"})
        if user_to_delete[0] == session.get('username'):
            return jsonify({"success": False, "error": "Cannot delete your own account while logged in!"})
            
        c.execute("DELETE FROM users WHERE id=?", (user_id,))
        conn.commit()
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

# COMPANY MANAGEMENT APIs
@app.route('/api/companies', methods=['GET'])
@login_required
def get_companies():
    # Allow admins, the supervisor, or the monitoring user to list companies
    if session.get('role') != 'admin' and session.get('username') not in ('EgSA_Supervisor', 'Super_User'):
        return jsonify({"success": False, "error": "Admin or supervisor required"}), 403
    try:
        conn = sqlite3.connect('iot_data.db')
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT id, name, created_at FROM companies ORDER BY created_at ASC")
        companies = [dict(ix) for ix in c.fetchall()]
        conn.close()
        return jsonify({"success": True, "companies": companies})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/api/companies', methods=['POST'])
@admin_required
def add_company():
    if session.get('username') != 'EgSA_Supervisor':
        return jsonify({"success": False, "error": "Only EgSA_Supervisor can add companies"}), 403
    
    data = request.json
    company_name = data.get('company_name', '').strip()
    
    if not company_name:
        return jsonify({"success": False, "error": "Company name is required"})
    
    try:
        conn = sqlite3.connect('iot_data.db')
        c = conn.cursor()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        c.execute("INSERT INTO companies (name, created_at) VALUES (?, ?)", (company_name, now))
        conn.commit()
        conn.close()
        return jsonify({"success": True, "message": "Company added successfully"})
    except sqlite3.IntegrityError:
        return jsonify({"success": False, "error": "Company already exists"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route('/api/set_company', methods=['POST'])
@login_required
def set_company():
    """Allow the special supervisor or monitoring user to set the active
    company in the session for monitoring purposes.
    """
    data = request.json or {}
    target = data.get('company', '').strip()
    if not target:
        return jsonify({"success": False, "error": "Company is required"}), 400

    # Only the designated supervisor or Super_User may switch active company
    if session.get('username') not in ('EgSA_Supervisor', 'Super_User'):
        return jsonify({"success": False, "error": "Only supervisor or Super_User may change active company"}), 403

    # Persist the selected company in the session
    session['company'] = target
    logging.info(f"Session company set to: {target} by {session.get('username')}")
    return jsonify({"success": True, "company": target})

# IOT CORE APIs
@app.route('/api/connect', methods=['POST'])
@login_required
def api_connect():
    global mqtt_client
    data = request.json
    
    # Parse and validate connection parameters
    try:
        broker = (data.get("broker") or "broker.hivemq.com").strip()
        port = int(data.get("port", 1883))
        company = (data.get("company") or "Company_ID").strip()
        base_id = (data.get("client_id") or "iot_server").strip() or "iot_server"
        client_id = f"{base_id}_{int(time.time())}"
        key_hex = (data.get("aes_key") or "").strip()
        
        if not key_hex:
            err = "AES key (hex) is required"
            log_event(f"[CONNECT] ERROR: {err}")
            return jsonify({"success": False, "error": err}), 400
        
        try:
            aes_key = bytes.fromhex(key_hex)
        except Exception as e:
            err = f"Invalid hex for AES key: {e}"
            logging.error(f"[CONNECT] {err}")
            log_event(f"[CONNECT] ERROR: {err}")
            return jsonify({"success": False, "error": err}), 400

        if len(aes_key) != 16:
            err = f"AES key must be 16 bytes (32 hex chars), got {len(aes_key)} bytes"
            log_event(f"[CONNECT] ERROR: {err}")
            return jsonify({"success": False, "error": err}), 400
            
    except ValueError as e:
        err = f"Invalid port number: {e}"
        logging.error(f"[CONNECT] {err}")
        log_event(f"[CONNECT] ERROR: {err}")
        return jsonify({"success": False, "error": err}), 400
    except Exception as e:
        err = f"Error parsing connection parameters: {e}"
        logging.exception(f"[CONNECT] {err}")
        log_event(f"[CONNECT] ERROR: {err}")
        return jsonify({"success": False, "error": err}), 400
    
    # Check authorization
    if session.get('role') != 'admin' and session.get('username') not in ('EgSA_Supervisor', 'Super_User'):
        err = "Admin privileges required"
        logging.warning(f"[CONNECT] Authorization denied for user {session.get('username')}: {err}")
        log_event(f"[CONNECT] DENIED: {err}")
        return jsonify({"success": False, "error": err}), 403

    # Build topic subscriptions. We subscribe broadly so case variations and
    # alternate topic spellings still reach the parser.
    if session.get('username') == 'EgSA_Supervisor':
        topics = ["EgSA/+/+/#"]
        log_event(f"[CONNECT] Supervisor mode - subscribing to all companies")
    else:
        topics = [f"EgSA/{company}/+/#"]
        log_event(f"[CONNECT] Company mode - subscribing to {company} only")

    # Disconnect any existing client
    if mqtt_client:
        try:
            log_event(f"[CONNECT] Disconnecting existing MQTT client...")
            mqtt_client.disconnect()
        except Exception as e:
            logging.warning(f"[CONNECT] Error disconnecting old client: {e}")
    
    # Create and connect new client
    log_event(f"[CONNECT] Creating client and connecting to {broker}:{port} (client_id={client_id})...")
    log_event(f"[CONNECT] Topics: {', '.join(topics)}")
    logging.info(f"[CONNECT] Broker={broker}:{port}, Company={company}, ClientID={client_id}, Topics={len(topics)}")
    
    mqtt_client = MqttNodeClient(
        broker_host=broker, broker_port=port, aes_key_16=aes_key,
        client_id=client_id, subscribe_topics=topics, on_plaintext=on_mqtt_plaintext, on_status=on_mqtt_status
    )
    
    try:
        mqtt_client.connect()
        log_event(f"[CONNECT] Connection initiated, waiting for broker response...")
        logging.info(f"[CONNECT] Connection attempt succeeded (waiting for _on_connect callback)")
        return jsonify({"success": True})
    except OSError as e:
        err = f"Connection failed (network error): {e}"
        logging.error(f"[CONNECT] {err}")
        log_event(f"[CONNECT] ERROR: {err}")
        mqtt_client = None
        return jsonify({"success": False, "error": err})
    except Exception as e:
        err = f"Connection failed: {type(e).__name__}: {e}"
        logging.exception(f"[CONNECT] {err}")
        log_event(f"[CONNECT] ERROR: {err}")
        mqtt_client = None
        return jsonify({"success": False, "error": err})

@app.route('/api/disconnect', methods=['POST'])
@login_required
def api_disconnect():
    if session.get('role') != 'admin' and session.get('username') not in ('EgSA_Supervisor', 'Super_User'):
        return jsonify({"success": False, "error": "Admin privileges required"}), 403
    global mqtt_client
    if mqtt_client:
        mqtt_client.disconnect()
        mqtt_client = None
        log_event("Disconnected from broker.")
    return jsonify({"success": True})

@app.route('/api/broker_status', methods=['GET'])
@login_required
def api_broker_status():
    """Get detailed broker connection status for diagnostics."""
    if mqtt_client is None:
        return jsonify({
            "connected": False,
            "status": "Not initialized",
            "details": "MQTT client not created - click Connect first"
        })
    
    try:
        is_connected = mqtt_client.is_connected()
        tx_count = mqtt_client.counters.tx_counter
        rx_count = mqtt_client.counters.rx_counter
        
        return jsonify({
            "connected": is_connected,
            "status": "Connected" if is_connected else "Disconnected",
            "broker": f"{mqtt_client.broker_host}:{mqtt_client.broker_port}",
            "topics_subscribed": len(mqtt_client.subscribe_topics),
            "tx_messages": tx_count,
            "rx_messages": rx_count,
            "client_id": mqtt_client.client._client_id.decode() if hasattr(mqtt_client.client, '_client_id') else "Unknown"
        })
    except Exception as e:
        logging.error(f"[BROKER_STATUS] Error getting status: {e}")
        return jsonify({
            "connected": False,
            "status": "Error checking status",
            "details": str(e)
        })

@app.route('/api/command', methods=['POST'])
@admin_required
def api_command():
    global mqtt_client
    
    if not mqtt_client:
        err = "Not connected to broker"
        log_event(f"[CMD] ERROR: {err}")
        return jsonify({"success": False, "error": err})
        
    data = request.json
    try:
        node_id = int(data.get("node_id", 1))
        cmd_type = data.get("cmd_type", "SRATE")
        cmd_data_val = data.get("cmd_data", 5)
        broadcast = data.get("broadcast", False)
        company = data.get("company", "Company_ID").strip()
        
        cmd_id = CMD_NAMES.get(cmd_type, 0)
        if cmd_type == "STIME": cmd_data = int(time.time())
        elif cmd_type == "GOSTM": cmd_data = 0
        else:
            try: cmd_data = int(cmd_data_val)
            except ValueError:
                err = f"Invalid command data: {cmd_data_val}"
                log_event(f"[CMD] ERROR: {err}")
                return jsonify({"success": False, "error": err})
                
        msg = messages_pb2.CMD_Message()
        msg.node_id = node_id
        msg.cmd_id = cmd_id
        msg.cmd_data = cmd_data
        plain = msg.SerializeToString()
        topic = f"EgSA/{company}/BroadCast/CMD" if broadcast else f"EgSA/{company}/{node_id}/CMD"
            
        data_info = f" with Data={cmd_data}" if cmd_type != "GOSTM" else ""
        log_event(f"[CMD] Publishing '{cmd_type}' (id={cmd_id}) to '{topic}'{data_info}...")
        logging.info(f"[CMD] node={node_id} type={cmd_type} data={cmd_data} topic={topic}")
        
        mqtt_client.publish_plaintext(topic, plain)
        save_message(int(time.time()), "Command", node_id, "-", 0, 0, 0, 0, 0, f"{cmd_type}{data_info}", company, 0)
        log_event("[CMD] Command successfully encrypted, published, and saved.")
        logging.info(f"[CMD] Success - command {cmd_type} published to {topic}")
        return jsonify({"success": True})
    except Exception as e:
        err = f"Command failed: {type(e).__name__}: {e}"
        logging.exception(f"[CMD] {err}")
        log_event(f"[CMD] ERROR: {err}")
        return jsonify({"success": False, "error": err})

@app.route('/api/messages', methods=['GET'])
@login_required
def api_messages():
    start = request.args.get('start', '1970-01-01 00:00:00')
    end = request.args.get('end', '2099-12-31 23:59:59')
    company_arg = request.args.get('company', '').strip()
    msg_type = request.args.get('type', '').strip() or None
    try:
        page = max(1, int(request.args.get('page', 1)))
    except ValueError:
        page = 1
    try:
        page_size = min(1000, max(1, int(request.args.get('page_size', 50))))
    except ValueError:
        page_size = 50
    offset = (page - 1) * page_size

    if session.get('username') in ('EgSA_Supervisor', 'Super_User'):
        if company_arg:
            rows = query_messages_db(get_company_db_path(company_arg), start, end, msg_type, limit=page_size, offset=offset)
            total = count_messages_db(get_company_db_path(company_arg), start, end, msg_type)
        else:
            rows = query_messages_from_all_company_dbs(start, end, msg_type, limit=page_size, offset=offset)
            total = count_messages_from_all_company_dbs(start, end, msg_type)
    else:
        company = session.get('company') or 'Unknown'
        rows = query_messages_db(get_company_db_path(company), start, end, msg_type, limit=page_size, offset=offset)
        total = count_messages_db(get_company_db_path(company), start, end, msg_type)

    total_pages = (total + page_size - 1) // page_size if total else 1
    return jsonify({
        'rows': rows,
        'total': total,
        'page': page,
        'page_size': page_size,
        'total_pages': total_pages,
    })

@app.route('/api/node_latest', methods=['GET'])
@login_required
def api_node_latest():
    """Return the most recent Status/Telemetry record for every node in a
    company, plus the last N historical records for a specific node.
    Used by the supervisor to pre-seed the dashboard on company switch."""
    company_arg = request.args.get('company', '').strip()
    history_nid = request.args.get('history_node', '').strip()  # optional: node to fetch chart history for
    history_limit = 50

    # Resolve target company
    if session.get('username') in ('EgSA_Supervisor', 'Super_User'):
        company = company_arg or session.get('company') or 'Unknown'
    else:
        company = session.get('company') or 'Unknown'

    db_path = get_company_db_path(company)
    latest_per_node = []
    history_rows = []

    if os.path.exists(db_path):
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        # Latest record per node (Status or Telemetry only)
        c.execute("""
            SELECT m.* FROM messages m
            INNER JOIN (
                SELECT node_id, MAX(id) AS max_id
                FROM messages
                WHERE type IN ('Status','Telemetry')
                GROUP BY node_id
            ) latest ON m.id = latest.max_id
        """)
        latest_per_node = [_format_row_timestamp(dict(r)) for r in c.fetchall()]

        # Recent history for a specific node (for chart pre-seed)
        if history_nid:
            c.execute("""
                SELECT * FROM messages
                WHERE node_id = ?
                  AND type IN ('Status','Telemetry')
                  AND COALESCE(flow_live_valid, 0) = 1
                ORDER BY timestamp DESC, id DESC LIMIT ?
            """, (history_nid, history_limit))
            history_rows = list(reversed([_format_row_timestamp(dict(r)) for r in c.fetchall()]))

        conn.close()

    return jsonify({
        'company': company,
        'latest': latest_per_node,
        'history': history_rows,
    })


@app.route('/api/consumption', methods=['GET'])
@login_required
def api_consumption():
    """Return persisted day/month/year volume snapshots for one tenant."""
    company_arg = request.args.get('company', '').strip()
    if session.get('username') in ('EgSA_Supervisor', 'Super_User'):
        company = company_arg or session.get('company') or 'Unknown'
    else:
        company = session.get('company') or 'Unknown'

    period_type = request.args.get('period', '').strip().lower()
    if period_type and period_type not in ('day', 'month', 'year'):
        return jsonify({'error': 'period must be day, month, or year'}), 400

    node_id = request.args.get('node_id', '').strip()
    sensor_id = request.args.get('sensor_id', '').strip()
    db_path = ensure_message_db(company)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    query = 'SELECT * FROM consumption_periods WHERE 1=1'
    params = []
    if node_id:
        query += ' AND node_id = ?'
        params.append(node_id)
    if sensor_id:
        query += ' AND sensor_id = ?'
        params.append(sensor_id)
    if period_type:
        query += ' AND period_type = ?'
        params.append(period_type)
    query += ' ORDER BY period_key DESC, measured_at DESC LIMIT 1000'
    rows = [dict(row) for row in conn.execute(query, params).fetchall()]
    conn.close()
    for row in rows:
        row['volume_m3'] = row['volume_liters'] / 1000.0
        row['flow_meter_name'] = flow_meter_name(row['flow_meter_type'])
        row['source_name'] = period_source_name(row['source'])
        row['quality_name'] = period_quality_name(row['quality'])
    return jsonify({'company': company, 'rows': rows})


@app.route('/export_csv', methods=['GET'])
@login_required
def export_csv():
    start = request.args.get('start', '1970-01-01 00:00:00')
    end = request.args.get('end', '2099-12-31 23:59:59')
    company_arg = request.args.get('company', '').strip()
    if session.get('username') in ('EgSA_Supervisor', 'Super_User'):
        if company_arg:
            rows = query_messages_db(get_company_db_path(company_arg), start, end)
        else:
            rows = query_messages_from_all_company_dbs(start, end)
    else:
        company = session.get('company') or 'Unknown'
        rows = query_messages_db(get_company_db_path(company), start, end)

    def generate():
        data = StringIO()
        writer = csv.writer(data)
        writer.writerow(('Received At', 'Measured At', 'Time Source', 'Type', 'Node ID', 'Sensor ID', 'Node Status', 'Battery Voltage',
                         'Flow (m3/h)', 'Velocity (m/s)', 'Consumption Today (m3)', 'Consumption Month (m3)', 'Consumption Year (m3)',
                         'Flow Meter Type', 'Period Source', 'Flow Valid', 'Period Valid', 'Cumulative Valid', 'RTC Valid',
                         'Forward Total (L)', 'Reverse Total (L)', 'Net Total (L)', 'Period Quality', 'Alarm Flags',
                         'HNDA Temp', 'HNDA Moisture', 'HNDA Valid', 'Sondas Temp', 'Sondas Moisture', 'Sondas EC', 'Sondas Valid',
                         'Active Sensors', 'Sensor Mask', 'Details'))
        yield data.getvalue()
        data.seek(0); data.truncate(0)
        for row in rows:
            writer.writerow((
                row['timestamp'], row.get('measured_at', ''), row.get('time_source', ''),
                row['type'], row['node_id'], row['sensor_id'], row.get('node_status', ''), row.get('battery_voltage', ''),
                row['flow'], row['velocity'], row['flow_day'], row['flow_month'], row['flow_year'],
                row.get('flow_meter_type', ''), row.get('flow_period_source', ''), row.get('flow_live_valid', ''),
                row.get('flow_period_totals_valid', ''), row.get('flow_cumulative_totals_valid', ''), row.get('rtc_valid', ''),
                row.get('forward_total_liters', ''), row.get('reverse_total_liters', ''), row.get('net_total_liters', ''),
                row.get('flow_period_quality', ''), row.get('flow_meter_alarm_flags', ''),
                row.get('soil_temperature', ''), row.get('soil_moisture', ''), row.get('soil_moisture_temp_valid', ''),
                row.get('ec_temperature', ''), row.get('ec_moisture', ''), row.get('electrical_conductivity', ''), row.get('soil_moisture_temp_ec_valid', ''),
                row.get('active_sensor_count', ''), row.get('sensor_mask', ''), row['details']
            ))
            yield data.getvalue()
            data.seek(0); data.truncate(0)
    return Response(generate(), headers={'Content-Disposition': 'attachment; filename=iot_data_export.csv', 'Content-type': 'text/csv'})

@app.route('/export_log', methods=['GET'])
@admin_required
def export_log():
    try: return send_file('system.log', as_attachment=True, download_name='system.log')
    except Exception as e: return f"Log file not found: {e}", 404

if __name__ == '__main__':
    print("Running Web Server on http://127.0.0.1:8000")
    socketio.run(app, debug=False, host="127.0.0.1", port=8000, allow_unsafe_werkzeug=True)
