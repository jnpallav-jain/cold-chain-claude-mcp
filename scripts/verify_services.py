"""Live Part 2 smoke checks; explicit --live required. Does not run an agent."""

import argparse
import json
import uuid
from pathlib import Path
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from src.config import get_settings
from src.services.container import get_services
from src.services.database import create_sql_engine
from src.services.audit import AuditEvent


def check_denial(engine, sql):
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql(sql)
    except DBAPIError as error:
        if "229" in str(error.orig):
            return True
        raise RuntimeError("Unexpected failure while checking SQL permission") from None
    raise AssertionError("Forbidden SQL operation unexpectedly succeeded")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--skip-sop", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not args.live:
        parser.error(
            "--live is required to contact services and insert one audit event"
        )
    settings = get_settings()
    services = get_services()
    rows = services.telemetry.query(
        "SELECT Current_Temperature_C FROM FDE_VIEWS.VW_ACTIVE_FLEET ORDER BY Current_Temperature_C"
    ).rows
    assert [row[0] for row in rows] == [2.5, 4.0, 4.1, 7.0], (
        "Synthetic fleet results differ from fixture"
    )
    breaches = services.telemetry.query(
        "SELECT Current_Temperature_C FROM FDE_VIEWS.VW_ACTIVE_FLEET WHERE Current_Temperature_C > 4"
    ).rows
    assert len(breaches) == 2
    session = "part2-" + str(uuid.uuid4())[:12]
    services.audit.write(
        AuditEvent(
            session,
            "service_check",
            "query_telemetry_db",
            "Synthetic service check; no model execution.",
        )
    )
    agent = create_sql_engine(settings)
    try:
        denied = {
            "raw_select": check_denial(
                agent, "SELECT TOP 1 * FROM dbo.TBL_SC_FLEET_HIST_RAW"
            ),
            "raw_delete": check_denial(
                agent, "DELETE FROM dbo.TBL_SC_FLEET_HIST_RAW WHERE 1=0"
            ),
            "audit_select": check_denial(
                agent, "SELECT TOP 1 * FROM FDE_VIEWS.AgentAuditLog"
            ),
            "audit_update": check_denial(
                agent, "UPDATE FDE_VIEWS.AgentAuditLog SET Content='blocked' WHERE 1=0"
            ),
        }
    finally:
        agent.dispose()
    admin = create_sql_engine(settings, admin=True)
    try:
        with admin.connect() as conn:
            assert (
                conn.execute(
                    text(
                        "SELECT COUNT(*) FROM FDE_VIEWS.AgentAuditLog WHERE SessionID=:session"
                    ),
                    {"session": session},
                ).scalar()
                == 1
            )
            assert (
                conn.execute(text("SELECT DB_NAME()")).scalar() == settings.sql_database
            )
    finally:
        admin.dispose()
    weather = services.weather.fetch(33.77, -118.19)
    result = {
        "sql_database": settings.sql_database,
        "synthetic_rows": len(rows),
        "temperature_breaches": len(breaches),
        "audit_insert_and_admin_read": True,
        "denied_operations": denied,
        "weather_observed_at": weather.observed_at,
        "weather_valid": True,
    }
    if not args.skip_sop:
        passages = services.sop.search(
            "What is the fresh perishables temperature limit and the response to a critical breach?"
        )
        assert 1 <= len(passages) <= settings.retrieval_k
        assert all(p.metadata.get("source_file") for p in passages)
        assert any("4.0" in p.text for p in passages)
        result["sop"] = {
            "passages": len(passages),
            "sources": sorted({p.metadata["source_file"] for p in passages}),
            "index": settings.pinecone_index_name,
            "namespace": settings.pinecone_namespace,
        }
    print(json.dumps(result, indent=2))
    if args.output:
        args.output.write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error_type": type(error).__name__,
                    "message": "Live service verification failed. No credentials or raw connection errors are printed.",
                }
            )
        )
        raise SystemExit(1)
