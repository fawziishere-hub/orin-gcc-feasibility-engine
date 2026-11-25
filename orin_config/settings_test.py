"""Test settings: always in-memory SQLite.

Without this, a DATABASE_URL in .env makes pytest create and destroy a real
database on the developer's Postgres (slow, billed, and can fail on teardown).
Postgres-specific config is covered by tests/test_settings.py instead, which
needs no connection.
"""
from .settings import *  # noqa: F401,F403

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}
CELERY_TASK_ALWAYS_EAGER = True
