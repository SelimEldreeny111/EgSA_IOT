"""Durable, tenant-scoped flash downloads; acknowledge only after SQLite commit.

Archived samples are deliberately separate from live meter/consumption tables.
The node sends one indexed row at a time and retries until its application ACK.
"""
import json
import sqlite3
import time
from contextlib import closing
from google.protobuf.json_format import MessageToDict
from ..protocol.validation import company_id, integer
from ..protocol.topics import region_id

FLASH_COMMANDS = {'CLEAR_FLASH': 9, 'FLASH_STATUS': 10, 'FLASH_LAST': 11,
                  'FLASH_TODAY': 12, 'FLASH_CANCEL': 13}
HISTORY_ACK = 14
MAX_RECORDS = 14322
STATE_NAMES = ['Disabled', 'Missing', 'Unformatted', 'Recovering', 'Ready', 'Full', 'Fault']
RESULT_NAMES = ['OK', 'Empty', 'Not ready', 'Time untrusted', 'Cancelled',
                'Retention changed', 'ACK timeout', 'Read/encode failure', 'Busy']


class FlashArchive:
    """One database, explicit company/region/node keys on every query."""
    def __init__(self, path):
        self.path = str(path)
        with closing(self._db()) as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS flash_status(
                    company TEXT, region TEXT, node INTEGER, received INTEGER, info TEXT,
                    PRIMARY KEY(company,region,node));
                CREATE TABLE IF NOT EXISTS flash_records(
                    company TEXT, region TEXT, node INTEGER, generation INTEGER, sequence INTEGER,
                    epoch INTEGER, day INTEGER, sample BLOB, data TEXT,
                    PRIMARY KEY(company,region,node,generation,sequence));
                CREATE TABLE IF NOT EXISTS flash_transfers(
                    company TEXT, region TEXT, node INTEGER, request INTEGER, generation INTEGER,
                    total INTEGER, received INTEGER, phase INTEGER, result INTEGER, complete INTEGER,
                    updated INTEGER, PRIMARY KEY(company,region,node,request));
                CREATE TABLE IF NOT EXISTS flash_transfer_rows(
                    company TEXT, region TEXT, node INTEGER, request INTEGER, idx INTEGER, sequence INTEGER,
                    PRIMARY KEY(company,region,node,request,idx),
                    UNIQUE(company,region,node,request,sequence));
            ''')
            db.commit()

    def _db(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def scope(company, region, node):
        return company_id(company), region_id(region), integer(node, 1, 65535, 'Node ID')

    @staticmethod
    def info(message):
        """Validate the known chip geometry before showing any reported counters."""
        data = MessageToDict(message, preserving_proto_field_name=True,
                             always_print_fields_with_no_presence=True)
        if not 0 <= message.state <= 6:
            raise ValueError('Unknown flash state')
        if not (message.used_bytes <= message.usable_bytes <= message.capacity_bytes <= 8388608):
            raise ValueError('Invalid flash capacity accounting')
        if message.free_bytes != message.usable_bytes - message.used_bytes:
            raise ValueError('Invalid flash free space')
        if not (message.record_count <= message.maximum_records <= MAX_RECORDS):
            raise ValueError('Invalid flash frame count')
        if message.clear_sectors_remaining > 2046:
            raise ValueError('Invalid flash clear progress')
        data['state_name'] = STATE_NAMES[message.state]
        return data

    def accept(self, company, region, node, msg, now=None):
        """Persist metadata/row and return protocol ACK only after transaction commit."""
        scope = self.scope(company, region, node)
        if msg.node_id != scope[2]:
            raise ValueError('Archived node ID does not match topic')
        now = int(time.time() if now is None else now)
        status = self.info(msg.flash_log) if msg.HasField('flash_log') else None
        h = msg.history if msg.HasField('history') else None
        if h and (h.kind not in (1, 2) or h.phase not in (1, 2, 3) or h.result > 8
                  or h.total > MAX_RECORDS or h.index > h.total):
            raise ValueError('Invalid history envelope')
        if h and h.kind == 2 and not h.request_id:
            raise ValueError('History transfer requires a request ID')
        if h and h.phase == 2 and (not h.generation or not 1 <= h.sequence <= MAX_RECORDS
                                   or not 1 <= h.index <= h.total or not msg.sample_time_valid
                                   or not msg.stored_sample or msg.live_fallback or h.result != 0
                                   or msg.sample_sequence != h.sequence):
            raise ValueError('Invalid stored sample metadata')
        if h and h.phase == 3 and h.result in (0, 1) and h.index != h.total:
            raise ValueError('Successful history end must cover the declared total')
        ack = None
        with closing(self._db()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            if status is not None:
                db.execute('INSERT OR REPLACE INTO flash_status VALUES(?,?,?,?,?)',
                           (*scope, now, json.dumps(status)))
            if h and h.phase == 2:
                sample = type(msg)()
                sample.CopyFrom(msg)
                for field in ('flash_log', 'history', 'command_ack_request_id',
                              'command_ack_cmd_id', 'command_ack_success'):
                    sample.ClearField(field)
                raw = sample.SerializeToString(deterministic=True)
                key = (*scope, h.generation, h.sequence)
                previous = db.execute('SELECT sample FROM flash_records WHERE company=? AND region=? '
                                      'AND node=? AND generation=? AND sequence=?', key).fetchone()
                if previous and bytes(previous['sample']) != raw:
                    raise ValueError('Stored sequence reused with different sample')
                data = MessageToDict(sample, preserving_proto_field_name=True,
                                     always_print_fields_with_no_presence=True)
                db.execute('INSERT OR IGNORE INTO flash_records VALUES(?,?,?,?,?,?,?,?,?)',
                           (*key, msg.timestamp, h.day_key, raw, json.dumps(data)))
            if h and h.kind == 2:
                transfer_key = (*scope, h.request_id)
                previous = db.execute('SELECT * FROM flash_transfers WHERE company=? AND region=? '
                                      'AND node=? AND request=?', transfer_key).fetchone()
                if previous and previous['generation'] != h.generation:
                    raise ValueError('Transfer generation changed')
                if previous and previous['phase'] >= 2 and h.phase >= 2 and previous['total'] != h.total:
                    raise ValueError('Transfer total changed')
                if h.phase == 2:
                    row = db.execute('SELECT sequence FROM flash_transfer_rows WHERE company=? AND region=? '
                                     'AND node=? AND request=? AND idx=?', (*transfer_key, h.index)).fetchone()
                    if row and row['sequence'] != h.sequence:
                        raise ValueError('Transfer index reused')
                    inverse = db.execute('SELECT idx FROM flash_transfer_rows WHERE company=? AND region=? '
                                         'AND node=? AND request=? AND sequence=?', (*transfer_key, h.sequence)).fetchone()
                    if inverse and inverse['idx'] != h.index:
                        raise ValueError('Sequence repeated at a different index')
                    db.execute('INSERT OR IGNORE INTO flash_transfer_rows VALUES(?,?,?,?,?,?)',
                               (*transfer_key, h.index, h.sequence))
                received = db.execute('SELECT COUNT(*) FROM flash_transfer_rows WHERE company=? AND region=? '
                                      'AND node=? AND request=?', transfer_key).fetchone()[0]
                total = h.total if h.phase != 1 else (previous['total'] if previous else 0)
                phase = max(h.phase, previous['phase'] if previous else 0)
                result = previous['result'] if previous and previous['phase'] > h.phase else h.result
                complete = phase == 3 and result in (0, 1) and received == total
                db.execute('INSERT OR REPLACE INTO flash_transfers VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                           (*transfer_key, h.generation, total, received, phase, result, int(complete), now))
                if h.ack_required and h.phase in (2, 3):
                    ack = (h.request_id, (h.phase << 32) | h.index)
        return {'Company': company, 'Region': region, 'Node ID': node,
                'memory': status, 'history': MessageToDict(h, preserving_proto_field_name=True,
                always_print_fields_with_no_presence=True) if h else None}, ack

    def summary(self, company, region, node):
        scope = self.scope(company, region, node)
        with closing(self._db()) as db:
            status = db.execute('SELECT received,info FROM flash_status WHERE company=? AND region=? AND node=?', scope).fetchone()
            transfers = db.execute('SELECT * FROM flash_transfers WHERE company=? AND region=? AND node=? '
                                   'ORDER BY updated DESC LIMIT 20', scope).fetchall()
        return {'memory': json.loads(status['info']) if status else None,
                'received_at': status['received'] if status else None,
                'transfers': [dict(row) for row in transfers]}

    def records(self, company, region, node, limit=200, offset=0):
        scope = self.scope(company, region, node)
        limit = integer(limit, 1, 200, 'Page size')
        offset = integer(offset, 0, 10000000, 'Offset')
        with closing(self._db()) as db:
            rows = db.execute('SELECT generation,sequence,epoch,day,data FROM flash_records WHERE '
                              'company=? AND region=? AND node=? ORDER BY generation DESC,sequence '
                              'LIMIT ? OFFSET ?', (*scope, limit, offset)).fetchall()
        return [dict(row, data=json.loads(row['data'])) for row in rows]

    def all_records(self, company, region, node, limit=MAX_RECORDS * 4):
        """Every archived sample for one node (all generations), oldest first, for analysis."""
        scope = self.scope(company, region, node)
        with closing(self._db()) as db:
            rows = db.execute('SELECT generation,sequence,epoch,day,data FROM flash_records WHERE '
                              'company=? AND region=? AND node=? ORDER BY epoch,generation,sequence LIMIT ?',
                              (*scope, int(limit))).fetchall()
        return [dict(row, data=json.loads(row['data'])) for row in rows]

    def nodes(self, company, region):
        """Node IDs that have a flash status, transfer or archived sample in this region."""
        scope = (company_id(company), region_id(region))
        with closing(self._db()) as db:
            rows = db.execute('SELECT node FROM flash_status WHERE company=? AND region=? UNION '
                              'SELECT node FROM flash_records WHERE company=? AND region=? UNION '
                              'SELECT node FROM flash_transfers WHERE company=? AND region=?',
                              scope * 3).fetchall()
        return sorted(r[0] for r in rows)
