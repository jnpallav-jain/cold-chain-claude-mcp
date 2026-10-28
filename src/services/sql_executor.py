"""Native driver timeout and explicit cursor cancellation for a checked-out query."""

import threading
from src.services.errors import ServiceError


class QueryCancelled(ServiceError):
    pass


class QueryTimedOut(ServiceError):
    pass


class QueryCancellation:
    """A cancellation handle belongs to exactly one query, never a global cursor."""

    def __init__(self):
        self.event = threading.Event()
        self.ready = threading.Event()
        self._lock = threading.Lock()
        self._callback = None
        self.spid = None
        self.cancel_attempted = False

    def attach(self, callback):
        with self._lock:
            self._callback = callback
            self.ready.set()
            if self.event.is_set():
                callback()

    def detach(self):
        with self._lock:
            self._callback = None

    def cancel(self):
        with self._lock:
            if self.event.is_set():
                return
            self.event.set()
            if self._callback:
                self.cancel_attempted = True
                try:
                    self._callback()
                except Exception:
                    pass  # Driver may have already completed/closed; never expose its diagnostics.


class SqlQueryExecutor:
    def __init__(self, engine, settings):
        self.engine, self.settings = engine, settings

    def execute(self, query, *, cancellation=None):
        token = cancellation if cancellation is not None else QueryCancellation()
        lease = cursor = timer = None
        failed = False
        try:
            if token.event.is_set():
                raise QueryCancelled("SQL query cancelled.")
            lease = self.engine.raw_connection()
            driver = lease.driver_connection
            dialect = self.engine.dialect.name
            if dialect == "mssql":
                # pyodbc connection.timeout configures SQL_ATTR_QUERY_TIMEOUT on each new cursor.
                driver.timeout = self.settings.sql_query_timeout
            cursor = driver.cursor()
            if dialect == "mssql":
                cursor.execute("SELECT @@SPID")
                token.spid = int(cursor.fetchone()[0])
                cancel = cursor.cancel
                sql = query.sql
            elif dialect == "sqlite":
                # SQLite is used only by offline fixture tests, never configured for production.
                cancel = driver.interrupt
                sql = query.expression.sql(dialect="sqlite")
            else:
                raise ServiceError("Unsupported telemetry database driver.")
            token.attach(cancel)
            if token.event.is_set():
                raise QueryCancelled("SQL query cancelled.")
            # Backup cancellation if a driver does not return promptly at its native timeout.
            timer = threading.Timer(self.settings.sql_query_timeout + 0.5, token.cancel)
            timer.daemon = True
            timer.start()
            cursor.execute(sql)
            columns = [column[0] for column in cursor.description]
            rows = [tuple(row) for row in cursor.fetchmany(self.settings.sql_row_limit)]
            if token.event.is_set():
                raise QueryCancelled("SQL query cancelled.")
            return columns, rows
        except (QueryCancelled, QueryTimedOut):
            failed = True
            raise
        except ServiceError:
            failed = True
            raise
        except Exception as error:
            failed = True
            if token.event.is_set():
                raise QueryCancelled(
                    "SQL query cancelled or exceeded its deadline."
                ) from None
            if any(code in str(error) for code in ("HYT00", "HYT01")):
                raise QueryTimedOut(
                    "SQL query exceeded its driver time limit."
                ) from None
            raise ServiceError(
                "Telemetry database unavailable or query rejected."
            ) from None
        finally:
            if timer:
                timer.cancel()
            # Synchronize against cancellation before closing/releasing this cursor.
            token.detach()
            if cursor is not None:
                try:
                    cursor.close()
                except Exception:
                    pass
            if lease is not None:
                try:
                    if failed or token.event.is_set():
                        lease.invalidate()  # Never return a cancelled connection to the pool.
                finally:
                    lease.close()
