from dataclasses import dataclass
from functools import cached_property
from sqlalchemy import text
from src.config import Settings
from src.services.database import create_sql_engine
from src.services.errors import ServiceError


@dataclass(frozen=True)
class TelemetryResult:
    columns: list[str]
    rows: list[tuple]


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

    def query(self, sql_query: str) -> TelemetryResult:
        # Preserved baseline check. Parsed SQL validation and execution budgets belong to Part 4.
        if not sql_query.strip().upper().startswith("SELECT"):
            raise ServiceError(
                "SECURITY BLOCK: Only SELECT operations are authorized on this view."
            )
        try:
            with self.engine.connect() as conn:
                cursor = conn.execute(text(sql_query))
                return TelemetryResult(
                    list(cursor.keys()),
                    [
                        tuple(row)
                        for row in cursor.fetchmany(self.settings.sql_row_limit)
                    ],
                )
        except ServiceError:
            raise
        except Exception:
            raise ServiceError(
                "Telemetry database unavailable or query rejected."
            ) from None
