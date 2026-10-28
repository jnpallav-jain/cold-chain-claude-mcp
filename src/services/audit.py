from dataclasses import dataclass
from functools import cached_property
from sqlalchemy import text
from src.config import Settings
from src.services.database import create_sql_engine
from src.services.errors import ServiceError


@dataclass(frozen=True)
class AuditEvent:
    session_id: str
    node_name: str
    tool_name: str
    content: str


class AuditService:
    def __init__(self, settings: Settings, *, engine=None):
        self.settings, self._engine = settings, engine

    @cached_property
    def engine(self):
        return (
            self._engine
            if self._engine is not None
            else create_sql_engine(self.settings)
        )

    def write(self, event: AuditEvent) -> None:
        try:
            with self.engine.begin() as conn:
                conn.execute(
                    text("""INSERT INTO FDE_VIEWS.AgentAuditLog
                    (SessionID,NodeExecuted,ToolName,Content) VALUES
                    (:session_id,:node_name,:tool_name,:content)"""),
                    vars(event),
                )
        except Exception:
            raise ServiceError("Audit write failed.") from None

    def read_recent(self, *, engine=None):
        # The caller must supply an administrative connection; never read using the agent login.
        if engine is None:
            raise ServiceError(
                "Administrative connection required to inspect audit records."
            )
        try:
            with engine.connect() as conn:
                rows = conn.execute(
                    text("""SELECT TOP 200 LogID,Timestamp,SessionID,NodeExecuted,ToolName,Content
                    FROM FDE_VIEWS.AgentAuditLog ORDER BY Timestamp DESC""")
                )
                return list(rows.mappings())
        except Exception:
            raise ServiceError("Audit read unavailable.") from None
