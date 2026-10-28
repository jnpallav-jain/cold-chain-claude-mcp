"""Local simulation control plane. No approval/execution method is exposed through MCP."""

from contextlib import contextmanager
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
import time
from uuid import uuid4
from pydantic import BaseModel, ConfigDict, Field
from src.security.redaction import Redactor
from src.services.errors import ServiceError


class IncidentProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    summary: str = Field(min_length=10, max_length=500)
    evidence: str = Field(min_length=10, max_length=2000)
    sop_reference: str = Field(min_length=5, max_length=300)


def password_hash(password):
    if len(password) < 12 or len(password) > 256:
        raise ValueError("Use an operator password between 12 and 256 characters.")
    salt = secrets.token_hex(16)
    digest = hashlib.scrypt(
        password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1
    ).hex()
    return f"scrypt${salt}${digest}"


def verify_password(password, encoded):
    try:
        if not 1 <= len(password) <= 256:
            return False
        algorithm, salt, expected = encoded.split("$")
        if algorithm != "scrypt" or len(salt) != 32 or len(expected) != 128:
            return False
        actual = hashlib.scrypt(
            password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1
        ).hex()
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


class ApprovalService:
    """Atomic proposal/decision/incident ledger; OS access to this file is privileged."""

    def __init__(self, settings, *, path=None, clock=time.time):
        self.settings = settings
        self.path = path or settings.resolve_path(settings.approval_db_path)
        self.clock = clock
        self.redactor = Redactor(settings)
        self._auth_lock = threading.Lock()
        self._failed_attempts = 0
        self._locked_until = 0.0

    @property
    def configured(self):
        return bool(
            self.settings.approval_operator
            and self.settings.approval_password_hash.get_secret_value()
        )

    @contextmanager
    def _transaction(self):
        conn = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            # Create privately before sqlite opens it. No credentials live in this database.
            fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
            os.close(fd)
            conn = sqlite3.connect(self.path, timeout=3)
            conn.row_factory = sqlite3.Row
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS proposals (
                    id TEXT PRIMARY KEY, session_id TEXT NOT NULL, digest TEXT NOT NULL,
                    payload TEXT NOT NULL, status TEXT NOT NULL, created REAL NOT NULL,
                    expires REAL NOT NULL, UNIQUE(session_id,digest));
                CREATE TABLE IF NOT EXISTS incidents (
                    id TEXT PRIMARY KEY, proposal_id TEXT NOT NULL UNIQUE,
                    session_id TEXT NOT NULL, payload TEXT NOT NULL,
                    operator TEXT NOT NULL, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS decisions (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL, proposal_id TEXT NOT NULL,
                    event TEXT NOT NULL, operator TEXT, timestamp REAL NOT NULL,
                    details TEXT NOT NULL);
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
                "Approval storage unavailable; no action was committed."
            ) from None
        finally:
            if conn:
                conn.close()

    def _event(
        self, conn, session_id, proposal_id, event, *, operator=None, details=None
    ):
        conn.execute(
            "INSERT INTO decisions(session_id,proposal_id,event,operator,timestamp,details) VALUES(?,?,?,?,?,?)",
            (
                session_id,
                proposal_id,
                event,
                operator,
                self.clock(),
                json.dumps(self.redactor.data(details or {})),
            ),
        )

    def propose(self, session_id, **payload):
        if not self.configured:
            raise ServiceError(
                "Simulation approvals are disabled. Configure a local operator first."
            )
        validated = IncidentProposal.model_validate(payload).model_dump()
        encoded = json.dumps(
            self.redactor.data(validated), sort_keys=True, ensure_ascii=False
        )
        digest = hashlib.sha256(encoded.encode()).hexdigest()
        with self._transaction() as conn:
            prior = conn.execute(
                "SELECT * FROM proposals WHERE session_id=? AND digest=?",
                (session_id, digest),
            ).fetchone()
            if prior:
                return self._public(prior)
            proposal_id = str(uuid4())
            now = self.clock()
            conn.execute(
                "INSERT INTO proposals VALUES(?,?,?,?,?,?,?)",
                (
                    proposal_id,
                    session_id,
                    digest,
                    encoded,
                    "pending",
                    now,
                    now + self.settings.approval_ttl_seconds,
                ),
            )
            self._event(
                conn,
                session_id,
                proposal_id,
                "proposed",
                details={"digest": digest, "simulation": True},
            )
            return self._public(
                conn.execute(
                    "SELECT * FROM proposals WHERE id=?", (proposal_id,)
                ).fetchone()
            )

    def _public(self, row):
        return {
            "proposal_id": row["id"],
            "session_id": row["session_id"],
            "digest": row["digest"],
            "payload": json.loads(row["payload"]),
            "status": row["status"],
            "created_at_unix": row["created"],
            "expires_at_unix": row["expires"],
            "simulation": True,
            "external_notification": False,
        }

    def list_for_session(self, session_id):
        with self._transaction() as conn:
            return [
                self._public(row)
                for row in conn.execute(
                    "SELECT * FROM proposals WHERE session_id=? ORDER BY created DESC LIMIT 50",
                    (session_id,),
                )
            ]

    def _authenticate(self, operator, password):
        # One shared lockout for this local single-operator demo. Deployment auth is Part 7.
        with self._auth_lock:
            if time.monotonic() < self._locked_until:
                return False
            valid = verify_password(
                password, self.settings.approval_password_hash.get_secret_value()
            )
            valid = (
                valid
                and hmac.compare_digest(
                    operator.encode(), self.settings.approval_operator.encode()
                )
                and self.configured
            )
            if valid:
                self._failed_attempts = 0
                return True
            self._failed_attempts += 1
            if self._failed_attempts >= 5:
                self._locked_until = time.monotonic() + 60
                self._failed_attempts = 0
            return False

    def decide(self, session_id, proposal_id, digest, decision, *, operator, password):
        """Human endpoint only: approve+execute atomically, or reject. Never accepts replacement payload."""
        if decision not in {"approve", "reject"}:
            raise ServiceError("Choose approve or reject.")
        authenticated = self._authenticate(operator, password)
        error = None
        outcome = None
        with self._transaction() as conn:
            row = conn.execute(
                "SELECT * FROM proposals WHERE id=? AND session_id=?",
                (proposal_id, session_id),
            ).fetchone()
            if not authenticated:
                self._event(conn, session_id, proposal_id, "authentication_denied")
                error = "Invalid operator credentials or temporary lockout."
            elif not row:
                self._event(
                    conn,
                    session_id,
                    proposal_id,
                    "decision_denied",
                    operator=operator,
                    details={"reason": "session_or_proposal"},
                )
                error = "Proposal is unavailable in this conversation."
            elif (
                not hmac.compare_digest(digest, row["digest"])
                or hashlib.sha256(row["payload"].encode()).hexdigest() != row["digest"]
            ):
                self._event(
                    conn,
                    session_id,
                    proposal_id,
                    "decision_denied",
                    operator=operator,
                    details={"reason": "digest"},
                )
                error = "Proposal content changed; approval refused."
            elif row["status"] == "executed" and decision == "approve":
                incident = conn.execute(
                    "SELECT id FROM incidents WHERE proposal_id=?", (proposal_id,)
                ).fetchone()
                self._event(
                    conn,
                    session_id,
                    proposal_id,
                    "duplicate_prevented",
                    operator=operator,
                )
                outcome = {
                    "status": "executed",
                    "incident_id": incident["id"],
                    "duplicate_prevented": True,
                }
            elif row["status"] != "pending":
                error = "Proposal already decided; no additional action was taken."
                self._event(
                    conn,
                    session_id,
                    proposal_id,
                    "decision_denied",
                    operator=operator,
                    details={"reason": "already_decided"},
                )
            elif self.clock() >= row["expires"]:
                conn.execute(
                    "UPDATE proposals SET status='expired' WHERE id=?", (proposal_id,)
                )
                self._event(conn, session_id, proposal_id, "expired", operator=operator)
                error = "Proposal expired; start a fresh conversation and reassess."
            elif decision == "reject":
                conn.execute(
                    "UPDATE proposals SET status='rejected' WHERE id=?", (proposal_id,)
                )
                self._event(
                    conn, session_id, proposal_id, "rejected", operator=operator
                )
                outcome = {"status": "rejected"}
            else:
                incident_id = str(uuid4())
                self._event(
                    conn,
                    session_id,
                    proposal_id,
                    "approved",
                    operator=operator,
                    details={"digest": digest},
                )
                conn.execute(
                    "INSERT INTO incidents VALUES(?,?,?,?,?,?)",
                    (
                        incident_id,
                        proposal_id,
                        session_id,
                        row["payload"],
                        operator,
                        self.clock(),
                    ),
                )
                conn.execute(
                    "UPDATE proposals SET status='executed' WHERE id=?", (proposal_id,)
                )
                self._event(
                    conn,
                    session_id,
                    proposal_id,
                    "executed",
                    operator=operator,
                    details={"incident_id": incident_id, "simulation": True},
                )
                outcome = {
                    "status": "executed",
                    "incident_id": incident_id,
                    "duplicate_prevented": False,
                }
        if error:
            raise ServiceError(error)
        return {**outcome, "simulation": True, "external_notification": False}

    def trail(self, session_id):
        with self._transaction() as conn:
            return [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM decisions WHERE session_id=? ORDER BY sequence",
                    (session_id,),
                )
            ]
