"""Case-sensitive WIOT company/region topic contract; no legacy aliases."""
import re

DEFAULT_REGION = 'Region_1'
SUBSCRIPTIONS = ['wiot/+/+/+/data', 'wiot/+/+/+/status',
                 'wiot/+/+/+/cmd', 'wiot/+/+/broadcast']


def region_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,40}', value):
        raise ValueError('Region ID must be 1..40 ASCII letters, digits, _ or -')
    return value


def command_topic(company, region, node_id, broadcast=False):
    from .validation import company_id, integer
    prefix = f'wiot/{company_id(company)}/{region_id(region)}'
    return prefix + ('/broadcast' if broadcast else '/' + str(integer(node_id, 1, 65535, 'Node ID')) + '/cmd')


def migrate_region_storage(db):
    """Additive migration; existing records belong to documented Region_1.

    Rebuild the consumption uniqueness constraint transactionally so identical
    node/sensor IDs in different regions cannot overwrite each other's periods.
    Caller owns the transaction and commits only after all migrations succeed.
    """
    for table in ('messages', 'meter_samples', 'consumption_periods'):
        columns = [r[1] for r in db.execute(f'PRAGMA table_info({table})')]
        if 'region' not in columns:
            db.execute(f"ALTER TABLE {table} ADD COLUMN region TEXT NOT NULL DEFAULT 'Region_1'")
    schema = db.execute("SELECT sql FROM sqlite_master WHERE name='consumption_periods'").fetchone()[0]
    if 'unique(region,' not in ''.join(schema.lower().split()):
        updated = re.sub(r'CREATE TABLE\s+["\[]?consumption_periods["\]]?',
                         'CREATE TABLE consumption_periods_regions', schema, count=1, flags=re.I)
        updated = re.sub(r'UNIQUE\s*\(\s*node_id', 'UNIQUE(region, node_id', updated, count=1, flags=re.I)
        db.execute(updated)
        cols = [r[1] for r in db.execute('PRAGMA table_info(consumption_periods)')]
        names = ','.join(cols)
        db.execute(f'INSERT INTO consumption_periods_regions ({names}) SELECT {names} FROM consumption_periods')
        db.execute('DROP TABLE consumption_periods')
        db.execute('ALTER TABLE consumption_periods_regions RENAME TO consumption_periods')
    db.execute('CREATE INDEX IF NOT EXISTS idx_region_messages ON messages(region,node_id,id)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_region_periods ON consumption_periods(region,node_id,sensor_id,period_type,period_key)')
