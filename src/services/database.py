"""Shared SQL engine construction; engine creation itself makes no connection."""

from sqlalchemy import create_engine, event
from sqlalchemy.engine import URL
from src.config import Settings


def _quote(value):
    return "{" + str(value).replace("}", "}}") + "}"


def create_sql_engine(settings: Settings, *, admin=False, database=None):
    if admin:
        settings.require("sql_admin_password")
        user, password = settings.sql_admin_user, settings.sql_admin_password
    else:
        settings.require("sql_agent_password")
        user, password = settings.sql_agent_user, settings.sql_agent_password
    target = database or settings.sql_database
    # master is used only by the administrative provisioning connection.
    if target != settings.sql_database and not (admin and target == "master"):
        raise ValueError("Unexpected SQL database target")
    connection_string = (
        "DRIVER={ODBC Driver 18 for SQL Server};"
        f"SERVER={_quote(settings.sql_host + ',' + str(settings.sql_port))};"
        f"DATABASE={_quote(target)};UID={_quote(user)};PWD={_quote(password.get_secret_value())};"
        "Encrypt=yes;TrustServerCertificate=yes;"
    )
    engine = create_engine(
        URL.create("mssql+pyodbc", query={"odbc_connect": connection_string}),
        connect_args={"timeout": settings.sql_login_timeout},
        pool_pre_ping=True,
        hide_parameters=True,
        pool_size=2,
        max_overflow=0,
        pool_timeout=settings.sql_pool_timeout,
    )

    if not admin:

        @event.listens_for(engine, "connect")
        def configure_query_timeout(connection, record):
            connection.timeout = settings.sql_query_timeout

    return engine
