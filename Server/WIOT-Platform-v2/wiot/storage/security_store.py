"""Sessions, two-factor enrolment, invitations and page permissions (R2.3, points 17 and 21).

Everything lives in the main database (``iot_data.db``) as additive tables and columns.

* ``sessions``: one row per signed-in browser or API client (JWT ``jti``); a session can be revoked
  individually (``revoked_at``), on top of the per-user ``token_version`` that signs out every session.
* ``users.totp_secret`` (sealed with the server key), ``totp_enabled``, ``totp_last_step`` (a code cannot be
  reused) and ``recovery_codes`` (10 one-time codes, stored as SHA-256 hashes).
* ``users.pages``: JSON list of the dashboard pages a user may open; NULL = every page of the role.
* ``invitations``: e-mail invitations with a hashed one-time token, role, company and expiry.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import time

from ..security import seal, unseal
from ..services import totp

SESSION_TOUCH_S = 60
INVITE_TTL_S = 7 * 86400
PAGES = ("farm", "planning", "crop", "satellite", "regional", "maintenance", "commission", "assistant", "world", "overview", "alerts", "health", "notify", "commands", "analytics", "history",
         "flash", "reports", "water", "org", "admin", "security", "usage", "integrations", "help")


def _h(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class SecurityStore:
    def __init__(self, main, secret_key: str):
        self.main = main
        self.secret_key = secret_key
        self._touched: dict[str, float] = {}

    def init_schema(self) -> None:
        with self.main.connect() as db:
            cols = {r["name"] for r in db.execute("PRAGMA table_info(users)")}
            for name, ddl in {"totp_secret": "TEXT", "totp_enabled": "INTEGER NOT NULL DEFAULT 0",
                              "totp_last_step": "INTEGER", "recovery_codes": "TEXT", "pages": "TEXT",
                              "email": "TEXT", "sso_subject": "TEXT"}.items():
                if name not in cols:
                    db.execute(f"ALTER TABLE users ADD COLUMN {name} {ddl}")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS sessions (
                    jti TEXT PRIMARY KEY, user_id INTEGER NOT NULL, username TEXT NOT NULL,
                    created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL, last_seen_at INTEGER NOT NULL,
                    ip TEXT, user_agent TEXT, method TEXT NOT NULL DEFAULT 'password',
                    revoked_at INTEGER, revoked_by TEXT);
                CREATE INDEX IF NOT EXISTS sessions_by_user ON sessions(user_id, expires_at);
                CREATE TABLE IF NOT EXISTS invitations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, token_hash TEXT UNIQUE NOT NULL,
                    email TEXT NOT NULL, role TEXT NOT NULL, company TEXT NOT NULL, pages TEXT,
                    invited_by TEXT NOT NULL, created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL,
                    accepted_at INTEGER, accepted_username TEXT, revoked_at INTEGER);
            """)

    # ------------------------------------------------------------- sessions
    def record_session(self, jti: str, user: dict, expires_at: int, ip: str | None, user_agent: str | None,
                       method: str = "password") -> None:
        now = int(time.time())
        with self.main.connect() as db:
            db.execute("INSERT OR REPLACE INTO sessions(jti, user_id, username, created_at, expires_at, last_seen_at, "
                       "ip, user_agent, method) VALUES(?,?,?,?,?,?,?,?,?)",
                       (jti, user["id"], user["username"], now, int(expires_at), now, ip,
                        (user_agent or "")[:200], method))
            db.execute("DELETE FROM sessions WHERE expires_at<?", (now - 30 * 86400,))

    def session_active(self, jti: str | None) -> bool:
        """False only for a revoked session. Tokens issued before R2.3 have no row and stay valid."""
        if not jti:
            return True
        with self.main.connect() as db:
            row = db.execute("SELECT revoked_at FROM sessions WHERE jti=?", (jti,)).fetchone()
            if row is None:
                return True
            if row["revoked_at"]:
                return False
            now = time.time()
            if now - self._touched.get(jti, 0) > SESSION_TOUCH_S:
                self._touched[jti] = now
                db.execute("UPDATE sessions SET last_seen_at=? WHERE jti=?", (int(now), jti))
        return True

    def list_sessions(self, user_id: int | None = None, company: str | None = None) -> list[dict]:
        q = ("SELECT s.jti, s.user_id, s.username, s.created_at, s.expires_at, s.last_seen_at, s.ip, s.user_agent, "
             "s.method, s.revoked_at, s.revoked_by, u.company FROM sessions s LEFT JOIN users u ON u.id=s.user_id "
             "WHERE s.expires_at>? AND s.revoked_at IS NULL")
        params: list = [int(time.time())]
        if user_id is not None:
            q += " AND s.user_id=?"
            params.append(user_id)
        if company is not None:
            q += " AND u.company=?"
            params.append(company)
        with self.main.connect() as db:
            return [dict(r) for r in db.execute(q + " ORDER BY s.last_seen_at DESC LIMIT 500", params)]

    def get_session(self, jti: str) -> dict | None:
        with self.main.connect() as db:
            row = db.execute("SELECT s.*, u.company FROM sessions s LEFT JOIN users u ON u.id=s.user_id "
                             "WHERE s.jti=?", (jti,)).fetchone()
        return dict(row) if row else None

    def revoke_session(self, jti: str, by: str) -> bool:
        with self.main.connect() as db:
            cur = db.execute("UPDATE sessions SET revoked_at=?, revoked_by=? WHERE jti=? AND revoked_at IS NULL",
                             (int(time.time()), by, jti))
        return cur.rowcount > 0

    # ----------------------------------------------------------- two-factor
    def totp_status(self, user_id: int) -> dict:
        u = self.main.get_user_by_id(user_id) or {}
        codes = json.loads(u.get("recovery_codes") or "[]")
        return {"enabled": bool(u.get("totp_enabled")), "pending": bool(u.get("totp_secret")) and not u.get("totp_enabled"),
                "recovery_codes_left": len(codes)}

    def totp_begin(self, user: dict, issuer: str = "WIOT") -> dict:
        if user.get("totp_enabled"):
            raise ValueError("Two-factor sign-in is already on; turn it off first to enrol a new device")
        secret = totp.new_secret()
        with self.main.connect() as db:
            db.execute("UPDATE users SET totp_secret=?, totp_last_step=NULL WHERE id=?",
                       (seal(self.secret_key, secret), user["id"]))
        return {"secret": secret, "uri": totp.provisioning_uri(secret, user["username"], issuer)}

    def _secret(self, user: dict) -> str | None:
        sealed = user.get("totp_secret")
        if not sealed:
            return None
        try:
            return unseal(self.secret_key, sealed)
        except ValueError:
            return None

    def totp_enable(self, user: dict, code: str) -> list[str]:
        secret = self._secret(user)
        if not secret:
            raise ValueError("Start the set-up first")
        step = totp.verify(secret, code)
        if step is None:
            raise ValueError("Code is not valid; check the device clock and try the next code")
        codes = [f"{secrets.token_hex(2)}-{secrets.token_hex(2)}-{secrets.token_hex(2)}" for _ in range(10)]
        with self.main.connect() as db:
            db.execute("UPDATE users SET totp_enabled=1, totp_last_step=?, recovery_codes=?, "
                       "token_version=token_version+1 WHERE id=?",
                       (step, json.dumps([_h(c) for c in codes]), user["id"]))
        return codes

    def totp_disable(self, user_id: int) -> None:
        with self.main.connect() as db:
            db.execute("UPDATE users SET totp_enabled=0, totp_secret=NULL, totp_last_step=NULL, recovery_codes=NULL "
                       "WHERE id=?", (user_id,))

    def check_second_factor(self, user: dict, code: str | None) -> str | None:
        """'totp' or 'recovery' when the code is accepted, else None. Consumes recovery codes."""
        if not code:
            return None
        code = code.strip()
        secret = self._secret(user)
        if secret:
            step = totp.verify(secret, code, last_step=user.get("totp_last_step"))
            if step is not None:
                with self.main.connect() as db:
                    db.execute("UPDATE users SET totp_last_step=? WHERE id=?", (step, user["id"]))
                return "totp"
        codes = json.loads(user.get("recovery_codes") or "[]")
        h = _h(code.lower())
        if h in codes:
            codes.remove(h)
            with self.main.connect() as db:
                db.execute("UPDATE users SET recovery_codes=? WHERE id=?", (json.dumps(codes), user["id"]))
            return "recovery"
        return None

    # ------------------------------------------------------- page permissions
    @staticmethod
    def pages_of(user: dict) -> list[str] | None:
        raw = user.get("pages")
        if not raw:
            return None
        try:
            pages = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return [p for p in pages if p in PAGES] if isinstance(pages, list) else None

    def set_pages(self, user_id: int, pages: list[str] | None) -> None:
        if pages is not None:
            bad = [p for p in pages if p not in PAGES]
            if bad:
                raise ValueError(f"Unknown page(s): {', '.join(bad)}")
            pages = sorted(set(pages))
        with self.main.connect() as db:
            db.execute("UPDATE users SET pages=? WHERE id=?", (json.dumps(pages) if pages is not None else None, user_id))

    # ------------------------------------------------------------ invitations
    def invite(self, email: str, role: str, company: str, by: str, pages: list[str] | None = None,
               ttl_s: int = INVITE_TTL_S) -> tuple[dict, str]:
        email = (email or "").strip().lower()
        if "@" not in email or len(email) > 200 or " " in email:
            raise ValueError("A valid e-mail address is required")
        if role not in ("admin", "monitor", "user"):
            raise ValueError("Role must be admin, monitor or user")
        if company not in self.main.company_names():
            raise ValueError("Unknown company")
        if pages is not None:
            bad = [p for p in pages if p not in PAGES]
            if bad:
                raise ValueError(f"Unknown page(s): {', '.join(bad)}")
            pages = sorted(set(pages)) or None
        token = secrets.token_urlsafe(32)
        now = int(time.time())
        with self.main.connect() as db:
            inv_id = db.execute("INSERT INTO invitations(token_hash, email, role, company, pages, invited_by, created_at, "
                                "expires_at) VALUES(?,?,?,?,?,?,?,?)",
                                (_h(token), email, role, company, json.dumps(pages) if pages else None, by, now,
                                 now + ttl_s)).lastrowid
        return self.get_invitation(inv_id), token

    def get_invitation(self, inv_id: int) -> dict | None:
        with self.main.connect() as db:
            row = db.execute("SELECT id, email, role, company, pages, invited_by, created_at, expires_at, accepted_at, "
                             "accepted_username, revoked_at FROM invitations WHERE id=?", (inv_id,)).fetchone()
        return dict(row) if row else None

    def list_invitations(self, company: str | None) -> list[dict]:
        q = ("SELECT id, email, role, company, invited_by, created_at, expires_at, accepted_at, accepted_username, "
             "revoked_at FROM invitations")
        params: tuple = ()
        if company is not None:
            q += " WHERE company=?"
            params = (company,)
        with self.main.connect() as db:
            return [dict(r) for r in db.execute(q + " ORDER BY id DESC LIMIT 200", params)]

    def revoke_invitation(self, inv_id: int) -> None:
        with self.main.connect() as db:
            db.execute("UPDATE invitations SET revoked_at=? WHERE id=? AND accepted_at IS NULL",
                       (int(time.time()), inv_id))

    def lookup_invitation(self, token: str) -> dict:
        with self.main.connect() as db:
            row = db.execute("SELECT * FROM invitations WHERE token_hash=?", (_h(token or ""),)).fetchone()
        if row is None or row["revoked_at"] or row["accepted_at"] or row["expires_at"] < time.time():
            raise ValueError("This invitation is not valid any more; ask for a new one")
        return dict(row)

    def accept_invitation(self, token: str, username: str, password: str) -> dict:
        inv = self.lookup_invitation(token)
        user_id = self.main.create_user(username, password, inv["role"], inv["company"])
        with self.main.connect() as db:
            db.execute("UPDATE users SET email=?, pages=? WHERE id=?", (inv["email"], inv["pages"], user_id))
            db.execute("UPDATE invitations SET accepted_at=?, accepted_username=? WHERE id=?",
                       (int(time.time()), username, inv["id"]))
        return self.main.get_user_by_id(user_id)
