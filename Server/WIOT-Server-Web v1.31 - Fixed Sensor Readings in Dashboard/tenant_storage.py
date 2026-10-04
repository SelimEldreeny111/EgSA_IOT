"""Stable, platform-independent tenant storage identities and legacy preflight.

No files are moved/deleted and no production migration is performed here.
Existing unambiguous filenames remain usable. New databases use full SHA-256
of the immutable, case-sensitive UTF-8 company topic ID, never lossy sanitizing.
Ambiguous legacy files fail closed and require an operator-reviewed migration.
"""
import hashlib
import re
from pathlib import Path
from contextlib import closing
from input_validation import company_id


def storage_id(company):
    return 'tenant_' + hashlib.sha256(company_id(company).encode('utf-8')).hexdigest()


def legacy_name(company):
    return re.sub(r'[^A-Za-z0-9_-]+', '_', company) or 'Unknown'


def preflight(companies, directory):
    """Read-only collision inventory, including Windows case-insensitivity."""
    groups = {}
    problems = []
    for company in companies:
        try:
            company_id(company)
        except ValueError:
            problems.append({'company': company, 'reason': 'invalid topic ID'})
            continue
        if (Path(directory) / (storage_id(company) + '.db')).exists():
            continue
        groups.setdefault(legacy_name(company).casefold(), []).append(company)
    for basename, owners in groups.items():
        files = [p for p in Path(directory).glob('*.db') if p.stem.casefold() == basename]
        if files and len(owners) > 1:
            problems.append({'companies': owners, 'files': [str(p) for p in files],
                'reason': 'ambiguous legacy database; manual migration required'})
    return problems


def database_path(company, directory, known_companies=()):
    """Resolve one identity; never open another company's legacy filename."""
    target = Path(directory) / (storage_id(company) + '.db')
    if target.exists():
        return str(target)
    legacy = legacy_name(company)
    candidates = [p for p in Path(directory).glob('*.db')
                  if p.stem.casefold() == legacy.casefold()]
    if not candidates:
        return str(target)
    owners = set(known_companies) | {company}
    claimants = [c for c in owners if legacy_name(c).casefold() == legacy.casefold()
                 and not (Path(directory) / (storage_id(c) + '.db')).exists()]
    if len(claimants) != 1 or len(candidates) != 1:
        raise ValueError('Ambiguous legacy tenant database; run tenant preflight and approve migration')
    # Do not adopt an existing unregistered/mixed legacy DB on a name guess.
    import sqlite3
    with closing(sqlite3.connect(candidates[0].resolve().as_uri() + '?mode=ro', uri=True)) as conn:
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='messages'").fetchone():
            rows = conn.execute('SELECT DISTINCT company FROM messages').fetchall()
            if any(row[0] != company for row in rows):
                raise ValueError('Legacy database contains another tenant; migration required')
    return str(candidates[0])


if __name__ == '__main__':
    import argparse
    import json
    import sqlite3
    parser = argparse.ArgumentParser(description='Read-only tenant database migration preflight')
    parser.add_argument('--main-db', required=True)
    parser.add_argument('--messages-dir', required=True)
    args = parser.parse_args()
    with closing(sqlite3.connect(Path(args.main_db).resolve().as_uri() + '?mode=ro', uri=True)) as conn:
        companies = [r[0] for r in conn.execute('SELECT name FROM companies')]
    issues = preflight(companies, args.messages_dir)
    for company in companies:
        try:
            database_path(company, args.messages_dir, companies)
        except ValueError as exc:
            issues.append({'company': company, 'reason': str(exc)})
    print(json.dumps({'safe_to_start': not issues, 'issues': issues}, indent=2))
    raise SystemExit(1 if issues else 0)
