"""Database config helper.

Extracted from settings so it can be unit-tested without a live server. Both
Postgres bugs found in this project (a dropped `sslmode`, then an OPTIONS key
libpq rejected) were invisible on SQLite and would have been caught here.
"""
import dj_database_url


def build_database_config(database_url: str, conn_max_age: int = 0) -> dict:
    """Pooler-safe Django database dict from a Postgres URL.

    conn_max_age=0: serverless runtimes must not hold connections between requests.
    """
    parsed = dj_database_url.parse(database_url, conn_max_age=conn_max_age)
    # Top-level Django setting. Inside OPTIONS it is forwarded to libpq, which
    # rejects it as "invalid connection option" and breaks every connection.
    parsed["DISABLE_SERVER_SIDE_CURSORS"] = True
    parsed.setdefault("OPTIONS", {})
    # psycopg3 prepares statements after 5 executions; those are session-scoped,
    # so a transaction pooler (Neon's -pooler host) can hand the same name to a
    # different backend and raise "prepared statement ... already exists".
    parsed["OPTIONS"]["prepare_threshold"] = None
    return parsed
