"""Identity, tenant registry and audit trail (``iot_data.db``).

Schema is the v1.31 schema plus additive columns/tables only, so a v1 server
can still open the same file.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from contextlib import closing, contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

from ..protocol.validation import company_id
from ..security import (
    GLOBAL_MONITOR_USERNAME,
    ROLES,
    SUPERVISOR_USERNAME,
    hash_password,
    validate_new_password,
)

log = logging.getLogger(__name__)
PROTECTED_USERS = (SUPERVISOR_USERNAME, GLOBAL_MONITOR_USERNAME)


class MainStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    # ------------------------------------------------------------------ schema
    def init_schema(self) -> None:
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE, password TEXT, role TEXT,
                    company TEXT DEFAULT 'Company_1');
                CREATE TABLE IF NOT EXISTS companies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE, created_at TEXT);
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts INTEGER NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL,
                    company TEXT, target TEXT, ip TEXT, details TEXT);
                CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(ts DESC);
                """
            )
            cols = {r["name"] for r in db.execute("PRAGMA table_info(users)")}
            additive = {
                "company": "TEXT DEFAULT 'Company_1'",
                "token_version": "INTEGER NOT NULL DEFAULT 0",
                "created_at": "INTEGER",
                "last_login_at": "INTEGER",
                "disabled": "INTEGER NOT NULL DEFAULT 0",
            }
            for name, ddl in additive.items():
                if name not in cols:
                    db.execute(f"ALTER TABLE users ADD COLUMN {name} {ddl}")
            if db.execute("SELECT COUNT(*) FROM companies").fetchone()[0] == 0:
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                db.executemany(
                    "INSERT INTO companies(name, created_at) VALUES(?, ?)",
                    [("Company_1", now), ("Company_2", now)],
                )

    def bootstrap_users(self, admin_pw: str | None, supervisor_pw: str | None,
                        monitor_pw: str | None) -> list[str]:
        """Create missing built-in accounts. Returns the usernames created."""
        created = []
        wanted = (
            ("admin", admin_pw, "admin", "Company_1", lambda db: db.execute(
                "SELECT 1 FROM users WHERE role='admin' AND username!=?", (SUPERVISOR_USERNAME,)
            ).fetchone()),
            (SUPERVISOR_USERNAME, supervisor_pw, "admin", "", lambda db: db.execute(
                "SELECT 1 FROM users WHERE username=?", (SUPERVISOR_USERNAME,)).fetchone()),
            (GLOBAL_MONITOR_USERNAME, monitor_pw, "monitor", "Company_1", lambda db: db.execute(
                "SELECT 1 FROM users WHERE username=?", (GLOBAL_MONITOR_USERNAME,)).fetchone()),
        )
        with self.connect() as db:
            for username, password, role, company, exists in wanted:
                if exists(db):
                    continue
                if not password:
                    raise RuntimeError(
                        f"Built-in account '{username}' is missing; set its bootstrap password "
                        "(WIOT_ADMIN_PASSWORD / WIOT_SUPERVISOR_PASSWORD / WIOT_MONITOR_PASSWORD)"
                    )
                db.execute(
                    "INSERT INTO users(username,password,role,company,created_at) VALUES(?,?,?,?,?)",
                    (username, hash_password(password), role, company, int(time.time())),
                )
                created.append(username)
        return created

    # ------------------------------------------------------------------ users
    def get_user(self, username: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
            return dict(row) if row else None

    def get_user_by_id(self, user_id: int) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            return dict(row) if row else None

    def touch_login(self, user_id: int) -> None:
        with self.connect() as db:
            db.execute("UPDATE users SET last_login_at=? WHERE id=?", (int(time.time()), user_id))

    def list_users(self, company: str | None) -> list[dict]:
        query = ("SELECT id, username, role, company, created_at, last_login_at, disabled "
                 "FROM users")
        params: tuple = ()
        if company is not None:
            query += " WHERE company=?"
            params = (company,)
        with self.connect() as db:
            rows = [dict(r) for r in db.execute(query + " ORDER BY id", params)]
        for row in rows:
            if row["username"] == SUPERVISOR_USERNAME:
                row["role"] = "supervisor"
            row["protected"] = row["username"] in PROTECTED_USERS
        return rows

    def create_user(self, username: str, password: str, role: str, company: str, *,
                    allow_supervisor: bool = False) -> int:
        username = (username or "").strip()
        if not 3 <= len(username) <= 80 or not all(c.isalnum() or c in "_-." for c in username):
            raise ValueError("Username must be 3..80 letters, digits, '.', '_' or '-'")
        if role not in ROLES or (role == "supervisor" and not allow_supervisor):
            raise ValueError("Role must be admin, monitor or user")
        validate_new_password(password)
        company_id(company)
        if company not in self.company_names():
            raise ValueError("Unknown company")
        try:
            with self.connect() as db:
                cur = db.execute(
                    "INSERT INTO users(username,password,role,company,created_at) VALUES(?,?,?,?,?)",
                    (username, hash_password(password), role, company, int(time.time())),
                )
                return int(cur.lastrowid)
        except sqlite3.IntegrityError as exc:
            raise ValueError("Username already exists") from exc

    def delete_user(self, user_id: int) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            if row is None:
                raise LookupError("User not found")
            if row["username"] in PROTECTED_USERS:
                raise PermissionError("Built-in accounts cannot be deleted")
            db.execute("DELETE FROM users WHERE id=?", (user_id,))
            return dict(row)

    def set_password(self, user_id: int, new_password: str) -> None:
        validate_new_password(new_password)
        with self.connect() as db:
            db.execute(
                "UPDATE users SET password=?, token_version=token_version+1 WHERE id=?",
                (hash_password(new_password), user_id),
            )

    # ---------------------------------------------------------------- tenants
    def company_names(self) -> list[str]:
        if not self.path.exists():
            return []
        with closing(sqlite3.connect(self.path)) as db:
            try:  # archived companies (Organization page) are not active tenants
                return [r[0] for r in db.execute("SELECT name FROM companies WHERE COALESCE(active, 1)=1 ORDER BY id")]
            except sqlite3.OperationalError:  # before the organization columns exist
                return [r[0] for r in db.execute("SELECT name FROM companies ORDER BY id")]

    def list_companies(self) -> list[dict]:
        with self.connect() as db:
            return [dict(r) for r in db.execute(
                "SELECT id, name, created_at FROM companies ORDER BY id")]

    def add_company(self, name: str) -> None:
        company_id(name)
        try:
            with self.connect() as db:
                db.execute(
                    "INSERT INTO companies(name, created_at) VALUES(?, ?)",
                    (name, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError("Company already exists") from exc

    # ------------------------------------------------------------------ audit
    def audit(self, actor: str, action: str, *, company: str | None = None,
              target: str | None = None, ip: str | None = None, details: dict | None = None) -> None:
        try:
            with self.connect() as db:
                db.execute(
                    "INSERT INTO audit_log(ts,actor,action,company,target,ip,details) VALUES(?,?,?,?,?,?,?)",
                    (int(time.time()), actor, action, company, target, ip,
                     json.dumps(details or {}, default=str)[:4000]),
                )
        except sqlite3.Error:
            log.exception("Audit write failed for action=%s", action)

    def list_audit(self, company: str | None, limit: int = 200) -> list[dict]:
        query = "SELECT * FROM audit_log"
        params: list = []
        if company is not None:
            query += " WHERE company=?"
            params.append(company)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        with self.connect() as db:
            rows = [dict(r) for r in db.execute(query, params)]
        for row in rows:
            try:
                row["details"] = json.loads(row["details"] or "{}")
            except json.JSONDecodeError:
                pass
        return rows
