"""Durable command intents, bounded mailbox and correlated execution audit.

V2 uses command_lifecycle.db. Optional legacy import reads pending_commands.db
without modifying it. PUBACK is broker receipt, never application execution.
Only queued SRATE/STRAN may retry (three attempts). STIME, GOSTM, WAKE and VALVE
are single-dispatch, avoiding stale clock rewinds or repeated physical actions.
"""
import json
import secrets
import sqlite3
import time
from contextlib import contextmanager, closing
from pathlib import Path

from input_validation import company_id, integer, SQLITE_MAX_INT

DEFAULT_TTL_SECONDS = 86400
MAX_TTL_SECONDS = 604800
RETRY_SECONDS = 15
MAX_ATTEMPTS = 3
ACK_TIMEOUT_SECONDS = 30
MAX_PENDING_PER_NODE = 32
RETRYABLE = ('SRATE', 'STRAN')
DESIRED_VALUES = ('SRATE', 'STRAN', 'STIME', 'VALVE')
ACTIVE_STATES = ('pending', 'dispatched', 'waiting_retry', 'broadcast_partial')


class CommandQueue:
    """Single-owner journal. Transactions serialize intent changes and claims."""
    def __init__(self, path, legacy_path=None):
        self.path = str(Path(path))
        with self._db() as db:
            existing = db.execute("PRAGMA table_info(pending_commands)").fetchall()
            if existing and 'delivery' not in {row['name'] for row in existing}:
                raise RuntimeError('Legacy mailbox: use a new lifecycle DB and legacy_path import')
            db.executescript("""
                CREATE TABLE IF NOT EXISTS pending_commands (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_id INTEGER UNIQUE NOT NULL, company TEXT NOT NULL,
                    node_id INTEGER NOT NULL, cmd_id INTEGER NOT NULL,
                    cmd_type TEXT NOT NULL, cmd_data INTEGER NOT NULL,
                    actor TEXT NOT NULL DEFAULT '', delivery TEXT NOT NULL,
                    broadcast INTEGER NOT NULL DEFAULT 0,
                    created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL,
                    next_attempt_at INTEGER NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                    state TEXT NOT NULL DEFAULT 'pending', reason TEXT NOT NULL DEFAULT '',
                    submitted_at INTEGER, broker_confirmed_at INTEGER,
                    ack_deadline INTEGER, acknowledged_at INTEGER, superseded_by INTEGER,
                    outcome_uncertain INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS pending_by_node
                    ON pending_commands(company,node_id,state,expires_at);
                CREATE INDEX IF NOT EXISTS command_active_by_state
                    ON pending_commands(state,expires_at,ack_deadline);
                CREATE INDEX IF NOT EXISTS command_timeline_by_company
                    ON pending_commands(company,id DESC);
                CREATE TABLE IF NOT EXISTS command_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, request_id INTEGER NOT NULL,
                    event TEXT NOT NULL, timestamp INTEGER NOT NULL, details TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS command_attempts (
                    request_id INTEGER NOT NULL, attempt INTEGER NOT NULL,
                    submitted_at INTEGER NOT NULL, broker_confirmed_at INTEGER, mqtt_mid INTEGER,
                    PRIMARY KEY(request_id,attempt)
                );
                CREATE TABLE IF NOT EXISTS command_receipts (
                    request_id INTEGER NOT NULL, node_id INTEGER NOT NULL, cmd_id INTEGER NOT NULL,
                    success INTEGER NOT NULL, received_at INTEGER NOT NULL, late INTEGER NOT NULL,
                    PRIMARY KEY(request_id,node_id)
                );
                CREATE TABLE IF NOT EXISTS command_metadata (name TEXT PRIMARY KEY,value TEXT NOT NULL);
            """)
            if 'mqtt_mid' not in {r['name'] for r in db.execute('PRAGMA table_info(command_attempts)')}:
                db.execute('ALTER TABLE command_attempts ADD COLUMN mqtt_mid INTEGER')
        if legacy_path and Path(legacy_path).is_file():
            self._import_legacy(legacy_path)

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _event(db, request_id, event, now, details=''):
        db.execute("INSERT INTO command_events(request_id,event,timestamp,details) VALUES(?,?,?,?)",
                   (request_id, event, now, str(details)[:1024]))

    def _import_legacy(self, path):
        """One-time additive import; source is read-only and remains recoverable."""
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM command_metadata WHERE name='legacy_import'").fetchone():
                return
            with closing(sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)) as old:
                old.row_factory = sqlite3.Row
                if old.execute("SELECT 1 FROM sqlite_master WHERE name='pending_commands'").fetchone():
                    for row in old.execute("SELECT * FROM pending_commands ORDER BY created_at,request_id"):
                        try:
                            company_id(row['company'])
                            integer(row['request_id'],1,0xFFFFFFFF,'Legacy request ID')
                            integer(row['node_id'],1,65535,'Legacy node ID')
                            command = integer(row['cmd_id'],1,6,'Legacy command ID')
                            if {1:'SRATE',2:'STRAN',3:'STIME',4:'GOSTM',5:'VALVE',6:'WAKE'}[command] != row['cmd_type']:
                                raise ValueError('Legacy command type mismatch')
                            value = integer(row['cmd_data'],0,SQLITE_MAX_INT,'Legacy command data')
                            if ((command in (1,2) and not 5<=value<=86400) or
                                (command==3 and value>0xFFFFFFFF) or (command==4 and value!=0) or
                                (command==5 and value not in (0,1)) or (command==6 and value>86400)):
                                raise ValueError('Legacy command outside supported range')
                            integer(row['attempts'],0,SQLITE_MAX_INT,'Legacy attempts')
                            if row['state'] not in ('pending','dispatched','acknowledged','rejected','expired'):
                                raise ValueError('Unknown legacy state')
                        except (ValueError,TypeError,KeyError) as exc:
                            raise RuntimeError('Legacy command import rejected; preserve and reconcile the source mailbox') from exc
                        db.execute("""INSERT INTO pending_commands
                            (request_id,company,node_id,cmd_id,cmd_type,cmd_data,actor,delivery,
                             created_at,expires_at,next_attempt_at,attempts,state,acknowledged_at,
                             submitted_at,ack_deadline,outcome_uncertain,reason)
                            VALUES(?,?,?,?,?,?,'legacy operator unknown','next_wake',?,?,?,?,?,?,?,?,?,?)""",
                            (row['request_id'], row['company'], row['node_id'], row['cmd_id'],
                             row['cmd_type'], row['cmd_data'], row['created_at'], row['expires_at'],
                             row['next_attempt_at'], row['attempts'],
                             'outcome_unknown' if row['state']=='expired' and row['attempts'] else row['state'],
                             row['acknowledged_at'],
                             row['created_at'] if row['attempts'] else None,
                             row['next_attempt_at'] + ACK_TIMEOUT_SECONDS if row['attempts'] else None,
                             int(row['attempts'] > 0 and row['state'] not in ('acknowledged','rejected')),
                             'Imported legacy mailbox; actor/publication proof unavailable'))
                        self._event(db, row['request_id'], 'legacy_import', int(time.time()))
            # Retire earlier active value intents before any legacy backlog dispatch.
            # Never replay an old setting or valve action ahead of its newer replacement.
            active = db.execute("""SELECT * FROM pending_commands
                WHERE state IN ('pending','dispatched','waiting_retry') ORDER BY id DESC""").fetchall()
            newest = {}
            for row in active:
                if row['cmd_type'] not in DESIRED_VALUES:
                    continue
                key = (row['company'], row['node_id'], row['cmd_id'])
                if key not in newest:
                    newest[key] = row['request_id']
                    continue
                db.execute("""UPDATE pending_commands SET state='superseded',superseded_by=?,
                    reason='Newer legacy intent retained',outcome_uncertain=? WHERE request_id=?""",
                    (newest[key], int(row['attempts']>0), row['request_id']))
                self._event(db, row['request_id'], 'superseded', int(time.time()), newest[key])
            db.execute("INSERT INTO command_metadata VALUES('legacy_import',?)", (str(Path(path).resolve()),))

    def _refresh(self, db, now):
        rows = db.execute("""SELECT * FROM pending_commands
            WHERE state IN ('pending','dispatched','waiting_retry','broadcast_partial')""").fetchall()
        for row in rows:
            expired = row['expires_at'] <= now
            timeout = row['ack_deadline'] is not None and row['ack_deadline'] <= now
            if expired:
                state = 'outcome_unknown' if row['attempts'] else 'expired'
                reason = 'TTL ended after submission; execution unknown' if row['attempts'] else 'Expired before submission'
            elif timeout and row['state'] in ('dispatched', 'broadcast_partial'):
                if row['delivery'] == 'next_wake' and row['cmd_type'] in RETRYABLE and row['attempts'] < MAX_ATTEMPTS:
                    state, reason = 'waiting_retry', 'ACK timeout; bounded retry only at a later Status'
                else:
                    state, reason = 'outcome_unknown', 'ACK timeout; no automatic resend'
            else:
                continue
            db.execute("UPDATE pending_commands SET state=?,reason=?,outcome_uncertain=? WHERE request_id=?",
                       (state, reason, int(row['attempts'] > 0), row['request_id']))
            self._event(db, row['request_id'], state, now, reason)

    def enqueue(self, company, node_id, cmd_id, cmd_type, cmd_data, request_id=None,
                ttl_seconds=DEFAULT_TTL_SECONDS, now=None, *, actor='', delivery='next_wake', broadcast=False):
        company_id(company)
        node_id = integer(node_id, 1, 65535, 'Node ID')
        cmd_id = integer(cmd_id, 1, 6, 'Command ID')
        if {1:'SRATE', 2:'STRAN', 3:'STIME', 4:'GOSTM', 5:'VALVE', 6:'WAKE'}[cmd_id] != cmd_type:
            raise ValueError('Command ID/type mismatch')
        cmd_data = integer(cmd_data, 0, SQLITE_MAX_INT, 'Command data')
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int) or not 60 <= ttl_seconds <= MAX_TTL_SECONDS:
            raise ValueError("Command TTL must be 60..604800 seconds")
        if delivery not in ('now', 'next_wake') or not isinstance(broadcast, bool) or (broadcast and delivery != 'now'):
            raise ValueError('Invalid delivery/broadcast policy')
        now = int(time.time() if now is None else now)
        target = 0 if broadcast else node_id
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            self._refresh(db, now)
            if request_id is None:
                for _ in range(32):
                    candidate = secrets.randbelow(0xFFFFFFFF) + 1
                    if not db.execute("SELECT 1 FROM pending_commands WHERE request_id=?", (candidate,)).fetchone():
                        request_id = candidate
                        break
                else:
                    raise RuntimeError('Could not allocate a unique request ID')
            request_id = integer(request_id, 1, 0xFFFFFFFF, 'Request ID')
            if db.execute("SELECT 1 FROM pending_commands WHERE request_id=?", (request_id,)).fetchone():
                raise ValueError('Request ID already exists')
            if cmd_type in DESIRED_VALUES:
                scope = "" if broadcast else " AND node_id=?"
                params = [company, cmd_id] + ([] if broadcast else [node_id])
                old = db.execute("""SELECT * FROM pending_commands WHERE company=? AND cmd_id=?
                    AND state IN ('pending','dispatched','waiting_retry','broadcast_partial')""" + scope, params).fetchall()
                for row in old:
                    reason = 'Replaced by newer operator intent; prior submission may already have executed' if row['attempts'] else 'Replaced before submission'
                    db.execute("""UPDATE pending_commands SET state='superseded',superseded_by=?,
                        outcome_uncertain=?,reason=? WHERE request_id=?""",
                        (request_id, int(row['attempts'] > 0), reason, row['request_id']))
                    self._event(db, row['request_id'], 'superseded', now, request_id)
            count = db.execute("""SELECT COUNT(*) FROM pending_commands WHERE company=? AND node_id=?
                AND state IN ('pending','dispatched','waiting_retry','broadcast_partial')""", (company, target)).fetchone()[0]
            if count >= MAX_PENDING_PER_NODE:
                raise ValueError('Node command window full; wait for completion/expiry')
            db.execute("""INSERT INTO pending_commands
                (request_id,company,node_id,cmd_id,cmd_type,cmd_data,actor,delivery,broadcast,
                 created_at,expires_at,next_attempt_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (request_id, company, target, cmd_id, cmd_type, cmd_data, str(actor)[:80], delivery,
                 int(broadcast), now, now + ttl_seconds, now))
            self._event(db, request_id, 'accepted', now, delivery)
        return {'request_id': request_id, 'expires_at': now + ttl_seconds, 'node_id': target}

    def _claim(self, db, row, now):
        attempt = row['attempts'] + 1
        # STIME is refreshed once on first dispatch, then is never automatically retried.
        data = now if row['cmd_type'] == 'STIME' and attempt == 1 else row['cmd_data']
        db.execute("""UPDATE pending_commands SET state='dispatched',cmd_data=?,attempts=?,
            submitted_at=?,ack_deadline=?,next_attempt_at=?,reason='',outcome_uncertain=1
            WHERE request_id=?""", (data, attempt, now, now + ACK_TIMEOUT_SECONDS,
                                   now + RETRY_SECONDS, row['request_id']))
        db.execute("INSERT INTO command_attempts(request_id,attempt,submitted_at) VALUES(?,?,?)",
                   (row['request_id'], attempt, now))
        self._event(db, row['request_id'], 'submitted', now, f'attempt={attempt}')
        return dict(db.execute("SELECT * FROM pending_commands WHERE request_id=?", (row['request_id'],)).fetchone())

    def claim_on_status(self, company, node_id, now=None):
        """One command per Status. Operator VALVE > fresh pending > bounded retry."""
        now = int(time.time() if now is None else now)
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            self._refresh(db, now)
            row = db.execute("""SELECT * FROM pending_commands
                WHERE company=? AND node_id=? AND delivery='next_wake'
                  AND state IN ('pending','dispatched','waiting_retry')
                  AND next_attempt_at<=? AND expires_at>?
                  AND (attempts=0 OR (cmd_type IN ('SRATE','STRAN') AND attempts<?))
                ORDER BY CASE WHEN cmd_type='VALVE' THEN 0 ELSE 1 END,
                         CASE WHEN attempts=0 THEN 0 ELSE 1 END,id LIMIT 1""",
                (company, node_id, now, now, MAX_ATTEMPTS)).fetchone()
            return self._claim(db, row, now) if row else None

    def claim_immediate(self, request_id, now=None):
        now = int(time.time() if now is None else now)
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            self._refresh(db, now)
            row = db.execute("""SELECT * FROM pending_commands
                WHERE request_id=? AND delivery='now' AND state='pending'""", (request_id,)).fetchone()
            return self._claim(db, row, now) if row else None

    def confirm_publish(self, request_id, attempt, now=None):
        """PUBACK belongs to one attempt, even if its node ACK arrived first."""
        now = int(time.time() if now is None else now)
        with self._db() as db:
            cursor = db.execute("""UPDATE command_attempts SET broker_confirmed_at=?
                WHERE request_id=? AND attempt=? AND broker_confirmed_at IS NULL""", (now, request_id, attempt))
            if cursor.rowcount:
                db.execute("UPDATE pending_commands SET broker_confirmed_at=? WHERE request_id=?",
                           (now, request_id))
                self._event(db, request_id, 'broker_confirmed', now, f'attempt={attempt}')
            return cursor.rowcount == 1

    def record_transport_mid(self, request_id, attempt, mid):
        """MID is connection-local transport evidence, not an application ID."""
        mid = integer(mid, 1, 65535, 'MQTT MID')
        with self._db() as db:
            return db.execute('UPDATE command_attempts SET mqtt_mid=? WHERE request_id=? AND attempt=?',
                              (mid, request_id, attempt)).rowcount == 1

    def publish_failed(self, request_id, attempt, reason, now=None):
        """A failed transport call may have queued/sent data; never say not executed."""
        now = int(time.time() if now is None else now)
        with self._db() as db:
            self._event(db, request_id, 'publish_error', now, reason)
            db.execute("""UPDATE pending_commands SET reason=?,outcome_uncertain=1
                WHERE request_id=? AND attempts=? AND state='dispatched'""",
                ('Publish error; execution unknown: ' + str(reason)[:300], request_id, attempt))

    def acknowledge(self, company, node_id, request_id, cmd_id, success=True, now=None):
        if not request_id:
            return False
        now = int(time.time() if now is None else now)
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("""SELECT * FROM pending_commands WHERE request_id=? AND company=?
                AND cmd_id=? AND (node_id=? OR broadcast=1) AND attempts>0""",
                (request_id, company, cmd_id, node_id)).fetchone()
            if row is None:
                return False
            if not 1 <= node_id <= 65535:
                return False
            late = row['state'] in ('outcome_unknown', 'superseded') or (
                row['ack_deadline'] is not None and now > row['ack_deadline'])
            cursor = db.execute("""INSERT OR IGNORE INTO command_receipts
                VALUES(?,?,?,?,?,?)""", (request_id, node_id, cmd_id, int(success), now, int(late)))
            if not cursor.rowcount:
                return False
            state = row['state'] if row['state'] == 'superseded' else (
                'broadcast_partial' if row['broadcast'] else 'acknowledged' if success else 'rejected')
            reason = ('Individual broadcast receipt; expected fleet membership is not defined' if row['broadcast']
                      else 'Late matching node reply' if late else '')
            db.execute("""UPDATE pending_commands SET state=?,acknowledged_at=?,reason=?,
                outcome_uncertain=? WHERE request_id=?""",
                (state, now, reason, int(row['broadcast'] or row['state'] == 'superseded'), request_id))
            self._event(db, request_id, 'node_ack' if success else 'node_rejected', now,
                        json.dumps({'node_id': node_id, 'late': bool(late)}))
            return True

    def get(self, request_id, company, node_id, now=None):
        now = int(time.time() if now is None else now)
        with self._db() as db:
            self._refresh(db, now)
            row = db.execute("SELECT * FROM pending_commands WHERE request_id=? AND company=? AND node_id=?",
                             (request_id, company, node_id)).fetchone()
            if row is None:
                return None
            item = dict(row)
            item['receipts'] = [dict(r) for r in db.execute(
                "SELECT * FROM command_receipts WHERE request_id=? ORDER BY node_id", (request_id,))]
            item['events'] = [dict(r) for r in db.execute(
                "SELECT event,timestamp,details FROM command_events WHERE request_id=? ORDER BY id", (request_id,))]
            item['attempt_records'] = [dict(r) for r in db.execute(
                'SELECT * FROM command_attempts WHERE request_id=? ORDER BY attempt', (request_id,))]
            return item

    def list(self, company, node_id=None, limit=50, now=None):
        now = int(time.time() if now is None else now)
        limit = integer(limit, 1, 200, 'Timeline limit')
        with self._db() as db:
            self._refresh(db, now)
            scope = " AND node_id=?" if node_id is not None else ""
            params = [company] + ([node_id] if node_id is not None else []) + [limit]
            return [dict(r) for r in db.execute(
                "SELECT * FROM pending_commands WHERE company=?" + scope + " ORDER BY id DESC LIMIT ?", params)]
