from dataclasses import dataclass
from functools import cached_property
from src.config import Settings
from src.security.sql_policy import validate_query
from src.services.database import create_sql_engine
from src.services.sql_executor import SqlQueryExecutor


@dataclass(frozen=True)
class TelemetryResult:
    columns: list[str]
    rows: list[tuple]
    normalized_sql: str | None = None


class TelemetryService:
    def __init__(self, settings: Settings, *, engine=None):
        self.settings, self._engine = settings, engine

    @cached_property
    def engine(self):
        return (
            self._engine
            if self._engine is not None
            else create_sql_engine(self.settings)
        )

    def query(self, sql_query: str, *, cancellation=None) -> TelemetryResult:
        query = validate_query(
            sql_query,
            row_limit=self.settings.sql_row_limit,
            max_chars=self.settings.sql_max_chars,
        )
        columns, rows = SqlQueryExecutor(self.engine, self.settings).execute(
            query, cancellation=cancellation
        )
        return TelemetryResult(columns, rows, query.sql)
