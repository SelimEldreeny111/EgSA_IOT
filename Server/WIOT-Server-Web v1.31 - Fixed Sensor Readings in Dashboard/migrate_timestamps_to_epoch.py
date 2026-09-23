import os
import shutil
import sqlite3
import time
from datetime import datetime

MESSAGE_DB_DIR = 'messages_dbs'


def to_epoch(value):
    if value is None:
        return int(time.time())
    if isinstance(value, (int, float)):
        return int(value)
    value = str(value).strip()
    if value == '':
        return int(time.time())
    if value.isdigit():
        return int(value)
    try:
        return int(float(value))
    except Exception:
        pass
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%dT%H:%M:%S.%f'):
        try:
            return int(datetime.strptime(value, fmt).timestamp())
        except Exception:
            pass
    try:
        return int(datetime.fromisoformat(value).timestamp())
    except Exception:
        pass
    return int(time.time())


def migrate_db(path):
    print(f'Processing {path}')
    backup_path = path + '.bak'
    if not os.path.exists(backup_path):
        shutil.copy2(path, backup_path)
        print(f'  created backup {backup_path}')
    conn = sqlite3.connect(path)
    c = conn.cursor()
    c.execute('PRAGMA table_info(messages)')
    cols = c.fetchall()
    ts_col = next((col for col in cols if col[1] == 'timestamp'), None)
    if not ts_col:
        raise RuntimeError('messages table has no timestamp column')
    if ts_col[2].upper() == 'INTEGER':
        print('  timestamp already INTEGER, skipping')
        conn.close()
        return

    c.execute('SELECT * FROM messages')
    rows = c.fetchall()
    colnames = [d[0] for d in c.description]
    print(f'  row count {len(rows)}')

    create_columns = []
    for col in cols:
        name = col[1]
        typ = 'INTEGER' if name == 'timestamp' else col[2]
        notnull = ' NOT NULL' if col[3] else ''
        dflt = '' if col[4] is None else f" DEFAULT {repr(col[4])}"
        if name == 'id':
            create_columns.append('id INTEGER PRIMARY KEY AUTOINCREMENT')
        else:
            create_columns.append(f'{name} {typ}{notnull}{dflt}')

    c.execute('CREATE TABLE messages_new (' + ', '.join(create_columns) + ')')
    placeholders = ','.join('?' for _ in colnames)
    insert_sql = 'INSERT INTO messages_new (' + ','.join(colnames) + ') VALUES (' + placeholders + ')'
    for row in rows:
        row = list(row)
        ts_idx = colnames.index('timestamp')
        row[ts_idx] = to_epoch(row[ts_idx])
        c.execute(insert_sql, tuple(row))

    c.execute('DROP TABLE messages')
    c.execute('ALTER TABLE messages_new RENAME TO messages')
    conn.commit()
    conn.close()
    print('  migrated successfully')


if __name__ == '__main__':
    if not os.path.isdir(MESSAGE_DB_DIR):
        raise SystemExit(f'Message DB dir not found: {MESSAGE_DB_DIR}')
    for filename in sorted(os.listdir(MESSAGE_DB_DIR)):
        if not filename.endswith('.db'):
            continue
        migrate_db(os.path.join(MESSAGE_DB_DIR, filename))
    print('All company databases migrated.')
