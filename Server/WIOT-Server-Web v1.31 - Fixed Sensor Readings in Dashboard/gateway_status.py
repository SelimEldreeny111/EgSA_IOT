"""Durable gateway life indications, scoped by company, region and gateway ID."""
import sqlite3
import time
from contextlib import closing
from google.protobuf.json_format import MessageToDict
from messages_pb2 import Gateway_Status
from input_validation import company_id, integer, SQLITE_MAX_INT
from region_topics import region_id


class GatewayStatusStore:
    """Keep the latest gateway snapshot and a durable history of received heartbeats."""

    def __init__(self, path):
        self.path = str(path)
        with closing(self._db()) as db:
            if db.execute('PRAGMA user_version').fetchone()[0] == 0:
                db.executescript('''
                    BEGIN IMMEDIATE;
                    CREATE TABLE IF NOT EXISTS gateway_status (
                        company TEXT NOT NULL, region TEXT NOT NULL, gateway_id INTEGER NOT NULL,
                        received_at REAL NOT NULL, payload BLOB NOT NULL,
                        PRIMARY KEY(company,region,gateway_id));
                    CREATE TABLE IF NOT EXISTS gateway_heartbeat_history (
                        id INTEGER PRIMARY KEY, company TEXT NOT NULL, region TEXT NOT NULL,
                        gateway_id INTEGER NOT NULL, received_at REAL NOT NULL, payload BLOB NOT NULL,
                        fingerprint TEXT, UNIQUE(company,region,gateway_id,fingerprint));
                    CREATE INDEX IF NOT EXISTS gateway_history_region_time
                        ON gateway_heartbeat_history(region,received_at DESC,id DESC);
                    CREATE INDEX IF NOT EXISTS gateway_history_company_time
                        ON gateway_heartbeat_history(company,region,received_at DESC,id DESC);
                    INSERT INTO gateway_heartbeat_history(company,region,gateway_id,received_at,payload)
                        SELECT s.company,s.region,s.gateway_id,s.received_at,s.payload FROM gateway_status s
                        WHERE NOT EXISTS (
                            SELECT 1 FROM gateway_heartbeat_history h WHERE h.company=s.company
                            AND h.region=s.region AND h.gateway_id=s.gateway_id AND h.received_at=s.received_at
                        );
                    PRAGMA user_version=1;
                    COMMIT;
                ''')

    def _db(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        return db

    def accept(self, company, region, gateway_id, message, received_at=None, *, fingerprint=None):
        """Validate, then commit the heartbeat and latest snapshot together."""
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
        entry = (company, region, gateway_id, received_at, message.SerializeToString())
        with closing(self._db()) as db, db:
            saved = db.execute('''INSERT INTO gateway_heartbeat_history
                (company,region,gateway_id,received_at,payload,fingerprint) VALUES (?,?,?,?,?,?)
                ON CONFLICT(company,region,gateway_id,fingerprint) DO NOTHING''',
                (*entry, str(fingerprint) if fingerprint is not None else None))
            if not saved.rowcount:
                return
            db.execute('''INSERT INTO gateway_status VALUES(?,?,?,?,?)
                ON CONFLICT(company,region,gateway_id) DO UPDATE SET
                    received_at=excluded.received_at,payload=excluded.payload
                    WHERE excluded.received_at >= gateway_status.received_at''', entry)

    @staticmethod
    def _snapshot_data(row):
        msg = Gateway_Status.FromString(row['payload'])
        data = MessageToDict(msg, preserving_proto_field_name=True,
                             always_print_fields_with_no_presence=True)
        data.update(company=row['company'], region=row['region'], received_at=row['received_at'],
                    uptime_seconds=msg.uptime_seconds, last_node_age_seconds=msg.last_node_age_seconds,
                    transport='Wi-Fi' if msg.uplink_transport == 1 else 'SIM800')
        return data

    def list(self, company, region, observing, observed_since=0, now=None):
        """Missing two intervals is overdue, three is offline. A disconnected server is unobserved."""
        company, region = company_id(company), region_id(region)
        now = time.time() if now is None else now
        with closing(self._db()) as db:
            rows = db.execute('''SELECT * FROM gateway_status
                WHERE company=? AND region=? ORDER BY gateway_id''', (company, region)).fetchall()
        result = []
        for row in rows:
            data = self._snapshot_data(row)
            age = max(0, now - row['received_at'])
            interval = data['heartbeat_interval_seconds']
            state = 'online'
            if not observing or row['received_at'] < observed_since:
                state = 'unobserved'
            elif age >= 3 * interval:
                state = 'offline'
            elif age >= 2 * interval:
                state = 'overdue'
            data.update(age_seconds=int(age), state=state)
            result.append(data)
        return result

    def history(self, company, region, start, end, limit=None, offset=0):
        """Return heartbeats in the history window, with a stable page order."""
        query = 'FROM gateway_heartbeat_history WHERE region=? AND received_at>=? AND received_at<?'
        params = [region_id(region), start, end + 1]  # Include fractional times in the final second.
        if company is not None:
            query += ' AND company=?'
            params.append(company_id(company))
        with closing(self._db()) as db:
            db.execute('BEGIN')
            total = db.execute('SELECT COUNT(*) ' + query, params).fetchone()[0]
            query = 'SELECT * ' + query + ' ORDER BY received_at DESC,id DESC'
            if limit is not None:
                query += ' LIMIT ? OFFSET ?'
                params.extend([limit, offset])
            rows = db.execute(query, params).fetchall()
        return [self._snapshot_data(row) for row in rows], total

    def regions(self, company):
        with closing(self._db()) as db:
            return {row[0] for row in db.execute(
                'SELECT DISTINCT region FROM gateway_status WHERE company=?', (company_id(company),))}
