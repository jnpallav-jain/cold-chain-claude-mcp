"""Persistent admission controls for a single-instance, invite-only Streamlit demo."""

from contextlib import contextmanager
from functools import lru_cache
import hashlib
import hmac
import os
import secrets
import sqlite3
import time
from uuid import uuid4
from src.config import get_settings
from src.services.approvals import verify_password
from src.services.errors import ServiceError


class DemoControl:
    def __init__(self, settings, *, path=None, clock=time.time):
        self.settings = settings
        self.path = path or settings.resolve_path(settings.demo_control_path)
        self.clock = clock

    @property
    def configured(self):
        return bool(self.settings.demo_password_hash.get_secret_value())

    @property
    def stop_path(self):
        return self.path.parent / "DEMO_STOPPED"

    @property
    def credential_version(self):
        return hashlib.sha256(
            (
                self.settings.demo_user
                + self.settings.demo_password_hash.get_secret_value()
            ).encode()
        ).hexdigest()

    @contextmanager
    def transaction(self):
        conn = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
            os.close(fd)
            conn = sqlite3.connect(self.path, timeout=3)
            conn.row_factory = sqlite3.Row
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS logins (timestamp REAL NOT NULL, success INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, principal TEXT NOT NULL, version TEXT NOT NULL, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS requests (id TEXT PRIMARY KEY, principal TEXT NOT NULL, session_hash TEXT NOT NULL, started REAL NOT NULL, expires REAL NOT NULL, finished REAL, day TEXT NOT NULL, reservation_cents INTEGER NOT NULL);
            """)
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except ServiceError:
            if conn:
                conn.rollback()
            raise
        except Exception:
            if conn:
                conn.rollback()
            raise ServiceError(
                "Demo control storage unavailable. Requests are disabled."
            ) from None
        finally:
            if conn:
                conn.close()

    @staticmethod
    def token_hash(token):
        return hashlib.sha256(token.encode()).hexdigest()

    def login(self, username, password):
        if not self.configured:
            raise ServiceError("Demo access is not configured.")
        now = self.clock()
        # Compute outside the DB lock. Never persist usernames/passwords from failed attempts.
        valid = verify_password(
            password, self.settings.demo_password_hash.get_secret_value()
        ) and hmac.compare_digest(username.encode(), self.settings.demo_user.encode())
        denied = False
        with self.transaction() as conn:
            failures = conn.execute(
                "SELECT COUNT(*) FROM logins WHERE timestamp>? AND success=0",
                (now - 60,),
            ).fetchone()[0]
            if failures >= 5:
                denied = True
            else:
                conn.execute("INSERT INTO logins VALUES(?,?)", (now, int(valid)))
                denied = not valid
            if not denied:
                token = secrets.token_urlsafe(32)
                conn.execute("DELETE FROM sessions WHERE expires<=?", (now,))
                conn.execute(
                    "INSERT INTO sessions VALUES(?,?,?,?)",
                    (
                        self.token_hash(token),
                        self.settings.demo_user,
                        self.credential_version,
                        now + self.settings.demo_session_seconds,
                    ),
                )
        if denied:
            raise ServiceError(
                "Invalid demo credentials or temporary login limit. Try again later."
            )
        return token

    def _principal(self, conn, token):
        if not self.configured or not isinstance(token, str) or len(token) > 128:
            raise ServiceError("Sign in to the demo before continuing.")
        row = conn.execute(
            "SELECT * FROM sessions WHERE token_hash=? AND expires>? AND version=?",
            (self.token_hash(token), self.clock(), self.credential_version),
        ).fetchone()
        if not row:
            raise ServiceError("Demo session expired. Sign in again.")
        return row["principal"]

    def validate(self, token):
        with self.transaction() as conn:
            return self._principal(conn, token)

    def logout(self, token):
        with self.transaction() as conn:
            conn.execute(
                "DELETE FROM sessions WHERE token_hash=?", (self.token_hash(token),)
            )

    def admit(self, token):
        if self.stop_path.exists():
            raise ServiceError(
                "Demo is paused by the operator. No model request was started."
            )
        now = self.clock()
        day = time.strftime("%Y-%m-%d", time.gmtime(now))
        with self.transaction() as conn:
            principal = self._principal(conn, token)
            if self.stop_path.exists():
                raise ServiceError("Demo is paused by the operator.")
            active = conn.execute(
                "SELECT COUNT(*) FROM requests WHERE finished IS NULL AND expires>?",
                (now,),
            ).fetchone()[0]
            if active >= self.settings.demo_max_concurrent:
                raise ServiceError(
                    "The demo is busy. Please try again after the current request finishes."
                )
            recent = conn.execute(
                "SELECT COUNT(*) FROM requests WHERE principal=? AND started>?",
                (principal, now - 3600),
            ).fetchone()[0]
            if recent >= self.settings.demo_requests_per_hour:
                raise ServiceError(
                    "Hourly demo request limit reached. Try again later."
                )
            reserved = conn.execute(
                "SELECT COALESCE(SUM(reservation_cents),0) FROM requests WHERE day=?",
                (day,),
            ).fetchone()[0]
            reservation = self.settings.demo_request_budget_cents
            if reserved + reservation > self.settings.demo_daily_budget_cents:
                raise ServiceError(
                    "Daily demo admission budget reached. Requests resume on the next UTC day."
                )
            request_id = str(uuid4())
            conn.execute(
                "INSERT INTO requests VALUES(?,?,?,?,?,NULL,?,?)",
                (
                    request_id,
                    principal,
                    self.token_hash(token),
                    now,
                    now
                    + self.settings.claude_request_timeout
                    + self.settings.tool_timeout
                    + 30,
                    day,
                    reservation,
                ),
            )
            return request_id

    def finish(self, request_id):
        with self.transaction() as conn:
            conn.execute(
                "UPDATE requests SET finished=? WHERE id=? AND finished IS NULL",
                (self.clock(), request_id),
            )


@lru_cache(maxsize=1)
def get_demo_control():
    return DemoControl(get_settings())
