"""Load migrations/001_initial.sql and run it through PostgreSQL."""

from psycopg.pq import ExecStatus
from sqlalchemy.engine import Connection


def prepare_schema_sql(sql: str) -> str:
    """Drop the outer BEGIN/COMMIT so Alembic can own the transaction.

    The PL/pgSQL function body also contains a BEGIN line. Only the
    transaction statements, which end with a semicolon, are removed.
    """

    kept: list[str] = []
    for line in sql.splitlines():
        if line.strip().upper() in {"BEGIN;", "COMMIT;"}:
            continue
        kept.append(line)
    body = "\n".join(kept).strip()
    return body + "\n"


def exec_sql_script(connection: Connection, sql: str) -> None:
    """Execute a multi-statement script on the Alembic psycopg connection.

    The extended query protocol accepts one statement at a time, and the
    schema file contains a dollar-quoted function. libpq's simple query
    protocol runs the whole script on the same connection and transaction.
    """

    raw = connection.connection
    driver = getattr(raw, "driver_connection", raw)
    pgconn = driver.pgconn
    result = pgconn.exec_(sql.encode("utf-8"))
    if result.status not in (ExecStatus.COMMAND_OK, ExecStatus.TUPLES_OK):
        message = (pgconn.error_message or b"schema script failed").decode()
        raise RuntimeError(message.strip() or "schema script failed")
