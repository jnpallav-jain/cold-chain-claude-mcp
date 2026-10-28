"""Live deterministic database deadline/cancellation and permission checks. No model calls."""

import argparse
import json
import threading
import time
from pathlib import Path
from sqlalchemy import text
from src.config import get_settings
from src.services.database import create_sql_engine
from src.services.telemetry import TelemetryService
from src.services.sql_executor import QueryCancellation, QueryTimedOut, QueryCancelled

VIEW = "FDE_VIEWS.VW_ACTIVE_FLEET"


def blocked_query_check(settings, *, explicit_cancel):
    """Hold a rollback-only lock so a harmless approved SELECT must wait."""
    adjusted = settings.model_copy(
        update={"sql_query_timeout": 5 if explicit_cancel else 1}
    )
    engine = create_sql_engine(adjusted)
    admin = create_sql_engine(settings, admin=True)
    token = QueryCancellation()
    outcome = {}
    started = time.monotonic()
    lock = admin.connect()
    transaction = lock.begin()
    thread = None
    try:
        lock.exec_driver_sql(
            "UPDATE dbo.TBL_SC_FLEET_HIST_RAW WITH (TABLOCKX,HOLDLOCK) SET IOT_TEMP_VAL_C=IOT_TEMP_VAL_C"
        )

        def worker():
            try:
                TelemetryService(adjusted, engine=engine).query(
                    f"SELECT Current_Temperature_C FROM {VIEW}", cancellation=token
                )
                outcome["unexpected_success"] = True
            except Exception as error:
                outcome["error_type"] = type(error).__name__
            finally:
                outcome["elapsed_seconds"] = round(time.monotonic() - started, 3)

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        if explicit_cancel:
            assert token.ready.wait(3), "Query did not obtain a cursor"
            time.sleep(0.2)
            token.cancel()
        thread.join(4 if explicit_cancel else 3)
        assert not thread.is_alive(), (
            "Database query did not stop within the test deadline"
        )
        assert not outcome.get("unexpected_success"), (
            "SELECT did not block under the test lock"
        )
        if explicit_cancel:
            assert token.cancel_attempted, (
                "Native cursor cancellation was not attempted"
            )
            assert outcome["error_type"] == QueryCancelled.__name__, outcome
        else:
            assert outcome["error_type"] == QueryTimedOut.__name__, outcome
        # Check the cancelled/expired connection has no active server request.
        with admin.connect() as inspector:
            for _ in range(10):
                active = inspector.execute(
                    text(
                        "SELECT COUNT(*) FROM sys.dm_exec_requests WHERE session_id=:spid"
                    ),
                    {"spid": token.spid},
                ).scalar()
                if active == 0:
                    break
                time.sleep(0.1)
            assert active == 0, "Stopped client still has an active SQL Server request"
        outcome["active_server_requests_after_stop"] = active
        outcome["native_cancel_attempted"] = token.cancel_attempted
        return outcome
    finally:
        if thread is not None and thread.is_alive():
            token.cancel()
        transaction.rollback()
        lock.close()
        if thread is not None:
            thread.join(3)
        engine.dispose()
        admin.dispose()


def verify_permissions(settings):
    agent = create_sql_engine(settings)
    try:
        with agent.connect() as conn:
            result = {}
            for label, entity, permission, expected in [
                ("view_read", "FDE_VIEWS.VW_ACTIVE_FLEET", "SELECT", 1),
                ("raw_read", "dbo.TBL_SC_FLEET_HIST_RAW", "SELECT", 0),
                ("raw_insert", "dbo.TBL_SC_FLEET_HIST_RAW", "INSERT", 0),
                ("raw_update", "dbo.TBL_SC_FLEET_HIST_RAW", "UPDATE", 0),
                ("raw_delete", "dbo.TBL_SC_FLEET_HIST_RAW", "DELETE", 0),
                ("raw_alter", "dbo.TBL_SC_FLEET_HIST_RAW", "ALTER", 0),
                ("audit_insert", "FDE_VIEWS.AgentAuditLog", "INSERT", 1),
                ("audit_read", "FDE_VIEWS.AgentAuditLog", "SELECT", 0),
                ("audit_update", "FDE_VIEWS.AgentAuditLog", "UPDATE", 0),
                ("audit_delete", "FDE_VIEWS.AgentAuditLog", "DELETE", 0),
                ("audit_alter", "FDE_VIEWS.AgentAuditLog", "ALTER", 0),
            ]:
                value = conn.execute(
                    text("SELECT HAS_PERMS_BY_NAME(:entity,'OBJECT',:permission)"),
                    {"entity": entity, "permission": permission},
                ).scalar()
                assert value == expected, f"Unexpected permission for {label}"
                result[label] = bool(value)
            return result
    finally:
        agent.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not args.live:
        parser.error(
            "--live is required; this creates a short-lived rollback-only lock in the dedicated database"
        )
    settings = get_settings()
    result = {
        "database": settings.sql_database,
        "permissions": verify_permissions(settings),
    }
    before = (
        TelemetryService(settings)
        .query(
            f"SELECT Current_Temperature_C FROM {VIEW} ORDER BY Current_Temperature_C"
        )
        .rows
    )
    result["native_query_timeout"] = blocked_query_check(
        settings, explicit_cancel=False
    )
    result["explicit_cursor_cancel"] = blocked_query_check(
        settings, explicit_cancel=True
    )
    after = (
        TelemetryService(settings)
        .query(
            f"SELECT Current_Temperature_C FROM {VIEW} ORDER BY Current_Temperature_C"
        )
        .rows
    )
    assert before == after, "Synthetic data changed during guardrail checks"
    result["synthetic_data_unchanged"] = True
    result["successful_query_after_cancellation"] = True
    if args.output:
        args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error_type": type(error).__name__,
                    "message": "Guardrail verification failed; no raw database diagnostics printed.",
                }
            )
        )
        raise SystemExit(1)
