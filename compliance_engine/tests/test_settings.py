"""Regression tests for the Postgres config that SQLite-based tests cannot see.

Both outages in this project came from this dict: an OPTIONS overwrite that
dropped ?sslmode, and DISABLE_SERVER_SIDE_CURSORS nested where libpq read it.
"""
from orin_config.db import build_database_config

NEON_POOLED = (
    "postgresql://user:secret@ep-cool-1234-pooler.eu-central-1.aws.neon.tech/neondb"
    "?sslmode=require"
)


def test_neon_url_preserves_sslmode():
    config = build_database_config(NEON_POOLED)
    assert config["ENGINE"] == "django.db.backends.postgresql"
    assert config["OPTIONS"]["sslmode"] == "require"


def test_disable_server_side_cursors_is_top_level_only():
    config = build_database_config(NEON_POOLED)
    assert config["DISABLE_SERVER_SIDE_CURSORS"] is True
    # Inside OPTIONS this is forwarded to libpq, which rejects the whole connection.
    assert "DISABLE_SERVER_SIDE_CURSORS" not in config["OPTIONS"]


def test_pooler_safe_settings():
    config = build_database_config(NEON_POOLED)
    assert config["CONN_MAX_AGE"] == 0  # no connections held between lambdas
    assert config["OPTIONS"]["prepare_threshold"] is None  # psycopg3 + PgBouncer
