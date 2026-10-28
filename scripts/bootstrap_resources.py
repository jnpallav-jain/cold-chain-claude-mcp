"""Provision isolated SQL and Pinecone resources. Defaults to a non-mutating plan."""

import argparse
import json
from sqlalchemy import text, inspect
from src.config import PROJECT_ROOT, get_settings
from src.services.database import create_sql_engine
from src.services.loader import load_telemetry
from src.services.sop import pinecone_client, describe_compatible_index


def provision_sql(settings):
    settings.require("sql_admin_password", "sql_agent_password")
    master = create_sql_engine(settings, admin=True, database="master")
    try:
        with master.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            if (
                conn.execute(
                    text("SELECT DB_ID(:name)"), {"name": settings.sql_database}
                ).scalar()
                is None
            ):
                conn.exec_driver_sql(f"CREATE DATABASE [{settings.sql_database}]")
            conn.execute(
                text("""IF NOT EXISTS (SELECT 1 FROM sys.server_principals WHERE name='USR_CC_CLAUDE_RO')
                BEGIN
                    DECLARE @sql nvarchar(max) = N'CREATE LOGIN [USR_CC_CLAUDE_RO] WITH PASSWORD = ' + QUOTENAME(:password, CHAR(39));
                    EXEC sp_executesql @sql;
                END"""),
                {"password": settings.sql_agent_password.get_secret_value()},
            )
    finally:
        master.dispose()
    engine = create_sql_engine(settings, admin=True)
    try:
        loaded = 0
        if not inspect(engine).has_table("TBL_SC_FLEET_HIST_RAW", schema="dbo"):
            loaded = load_telemetry(settings, engine=engine)
        script = (PROJECT_ROOT / "scripts/setup_security_and_view.sql").read_text()
        import re

        batches = re.split(r"^GO\s*$", script, flags=re.MULTILINE | re.IGNORECASE)
        with engine.begin() as conn:
            for batch in batches:
                if batch.strip():
                    conn.exec_driver_sql(batch)
        return {"database": settings.sql_database, "loaded_rows": loaded}
    finally:
        engine.dispose()


def provision_pinecone(settings):
    from pinecone import ServerlessSpec

    client = pinecone_client(settings)
    if settings.pinecone_index_name not in client.list_indexes().names():
        client.create_index(
            name=settings.pinecone_index_name,
            dimension=settings.embedding_dimension,
            metric="cosine",
            spec=ServerlessSpec(
                cloud=settings.pinecone_cloud, region=settings.pinecone_region
            ),
            deletion_protection="enabled",
            tags={"project": "cold-chain-claude-mcp"},
            timeout=90,
        )
    desc = describe_compatible_index(settings, client)
    return {
        "index": settings.pinecone_index_name,
        "dimension": desc.dimension,
        "namespace": settings.pinecone_namespace,
        "ready": True,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--component", choices=["sql", "pinecone", "all"], default="all"
    )
    args = parser.parse_args()
    settings = get_settings()
    if not args.apply:
        print(
            json.dumps(
                {
                    "mode": "plan",
                    "sql_host": settings.sql_host,
                    "sql_port": settings.sql_port,
                    "sql_database": settings.sql_database,
                    "pinecone_index": settings.pinecone_index_name,
                    "pinecone_namespace": settings.pinecone_namespace,
                },
                indent=2,
            )
        )
        return
    result = {}
    try:
        if args.component in {"sql", "all"}:
            result["sql"] = provision_sql(settings)
        if args.component in {"pinecone", "all"}:
            result["pinecone"] = provision_pinecone(settings)
    except Exception as error:
        # Never print SQL connection strings, API keys, or underlying request content.
        print(
            json.dumps(
                {
                    "status": "failed",
                    "component": args.component,
                    "error_type": type(error).__name__,
                    "message": "Provisioning failed; check credentials, resource limits, compatibility, and service availability.",
                }
            )
        )
        raise SystemExit(1)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
