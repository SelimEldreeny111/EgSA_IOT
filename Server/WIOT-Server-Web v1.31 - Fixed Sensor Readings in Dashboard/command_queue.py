"""Durable, per-node command mailbox for RTC-sleeping nodes.

Commands are dispatched only after a validated node Status arrives. MQTT
publication is not an acknowledgement: a matching application Telemetry ACK
must be received before a row is marked complete. Expired commands are never
sent. Value-setting commands may retry after a lost ACK. WAKE is dispatched
at most once: repeating it after a Standby reset would start a fresh lease.
"""

import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path


DEFAULT_TTL_SECONDS = 86400
MAX_TTL_SECONDS = 604800
RETRY_SECONDS = 15


class CommandQueue:
    def __init__(self, path):
        self.path = str(Path(path))
        with self._db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS pending_commands (
                request_id INTEGER PRIMARY KEY,
                company TEXT NOT NULL,
                node_id INTEGER NOT NULL,
                cmd_id INTEGER NOT NULL,
                cmd_type TEXT NOT NULL,
                cmd_data INTEGER NOT NULL,
                created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                next_attempt_at INTEGER NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                state TEXT NOT NULL DEFAULT 'pending',
                acknowledged_at INTEGER
            )""")
            db.execute("""CREATE INDEX IF NOT EXISTS pending_by_node
                ON pending_commands(company, node_id, state, expires_at)""")

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def enqueue(self, company, node_id, cmd_id, cmd_type, cmd_data,
                request_id, ttl_seconds=DEFAULT_TTL_SECONDS, now=None):
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int) or not 60 <= ttl_seconds <= MAX_TTL_SECONDS:
            raise ValueError("Command TTL must be 60..604800 seconds")
        now = int(time.time() if now is None else now)
        with self._db() as db:
            db.execute("""INSERT INTO pending_commands
                (request_id, company, node_id, cmd_id, cmd_type, cmd_data,
                 created_at, expires_at, next_attempt_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (request_id, company, node_id, cmd_id, cmd_type, cmd_data,
                 now, now + ttl_seconds, now))
        return {"request_id": request_id, "expires_at": now + ttl_seconds}

    def claim_on_status(self, company, node_id, now=None):
        """Take one due command; one per Status limits radio/command-window load."""
        now = int(time.time() if now is None else now)
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("""UPDATE pending_commands SET state='expired'
                WHERE state IN ('pending','dispatched') AND expires_at<=?""", (now,))
            row = db.execute("""SELECT * FROM pending_commands
                WHERE company=? AND node_id=? AND state IN ('pending','dispatched')
                  AND next_attempt_at<=? AND expires_at>?
                  AND NOT (cmd_type='WAKE' AND state='dispatched')
                ORDER BY created_at, request_id LIMIT 1""",
                (company, node_id, now, now)).fetchone()
            if row is None:
                return None
            db.execute("""UPDATE pending_commands
                SET state='dispatched', attempts=attempts+1, next_attempt_at=?
                WHERE request_id=?""", (now + RETRY_SECONDS, row["request_id"]))
            return dict(row)

    def acknowledge(self, company, node_id, request_id, cmd_id,
                    success=True, now=None):
        if not request_id:
            return False
        now = int(time.time() if now is None else now)
        with self._db() as db:
            cursor = db.execute("""UPDATE pending_commands
                SET state=?, acknowledged_at=?
                WHERE request_id=? AND company=? AND node_id=? AND cmd_id=?
                  AND state='dispatched' AND expires_at>?""",
                ('acknowledged' if success else 'rejected', now,
                 request_id, company, node_id, cmd_id, now))
            return cursor.rowcount == 1

    def get(self, request_id, company, node_id, now=None):
        now = int(time.time() if now is None else now)
        with self._db() as db:
            db.execute("""UPDATE pending_commands SET state='expired'
                WHERE request_id=? AND company=? AND node_id=?
                  AND state IN ('pending','dispatched') AND expires_at<=?""",
                (request_id, company, node_id, now))
            row = db.execute("""SELECT request_id, cmd_type, state, attempts,
                       created_at, expires_at, acknowledged_at
                FROM pending_commands WHERE request_id=? AND company=? AND node_id=?""",
                (request_id, company, node_id)).fetchone()
            return dict(row) if row else None
