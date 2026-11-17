"""Durable gateway life indications, scoped by company, region and gateway ID."""
import sqlite3
import time
from contextlib import closing
from google.protobuf.json_format import MessageToDict
from input_validation import company_id, integer, SQLITE_MAX_INT
from region_topics import region_id


class GatewayStatusStore:
    """Keep one snapshot per gateway. Determine freshness from server receive time."""

    def __init__(self, path):
        self.path = str(path)
        with closing(self._db()) as db:
            db.execute('''CREATE TABLE IF NOT EXISTS gateway_status (
                company TEXT NOT NULL, region TEXT NOT NULL, gateway_id INTEGER NOT NULL,
                received_at REAL NOT NULL, payload BLOB NOT NULL,
                PRIMARY KEY(company,region,gateway_id))''')
            db.commit()

    def _db(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        return db

    def accept(self, company, region, gateway_id, message, received_at=None):
        """Validate before an atomic upsert. No sensor records or command ACKs are created."""
        company, region = company_id(company), region_id(region)
        integer(gateway_id, 1, 65535, 'Gateway ID')
        if message.gateway_id != gateway_id:
            raise ValueError('Gateway ID does not match MQTT topic')
        integer(message.heartbeat_interval_seconds, 10, 86400, 'Heartbeat interval')
        integer(message.uplink_transport, 1, 2, 'Gateway transport')
        integer(message.uptime_seconds, 0, SQLITE_MAX_INT, 'Gateway uptime')
        integer(message.last_node_age_seconds, 0, message.uptime_seconds, 'Last node age')
        if not message.has_node_uplink and message.last_node_age_seconds:
            raise ValueError('Node age requires an observed node uplink')
        received_at = time.time() if received_at is None else received_at
        with closing(self._db()) as db:
            db.execute('''INSERT INTO gateway_status VALUES(?,?,?,?,?)
                ON CONFLICT(company,region,gateway_id) DO UPDATE SET
                    received_at=excluded.received_at,payload=excluded.payload''',
                (company, region, gateway_id, received_at, message.SerializeToString()))
            db.commit()

    def list(self, company, region, observing, observed_since=0, now=None):
        """Missing two intervals is overdue, three is offline. A disconnected server is unobserved."""
        from messages_pb2 import Gateway_Status
        company, region = company_id(company), region_id(region)
        now = time.time() if now is None else now
        with closing(self._db()) as db:
            rows = db.execute('''SELECT * FROM gateway_status
                WHERE company=? AND region=? ORDER BY gateway_id''', (company, region)).fetchall()
        result = []
        for row in rows:
            msg = Gateway_Status.FromString(row['payload'])
            age = max(0, now - row['received_at'])
            interval = msg.heartbeat_interval_seconds
            state = 'online'
            if not observing or row['received_at'] < observed_since:
                state = 'unobserved'
            elif age >= 3 * interval:
                state = 'offline'
            elif age >= 2 * interval:
                state = 'overdue'
            data = MessageToDict(msg, preserving_proto_field_name=True,
                                 always_print_fields_with_no_presence=True)
            data.update(company=company, region=region, gateway_id=msg.gateway_id,
                        uptime_seconds=msg.uptime_seconds, last_node_age_seconds=msg.last_node_age_seconds,
                        received_at=row['received_at'], age_seconds=int(age), state=state,
                        transport='Wi-Fi' if msg.uplink_transport == 1 else 'SIM800')
            result.append(data)
        return result

    def regions(self, company):
        with closing(self._db()) as db:
            return {row[0] for row in db.execute(
                'SELECT DISTINCT region FROM gateway_status WHERE company=?', (company_id(company),))}
